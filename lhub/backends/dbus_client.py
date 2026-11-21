"""System D-Bus transport layer for hardware backends and health diagnostics.

Stack decision (verified against PySide6 6.12.0 on this codebase):
- ``PySide6.QtDBus`` integrates natively into the Qt main event loop for
  asynchronous D-Bus signal subscriptions (``DeviceAdded``, ``DeviceRemoved``,
  ``PropertiesChanged``, ``DeviceNew``, ``Resync``, ``NameOwnerChanged``) via
  ``QDBusConnection.systemBus().connect(..., SLOT("handle_signal(QDBusMessage)"))``
  with zero extra threads.
- However, PySide6's Shiboken6 bindings for ``QDBusArgument`` cannot safely
  marshal ``uint32`` values inside ``(uv)`` (``Button.Mapping``) or descend
  into read-only ``(uv)`` / ``a{sv}`` structures without warnings or errors,
  and ``QDBusInterface.property()`` fails on ``QList<QDBusObjectPath>`` (``ao``)
  and unregistered ``(uv)`` types.
- Therefore, synchronous thread-safe RPC calls (method calls, ``Properties.Get``,
  ``Properties.GetAll``, ``Properties.Set``) use ``jeepney`` (pure-Python MIT
  D-Bus wire protocol), while event-loop signal monitoring uses
  ``PySide6.QtDBus``. Both are encapsulated behind :class:`SystemDBusClient`
  so all unit tests run cleanly offline via dependency injection / mocks.
"""

from dataclasses import dataclass
import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, SLOT, Slot
from PySide6.QtDBus import QDBusArgument, QDBusConnection, QDBusMessage, QDBusObjectPath, QDBusVariant

try:
    from jeepney import DBusAddress, new_method_call
    from jeepney.io.blocking import open_dbus_connection
    from jeepney.low_level import MessageFlag
    from jeepney.wrappers import DBusErrorResponse, unwrap_msg

    _JEEPNEY_AVAILABLE = True
except ImportError:  # pragma: no cover - guarded for minimal environments
    DBusAddress = None  # type: ignore[assignment]
    new_method_call = None  # type: ignore[assignment]
    open_dbus_connection = None  # type: ignore[assignment]
    MessageFlag = None  # type: ignore[assignment]
    DBusErrorResponse = Exception  # type: ignore[assignment,misc]
    unwrap_msg = None  # type: ignore[assignment]
    _JEEPNEY_AVAILABLE = False

logger = logging.getLogger(__name__)

DBUS_SERVICE = "org.freedesktop.DBus"
DBUS_PATH = "/org/freedesktop/DBus"
DBUS_IFACE = "org.freedesktop.DBus"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

_DBUS_BASIC_TYPES = frozenset("ybnqiuxtdsogh")
_SERVICE_UNAVAILABLE_ERRORS = frozenset(
    {
        "org.freedesktop.DBus.Error.ServiceUnknown",
        "org.freedesktop.DBus.Error.NameHasNoOwner",
    }
)


class DBusError(Exception):
    """Base error for D-Bus transport failures."""


class DBusUnavailableError(DBusError):
    """Raised when the system bus or target service is unavailable."""


class DBusTimeoutError(DBusError):
    """Raised when a D-Bus method call times out."""


class DBusCallError(DBusError):
    """Raised when a D-Bus peer returns an error reply."""

    def __init__(self, error_name: str, error_message: str = ""):
        self.error_name = error_name or "org.freedesktop.DBus.Error.Failed"
        self.error_message = error_message or ""
        super().__init__(f"[{self.error_name}] {self.error_message}".strip())


@dataclass(frozen=True)
class DBusSignalEvent:
    """Normalized representation of a received D-Bus signal."""

    service: str
    path: str
    interface: str
    member: str
    args: Tuple[Any, ...] = ()


def _consume_single_complete_type(sig: str, pos: int) -> Optional[int]:
    """Advance ``pos`` past exactly one complete D-Bus type, or return None if invalid."""
    n = len(sig)
    if pos >= n:
        return None
    ch = sig[pos]
    if ch in _DBUS_BASIC_TYPES or ch == "v":
        return pos + 1
    if ch == "a":
        if pos + 1 >= n:
            return None
        if sig[pos + 1] == "{":
            # Dict entry: { <basic_key> <complete_value> }
            if pos + 3 >= n or sig[pos + 2] not in _DBUS_BASIC_TYPES:
                return None
            after_val = _consume_single_complete_type(sig, pos + 3)
            if after_val is None or after_val >= n or sig[after_val] != "}":
                return None
            return after_val + 1
        return _consume_single_complete_type(sig, pos + 1)
    if ch == "(":
        cur = pos + 1
        if cur >= n or sig[cur] == ")":
            return None
        while cur < n and sig[cur] != ")":
            nxt = _consume_single_complete_type(sig, cur)
            if nxt is None:
                return None
            cur = nxt
        if cur >= n or sig[cur] != ")":
            return None
        return cur + 1
    return None


def _is_dbus_signature(sig: str) -> bool:
    """Return True if ``sig`` is a single complete D-Bus type signature."""
    if not isinstance(sig, str) or not sig:
        return False
    return _consume_single_complete_type(sig, 0) == len(sig)


def unwrap_variant(value: Any, recursive: bool = False) -> Any:
    """Unwrap one (or all) D-Bus variant / object-path wrapper layer(s).

    Handles ``QDBusVariant``, ``QDBusObjectPath``, and ``jeepney`` ``(signature, value)``
    variant tuples while leaving plain Python values untouched.
    """
    current = value
    while True:
        if isinstance(current, QDBusVariant):
            current = current.variant()
        elif isinstance(current, QDBusObjectPath):
            return current.path()
        elif (
            isinstance(current, tuple)
            and len(current) == 2
            and isinstance(current[0], str)
            and _is_dbus_signature(current[0])
        ):
            current = current[1]
        else:
            return current
        if not recursive:
            if isinstance(current, QDBusObjectPath):
                return current.path()
            return current


def unwrap_dbus_properties(raw_props: Dict[str, Any]) -> Dict[str, Any]:
    """Unwrap one D-Bus variant layer per entry of a ``GetAll`` ``a{sv}`` dict.

    Preserves inner typed values (such as ``Resolution``'s ``('u', 800)`` or
    ``Mapping``'s ``(action_type, ('u', val))``) so callers can inspect inner
    type tags unambiguously, while remaining safe on plain dicts from unit tests.
    """
    if not isinstance(raw_props, dict):
        return {}
    return {str(k): unwrap_variant(v, recursive=False) for k, v in raw_props.items()}


def _is_duck_typed_dbus_arg(value: Any) -> bool:
    return (
        not isinstance(value, QDBusArgument)
        and hasattr(value, "currentType")
        and hasattr(value, "atEnd")
    )


def unpack_qdbus_argument(value: Any) -> Any:
    """Safely unpack ``QDBusVariant``, ``QDBusObjectPath``, containers, or mock ``QDBusArgument``s.

    Note: PySide6 6.12 exposes only non-const write overloads for ``QDBusArgument``
    container traversal (``beginStructure``, ``beginMap``, ``endArray``), which emit
    ``QDBusArgument: write from a read-only object`` on real read-only Qt arguments.
    For real ``QDBusArgument`` instances, only ``BasicType`` / ``VariantType`` are
    extracted via ``asVariant()``; complex container instances are returned as-is,
    while duck-typed test doubles are unpacked recursively.
    """
    if isinstance(value, QDBusVariant):
        return unpack_qdbus_argument(value.variant())
    if isinstance(value, QDBusObjectPath):
        return value.path()
    if isinstance(value, list):
        return [unpack_qdbus_argument(item) for item in value]
    if isinstance(value, tuple):
        return tuple(unpack_qdbus_argument(item) for item in value)
    if isinstance(value, dict):
        return {unpack_qdbus_argument(k): unpack_qdbus_argument(v) for k, v in value.items()}

    if isinstance(value, QDBusArgument):
        et = value.currentType()
        if et in (QDBusArgument.ElementType.BasicType, QDBusArgument.ElementType.VariantType):
            return unpack_qdbus_argument(value.asVariant())
        return value

    if _is_duck_typed_dbus_arg(value):
        et = value.currentType()
        el_types = QDBusArgument.ElementType
        if et == el_types.MapType:
            out: Dict[Any, Any] = {}
            value.beginMap()
            while not value.atEnd():
                value.beginMapEntry()
                k = unpack_qdbus_argument(value.asVariant() if hasattr(value, "asVariant") else value)
                v = unpack_qdbus_argument(value.asVariant() if hasattr(value, "asVariant") else value)
                value.endMapEntry()
                out[k] = v
            value.endMap()
            return out
        if et == el_types.ArrayType:
            items: List[Any] = []
            value.beginArray()
            while not value.atEnd():
                items.append(unpack_qdbus_argument(value.asVariant() if hasattr(value, "asVariant") else value))
            value.endArray()
            return items
        if et == el_types.StructureType:
            fields: List[Any] = []
            value.beginStructure()
            while not value.atEnd():
                fields.append(unpack_qdbus_argument(value.asVariant() if hasattr(value, "asVariant") else value))
            value.endStructure()
            return tuple(fields)
        if et in (el_types.VariantType, el_types.BasicType) and hasattr(value, "asVariant"):
            return unpack_qdbus_argument(value.asVariant())

    return value


def extract_qdbus_message_args(message: Any) -> Tuple[Any, ...]:
    """Extract normalized positional arguments from a ``QDBusMessage`` signal."""
    if message is None or not hasattr(message, "arguments"):
        return ()
    raw_args = message.arguments() or []
    return tuple(unpack_qdbus_argument(arg) for arg in raw_args)


class _SignalSubscription(QObject):
    """Qt event-loop receiver binding a single ``QDBusConnection.connect`` subscription."""

    def __init__(
        self,
        bus: Any,
        service: str,
        path: str,
        interface: str,
        signal_name: str,
        callback: Callable[[DBusSignalEvent], None],
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._bus = bus
        self._service = service
        self._path = path
        self._interface = interface
        self._signal_name = signal_name
        self._callback = callback
        self._connected = False

    @Slot(QDBusMessage)
    def handle_signal(self, message: QDBusMessage) -> None:
        event = DBusSignalEvent(
            service=message.service() if hasattr(message, "service") else self._service,
            path=message.path() if hasattr(message, "path") else self._path,
            interface=message.interface() if hasattr(message, "interface") else self._interface,
            member=message.member() if hasattr(message, "member") else self._signal_name,
            args=extract_qdbus_message_args(message),
        )
        try:
            self._callback(event)
        except Exception as exc:
            logger.warning(
                "Error in D-Bus signal callback for %s.%s (%s): %s",
                event.interface,
                event.member,
                event.path,
                exc,
            )

    def connect_signal(self) -> bool:
        if self._connected:
            return True
        ok = bool(
            self._bus.connect(
                self._service,
                self._path,
                self._interface,
                self._signal_name,
                self,
                SLOT("handle_signal(QDBusMessage)"),
            )
        )
        self._connected = ok
        return ok

    def disconnect_signal(self) -> bool:
        if not self._connected:
            return False
        self._connected = False
        try:
            return bool(
                self._bus.disconnect(
                    self._service,
                    self._path,
                    self._interface,
                    self._signal_name,
                    self,
                    SLOT("handle_signal(QDBusMessage)"),
                )
            )
        except Exception as exc:
            logger.debug("Failed disconnecting D-Bus signal %s.%s: %s", self._interface, self._signal_name, exc)
            return False


class SystemDBusClient:
    """Thread-safe system D-Bus RPC client with QtDBus signal monitoring."""

    def __init__(
        self,
        timeout: float = 3.0,
        connection_factory: Optional[Callable[[], Any]] = None,
        qdbus_bus_factory: Optional[Callable[[], Any]] = None,
    ):
        self._timeout = float(timeout)
        self._connection_factory = connection_factory
        self._qdbus_bus_factory = qdbus_bus_factory
        self._lock = threading.Lock()
        self._conn: Any = None
        self._sub_lock = threading.Lock()
        self._next_sub_id = 1
        self._subscriptions: Dict[int, _SignalSubscription] = {}

    def _open_connection(self) -> Any:
        if self._connection_factory is not None:
            conn = self._connection_factory()
            if conn is None:
                raise DBusUnavailableError("System D-Bus connection factory returned None")
            return conn
        if not _JEEPNEY_AVAILABLE or open_dbus_connection is None:
            raise DBusUnavailableError("jeepney is not installed")
        try:
            return open_dbus_connection(bus="SYSTEM", auth_timeout=min(self._timeout, 2.0))
        except (OSError, TimeoutError, ValueError, StopIteration, DBusErrorResponse) as exc:
            raise DBusUnavailableError(f"Could not connect to system D-Bus: {exc}") from exc

    def _close_connection_locked(self) -> None:
        if self._conn is not None:
            close_fn = getattr(self._conn, "close", None)
            self._conn = None
            if callable(close_fn):
                try:
                    close_fn()
                except Exception as exc:
                    logger.debug("Error closing system D-Bus connection: %s", exc)

    def _get_connection_locked(self) -> Any:
        if self._conn is None:
            self._conn = self._open_connection()
        return self._conn

    def _send_and_unwrap(self, msg: Any, timeout: Optional[float] = None) -> Tuple[Any, ...]:
        eff_timeout = self._timeout if timeout is None else float(timeout)
        with self._lock:
            last_exc: Optional[Exception] = None
            for attempt in range(2):
                conn = self._get_connection_locked()
                try:
                    reply = conn.send_and_get_reply(msg, timeout=eff_timeout)
                    break
                except TimeoutError as exc:
                    raise DBusTimeoutError(f"System D-Bus call timed out after {eff_timeout:.1f}s") from exc
                except (BrokenPipeError, ConnectionResetError, EOFError, OSError) as exc:
                    last_exc = exc
                    self._close_connection_locked()
                    if attempt == 0:
                        continue
                    raise DBusUnavailableError(f"System D-Bus I/O failed: {exc}") from exc
            else:  # pragma: no cover - defensive
                raise DBusUnavailableError(f"System D-Bus I/O failed: {last_exc}")

        try:
            body = unwrap_msg(reply) if unwrap_msg is not None else reply.body
            return tuple(body) if isinstance(body, (tuple, list)) else (body,)
        except DBusErrorResponse as exc:
            err_name = getattr(exc, "name", "") or "org.freedesktop.DBus.Error.Failed"
            err_data = getattr(exc, "data", ())
            if isinstance(err_data, (tuple, list)) and err_data:
                err_msg = str(err_data[0])
            elif err_data:
                err_msg = str(err_data)
            else:
                err_msg = ""
            if err_name in _SERVICE_UNAVAILABLE_ERRORS:
                raise DBusUnavailableError(f"[{err_name}] {err_msg}".strip()) from exc
            raise DBusCallError(err_name, err_msg) from exc

    def _get_qdbus_bus(self) -> Any:
        if self._qdbus_bus_factory is not None:
            return self._qdbus_bus_factory()
        return QDBusConnection.systemBus()

    def is_bus_available(self) -> bool:
        try:
            with self._lock:
                self._get_connection_locked()
            return True
        except DBusError:
            return False

    def call_method(
        self,
        service: str,
        path: str,
        interface: str,
        method: str,
        signature: str = "",
        args: Tuple[Any, ...] = (),
        timeout: Optional[float] = None,
        auto_start: bool = False,
    ) -> Tuple[Any, ...]:
        if DBusAddress is None or new_method_call is None:
            raise DBusUnavailableError("jeepney is not installed")
        addr = DBusAddress(path, bus_name=service, interface=interface)
        msg = new_method_call(addr, method, signature or None, args)
        if not auto_start and MessageFlag is not None:
            msg.header.flags |= MessageFlag.no_auto_start
        return self._send_and_unwrap(msg, timeout=timeout)

    def has_name_owner(self, service: str, timeout: Optional[float] = None) -> bool:
        try:
            reply = self.call_method(
                DBUS_SERVICE,
                DBUS_PATH,
                DBUS_IFACE,
                "NameHasOwner",
                "s",
                (service,),
                timeout=timeout,
            )
            return bool(reply and reply[0])
        except DBusError:
            return False

    def list_activatable_names(self, timeout: Optional[float] = None) -> List[str]:
        reply = self.call_method(
            DBUS_SERVICE,
            DBUS_PATH,
            DBUS_IFACE,
            "ListActivatableNames",
            timeout=timeout,
        )
        if not reply:
            return []
        raw = reply[0]
        return [str(name) for name in raw] if isinstance(raw, (list, tuple)) else []

    def is_service_activatable(self, service: str, timeout: Optional[float] = None) -> bool:
        try:
            return service in self.list_activatable_names(timeout=timeout)
        except DBusError:
            return False

    def start_service_by_name(
        self,
        service: str,
        flags: int = 0,
        timeout: Optional[float] = None,
    ) -> int:
        reply = self.call_method(
            DBUS_SERVICE,
            DBUS_PATH,
            DBUS_IFACE,
            "StartServiceByName",
            "su",
            (service, int(flags)),
            timeout=timeout,
            auto_start=True,
        )
        return int(reply[0]) if reply else 0

    def get_property(
        self,
        service: str,
        path: str,
        interface: str,
        prop_name: str,
        timeout: Optional[float] = None,
    ) -> Any:
        reply = self.call_method(
            service,
            path,
            DBUS_PROPERTIES_IFACE,
            "Get",
            "ss",
            (interface, prop_name),
            timeout=timeout,
        )
        if not reply:
            return None
        return unwrap_variant(reply[0], recursive=False)

    def get_all_properties(
        self,
        service: str,
        path: str,
        interface: str,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        reply = self.call_method(
            service,
            path,
            DBUS_PROPERTIES_IFACE,
            "GetAll",
            "s",
            (interface,),
            timeout=timeout,
        )
        if not reply or not isinstance(reply[0], dict):
            return {}
        return unwrap_dbus_properties(reply[0])

    def set_property(
        self,
        service: str,
        path: str,
        interface: str,
        prop_name: str,
        value_signature: str,
        value: Any,
        timeout: Optional[float] = None,
    ) -> None:
        self.call_method(
            service,
            path,
            DBUS_PROPERTIES_IFACE,
            "Set",
            "ssv",
            (interface, prop_name, (value_signature, value)),
            timeout=timeout,
        )

    def subscribe_signal(
        self,
        service: str,
        path: str,
        interface: str,
        signal_name: str,
        callback: Callable[[DBusSignalEvent], None],
    ) -> Optional[int]:
        try:
            bus = self._get_qdbus_bus()
        except Exception as exc:
            logger.debug("Could not acquire QDBusConnection systemBus: %s", exc)
            return None

        if bus is None or not getattr(bus, "isConnected", lambda: False)():
            logger.debug("QDBusConnection systemBus is not connected; skipping signal %s.%s", interface, signal_name)
            return None

        sub = _SignalSubscription(
            bus=bus,
            service=service,
            path=path,
            interface=interface,
            signal_name=signal_name,
            callback=callback,
        )
        if not sub.connect_signal():
            logger.debug(
                "Failed to connect D-Bus signal %s.%s on %s (%s)",
                interface,
                signal_name,
                path or "*",
                service,
            )
            return None

        with self._sub_lock:
            sub_id = self._next_sub_id
            self._next_sub_id += 1
            self._subscriptions[sub_id] = sub
        return sub_id

    def unsubscribe_signal(self, subscription_id: int) -> bool:
        with self._sub_lock:
            sub = self._subscriptions.pop(subscription_id, None)
        if sub is None:
            return False
        sub.disconnect_signal()
        return True

    def close(self) -> None:
        with self._sub_lock:
            subs = list(self._subscriptions.values())
            self._subscriptions.clear()
        for sub in subs:
            sub.disconnect_signal()

        with self._lock:
            self._close_connection_locked()


_DEFAULT_CLIENT_LOCK = threading.Lock()
_DEFAULT_CLIENT: Optional[SystemDBusClient] = None


def get_system_dbus_client() -> SystemDBusClient:
    """Return the shared lazily initialized :class:`SystemDBusClient` instance."""
    global _DEFAULT_CLIENT
    with _DEFAULT_CLIENT_LOCK:
        if _DEFAULT_CLIENT is None:
            _DEFAULT_CLIENT = SystemDBusClient()
        return _DEFAULT_CLIENT
