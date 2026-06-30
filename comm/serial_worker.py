"""Serial communication worker running in QThread."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from queue import Empty, Queue

import serial
from PyQt6.QtCore import QObject, pyqtSignal

from protocol.codec import RX_FRAME_LEN, build_tx_frame, format_hex, parse_rx_frame
from protocol.validator import needs_retry


@dataclass
class SendResult:
    """Result of a single send/receive cycle."""

    success: bool
    tx_frame: bytes
    rx_frame: bytes | None = None
    parsed: dict | None = None
    retries: int = 0
    low_value_retries: int = 0
    error: str = ""


def _timestamp() -> str:
    now = datetime.now()
    return now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"


def _format_serial_error(port: str, exc: Exception) -> str:
    """Turn pyserial exceptions into actionable Chinese messages."""
    msg = str(exc).strip()
    lower = msg.lower()

    if "access is denied" in lower or "permission" in lower:
        return (
            f"无法打开 {port}：端口被占用或无权限。\n"
            "请关闭其他串口工具（Arduino IDE、串口助手等）后重试。"
        )
    if "could not open port" in lower or "filenotfound" in lower or "no such file" in lower:
        return f"无法打开 {port}：端口不存在或已拔出。请点击「刷新」后重新选择 COM 口。"
    if "timeout" in lower:
        return f"打开 {port} 超时：{msg}"
    return f"连接 {port} 失败：{msg}"


class SerialWorker(QObject):
    """QThread worker for non-blocking serial I/O."""

    connected = pyqtSignal(str, int)  # port, baudrate
    disconnected = pyqtSignal()
    connect_failed = pyqtSignal(str)
    error = pyqtSignal(str)
    tx_logged = pyqtSignal(str)
    rx_logged = pyqtSignal(str)
    send_complete = pyqtSignal(object)  # SendResult
    batch_progress = pyqtSignal(int, int)  # current, total
    batch_complete = pyqtSignal(list)  # list[SendResult]

    def __init__(self) -> None:
        super().__init__()
        self._serial: serial.Serial | None = None
        self._thread_running = True
        self._stop_requested = False
        self._cmd_queue: Queue = Queue()
        self._rx_buffer = bytearray()
        self._timeout_ms = 500
        self._max_retries = 3
        self._connected_port = ""
        self._connected_baud = 0

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def set_timeout(self, ms: int) -> None:
        self._timeout_ms = max(50, ms)

    def set_max_retries(self, n: int) -> None:
        self._max_retries = max(0, n)

    def connect_port(
        self,
        port: str,
        baudrate: int = 115200,
        parity: str = "N",
        stopbits: int = 1,
        bytesize: int = 8,
    ) -> None:
        """Queue a connect request (processed in worker thread)."""
        self._cmd_queue.put(
            {
                "type": "connect",
                "port": port,
                "baudrate": baudrate,
                "parity": parity,
                "stopbits": stopbits,
                "bytesize": bytesize,
            }
        )

    def disconnect_port(self) -> None:
        """Queue a disconnect request (processed in worker thread)."""
        self._cmd_queue.put({"type": "disconnect"})

    def shutdown(self) -> None:
        """Stop worker thread loop."""
        self._thread_running = False
        self._cmd_queue.put({"type": "shutdown"})

    def stop_batch(self) -> None:
        self._stop_requested = True

    def send_frame(
        self,
        cmd: int,
        channels: list[int],
        expected_signs: list[int] | None = None,
    ) -> None:
        """Queue a single frame send (processed in worker loop)."""
        self._cmd_queue.put(
            {
                "type": "send",
                "cmd": cmd,
                "channels": channels,
                "expected_signs": expected_signs,
            }
        )

    def send_batch(self, groups: list[dict]) -> None:
        """Queue a batch test."""
        self._stop_requested = False
        self._cmd_queue.put({"type": "batch", "groups": groups})

    def run_loop(self) -> None:
        """Main worker loop — call from QThread.started."""
        while self._thread_running:
            self._poll_serial()

            try:
                cmd = self._cmd_queue.get(timeout=0.01)
            except Empty:
                continue

            cmd_type = cmd.get("type")
            if cmd_type == "connect":
                self._do_connect(cmd)
            elif cmd_type == "disconnect":
                self._do_disconnect()
            elif cmd_type == "send":
                result = self._do_send(cmd["cmd"], cmd["channels"])
                self.send_complete.emit(result)
            elif cmd_type == "batch":
                results = self._do_batch(cmd["groups"])
                self.batch_complete.emit(results)
            elif cmd_type == "shutdown":
                break

        self._do_disconnect()

    def _do_connect(self, params: dict) -> None:
        if self.is_connected:
            self._do_disconnect()

        port = params["port"]
        baudrate = int(params["baudrate"])
        parity = params["parity"]
        stopbits = int(params["stopbits"])
        bytesize = int(params["bytesize"])

        parity_map = {
            "N": serial.PARITY_NONE,
            "E": serial.PARITY_EVEN,
            "O": serial.PARITY_ODD,
            "M": serial.PARITY_MARK,
            "S": serial.PARITY_SPACE,
        }
        stopbits_map = {1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}

        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=bytesize,
                parity=parity_map.get(parity, serial.PARITY_NONE),
                stopbits=stopbits_map.get(stopbits, serial.STOPBITS_ONE),
                timeout=0.01,
                write_timeout=1.0,
            )
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
            self._rx_buffer.clear()
            self._connected_port = port
            self._connected_baud = baudrate
            self.connected.emit(port, baudrate)
        except (serial.SerialException, OSError, ValueError) as exc:
            self._serial = None
            self._connected_port = ""
            self._connected_baud = 0
            self.connect_failed.emit(_format_serial_error(port, exc))

    def _do_disconnect(self) -> None:
        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except serial.SerialException:
                pass
        self._serial = None
        had_connection = bool(self._connected_port)
        self._connected_port = ""
        self._connected_baud = 0
        if had_connection:
            self.disconnected.emit()

    def _poll_serial(self) -> None:
        if not self.is_connected:
            return
        try:
            waiting = self._serial.in_waiting
            if waiting > 0:
                self._rx_buffer.extend(self._serial.read(waiting))
        except serial.SerialException as exc:
            self.error.emit(f"读取错误: {exc}")
            self._do_disconnect()

    def _read_rx_frame(self) -> bytes | None:
        """Try to extract a 17-byte RX frame from buffer."""
        if len(self._rx_buffer) >= RX_FRAME_LEN:
            frame = bytes(self._rx_buffer[:RX_FRAME_LEN])
            del self._rx_buffer[:RX_FRAME_LEN]
            return frame
        return None

    def _do_send(self, cmd: int, channels: list[int]) -> SendResult:
        if not self.is_connected:
            return SendResult(
                success=False,
                tx_frame=b"",
                error="串口未连接",
            )

        frame = build_tx_frame(cmd, channels)
        retries = 0
        low_value_retries = 0

        while retries <= self._max_retries:
            if self._stop_requested:
                return SendResult(
                    success=False,
                    tx_frame=frame,
                    retries=retries,
                    low_value_retries=low_value_retries,
                    error="已停止",
                )

            try:
                self._rx_buffer.clear()
                self._serial.write(frame)
                self._serial.flush()
            except serial.SerialException as exc:
                return SendResult(
                    success=False,
                    tx_frame=frame,
                    retries=retries,
                    error=f"发送失败: {exc}",
                )

            self.tx_logged.emit(f"[{_timestamp()}]发送→{format_hex(frame)}")

            deadline = time.monotonic() + self._timeout_ms / 1000.0
            rx_frame = None

            while time.monotonic() < deadline:
                self._poll_serial()
                rx_frame = self._read_rx_frame()
                if rx_frame is not None:
                    break
                time.sleep(0.005)

            if rx_frame is None:
                retries += 1
                if retries <= self._max_retries:
                    continue
                return SendResult(
                    success=False,
                    tx_frame=frame,
                    retries=retries,
                    low_value_retries=low_value_retries,
                    error=f"接收超时 ({self._timeout_ms}ms)",
                )

            self.rx_logged.emit(f"[{_timestamp()}]接收←{format_hex(rx_frame)}")

            try:
                parsed = parse_rx_frame(rx_frame)
            except ValueError as exc:
                retries += 1
                if retries <= self._max_retries:
                    continue
                return SendResult(
                    success=False,
                    tx_frame=frame,
                    rx_frame=rx_frame,
                    retries=retries,
                    low_value_retries=low_value_retries,
                    error=str(exc),
                )

            if needs_retry(parsed["outputs"]):
                low_value_retries += 1
                retries += 1
                if retries <= self._max_retries:
                    continue
                return SendResult(
                    success=False,
                    tx_frame=frame,
                    rx_frame=rx_frame,
                    parsed=parsed,
                    retries=retries,
                    low_value_retries=low_value_retries,
                    error="通道原始值 < 0x1FF，已达最大重试",
                )

            return SendResult(
                success=True,
                tx_frame=frame,
                rx_frame=rx_frame,
                parsed=parsed,
                retries=retries,
                low_value_retries=low_value_retries,
            )

        return SendResult(
            success=False,
            tx_frame=frame,
            retries=retries,
            low_value_retries=low_value_retries,
            error="未知错误",
        )

    def _do_batch(self, groups: list[dict]) -> list[SendResult]:
        results: list[SendResult] = []
        total = len(groups)

        for idx, group in enumerate(groups):
            if self._stop_requested:
                break

            result = self._do_send(group["cmd"], group["channels"])
            result_group = {**group, "result": result}
            results.append(result_group)  # type: ignore[arg-type]
            self.batch_progress.emit(idx + 1, total)
            self.send_complete.emit(result)

        return results
