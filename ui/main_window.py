"""Main application window with 4-panel layout."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QThread, QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from analysis.ber import SignBERTracker, voltage_sign
from analysis.snr import SNRTracker
from comm.port_utils import format_port_log_line, list_com_ports
from comm.serial_worker import SerialWorker
from csv_loader import infer_expected_signs_from_channels, load_test_csv
from protocol.codec import build_tx_frame, format_hex, parse_cmd, raw_to_tx_voltage


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("EVB 通信质量监测")
        self.resize(1400, 900)

        self._ber_tracker = SignBERTracker()
        self._snr_tracker = SNRTracker()
        self._test_groups: list[dict] = []
        self._batch_running = False
        self._batch_results: list[dict] = []
        self._batch_index = 0
        self._chart_update_counter = 0
        self._default_expected_signs: list[int] | None = None
        self._known_ports: list[str] = []
        self._is_serial_connected = False

        self._worker = SerialWorker()
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run_loop)
        self._thread.start()

        self._setup_ui()
        self._connect_signals()

        self._port_refresh_timer = QTimer(self)
        self._port_refresh_timer.setInterval(1500)
        self._port_refresh_timer.timeout.connect(self._auto_refresh_ports)
        self._port_refresh_timer.start()

        self._refresh_ports(log=True)
        self._update_tx_preview()
        self._set_connection_status(connected=False)

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        root.addLayout(self._build_toolbar())

        splitter_v = QSplitter(Qt.Orientation.Vertical)
        splitter_top = QSplitter(Qt.Orientation.Horizontal)
        splitter_bottom = QSplitter(Qt.Orientation.Horizontal)

        splitter_top.addWidget(self._build_send_panel())
        splitter_top.addWidget(self._build_snr_panel())
        splitter_bottom.addWidget(self._build_receive_panel())
        splitter_bottom.addWidget(self._build_ber_panel())

        splitter_v.addWidget(splitter_top)
        splitter_v.addWidget(splitter_bottom)
        splitter_v.setSizes([450, 450])
        splitter_top.setSizes([600, 600])
        splitter_bottom.setSizes([600, 600])

        root.addWidget(splitter_v, stretch=1)

        self._status_indicator = QLabel("●")
        self._status_indicator.setFont(QFont("", 14))
        self._status_label = QLabel("未连接")
        status_bar = self.statusBar()
        status_bar.addWidget(self._status_indicator)
        status_bar.addWidget(self._status_label, stretch=1)
        status_bar.showMessage("插入 USB 串口后端口会自动刷新，请选择 COM 口并点击「连接」")

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()

        title = QLabel("EVB 通信质量监测")
        title.setFont(QFont("", 12, QFont.Weight.Bold))
        bar.addWidget(title)
        bar.addSpacing(20)

        bar.addWidget(QLabel("COM:"))
        self._port_combo = QComboBox()
        self._port_combo.setMinimumWidth(120)
        bar.addWidget(self._port_combo)

        self._btn_refresh = QPushButton("刷新端口")
        self._btn_refresh.setToolTip("手动刷新 COM 口列表（未连接时每 1.5 秒自动刷新）")
        self._btn_refresh.clicked.connect(lambda: self._refresh_ports(log=True))
        bar.addWidget(self._btn_refresh)

        bar.addWidget(QLabel("波特率:"))
        self._baud_combo = QComboBox()
        for b in ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]:
            self._baud_combo.addItem(b)
        self._baud_combo.setCurrentText("115200")
        bar.addWidget(self._baud_combo)

        bar.addWidget(QLabel("校验:"))
        self._parity_combo = QComboBox()
        for p in [("无(N)", "N"), ("偶(E)", "E"), ("奇(O)", "O")]:
            self._parity_combo.addItem(p[0], p[1])
        bar.addWidget(self._parity_combo)

        bar.addWidget(QLabel("停止位:"))
        self._stopbits_combo = QComboBox()
        self._stopbits_combo.addItem("1", 1)
        self._stopbits_combo.addItem("2", 2)
        bar.addWidget(self._stopbits_combo)

        bar.addWidget(QLabel("超时(ms):"))
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(50, 10000)
        self._timeout_spin.setValue(500)
        self._timeout_spin.valueChanged.connect(self._on_timeout_changed)
        bar.addWidget(self._timeout_spin)

        bar.addWidget(QLabel("重试:"))
        self._retry_spin = QSpinBox()
        self._retry_spin.setRange(0, 10)
        self._retry_spin.setValue(3)
        self._retry_spin.valueChanged.connect(self._on_retry_changed)
        bar.addWidget(self._retry_spin)

        self._btn_connect = QPushButton("连接")
        self._btn_connect.clicked.connect(self._toggle_connect)
        bar.addWidget(self._btn_connect)

        self._btn_start = QPushButton("开始测试")
        self._btn_start.clicked.connect(self._start_batch)
        bar.addWidget(self._btn_start)

        self._btn_stop = QPushButton("停止")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_batch)
        bar.addWidget(self._btn_stop)

        bar.addStretch()
        return bar

    def _build_send_panel(self) -> QGroupBox:
        box = QGroupBox("① 发送面板")
        layout = QVBoxLayout(box)

        cmd_row = QHBoxLayout()
        cmd_row.addWidget(QLabel("CMD:"))
        self._cmd_edit = QLineEdit("0D")
        self._cmd_edit.setMaximumWidth(80)
        self._cmd_edit.textChanged.connect(self._update_tx_preview)
        cmd_row.addWidget(self._cmd_edit)
        cmd_row.addStretch()
        layout.addLayout(cmd_row)

        self._channel_table = QTableWidget(12, 3)
        self._channel_table.setHorizontalHeaderLabels(["通道", "原始值", "电压(V)"])
        self._channel_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for i in range(12):
            self._channel_table.setItem(i, 0, QTableWidgetItem(f"CH{i + 1}"))
            raw_item = QTableWidgetItem("2500")
            self._channel_table.setItem(i, 1, raw_item)
            self._channel_table.setItem(i, 2, QTableWidgetItem("2.500"))
        self._channel_table.cellChanged.connect(self._on_channel_changed)
        layout.addWidget(self._channel_table)

        self._tx_preview = QLineEdit()
        self._tx_preview.setReadOnly(True)
        self._tx_preview.setFont(QFont("Consolas", 9))
        layout.addWidget(QLabel("TX 帧预览:"))
        layout.addWidget(self._tx_preview)

        btn_row = QHBoxLayout()
        self._btn_send = QPushButton("发送单帧")
        self._btn_send.clicked.connect(self._send_single)
        btn_row.addWidget(self._btn_send)

        self._btn_load_csv = QPushButton("加载 CSV")
        self._btn_load_csv.clicked.connect(self._load_csv)
        btn_row.addWidget(self._btn_load_csv)
        layout.addLayout(btn_row)

        self._progress_label = QLabel("进度: 0/0")
        layout.addWidget(self._progress_label)

        self._load_example_channels()
        return box

    def _build_receive_panel(self) -> QGroupBox:
        box = QGroupBox("② 接收面板")
        layout = QVBoxLayout(box)

        self._iteration_label = QLabel("迭代计数: --")
        self._iteration_label.setFont(QFont("", 11, QFont.Weight.Bold))
        layout.addWidget(self._iteration_label)

        self._rx_log = QTextEdit()
        self._rx_log.setReadOnly(True)
        self._rx_log.setFont(QFont("Consolas", 9))
        layout.addWidget(self._rx_log)

        self._rx_table = QTableWidget(8, 4)
        self._rx_table.setHorizontalHeaderLabels(["输出", "原始值", "电压(V)", "符号"])
        self._rx_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for i in range(8):
            self._rx_table.setItem(i, 0, QTableWidgetItem(f"OUT{i + 1}"))
            for j in range(1, 4):
                self._rx_table.setItem(i, j, QTableWidgetItem("--"))
        layout.addWidget(self._rx_table)

        btn_row = QHBoxLayout()
        self._btn_clear_log = QPushButton("清空日志")
        self._btn_clear_log.clicked.connect(self._rx_log.clear)
        btn_row.addWidget(self._btn_clear_log)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return box

    def _build_snr_panel(self) -> QGroupBox:
        box = QGroupBox("③ SNR / 质量")
        layout = QVBoxLayout(box)

        pg.setConfigOptions(antialias=True)
        self._snr_plot = pg.PlotWidget(title="实时 SNR / 稳定性")
        self._snr_plot.setLabel("left", "dB / 稳定性")
        self._snr_plot.setLabel("bottom", "测试序号")
        self._snr_plot.addLegend()
        self._snr_curves: list[pg.PlotDataItem] = []
        colors = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4", "#f032e6", "#bfef45"]
        self._snr_history: list[list[float]] = [[] for _ in range(8)]
        for i in range(8):
            curve = self._snr_plot.plot(pen=colors[i], name=f"CH{i + 1}")
            self._snr_curves.append(curve)
        layout.addWidget(self._snr_plot, stretch=2)

        self._bar_plot = pg.PlotWidget(title="通道质量柱状图")
        self._bar_plot.setLabel("left", "质量值")
        self._bar_item = pg.BarGraphItem(x=np.arange(8), height=np.zeros(8), width=0.6)
        self._bar_plot.addItem(self._bar_item)
        layout.addWidget(self._bar_plot, stretch=1)

        stats = QGridLayout()
        self._lbl_retry = QLabel("重试次数: 0")
        self._lbl_success = QLabel("成功率: N/A")
        self._lbl_iteration_snr = QLabel("当前迭代: --")
        stats.addWidget(self._lbl_retry, 0, 0)
        stats.addWidget(self._lbl_success, 0, 1)
        stats.addWidget(self._lbl_iteration_snr, 1, 0)
        layout.addLayout(stats)
        return box

    def _build_ber_panel(self) -> QGroupBox:
        box = QGroupBox("④ BER / 统计")
        layout = QVBoxLayout(box)

        self._ber_labels: dict[str, QLabel] = {}
        for key, text in [
            ("ber", "符号 BER: N/A"),
            ("success", "符号正确率: N/A"),
            ("fer", "帧错误率: N/A"),
            ("retry", "低值重试: 0"),
            ("total", "已测帧数: 0"),
        ]:
            lbl = QLabel(text)
            lbl.setFont(QFont("", 10))
            self._ber_labels[key] = lbl
            layout.addWidget(lbl)

        self._ber_table = QTableWidget(8, 3)
        self._ber_table.setHorizontalHeaderLabels(["通道", "BER", "正确/总数"])
        self._ber_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for i in range(8):
            self._ber_table.setItem(i, 0, QTableWidgetItem(f"OUT{i + 1}"))
            self._ber_table.setItem(i, 1, QTableWidgetItem("N/A"))
            self._ber_table.setItem(i, 2, QTableWidgetItem("0/0"))
        layout.addWidget(self._ber_table)

        sign_row = QHBoxLayout()
        sign_row.addWidget(QLabel("默认期望符号:"))
        self._default_sign_edit = QLineEdit("+1,-1,+1,-1,+1,-1,+1,-1")
        self._default_sign_edit.setToolTip("无 CSV exp_sign 列时使用，逗号分隔 +1/-1/0")
        sign_row.addWidget(self._default_sign_edit)
        layout.addLayout(sign_row)

        btn_row = QHBoxLayout()
        self._btn_reset_stats = QPushButton("重置统计")
        self._btn_reset_stats.clicked.connect(self._reset_stats)
        btn_row.addWidget(self._btn_reset_stats)

        self._btn_export = QPushButton("导出 CSV 报告")
        self._btn_export.clicked.connect(self._export_report)
        btn_row.addWidget(self._btn_export)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return box

    def _connect_signals(self) -> None:
        self._worker.connected.connect(self._on_connected)
        self._worker.disconnected.connect(self._on_disconnected)
        self._worker.connect_failed.connect(self._on_connect_failed)
        self._worker.error.connect(self._on_error)
        self._worker.tx_logged.connect(self._on_tx_log)
        self._worker.rx_logged.connect(self._on_rx_log)
        self._worker.send_complete.connect(self._on_send_complete)
        self._worker.batch_progress.connect(self._on_batch_progress)
        self._worker.batch_complete.connect(self._on_batch_complete)

    def _load_example_channels(self) -> None:
        """Load channels from user example TX frame (big-endian decode)."""
        example = [0x0C0D, 0x0C0D, 0x0772, 0x06B6, 0x09C4, 0x05DC, 0x0DAC, 0x0C54, 0x09C4, 0x09C4, 0x09C4, 0x09C4]
        self._channel_table.blockSignals(True)
        for i, val in enumerate(example):
            self._channel_table.item(i, 1).setText(str(val))
            self._channel_table.item(i, 2).setText(f"{raw_to_tx_voltage(val):.3f}")
        self._channel_table.blockSignals(False)
        self._cmd_edit.setText("0D")

    def _auto_refresh_ports(self) -> None:
        if not self._is_serial_connected:
            self._refresh_ports(log=False)

    def _refresh_ports(self, log: bool = False) -> None:
        current_device = self._port_combo.currentData()
        if current_device is None:
            current_text = self._port_combo.currentText()
            current_device = current_text.split(" - ")[0] if current_text else ""

        ports = list_com_ports()
        devices = [p["device"] for p in ports]

        if devices == self._known_ports and not log:
            return

        newly_added = [d for d in devices if d not in self._known_ports]
        self._known_ports = devices

        self._port_combo.blockSignals(True)
        self._port_combo.clear()
        if not ports:
            self._port_combo.addItem("(未检测到 COM 口 — 请插入 USB 串口)", "")
        else:
            for port in ports:
                self._port_combo.addItem(port["label"], port["device"])

            select_idx = -1
            if current_device:
                select_idx = self._port_combo.findData(current_device)
            if select_idx < 0 and newly_added:
                select_idx = self._port_combo.findData(newly_added[-1])
            if select_idx >= 0:
                self._port_combo.setCurrentIndex(select_idx)
        self._port_combo.blockSignals(False)

        if log:
            ts = datetime.now().strftime("%H:%M:%S")
            if ports:
                lines = [f"[{ts}] 检测到 {len(ports)} 个 COM 口:"]
                lines.extend(format_port_log_line(p) for p in ports)
            else:
                lines = [
                    f"[{ts}] 未检测到 COM 口。",
                    "  请确认 USB 线已插好、驱动已安装（CH340/CP2102/FTDI），",
                    "  并在设备管理器中查看「端口(COM 和 LPT)」。",
                ]
            self._rx_log.append("\n".join(lines))

        if not self._is_serial_connected:
            if ports:
                self.statusBar().showMessage(
                    f"检测到 {len(ports)} 个 COM 口，请选择后点击「连接」（默认 115200 8N1）"
                )
            else:
                self.statusBar().showMessage("未检测到 COM 口 — 请插入 USB 串口或安装驱动")

    def _selected_port(self) -> str:
        device = self._port_combo.currentData()
        if device:
            return str(device)
        text = self._port_combo.currentText()
        if text.startswith("("):
            return ""
        return text.split(" - ")[0].strip()

    def _set_connection_status(self, connected: bool, port: str = "", baudrate: int = 0, error: str = "") -> None:
        if connected and port:
            self._status_indicator.setStyleSheet("color: #2ecc71;")
            self._status_label.setText(f"已连接 {port} @ {baudrate} bps")
            self.statusBar().showMessage(f"串口 {port} 已打开，可以发送单帧或开始批量测试")
        elif error:
            self._status_indicator.setStyleSheet("color: #e74c3c;")
            self._status_label.setText("连接失败")
            self.statusBar().showMessage(error)
        else:
            self._status_indicator.setStyleSheet("color: #95a5a6;")
            self._status_label.setText("未连接")

    def _toggle_connect(self) -> None:
        if self._is_serial_connected:
            self._worker.disconnect_port()
            return

        port = self._selected_port()
        if not port:
            QMessageBox.warning(
                self,
                "无法连接",
                "未选择有效的 COM 口。\n\n"
                "请插入 USB 串口后点击「刷新端口」，在下拉框中选择 COM 口（如 COM3），再点击「连接」。",
            )
            self._refresh_ports(log=True)
            return

        self._btn_connect.setEnabled(False)
        self._btn_connect.setText("连接中...")
        self.statusBar().showMessage(f"正在连接 {port} ...")
        self._worker.connect_port(
            port=port,
            baudrate=int(self._baud_combo.currentText()),
            parity=self._parity_combo.currentData(),
            stopbits=self._stopbits_combo.currentData(),
        )

    def _on_connected(self, port: str, baudrate: int) -> None:
        self._is_serial_connected = True
        self._port_refresh_timer.stop()
        self._btn_connect.setEnabled(True)
        self._btn_connect.setText("断开")
        self._port_combo.setEnabled(False)
        self._btn_refresh.setEnabled(False)
        self._baud_combo.setEnabled(False)
        self._parity_combo.setEnabled(False)
        self._stopbits_combo.setEnabled(False)
        self._set_connection_status(connected=True, port=port, baudrate=baudrate)
        ts = datetime.now().strftime("%H:%M:%S")
        self._rx_log.append(
            f"[{ts}] 串口已连接: {port}, {baudrate} bps, 8N1"
        )

    def _on_disconnected(self) -> None:
        self._is_serial_connected = False
        self._port_refresh_timer.start()
        self._btn_connect.setEnabled(True)
        self._btn_connect.setText("连接")
        self._port_combo.setEnabled(True)
        self._btn_refresh.setEnabled(True)
        self._baud_combo.setEnabled(True)
        self._parity_combo.setEnabled(True)
        self._stopbits_combo.setEnabled(True)
        self._set_connection_status(connected=False)
        self._refresh_ports(log=False)
        ts = datetime.now().strftime("%H:%M:%S")
        self._rx_log.append(f"[{ts}] 串口已断开")

    def _on_connect_failed(self, msg: str) -> None:
        self._is_serial_connected = False
        self._port_refresh_timer.start()
        self._btn_connect.setEnabled(True)
        self._btn_connect.setText("连接")
        self._set_connection_status(connected=False, error=msg)
        QMessageBox.warning(self, "串口连接失败", msg)
        ts = datetime.now().strftime("%H:%M:%S")
        self._rx_log.append(f"[{ts}] 连接失败: {msg.replace(chr(10), ' ')}")

    def _on_error(self, msg: str) -> None:
        self._set_connection_status(connected=False, error=msg)
        QMessageBox.warning(self, "串口错误", msg)

    def _on_timeout_changed(self, val: int) -> None:
        self._worker.set_timeout(val)

    def _on_retry_changed(self, val: int) -> None:
        self._worker.set_max_retries(val)

    def _get_channels(self) -> list[int]:
        channels = []
        for i in range(12):
            try:
                channels.append(int(self._channel_table.item(i, 1).text()))
            except ValueError:
                channels.append(0)
        return channels

    def _on_channel_changed(self, row: int, col: int) -> None:
        if col == 1:
            try:
                raw = int(self._channel_table.item(row, 1).text())
                raw = max(0, min(4095, raw))
                self._channel_table.blockSignals(True)
                self._channel_table.item(row, 1).setText(str(raw))
                self._channel_table.item(row, 2).setText(f"{raw_to_tx_voltage(raw):.3f}")
                self._channel_table.blockSignals(False)
            except ValueError:
                pass
        self._update_tx_preview()

    def _update_tx_preview(self) -> None:
        try:
            cmd = parse_cmd(self._cmd_edit.text())
            channels = self._get_channels()
            frame = build_tx_frame(cmd, channels)
            self._tx_preview.setText(format_hex(frame))
        except (ValueError, TypeError):
            self._tx_preview.setText("(无效输入)")

    def _send_single(self) -> None:
        if not self._is_serial_connected:
            QMessageBox.warning(
                self,
                "无法发送",
                "串口未连接。请先选择 COM 口并点击「连接」。",
            )
            return
        try:
            cmd = parse_cmd(self._cmd_edit.text())
            channels = self._get_channels()
        except ValueError as exc:
            QMessageBox.warning(self, "错误", str(exc))
            return
        self._worker.send_frame(cmd, channels)

    def _load_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "加载测试 CSV", str(Path("data")), "CSV (*.csv)"
        )
        if not path:
            return
        try:
            self._test_groups = load_test_csv(path)
            self._progress_label.setText(f"进度: 0/{len(self._test_groups)}")
            QMessageBox.information(
                self, "加载成功", f"已加载 {len(self._test_groups)} 组测试数据"
            )
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "加载失败", str(exc))

    def _start_batch(self) -> None:
        if not self._is_serial_connected:
            QMessageBox.warning(
                self,
                "无法开始测试",
                "串口未连接。请先选择 COM 口并点击「连接」。",
            )
            return
        if not self._test_groups:
            QMessageBox.warning(self, "错误", "请先加载 CSV 文件")
            return
        if self._batch_running:
            return

        self._batch_running = True
        self._batch_results.clear()
        self._batch_index = 0
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._worker.send_batch(self._test_groups)

    def _stop_batch(self) -> None:
        self._worker.stop_batch()

    def _parse_default_signs(self) -> list[int] | None:
        text = self._default_sign_edit.text().strip()
        if not text:
            return None
        try:
            return [int(s.strip()) for s in text.split(",")]
        except ValueError:
            return None

    def _get_expected_signs(self, group: dict | None = None) -> list[int] | None:
        if group and group.get("expected_signs") is not None:
            return group["expected_signs"]
        defaults = self._parse_default_signs()
        if defaults and len(defaults) >= 8:
            return defaults[:8]
        if group:
            return infer_expected_signs_from_channels(group["channels"])
        return infer_expected_signs_from_channels(self._get_channels())

    def _on_tx_log(self, msg: str) -> None:
        self._rx_log.append(msg)

    def _on_rx_log(self, msg: str) -> None:
        self._rx_log.append(msg)
        cursor = self._rx_log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._rx_log.setTextCursor(cursor)

    def _on_send_complete(self, result) -> None:
        if result.parsed:
            parsed = result.parsed
            self._iteration_label.setText(f"迭代计数: {parsed['iteration']}")
            self._lbl_iteration_snr.setText(f"当前迭代: {parsed['iteration']}")

            voltages = [o["voltage"] for o in parsed["outputs"]]
            for i, out in enumerate(parsed["outputs"]):
                sign = voltage_sign(out["voltage"])
                sign_str = {1: "+", -1: "-", 0: "0"}[sign]
                self._rx_table.item(i, 1).setText(f"0x{out['raw']:03X}")
                self._rx_table.item(i, 2).setText(f"{out['voltage']:.4f}")
                self._rx_table.item(i, 3).setText(sign_str)

            self._snr_tracker.update(voltages)
            self._chart_update_counter += 1
            if self._chart_update_counter % 5 == 0:
                self._update_charts()

            group = None
            if self._batch_running and self._batch_index < len(self._test_groups):
                group = self._test_groups[self._batch_index]

            expected = self._get_expected_signs(group)
            ber_result = self._ber_tracker.record(
                expected_signs=expected,
                measured_voltages=voltages,
                had_retry=result.retries > 0,
                low_value_retry=result.low_value_retries > 0,
            )
            self._update_ber_display()

            if self._batch_running:
                group_id = group["group_id"] if group else self._batch_index + 1
                self._batch_results.append(
                    {
                        "group_id": group_id,
                        "result": result,
                        "ber": ber_result,
                        "expected_signs": expected,
                    }
                )
                self._batch_index += 1

        if not result.success and result.error:
            self._rx_log.append(f"[错误] {result.error}")

    def _on_batch_progress(self, current: int, total: int) -> None:
        self._progress_label.setText(f"进度: {current}/{total}")

    def _on_batch_complete(self, results: list) -> None:
        self._batch_running = False
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._update_charts()
        self._update_ber_display()
        QMessageBox.information(self, "完成", f"批量测试完成，共 {len(results)} 组")

    def _update_charts(self) -> None:
        values = self._snr_tracker.display_values()
        for i, val in enumerate(values):
            self._snr_history[i].append(val)
            if len(self._snr_history[i]) > 200:
                self._snr_history[i] = self._snr_history[i][-200:]
            self._snr_curves[i].setData(self._snr_history[i])

        self._bar_item.setOpts(x=np.arange(8), height=np.array(values), width=0.6)

        summary = self._ber_tracker.summary()
        self._lbl_retry.setText(f"重试次数: {summary['retry_count']}")
        if summary["success_rate"] is not None:
            self._lbl_success.setText(f"成功率: {summary['success_rate']:.2%}")
        else:
            self._lbl_success.setText("成功率: N/A")

    def _update_ber_display(self) -> None:
        summary = self._ber_tracker.summary()
        if summary["ber"] is not None:
            self._ber_labels["ber"].setText(f"符号 BER: {summary['ber']:.4%}")
            self._ber_labels["success"].setText(f"符号正确率: {summary['success_rate']:.2%}")
        else:
            self._ber_labels["ber"].setText("符号 BER: N/A")
            self._ber_labels["success"].setText("符号正确率: N/A (无期望符号)")

        if summary["frame_error_rate"] is not None:
            self._ber_labels["fer"].setText(f"帧错误率: {summary['frame_error_rate']:.4%}")
        self._ber_labels["retry"].setText(f"低值重试: {summary['low_value_retries']}")
        self._ber_labels["total"].setText(f"已测帧数: {summary['frame_total']}")

        per_ch_ber = summary["per_channel_ber"]
        for i in range(8):
            ber = per_ch_ber[i]
            total = self._ber_tracker.per_channel_total[i]
            correct = self._ber_tracker.per_channel_correct[i]
            self._ber_table.item(i, 1).setText(f"{ber:.4%}" if ber is not None else "N/A")
            self._ber_table.item(i, 2).setText(f"{correct}/{total}")

    def _reset_stats(self) -> None:
        self._ber_tracker.reset()
        self._snr_tracker.reset()
        self._snr_history = [[] for _ in range(8)]
        self._batch_results.clear()
        for i in range(8):
            self._snr_curves[i].setData([])
        self._bar_item.setOpts(x=np.arange(8), height=np.zeros(8), width=0.6)
        self._update_ber_display()
        self._lbl_retry.setText("重试次数: 0")
        self._lbl_success.setText("成功率: N/A")

    def _export_report(self) -> None:
        if not self._batch_results:
            QMessageBox.warning(self, "导出", "无测试结果可导出")
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = str(Path("reports") / f"test_report_{ts}.csv")
        path, _ = QFileDialog.getSaveFileName(self, "导出报告", default_path, "CSV (*.csv)")
        if not path:
            return

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "group_id",
                    "tx_hex",
                    "rx_hex",
                    "iteration",
                    "success",
                    "retries",
                    "low_value_retries",
                ]
                + [f"out{i}_raw" for i in range(1, 9)]
                + [f"out{i}_voltage" for i in range(1, 9)]
                + [f"out{i}_sign" for i in range(1, 9)]
                + [f"exp_sign{i}" for i in range(1, 9)]
                + [f"sign_correct{i}" for i in range(1, 9)]
            )

            for entry in self._batch_results:
                result = entry["result"]
                row = [
                    entry.get("group_id", ""),
                    format_hex(result.tx_frame) if result.tx_frame else "",
                    format_hex(result.rx_frame) if result.rx_frame else "",
                    result.parsed["iteration"] if result.parsed else "",
                    result.success,
                    result.retries,
                    result.low_value_retries,
                ]
                if result.parsed:
                    for o in result.parsed["outputs"]:
                        row.append(f"0x{o['raw']:03X}")
                    for o in result.parsed["outputs"]:
                        row.append(f"{o['voltage']:.6f}")
                    for o in result.parsed["outputs"]:
                        row.append(voltage_sign(o["voltage"]))
                else:
                    row.extend([""] * 24)

                exp = entry.get("expected_signs")
                if exp:
                    row.extend(exp[:8])
                else:
                    row.extend([""] * 8)

                ber_ch = entry.get("ber", {}).get("channels", [])
                for ch in ber_ch[:8]:
                    row.append(ch.get("correct", ""))
                while len(row) < 47:
                    row.append("")

                writer.writerow(row)

            writer.writerow([])
            summary = self._ber_tracker.summary()
            writer.writerow(["=== 汇总 ==="])
            writer.writerow(["帧总数", summary["frame_total"]])
            writer.writerow(["符号 BER", f"{summary['ber']:.6f}" if summary['ber'] is not None else "N/A"])
            writer.writerow(["帧错误率", f"{summary['frame_error_rate']:.6f}" if summary['frame_error_rate'] is not None else "N/A"])
            writer.writerow(["重试次数", summary["retry_count"]])
            writer.writerow(["低值重试", summary["low_value_retries"]])

        QMessageBox.information(self, "导出成功", f"报告已保存至:\n{path}")

    def closeEvent(self, event) -> None:
        self._port_refresh_timer.stop()
        self._worker.shutdown()
        self._thread.quit()
        self._thread.wait(2000)
        super().closeEvent(event)


def run_app() -> None:
    import sys

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
