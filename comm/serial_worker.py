"""Serial communication worker running in QThread."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from queue import Empty, Queue

import serial
from PyQt6.QtCore import QObject, pyqtSignal

from comm.batch_snr_cap import BatchSnrCapGuard
from protocol.codec import RX_FRAME_LEN, build_tx_frame, format_hex, parse_rx_frame
from protocol.validator import needs_retry
from analysis.sign_compare import coded_bits_from_outputs


def _rx_has_ber_error(
    parsed: dict,
    ref_coded_bits: list[int] | None,
    matrix_mode: int,
) -> bool:
    """回传已收敛但 CodeBit 与仿真参考不一致 → 继续重发。"""
    if not ref_coded_bits:
        return False
    currents = [o["current"] for o in parsed.get("outputs", [])]
    meas = coded_bits_from_outputs(currents, matrix_mode)
    n = min(len(meas), len(ref_coded_bits))
    return any(int(meas[j]) != int(ref_coded_bits[j]) for j in range(n))


@dataclass
class RxAttempt:
    """单次成功解析的 RX（含未收敛需重发的那次）。"""

    rx_frame: bytes
    parsed: dict
    converged: bool  # CH1–8 raw ≥ 0x2FF


@dataclass
class SendResult:
    """Result of a single send/receive cycle.

    success=True means a valid 17 B RX was received (last attempt counts for BER).
    converged=True when CH1–8 raw >= 0x2FF on that last RX.
    attempts 记录每次有效 RX（含重发过程中的未收敛帧），用于导出多行实测。
    """

    success: bool
    tx_frame: bytes
    rx_frame: bytes | None = None
    parsed: dict | None = None
    converged: bool = False
    retries: int = 0
    low_value_retries: int = 0
    error: str = ""
    attempts: list[RxAttempt] = field(default_factory=list)


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
    batch_frame_done = pyqtSignal(int, int, object)  # index (0-based), total, result_group
    batch_complete = pyqtSignal(list)  # list[SendResult]

    def __init__(self) -> None:
        super().__init__()
        self._serial: serial.Serial | None = None
        self._thread_running = True
        self._stop_requested = False
        self._cmd_queue: Queue = Queue()
        self._rx_buffer = bytearray()
        self._timeout_ms = 500
        self._max_retries = 5  # CH1–8 未收敛时最多重发 5 次（共 6 次 TX）
        self._quiet_log = False  # 批量测试时抑制逐帧 hex 日志
        self._connected_port = ""
        self._connected_baud = 0
        self._batch_snr_cap = BatchSnrCapGuard(cap=1000, enabled=False)

    def configure_batch_snr_cap(self, *, cap: int, enabled: bool) -> None:
        self._batch_snr_cap.reset(cap=cap, enabled=enabled)

    @property
    def batch_snr_cap(self) -> BatchSnrCapGuard:
        return self._batch_snr_cap

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def set_timeout(self, ms: int) -> None:
        self._timeout_ms = max(50, ms)

    def set_max_retries(self, n: int) -> None:
        """设置 CH1–8 raw < 0x2FF 时的最大重发次数（不含首次发送）。"""
        self._max_retries = max(0, n)

    def connect_port(
        self,
        port: str,
        baudrate: int = 9600,
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

    def send_frame(self, channels: list[int], mode: int = 1, *, matrix_mode: int | None = None) -> None:
        """Queue a single frame send (processed in worker loop)."""
        self._cmd_queue.put(
            {
                "type": "send",
                "mode": mode,
                "matrix_mode": matrix_mode,
                "channels": channels,
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
                result = self._do_send(
                    cmd["channels"],
                    cmd.get("mode", 1),
                    matrix_mode=cmd.get("matrix_mode"),
                )
                self.send_complete.emit(result)
            elif cmd_type == "batch":
                try:
                    results = self._do_batch(cmd["groups"])
                except Exception as exc:
                    self.error.emit(f"批量测试异常: {exc}")
                    results = []
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

    def _wait_rx_frame(self) -> bytes | None:
        """阻塞读满 17 B，超时与 _timeout_ms 一致（替代 5 ms 空转轮询）。"""
        if not self.is_connected or self._serial is None:
            return None
        deadline = time.monotonic() + self._timeout_ms / 1000.0
        while time.monotonic() < deadline:
            if len(self._rx_buffer) >= RX_FRAME_LEN:
                return self._read_rx_frame()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            need = RX_FRAME_LEN - len(self._rx_buffer)
            ser = self._serial
            if ser is None:
                return None
            old_timeout = ser.timeout
            try:
                # 一次阻塞读剩余字节，避免 sleep(5ms) 空转
                ser.timeout = remaining
                chunk = ser.read(need)
                if chunk:
                    self._rx_buffer.extend(chunk)
            except serial.SerialException as exc:
                self.error.emit(f"读取错误: {exc}")
                self._do_disconnect()
                return None
            finally:
                if self._serial is ser:
                    try:
                        ser.timeout = old_timeout
                    except (serial.SerialException, OSError, AttributeError):
                        pass
        self._poll_serial()
        return self._read_rx_frame()

    def _do_send(
        self,
        channels: list[int],
        mode: int = 1,
        *,
        matrix_mode: int | None = None,
        ref_coded_bits: list[int] | None = None,
    ) -> SendResult:
        if not self.is_connected:
            return SendResult(
                success=False,
                tx_frame=b"",
                error="串口未连接",
            )

        frame = build_tx_frame(channels, mode)
        low_value_retries = 0
        attempts: list[RxAttempt] = []
        max_attempts = self._max_retries + 1
        retries = 0
        ber_mode = int(matrix_mode if matrix_mode is not None else mode)

        for tx_count in range(1, max_attempts + 1):
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

            if not self._quiet_log:
                self.tx_logged.emit(f"[{_timestamp()}]发送→{format_hex(frame)}")

            rx_frame = self._wait_rx_frame()

            if rx_frame is None:
                retries += 1
                if tx_count < max_attempts:
                    continue
                return SendResult(
                    success=False,
                    tx_frame=frame,
                    retries=retries,
                    low_value_retries=low_value_retries,
                    error=f"接收超时 ({self._timeout_ms}ms)",
                )

            if not self._quiet_log:
                self.rx_logged.emit(f"[{_timestamp()}]接收←{format_hex(rx_frame)}")

            try:
                parsed = parse_rx_frame(rx_frame)
            except ValueError as exc:
                retries += 1
                if tx_count < max_attempts:
                    continue
                return SendResult(
                    success=False,
                    tx_frame=frame,
                    rx_frame=rx_frame,
                    retries=retries,
                    low_value_retries=low_value_retries,
                    error=str(exc),
                )

            hw_converged = not needs_retry(parsed["outputs"])
            attempts.append(
                RxAttempt(
                    rx_frame=rx_frame,
                    parsed=parsed,
                    converged=hw_converged,
                )
            )

            if hw_converged:
                if _rx_has_ber_error(parsed, ref_coded_bits, ber_mode):
                    if tx_count < max_attempts:
                        retries += 1
                        continue
                return SendResult(
                    success=True,
                    converged=True,
                    tx_frame=frame,
                    rx_frame=rx_frame,
                    parsed=parsed,
                    retries=retries,
                    low_value_retries=low_value_retries,
                    attempts=attempts,
                )

            low_value_retries += 1
            retries += 1
            if tx_count < max_attempts:
                continue
            return SendResult(
                success=True,
                converged=False,
                tx_frame=frame,
                rx_frame=rx_frame,
                parsed=parsed,
                retries=retries,
                low_value_retries=low_value_retries,
                attempts=attempts,
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
        skipped = 0
        self._quiet_log = True
        try:
            for idx, group in enumerate(groups):
                if self._stop_requested:
                    break

                snr = group.get("snr_db")
                if self._batch_snr_cap.is_snr_full(
                    float(snr) if snr is not None else None
                ):
                    skipped += 1
                    skip_group = {
                        **group,
                        "result": SendResult(success=False, tx_frame=b"", error="skipped_snr_cap"),
                        "skipped": True,
                    }
                    results.append(skip_group)  # type: ignore[arg-type]
                    self.batch_frame_done.emit(idx, total, skip_group)
                    self.batch_progress.emit(idx + 1, total)
                    continue

                result = self._do_send(
                    group["channels"],
                    group.get("mode", 1),
                    matrix_mode=group.get("matrix_mode"),
                    ref_coded_bits=group.get("ref_coded_bits"),
                )
                if (
                    self._batch_snr_cap.enabled
                    and result.success
                    and result.converged
                    and snr is not None
                ):
                    self._batch_snr_cap.record_converged_frame(float(snr))

                result_group = {**group, "result": result, "skipped": False}
                results.append(result_group)  # type: ignore[arg-type]
                self.batch_frame_done.emit(idx, total, result_group)
                self.batch_progress.emit(idx + 1, total)
        finally:
            self._quiet_log = False
            if skipped:
                self.tx_logged.emit(
                    f"[批量] 已跳过 {skipped} 帧（当前 SNR 已达 BER 基数 {self._batch_snr_cap.cap}）"
                )

        return results
