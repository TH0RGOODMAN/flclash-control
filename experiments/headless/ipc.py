"""Private Windows pipe transport for FlClash's length-prefixed core RPC.

The GUI normally owns the server side. This transport owns a different pipe
and must only be used by a host that has acquired exclusive core ownership.
"""
from __future__ import annotations

from collections import deque
from concurrent.futures import Future, TimeoutError as FutureTimeout
import ctypes
import json
import os
import struct
import threading
import uuid
from typing import Any

MAX_FRAME_SIZE = 8 * 1024 * 1024


class IpcError(RuntimeError):
    """Transport failure without exposing a core configuration payload."""


def encode_frame(value: dict[str, Any]) -> bytes:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if not data or len(data) > MAX_FRAME_SIZE:
        raise IpcError("RPC frame exceeds the allowed size")
    return struct.pack("<I", len(data)) + data


def decode_length(header: bytes) -> int:
    if len(header) != 4:
        raise IpcError("Incomplete RPC frame header")
    length = struct.unpack("<I", header)[0]
    if length < 1 or length > MAX_FRAME_SIZE:
        raise IpcError("Invalid RPC frame size")
    return length


def private_security_attributes():
    """Grant this user and LocalSystem, reject inherited and remote access."""
    if os.name != "nt":
        raise IpcError("FlClash named pipe control requires Windows")
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        sid_text = win32security.ConvertSidToStringSid(sid)
    finally:
        token.Close()
    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        f"D:P(A;;GA;;;SY)(A;;GA;;;{sid_text})", win32security.SDDL_REVISION_1
    )
    attributes = win32security.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = descriptor
    attributes.bInheritHandle = False
    return attributes


class IpcChannel:
    """One connected core, bounded events, and concurrent RPC correlation."""

    def __init__(self, *, request_timeout: float = 15.0):
        if os.name != "nt":
            raise IpcError("FlClash named pipe control requires Windows")
        import win32api
        import win32event
        import win32file
        import win32pipe
        import pywintypes

        self._api = win32api
        self._event = win32event
        self._file = win32file
        self._pipe = win32pipe
        self._types = pywintypes
        self.request_timeout = request_timeout
        self.address = r"\\.\pipe\FlClashControl_" + uuid.uuid4().hex
        self._closed = threading.Event()
        self._connected = threading.Event()
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._io_lock = threading.RLock()
        self._operations: dict[int, tuple[Any, Any]] = {}
        self._pending: dict[str, tuple[str, Future]] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=100)
        self._reader: threading.Thread | None = None
        self._handle = None
        self._accept = None
        try:
            self._handle = win32pipe.CreateNamedPipe(
                self.address,
                win32pipe.PIPE_ACCESS_DUPLEX | 0x40000000 | 0x00080000,
                win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE
                | win32pipe.PIPE_WAIT | 0x00000008,
                1, 65536, 65536, 0, private_security_attributes(),
            )
            self._accept = self._overlapped()
            self._operations[id(self._accept)] = (self._accept, None)
            try:
                win32pipe.ConnectNamedPipe(self._handle, self._accept)
            except pywintypes.error as exc:
                if exc.winerror == 535:  # ERROR_PIPE_CONNECTED
                    win32event.SetEvent(self._accept.hEvent)
                elif exc.winerror != 997:  # ERROR_IO_PENDING
                    raise
        except Exception as exc:
            self.close()
            if isinstance(exc, IpcError):
                raise
            raise IpcError("Unable to create a private core pipe") from exc

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set() and not self._closed.is_set()

    def _overlapped(self):
        value = self._types.OVERLAPPED()
        value.hEvent = self._event.CreateEvent(None, True, False, None)
        return value

    def _cancel_operation(self, overlapped) -> None:
        """Keep each OVERLAPPED alive until the kernel finishes cancellation."""
        self._connected.clear()
        with self._io_lock:
            if self._handle is None or id(overlapped) not in self._operations:
                return
            self._cancel_all_io()
            try:
                self._file.GetOverlappedResult(self._handle, overlapped, True)
            except Exception:
                pass  # ERROR_OPERATION_ABORTED is a completed cancellation.

    def _cancel_all_io(self) -> None:
        cancel = ctypes.WinDLL("kernel32", use_last_error=True).CancelIoEx
        cancel.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        cancel.restype = ctypes.c_int
        cancel(int(self._handle), None)

    def _finish_operation(self, overlapped) -> None:
        with self._io_lock:
            self._operations.pop(id(overlapped), None)
            overlapped.hEvent.Close()

    def _wait(self, overlapped, timeout: float | None = None) -> None:
        import time
        until = None if timeout is None else time.monotonic() + timeout
        while not self._closed.is_set():
            if until is not None and time.monotonic() >= until:
                raise IpcError("Core pipe connection timed out")
            result = self._event.WaitForSingleObject(overlapped.hEvent, 100)
            if result == self._event.WAIT_OBJECT_0:
                return
            if result != self._event.WAIT_TIMEOUT:
                raise IpcError("Core pipe wait failed")
        raise IpcError("Core pipe is closed")

    def wait_connected(self, timeout: float = 15.0) -> None:
        if self.is_connected:
            return
        if self._accept is None:
            raise IpcError("Core pipe is closed")
        self._wait(self._accept, timeout)
        try:
            self._file.GetOverlappedResult(self._handle, self._accept, False)
        except self._types.error as exc:
            if exc.winerror != 535:
                raise IpcError("Core failed to connect to the private pipe") from exc
        finally:
            self._finish_operation(self._accept)
            self._accept = None
        self._connected.set()
        self._reader = threading.Thread(target=self._read_loop, name="flclash-core-reader", daemon=True)
        self._reader.start()

    def _read_exact(self, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            buffer = self._file.AllocateReadBuffer(min(size - len(chunks), 65536))
            overlapped = self._overlapped()
            completed = False
            try:
                with self._io_lock:
                    if self._closed.is_set():
                        raise IpcError("Core pipe is closed")
                    self._operations[id(overlapped)] = (overlapped, buffer)
                    self._file.ReadFile(self._handle, buffer, overlapped)
                self._wait(overlapped)
                count = self._file.GetOverlappedResult(self._handle, overlapped, False)
                completed = True
                if count == 0:
                    raise IpcError("Core disconnected")
                chunks.extend(buffer[:count])
            finally:
                if not completed:
                    self._cancel_operation(overlapped)
                self._finish_operation(overlapped)
        return bytes(chunks)

    def _write(self, data: bytes) -> None:
        with self._write_lock:
            offset = 0
            while offset < len(data):
                overlapped = self._overlapped()
                chunk = data[offset:offset + 65536]
                completed = False
                try:
                    with self._io_lock:
                        if self._closed.is_set():
                            raise IpcError("Core pipe is closed")
                        self._operations[id(overlapped)] = (overlapped, chunk)
                        self._file.WriteFile(self._handle, chunk, overlapped)
                    self._wait(overlapped, self.request_timeout)
                    count = self._file.GetOverlappedResult(self._handle, overlapped, False)
                    completed = True
                    if count <= 0:
                        raise IpcError("Core pipe write failed")
                    offset += count
                finally:
                    if not completed:
                        self._cancel_operation(overlapped)
                    self._finish_operation(overlapped)

    def _read_loop(self) -> None:
        try:
            while not self._closed.is_set():
                length = decode_length(self._read_exact(4))
                response = json.loads(self._read_exact(length).decode("utf-8"))
                if not isinstance(response, dict):
                    raise IpcError("Core returned an invalid RPC object")
                request_id = response.get("id")
                if not request_id:
                    with self._state_lock:
                        self._events.append(response)
                    continue
                with self._state_lock:
                    pending = self._pending.pop(request_id, None)
                if pending is None:
                    continue  # Timed-out responses cannot satisfy another request.
                method, future = pending
                if response.get("method") != method:
                    future.set_exception(IpcError("RPC response method did not match"))
                elif response.get("code", 0) != 0:
                    future.set_exception(IpcError(f"Core rejected RPC {method}"))
                else:
                    future.set_result(response.get("data"))
        except Exception:
            self._connected.clear()
            self._fail_pending(IpcError("Core pipe connection was lost"))

    def request(self, method: str, data: Any = None, *, timeout: float | None = None) -> Any:
        if not self.is_connected:
            raise IpcError("Core is not connected")
        request_id = uuid.uuid4().hex
        future: Future = Future()
        frame = encode_frame({"id": request_id, "method": method, "data": data})
        with self._state_lock:
            self._pending[request_id] = (method, future)
        try:
            self._write(frame)
            return future.result(timeout=self.request_timeout if timeout is None else timeout)
        except FutureTimeout as exc:
            raise IpcError(f"Core RPC {method} timed out") from exc
        finally:
            with self._state_lock:
                self._pending.pop(request_id, None)

    def events(self, *, clear: bool = True) -> list[dict[str, Any]]:
        with self._state_lock:
            result = list(self._events)
            if clear:
                self._events.clear()
            return result

    def _fail_pending(self, error: Exception) -> None:
        with self._state_lock:
            pending, self._pending = self._pending, {}
        for _, future in pending.values():
            if not future.done():
                future.set_exception(error)

    def close(self) -> None:
        self._closed.set()
        self._connected.clear()
        self._fail_pending(IpcError("Core pipe is closed"))
        with self._io_lock:
            handle = self._handle
            if handle is not None:
                self._cancel_all_io()
                # Hold the operation table lock until all retained OVERLAPPED
                # structs and buffers have reached a terminal kernel state.
                for overlapped, _buffer in list(self._operations.values()):
                    try:
                        self._file.GetOverlappedResult(handle, overlapped, True)
                    except Exception:
                        pass
                self._handle = None
                handle.Close()
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(timeout=2)
        if self._accept is not None:
            self._finish_operation(self._accept)
            self._accept = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
