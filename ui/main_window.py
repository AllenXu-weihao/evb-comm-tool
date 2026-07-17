"""
主窗口 — QTabWidget 四标签页
标签1: 测试执行 — 串口 | 单帧/批量入口 | 协议解析(TX/RX) | 日志
标签2: 批量测试可视化分析 — BER/迭代曲线、柱状图与 ok 协议样例
标签3: 批量测试记录表 — 3 组 FrameIdx 可切换
标签4: 单帧信息记录 — 通道表 + hex（单帧联调明细）
"""

from __future__ import annotations

import math
from time import monotonic
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QThread, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut, QShowEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from analysis.chart_live import SnrLiveAccumulator
from analysis.aggregate import (
    CaseRecord,
    analyze_by_snr,
    case_from_csv_group,
    clear_all_measured,
    clear_measured,
    converged_cases,
    count_sim_reference_error_bits,
    fill_measured,
    has_measured,
    frame_was_tested,
    recompute_measured_bit_compare,
    sim_coded_bits_for_ber,
)
from analysis.report_export import (
    filter_ber_error_rows,
    write_csv_report,
    write_excel_report,
)
from analysis.sign_compare import (
    ber_compare_label_for_mode,
    bit_label,
    chip_value_to_bit,
    compare_channels_for_mode,
    sign_label,
)
from comm.port_utils import format_port_log_line, list_com_ports
from comm.serial_worker import SendResult, SerialWorker
from csv_loader import (
    TestCsvDataset,
    TestDataLoad,
    load_test_csv,
    post_test_dataset_path,
    post_test_excel_paths,
    resolve_export_fieldnames,
    testset_dir,
    write_csv_snapshot,
)
from paste_parser import parse_pasted_testdata
from protocol.codec import (
    RX_FRAME_LEN,
    TX_FRAME_LEN,
    build_tx_frame,
    column_current_to_raw,
    format_adc_bytes_hex,
    format_hex,
    format_rx_decode,
    format_tx_decode,
    parse_mode,
    raw_to_row_voltage,
    resolve_tx_matrix_mode,
    row_voltage_to_raw,
)
from ui.channel_tables import ChannelTablesPanel
from ui.excerpt_panel import ExcerptPanel
from ui.physics_bar import PhysicsBarPanel
from ui.chart_settings import (
    DEFAULT_FRAMES_PER_SNR,
    MAX_FRAMES_PER_SNR,
    MIN_FRAMES_PER_SNR,
    get_auto_advance_snr,
    get_frames_per_snr,
    set_auto_advance_snr,
    set_frames_per_snr,
)
from ui.workers import (
    ChartAggWorker,
    CsvCheckpointWorker,
    CsvLoadWorker,
    PostTestDatasetWorker,
    PostTestExcelWorker,
)
from protocol.validator import RETRY_THRESHOLD
from ui.perf_settings import (
    BATCH_BAR_MIN_MS as _BATCH_BAR_MIN_MS,
    BATCH_CSV_SAVE_INTERVAL as _BATCH_CSV_SAVE_INTERVAL,
    BATCH_CHART_REFRESH_INTERVAL as _BATCH_CHART_REFRESH_INTERVAL,
    BATCH_PROGRESS_INTERVAL as _BATCH_PROGRESS_INTERVAL,
    BATCH_TABLE_UPDATE_INTERVAL as _BATCH_TABLE_UPDATE_INTERVAL,
    LOG_MAX_BLOCKS,
    PORT_REFRESH_MS,
    lite_banner,
)
from ui.theme import (
    COLOR_MATCH_FAIL,
    COLOR_MATCH_OK,
    COLOR_MEASURED_ROW_BG,
    COLOR_NON_CONVERGED_BG,
    COLOR_PASS_ROW_BG,
    COLOR_ERROR_CELL_BG,
    apply_app_theme,
    configure_data_table,
    qcolor,
)

# 用例表：每条用例占 2 行（仿真行 + 实测行）
_CASE_ROW_STRIDE = 2
# 大 CSV 加载时最多渲染前 N 组（超过阈值则 0 行，仅摘要 + 跳转）
_CASE_TABLE_PREVIEW_GROUPS = 20
_LARGE_CASE_TABLE_THRESHOLD = 20
# 用例表列索引
_CASE_COL_TYPE = 0
_CASE_COL_NAME = 1
_CASE_COL_SNR = 2
_CASE_COL_STATUS = 3
_CASE_COL_OUT1 = 4
_CASE_COL_ICOL1 = 8
_CASE_TABLE_COLS = 12
_CASE_TABLE_HEADERS = [
    "类型", "名称", "SNR(dB)", "状态",
    "Info1", "Info2", "Info3", "Info4",
    "Chip1", "Chip2", "Chip3", "Chip4",
]
_CASE_TABLE_TEXT = "#333333"
_MATRIX_MODE_LABELS: dict[int, str] = {1: "模式 1", 2: "模式 2", 3: "模式 3"}
_DEFAULT_WINDOW_SIZE = QSize(1280, 900)
# Win10 frame chrome estimate before first show (logical px).
_EST_FRAME_CHROME = QSize(16, 39)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DAC译码器测试工具")
        self._requested_size = QSize(_DEFAULT_WINDOW_SIZE)
        self._geometry_initialized = False
        self._adjusting_geometry = False

        self._test_cases: list[CaseRecord] = []
        self._csv_dataset: TestCsvDataset | None = None
        self._post_test_path: Path | None = None
        self._current_case: CaseRecord | None = None
        self._current_case_index = -1
        self._batch_running = False
        self._stop_flag = False
        self._csv_checkpoint_worker: CsvCheckpointWorker | None = None
        self._post_test_excel_worker: PostTestExcelWorker | None = None
        self._post_test_dataset_worker: PostTestDatasetWorker | None = None
        # 加载时快照：仿真行 CodeBit，用于测后自动监测是否被改写
        self._source_sim_coded: dict[tuple[str, str], dict[str, str]] = {}
        self._known_ports: list[str] = []
        self._is_serial_connected = False
        self._manual_case = CaseRecord(name="手动", mode=1, channels=[2500] * 12)
        self._csv_load_worker: CsvLoadWorker | None = None
        self._cases_building = False
        self._csv_load_path: str = ""
        self._default_matrix_mode = 1
        self._mode2_ber_ready = False
        self._chart_panel = None  # 延迟创建，首次打开「可视化分析」再加载 matplotlib
        self._chart_placeholder: QLabel | None = None
        self._chart_host: QWidget | None = None  # 可视化页容器（通道表常驻）
        self._chart_panel_building = False
        self._pending_batch_summary: str | None = None
        self._charts_dirty = True
        self._charts_drawn_once = False
        self._chart_agg_worker: ChartAggWorker | None = None
        self._chart_refresh_scheduled = False
        self._chart_live = SnrLiveAccumulator(max_per_snr=get_frames_per_snr())
        self._last_live_bar_ms = 0.0
        self._chart_live_timer = QTimer(self)
        self._chart_live_timer.setSingleShot(True)
        self._chart_live_timer.timeout.connect(self._flush_live_chart_refresh)
        self._batch_snr_cap_logged: set[float] = set()
        self._excerpt_panel: ExcerptPanel | None = None
        self._channel_tables: ChannelTablesPanel | None = None
        self._single_frame_tab: QWidget | None = None
        self._viz_tab_index = 1
        self._excerpt_tab_index = 2
        self._single_frame_tab_index = 3

        self._worker = SerialWorker()
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run_loop)
        self._thread.start()

        self._worker.set_timeout(3000)
        self._worker.set_max_retries(10)

        self._build_ui()
        self._relax_layout_minimums_for_screen()
        self._connect_signals()

        # Ctrl+V 仅绑定单帧相关控件，避免抢占 hex/日志框默认粘贴
        paste_targets = [self._single_group]
        if self._channel_tables is not None:
            paste_targets.extend(
                [
                    self._channel_tables,
                    self.send_table,
                    self.recv_table,
                    self.cmd_edit,
                ]
            )
        for _w in paste_targets:
            sc = QShortcut(QKeySequence.StandardKey.Paste, _w)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(self._paste_csv_row)

        self._port_refresh_timer = QTimer(self)
        self._port_refresh_timer.setInterval(PORT_REFRESH_MS)
        self._port_refresh_timer.timeout.connect(self._auto_refresh_ports)
        self._port_refresh_timer.start()

        self._refresh_ports(log=True)
        self._load_manual_channels_example()
        self._set_connection_status(connected=False)
        self._update_bulk_panel_visibility()
        banner = lite_banner()
        if banner:
            self._append_log(banner)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)

        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        self.test_tab = QWidget()
        self._build_test_tab()
        self.tab_widget.addTab(self.test_tab, "测试执行")

        # 可视化：仅图表（延迟加载 matplotlib）
        self._chart_host = QWidget()
        viz_layout = QVBoxLayout(self._chart_host)
        viz_layout.setContentsMargins(4, 4, 4, 4)
        viz_layout.setSpacing(6)
        self._chart_placeholder = QLabel(
            "首次打开本页时加载图表引擎（matplotlib）…\n弱机可设环境变量 EVB_UI_LITE=1"
        )
        self._chart_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chart_placeholder.setMinimumHeight(220)
        viz_layout.addWidget(self._chart_placeholder, stretch=1)
        self._viz_tab_index = self.tab_widget.addTab(
            self._chart_host, "批量测试可视化分析"
        )

        self._excerpt_panel = ExcerptPanel()
        self._excerpt_panel.refresh_requested.connect(self._excerpt_refresh_from_cases)
        self._excerpt_panel.open_workbook_requested.connect(self._excerpt_open_workbook)
        self._excerpt_panel.copy_pack_requested.connect(self._excerpt_copy_pack)
        self._excerpt_tab_index = self.tab_widget.addTab(
            self._excerpt_panel, "批量测试记录表"
        )

        self._single_frame_tab = QWidget()
        self._build_single_frame_tab()
        self._single_frame_tab_index = self.tab_widget.addTab(
            self._single_frame_tab, "单帧信息记录"
        )

        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("请选择 COM 口并点击「连接」")

    def _build_single_frame_tab(self) -> None:
        """界面4：单帧通道表 + hex（改电压/粘贴后在此查看与编辑）。"""
        tab_layout = QVBoxLayout(self._single_frame_tab)
        tab_layout.setContentsMargins(4, 4, 4, 4)
        tab_layout.setSpacing(6)

        tip = QLabel(
            "单帧联调明细：改行电压 / 仿真电流后，回「测试执行」点「单帧测试」。"
            "也可在本页直接编辑 hex 发送框。"
        )
        tip.setWordWrap(True)
        tab_layout.addWidget(tip)

        self._channel_tables = ChannelTablesPanel()
        self.cmd_edit = self._channel_tables.cmd_edit
        self.send_table = self._channel_tables.send_table
        self.recv_table = self._channel_tables.recv_table
        self.cmd_edit.textChanged.connect(self._update_send_preview)
        self.send_table.cellChanged.connect(self._on_send_cell_changed)
        self.recv_table.cellChanged.connect(self._on_sim_cell_changed)
        tab_layout.addWidget(self._channel_tables, stretch=2)

        hex_group = QGroupBox("单条收发 — hex")
        hex_layout = QVBoxLayout(hex_group)
        hex_layout.setSpacing(4)

        tx_row = QHBoxLayout()
        tx_row.addWidget(QLabel("发送"))
        self.tx_hex_edit = QLineEdit()
        self.tx_hex_edit.setObjectName("hexFrameEdit")
        self.tx_hex_edit.setPlaceholderText(
            f"{TX_FRAME_LEN} 字节 TX 帧 hex，空格分隔（可编辑/粘贴/复制）"
        )
        self.tx_hex_edit.editingFinished.connect(self._on_tx_hex_edited)
        tx_row.addWidget(self.tx_hex_edit, stretch=1)
        self.lbl_tx_count = QLabel("S:--")
        self.lbl_tx_count.setObjectName("hexLabel")
        self.lbl_tx_count.setMinimumWidth(44)
        tx_row.addWidget(self.lbl_tx_count)
        hex_layout.addLayout(tx_row)

        rx_row = QHBoxLayout()
        rx_row.addWidget(QLabel("接收"))
        self.rx_hex_edit = QLineEdit()
        self.rx_hex_edit.setObjectName("hexFrameEdit")
        self.rx_hex_edit.setReadOnly(True)
        self.rx_hex_edit.setPlaceholderText(
            f"{RX_FRAME_LEN} 字节 RX 帧 hex（只读，首字节为迭代次数，无 AA 帧头）"
        )
        rx_row.addWidget(self.rx_hex_edit, stretch=1)
        self.lbl_rx_count = QLabel("R:--")
        self.lbl_rx_count.setObjectName("hexLabel")
        self.lbl_rx_count.setMinimumWidth(44)
        rx_row.addWidget(self.lbl_rx_count)
        hex_layout.addLayout(rx_row)
        tab_layout.addWidget(hex_group)

        self._physics_bar = PhysicsBarPanel()
        tab_layout.addWidget(self._physics_bar, stretch=1)

    def _build_test_tab(self) -> None:
        tab_layout = QVBoxLayout(self.test_tab)
        tab_layout.setSpacing(6)

        serial_group = QGroupBox("串口配置")
        serial_layout = QHBoxLayout(serial_group)

        serial_layout.addWidget(QLabel("端口:"))
        self.cmb_port = QComboBox()
        self.cmb_port.setMinimumWidth(180)
        serial_layout.addWidget(self.cmb_port)

        serial_layout.addWidget(QLabel("波特率:"))
        self.cmb_baud = QComboBox()
        for b in ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]:
            self.cmb_baud.addItem(b)
        self.cmb_baud.setCurrentText("9600")
        serial_layout.addWidget(self.cmb_baud)

        serial_layout.addWidget(QLabel("8N1（8数据·无校验·1停止）"))
        serial_layout.addSpacing(12)

        self.btn_refresh = QPushButton("刷新端口")
        self.btn_connect = QPushButton("连接")
        self.btn_disconnect = QPushButton("断开")
        self.btn_disconnect.setEnabled(False)
        serial_layout.addWidget(self.btn_refresh)
        serial_layout.addWidget(self.btn_connect)
        serial_layout.addWidget(self.btn_disconnect)

        serial_layout.addSpacing(16)
        serial_layout.addWidget(QLabel("超时(ms):"))
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(50, 10000)
        self.timeout_spin.setValue(3000)
        self.timeout_spin.valueChanged.connect(self._on_timeout_changed)
        serial_layout.addWidget(self.timeout_spin)

        serial_layout.addWidget(QLabel("重试:"))
        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(0, 10)
        self.retry_spin.setValue(10)
        self.retry_spin.valueChanged.connect(self._on_retry_changed)
        serial_layout.addWidget(self.retry_spin)

        self.lbl_status = QLabel("○ 未连接")
        self.lbl_status.setObjectName("statusDisconnected")
        serial_layout.addWidget(self.lbl_status)
        serial_layout.addStretch()
        tab_layout.addWidget(serial_group)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        single_group = QGroupBox("单帧测试区")
        self._single_group = single_group
        single_layout = QVBoxLayout(single_group)
        single_hint = QLabel(
            "单帧：粘贴 CSV / 加载 A1 / 单帧测试。"
            "通道表与 hex 明细在「单帧信息记录」页；协议解析与日志在本页。"
        )
        single_hint.setWordWrap(True)
        single_layout.addWidget(single_hint)
        paste_row = QHBoxLayout()
        self.btn_paste_csv = QPushButton("粘贴 CSV 行")
        self.btn_paste_csv.setToolTip(
            "从 mode1.csv（或 Excel）选中一行 Ctrl+C 后粘贴。\n"
            "自动填充「单帧信息记录」页 12 路行电压、8 路仿真电流并更新 TX hex / ADC。"
        )
        paste_row.addWidget(self.btn_paste_csv)
        paste_row.addStretch()
        single_layout.addLayout(paste_row)
        self.btn_load_a1 = QPushButton("加载 A1 示例")
        self.btn_load_a1.setToolTip(
            "单帧联调：载入规范 §4.2 黄金抓包 TX（CH1 Mode=1，与 XCOM 抓包一致）。"
            "批量 Sim-to-Real 测试请用「加载 CSV」→ data/测试集/mode1.csv。"
        )
        self.btn_run_one = QPushButton("▶ 单帧测试")
        self.btn_run_one.setEnabled(False)
        single_layout.addWidget(self.btn_load_a1)
        single_layout.addWidget(self.btn_run_one)
        single_layout.addStretch()
        left_layout.addWidget(single_group)

        bulk_group = QGroupBox("批量测试区")
        bulk_layout = QVBoxLayout(bulk_group)
        load_row = QHBoxLayout()
        self.btn_load = QPushButton("加载 CSV")
        load_row.addWidget(self.btn_load)
        load_row.addSpacing(12)
        load_row.addWidget(QLabel("测试模式:"))
        self._cmb_matrix_mode = QComboBox()
        for mode_val in (1, 2, 3):
            self._cmb_matrix_mode.addItem(_MATRIX_MODE_LABELS[mode_val], mode_val)
        self._cmb_matrix_mode.setToolTip(
            "批量测试矩阵模式：加载 CSV 时按文件名/表头自动推断；\n"
            "运行全部前可手动覆盖。CH1 TX 高 4 bit = 1/2/3；\n"
            "BER=实测 vs 仿真 CodeBit（Out 硬判：正≥0→0，负→1）：\n"
            "模式1: Out[0..3]；模式2: Out[3,5,6,7]；模式3: Out[0,1]。"
        )
        load_row.addWidget(self._cmb_matrix_mode)
        load_row.addStretch()
        bulk_layout.addLayout(load_row)
        cap_row = QHBoxLayout()
        cap_row.addWidget(QLabel("BER基数(每SNR):"))
        self._frames_per_snr_spin = QSpinBox()
        self._frames_per_snr_spin.setRange(MIN_FRAMES_PER_SNR, MAX_FRAMES_PER_SNR)
        self._frames_per_snr_spin.setValue(get_frames_per_snr())
        self._frames_per_snr_spin.setToolTip(
            "BER 折线/柱图分母：每个 Eb/N0 最多计入的 ok 帧数（可设 1000、1300 等）"
        )
        self._frames_per_snr_spin.valueChanged.connect(self._on_frames_per_snr_changed)
        cap_row.addWidget(self._frames_per_snr_spin)
        self._chk_auto_advance_snr = QCheckBox("达基数自动下一 SNR")
        self._chk_auto_advance_snr.setChecked(get_auto_advance_snr())
        self._chk_auto_advance_snr.setToolTip(
            "批量测试时：当前 SNR 的 ok 收敛帧数达到基数后，跳过后续同 SNR 帧"
        )
        self._chk_auto_advance_snr.toggled.connect(self._on_auto_advance_snr_changed)
        cap_row.addWidget(self._chk_auto_advance_snr)
        cap_row.addStretch()
        bulk_layout.addLayout(cap_row)
        self._case_table_summary = QLabel("")
        self._case_table_summary.setWordWrap(True)
        self._case_table_summary.setVisible(False)
        bulk_layout.addWidget(self._case_table_summary)
        jump_row = QHBoxLayout()
        jump_row.addWidget(QLabel("跳转用例:"))
        self._jump_case_spin = QSpinBox()
        self._jump_case_spin.setMinimum(1)
        self._jump_case_spin.setMaximum(1)
        self._jump_case_spin.setEnabled(False)
        self._jump_case_spin.setToolTip("输入帧序号 1–N，跳转到对应用例（无需滚动大表）")
        self.btn_jump_case = QPushButton("跳转")
        self.btn_jump_case.setEnabled(False)
        jump_row.addWidget(self._jump_case_spin)
        jump_row.addWidget(self.btn_jump_case)
        jump_row.addStretch()
        bulk_layout.addLayout(jump_row)
        self.case_table = QTableWidget(0, _CASE_TABLE_COLS)
        self.case_table.setHorizontalHeaderLabels(_CASE_TABLE_HEADERS)
        self.case_table.setColumnHidden(_CASE_COL_SNR, True)
        self.case_table.horizontalHeader().setSectionResizeMode(_CASE_COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.case_table.horizontalHeader().setSectionResizeMode(_CASE_COL_STATUS, QHeaderView.ResizeMode.Stretch)
        for col in range(_CASE_COL_OUT1, _CASE_TABLE_COLS):
            self.case_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.case_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        configure_data_table(self.case_table)
        self.case_table.setAlternatingRowColors(False)
        bulk_layout.addWidget(self.case_table)
        bulk_btn_row = QHBoxLayout()
        self.btn_run_all = QPushButton("▶▶ 运行全部")
        self.btn_stop = QPushButton("■ 停止")
        self.btn_export = QPushButton("📊 导出报告")
        self.btn_export_dataset = QPushButton("导出测试后数据集")
        self.btn_check_dataset = QPushButton("检查数据准确性")
        self.btn_run_all.setEnabled(False)
        self.btn_stop.setEnabled(False)
        bulk_btn_row.addWidget(self.btn_run_all)
        bulk_btn_row.addWidget(self.btn_stop)
        bulk_btn_row.addStretch()
        bulk_btn_row.addWidget(self.btn_check_dataset)
        bulk_btn_row.addWidget(self.btn_export_dataset)
        bulk_btn_row.addWidget(self.btn_export)
        bulk_layout.addLayout(bulk_btn_row)
        left_layout.addWidget(bulk_group, stretch=1)
        self._bulk_panel_widgets = (
            self._case_table_summary,
            self._jump_case_spin,
            self.btn_jump_case,
            self.case_table,
            self.btn_run_all,
            self.btn_stop,
            self.btn_check_dataset,
            self.btn_export_dataset,
            self.btn_export,
        )
        tab_layout.addWidget(left, stretch=1)

        decode_group = QGroupBox("协议解析 — 发送 / 接收字段含义")
        decode_layout = QHBoxLayout(decode_group)
        decode_layout.setSpacing(8)

        tx_decode_box = QGroupBox("发送")
        tx_decode_layout = QVBoxLayout(tx_decode_box)
        tx_decode_layout.setContentsMargins(6, 6, 6, 6)
        self.decode_tx_text = QTextEdit()
        self.decode_tx_text.setObjectName("logPanel")
        self.decode_tx_text.setReadOnly(True)
        self.decode_tx_text.setMinimumHeight(220)
        self.decode_tx_text.setPlaceholderText("发送后显示 TX 逐字段含义…")
        tx_decode_layout.addWidget(self.decode_tx_text)

        rx_decode_box = QGroupBox("接收")
        rx_decode_layout = QVBoxLayout(rx_decode_box)
        rx_decode_layout.setContentsMargins(6, 6, 6, 6)
        self.decode_rx_text = QTextEdit()
        self.decode_rx_text.setObjectName("logPanel")
        self.decode_rx_text.setReadOnly(True)
        self.decode_rx_text.setMinimumHeight(220)
        self.decode_rx_text.setPlaceholderText("接收后显示 RX 逐字段含义…")
        rx_decode_layout.addWidget(self.decode_rx_text)

        decode_layout.addWidget(tx_decode_box, stretch=1)
        decode_layout.addWidget(rx_decode_box, stretch=1)
        tab_layout.addWidget(decode_group, stretch=1)

        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setObjectName("logPanel")
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(160)
        self.log_text.document().setMaximumBlockCount(LOG_MAX_BLOCKS)
        log_layout.addWidget(self.log_text)
        tab_layout.addWidget(log_group, stretch=1)

    def _destroy_chart_panel(self) -> None:
        """验算表结构升级时丢弃旧 ChartPanel。"""
        panel = self._chart_panel
        if panel is None:
            return
        host = self._chart_host
        if host is not None and host.layout() is not None:
            host.layout().removeWidget(panel)
        panel.deleteLater()
        self._chart_panel = None
        self._charts_drawn_once = False
        self._charts_dirty = True

    def _ensure_chart_panel(self):
        """首次打开「批量测试可视化分析」时再 import/创建 ChartPanel（跨机启动加速）。

        注意：必须先标记 _chart_panel，再改动布局，否则 currentChanged
        重入会再次进入本函数 → 无限重建 → 界面闪跳。
        """
        from ui.audit_schema import AUDIT_SCHEMA_VERSION
        from ui.chart_panel import ChartPanel

        if self._chart_panel is not None:
            if getattr(self._chart_panel, "audit_schema_version", None) == AUDIT_SCHEMA_VERSION:
                return self._chart_panel
            self._destroy_chart_panel()
        if getattr(self, "_chart_panel_building", False):
            return self._chart_panel  # type: ignore[return-value]

        self._chart_panel_building = True
        try:
            self.status_bar.showMessage("正在加载图表引擎…")
            panel = ChartPanel()
            panel.btn_refresh.clicked.connect(self._refresh_charts)
            panel.btn_mode2_compute_ber.clicked.connect(self._mode2_compute_ber)
            panel.btn_export.clicked.connect(self._export_charts)
            panel.frames_per_snr_changed.connect(self._on_frames_per_snr_changed)
            panel.auto_advance_snr_changed.connect(self._on_auto_advance_snr_changed)
            panel.set_frames_per_snr_value(get_frames_per_snr())
            panel.set_auto_advance_snr_checked(get_auto_advance_snr())
            panel.set_frames_per_snr_footnotes(get_frames_per_snr())
            # 先占位，阻止 tab 切换信号重入时再次创建
            self._chart_panel = panel

            host = self._chart_host
            if host is not None:
                lay = host.layout()
                if self._chart_placeholder is not None and lay is not None:
                    lay.removeWidget(self._chart_placeholder)
                    self._chart_placeholder.deleteLater()
                    self._chart_placeholder = None
                    lay.addWidget(panel, stretch=3)
            self._update_mode2_workflow_visibility()
            self.status_bar.showMessage(
                f"图表引擎已就绪 · 面板 v{AUDIT_SCHEMA_VERSION}"
            )
            return panel
        finally:
            self._chart_panel_building = False

    @property
    def chart_panel(self):
        return self._ensure_chart_panel()

    def _connect_signals(self) -> None:
        self.btn_refresh.clicked.connect(lambda: self._refresh_ports(log=True))
        self.btn_connect.clicked.connect(self._do_connect)
        self.btn_disconnect.clicked.connect(self._do_disconnect)
        self.btn_load.clicked.connect(self._load_cases)
        self.btn_load_a1.clicked.connect(self._load_a1_example)
        self.btn_paste_csv.clicked.connect(self._paste_csv_row)
        self.btn_run_one.clicked.connect(self._run_current)
        self.btn_run_all.clicked.connect(self._run_all)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_export.clicked.connect(self._export_report)
        self.btn_export_dataset.clicked.connect(self._export_post_test_dataset_dialog)
        self.btn_check_dataset.clicked.connect(self._check_dataset_accuracy)
        self.btn_jump_case.clicked.connect(self._jump_to_case)
        self._jump_case_spin.editingFinished.connect(self._jump_to_case)
        self._cmb_matrix_mode.currentIndexChanged.connect(self._on_matrix_mode_changed)

        self._worker.connected.connect(self._on_connected)
        self._worker.disconnected.connect(self._on_disconnected)
        self._worker.connect_failed.connect(self._on_connect_failed)
        self._worker.error.connect(self._on_error)
        self._worker.tx_logged.connect(self._on_tx_log)
        self._worker.rx_logged.connect(self._on_rx_log)
        self._worker.send_complete.connect(self._on_send_complete)
        self._worker.batch_progress.connect(self._on_batch_progress)
        self._worker.batch_frame_done.connect(self._on_batch_frame_done)
        self._worker.batch_complete.connect(self._on_batch_complete)

        self.case_table.cellClicked.connect(self._on_case_selected)

    def _load_manual_channels_example(self) -> None:
        self._load_a1_example(log=False)

    def _set_matrix_mode_selector(self, mode: int, *, sync_cmd: bool = True) -> None:
        """同步测试模式 QComboBox 与 `_default_matrix_mode`（CSV 推断或程序设置）。"""
        mode = max(1, min(3, int(mode)))
        self._default_matrix_mode = mode
        self._cmb_matrix_mode.blockSignals(True)
        idx = self._cmb_matrix_mode.findData(mode)
        if idx >= 0:
            self._cmb_matrix_mode.setCurrentIndex(idx)
        self._cmb_matrix_mode.blockSignals(False)
        if sync_cmd and self._current_case is None:
            self.cmd_edit.setText(str(mode))
        self._update_mode2_workflow_visibility()

    def _update_mode2_workflow_visibility(self) -> None:
        """Mode2 显示两阶段 BER 按钮；其余模式沿用「刷新图表」。"""
        if self._chart_panel is None:
            return
        mode2 = int(self._default_matrix_mode) == 2
        self._chart_panel.set_mode2_workflow(mode2)

    def _mode2_compute_ber(self) -> None:
        """Mode2：Out[3,5,6,7] CodeBit(实测) vs CodeBit(Sim)，刷新图表。"""
        if not self._test_cases:
            QMessageBox.warning(self, "Mode2 BER", "请先加载 CSV")
            return
        n = recompute_measured_bit_compare(self._test_cases)
        if n == 0:
            QMessageBox.information(
                self,
                "Mode2 BER",
                "尚无实测 RX 数据。请先运行批量测试或单帧测试。",
            )
            return
        self._append_log(
            f"===== Mode2 BER = Out[3,5,6,7] CodeBit(实测 vs Sim)，已重算 {n} 帧 ====="
        )
        self._mode2_ber_ready = True
        self._refresh_charts()
        if self._case_table_display_count(preview_only=True) > 0:
            self._update_case_list(preview_only=True)
        points = analyze_by_snr(self._test_cases, max_per_snr=get_frames_per_snr())
        if points:
            p = points[0]
            self._append_log(
                f"Eb/N0={p.snr_db:g} dB 实测 BER = {p.error_bits}/{p.channel_bits} "
                f"= {p.channel_ber:.2e}（4×已测帧数）"
            )
            if p.reference_ber is not None and math.isfinite(p.reference_ber):
                self._append_log(
                    f"Eb/N0={p.snr_db:g} dB 参考 BER = {p.reference_error_bits}/"
                    f"{p.reference_channel_bits} = {p.reference_ber:.2e} "
                    f"（Sim Out 硬判 vs 指定 CodeBit）"
                )

    def _on_matrix_mode_changed(self, _index: int) -> None:
        """用户手动切换测试模式：覆盖 CSV 推断，同步 TX 预览与单帧手动用例。"""
        data = self._cmb_matrix_mode.currentData()
        if data is None:
            return
        mode = int(data)
        self._default_matrix_mode = mode
        self._manual_case.mode = mode
        if self._current_case is None:
            self.cmd_edit.setText(str(mode))
            self._update_send_preview()
        self._update_mode2_workflow_visibility()

    def _paste_csv_row(self) -> None:
        """从剪贴板解析 testdata 行并填充单帧收发表。"""
        clip = QApplication.clipboard()
        text = clip.text() if clip else ""
        try:
            parsed = parse_pasted_testdata(text, matrix_mode=self._default_matrix_mode)
        except ValueError as exc:
            QMessageBox.warning(self, "粘贴失败", str(exc))
            return

        self.send_table.blockSignals(True)
        for i, raw in enumerate(parsed.channels):
            self.send_table.setItem(i, 1, QTableWidgetItem(f"{raw_to_row_voltage(raw):.6f}"))
            self.send_table.setItem(i, 2, QTableWidgetItem(str(raw)))
            self._sync_send_hex_row(i, raw)
        self.send_table.blockSignals(False)

        self.cmd_edit.setText(str(self._default_matrix_mode))
        self._populate_sim_table(parsed.sim_outputs)
        self._clear_chip_recv_columns()
        self._update_send_preview()

        # 单帧粘贴进入手动模式，不改动批量用例选中状态
        self._manual_case.mode = self._default_matrix_mode
        self._manual_case.channels = list(parsed.channels)
        self._manual_case.sim_outputs = parsed.sim_outputs
        self._manual_case.info_bits = parsed.info_bits
        self._manual_case.snr_db = parsed.snr_db
        self._manual_case.frame_idx = parsed.frame_idx
        self._manual_case.iter_ref = parsed.iter_ref

        meta_parts: list[str] = []
        if parsed.snr_db is not None:
            meta_parts.append(f"EbNo={parsed.snr_db:g}")
        if parsed.frame_idx is not None:
            meta_parts.append(f"FrameIdx={parsed.frame_idx}")
        meta = " ".join(meta_parts) + " → " if meta_parts else ""
        self._append_log(f"已粘贴 {meta}TX hex 已更新")

    def _load_a1_example(self, *, log: bool = True) -> None:
        """Spec §4.2 golden capture A1 — known-good TX for single-frame UART validation."""
        a1_raw = [1781, 1906, 2906, 3093, 2843, 2062, 3312, 3500, 2500, 2500, 2500, 4000]
        self.send_table.blockSignals(True)
        for i, raw in enumerate(a1_raw):
            self.send_table.setItem(i, 1, QTableWidgetItem(f"{raw_to_row_voltage(raw):.6f}"))
            self.send_table.setItem(i, 2, QTableWidgetItem(str(raw)))
            self._sync_send_hex_row(i, raw)
        self.send_table.blockSignals(False)
        self.cmd_edit.setText("1")
        self._populate_sim_table(None)
        self._clear_chip_recv_columns()
        self._update_send_preview()
        if log:
            tx_hex = format_hex(build_tx_frame(a1_raw, 1))
            self._append_log(
                f"已加载规范 §4.2 黄金抓包 A1（单帧联调）| TX: {tx_hex} | 非 Excel/CSV"
            )

    def _append_log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{ts}] {msg}")
        cursor = self.log_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)

    def _auto_refresh_ports(self) -> None:
        if not self._is_serial_connected:
            self._refresh_ports(log=False)

    def _refresh_ports(self, log: bool = False) -> None:
        current_device = self.cmb_port.currentData()
        if current_device is None:
            text = self.cmb_port.currentText()
            current_device = text.split(" - ")[0] if text and not text.startswith("(") else ""

        ports = list_com_ports()
        devices = [p["device"] for p in ports]
        if devices == self._known_ports and not log:
            return

        newly_added = [d for d in devices if d not in self._known_ports]
        self._known_ports = devices

        self.cmb_port.blockSignals(True)
        self.cmb_port.clear()
        if not ports:
            self.cmb_port.addItem("(未检测到 COM 口)", "")
        else:
            for port in ports:
                self.cmb_port.addItem(port["label"], port["device"])
            select_idx = -1
            if current_device:
                select_idx = self.cmb_port.findData(current_device)
            if select_idx < 0 and newly_added:
                select_idx = self.cmb_port.findData(newly_added[-1])
            if select_idx >= 0:
                self.cmb_port.setCurrentIndex(select_idx)
        self.cmb_port.blockSignals(False)

        if log:
            if ports:
                self._append_log(f"检测到 {len(ports)} 个 COM 口")
                for p in ports:
                    self._append_log(f"  {format_port_log_line(p)}")
            else:
                self._append_log("未检测到可用 COM 口")

    def _selected_port(self) -> str:
        device = self.cmb_port.currentData()
        if device:
            return str(device)
        text = self.cmb_port.currentText()
        if text.startswith("("):
            return ""
        return text.split(" - ")[0].strip()

    def _set_connection_status(self, connected: bool, port: str = "", baudrate: int = 0, error: str = "") -> None:
        if connected and port:
            self.lbl_status.setText("● 已连接")
            self.lbl_status.setObjectName("statusConnected")
            self.lbl_status.style().unpolish(self.lbl_status)
            self.lbl_status.style().polish(self.lbl_status)
            self.status_bar.showMessage(f"串口 {port} 已连接, {baudrate} 8N1")
        else:
            self.lbl_status.setText("○ 未连接")
            self.lbl_status.setObjectName("statusDisconnected")
            self.lbl_status.style().unpolish(self.lbl_status)
            self.lbl_status.style().polish(self.lbl_status)
            if error:
                self.status_bar.showMessage(error)
            else:
                self.status_bar.showMessage("请选择 COM 口并点击「连接」")

    def _do_connect(self) -> None:
        port = self._selected_port()
        if not port:
            QMessageBox.warning(self, "警告", "请先选择串口")
            self._refresh_ports(log=True)
            return
        self.btn_connect.setEnabled(False)
        self._worker.connect_port(port=port, baudrate=int(self.cmb_baud.currentText()))

    def _do_disconnect(self) -> None:
        self._worker.disconnect_port()

    def _on_connected(self, port: str, baudrate: int) -> None:
        self._is_serial_connected = True
        self._port_refresh_timer.stop()
        self.btn_connect.setEnabled(False)
        self.btn_disconnect.setEnabled(True)
        self.cmb_port.setEnabled(False)
        self.btn_refresh.setEnabled(False)
        self.cmb_baud.setEnabled(False)
        self._update_run_buttons()
        self._set_connection_status(connected=True, port=port, baudrate=baudrate)
        if self._test_cases and not self._batch_running:
            self._update_idle_status_message()
        self._append_log(f"串口 {port} 已连接, {baudrate} 8N1")

    def _on_disconnected(self) -> None:
        self._is_serial_connected = False
        self._port_refresh_timer.start()
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        self.cmb_port.setEnabled(True)
        self.btn_refresh.setEnabled(True)
        self.cmb_baud.setEnabled(True)
        self._update_run_buttons()
        self._set_connection_status(connected=False)
        self._refresh_ports(log=False)
        self._append_log("串口已断开")

    def _on_connect_failed(self, msg: str) -> None:
        self.btn_connect.setEnabled(True)
        self._set_connection_status(connected=False, error=msg)
        self._append_log(f"ERROR: {msg.replace(chr(10), ' ')}")
        QMessageBox.critical(self, "错误", msg)

    def _on_error(self, msg: str) -> None:
        self._append_log(f"ERROR: {msg}")

    def _on_timeout_changed(self, val: int) -> None:
        self._worker.set_timeout(val)

    def _on_retry_changed(self, val: int) -> None:
        self._worker.set_max_retries(val)

    def _get_channels_from_table(self) -> list[int]:
        channels = []
        for i in range(12):
            item = self.send_table.item(i, 2)
            try:
                channels.append(int(item.text()) if item else 2500)
            except ValueError:
                channels.append(2500)
        return channels

    def _get_sim_outputs_from_table(self) -> list[float] | None:
        """从接收表读取 8 路仿真电流；全空则返回 None。"""
        outputs: list[float] = []
        any_set = False
        for i in range(8):
            item = self.recv_table.item(i, 1)
            text = item.text().strip() if item else ""
            if not text:
                outputs.append(0.0)
                continue
            try:
                outputs.append(float(text))
                any_set = True
            except ValueError:
                outputs.append(0.0)
        return outputs if any_set else None

    def _update_sim_adc_row(self, row: int, i_col: float) -> None:
        """根据仿真电流更新 ADC raw 与 hex 列。"""
        raw = column_current_to_raw(i_col)
        self.recv_table.setItem(row, 2, QTableWidgetItem(f"0x{raw:03X}"))
        self.recv_table.setItem(row, 3, QTableWidgetItem(format_adc_bytes_hex(raw)))

    def _sync_send_hex_row(self, row: int, raw: int) -> None:
        """TX 表 hex 字节列：CH1 带模式 nibble，其余沿用 0。"""
        try:
            mode = self._resolved_tx_mode() if row == 0 else 0
        except Exception:
            mode = 0
        self.send_table.setItem(row, 3, QTableWidgetItem(format_adc_bytes_hex(raw, mode)))

    def _populate_sim_table(self, sim_outputs: list[float] | None) -> None:
        """填充 8 路仿真电流及派生 ADC/hex。"""
        self.recv_table.blockSignals(True)
        for i in range(8):
            if sim_outputs and i < len(sim_outputs):
                i_col = sim_outputs[i]
                self.recv_table.setItem(i, 1, QTableWidgetItem(f"{i_col:.6f}"))
                self._update_sim_adc_row(i, i_col)
            else:
                self.recv_table.setItem(i, 1, QTableWidgetItem(""))
                self.recv_table.setItem(i, 2, QTableWidgetItem(""))
                self.recv_table.setItem(i, 3, QTableWidgetItem(""))
        self.recv_table.blockSignals(False)

    def _on_sim_cell_changed(self, row: int, col: int) -> None:
        if col != 1:
            return
        self.recv_table.blockSignals(True)
        try:
            item = self.recv_table.item(row, 1)
            text = item.text().strip() if item else ""
            if not text:
                self.recv_table.setItem(row, 2, QTableWidgetItem(""))
                self.recv_table.setItem(row, 3, QTableWidgetItem(""))
            else:
                i_col = float(text)
                self.recv_table.setItem(row, 1, QTableWidgetItem(f"{i_col:.6f}"))
                self._update_sim_adc_row(row, i_col)
        except (ValueError, TypeError):
            pass
        self.recv_table.blockSignals(False)
        if self._current_case is not None:
            self._current_case.sim_outputs = self._get_sim_outputs_from_table()
        else:
            self._manual_case.sim_outputs = self._get_sim_outputs_from_table()

    def _on_send_cell_changed(self, row: int, col: int) -> None:
        self.send_table.blockSignals(True)
        try:
            if col == 1:
                v_row = float(self.send_table.item(row, 1).text())
                raw = row_voltage_to_raw(v_row)
                self.send_table.setItem(row, 2, QTableWidgetItem(str(raw)))
                self._sync_send_hex_row(row, raw)
            elif col == 2:
                raw = max(0, min(4095, int(self.send_table.item(row, 2).text())))
                self.send_table.setItem(row, 2, QTableWidgetItem(str(raw)))
                self.send_table.setItem(row, 1, QTableWidgetItem(f"{raw_to_row_voltage(raw):.6f}"))
                self._sync_send_hex_row(row, raw)
        except (ValueError, TypeError):
            pass
        self.send_table.blockSignals(False)
        self._update_send_preview()

    def _set_tx_hex_line(self, hex_str: str, byte_count: int | None = None) -> None:
        self.tx_hex_edit.blockSignals(True)
        self.tx_hex_edit.setText(hex_str)
        self.tx_hex_edit.blockSignals(False)
        if byte_count is not None:
            self.lbl_tx_count.setText(f"S:{byte_count}")
            return
        try:
            count = len(bytes.fromhex(hex_str.replace(" ", ""))) if hex_str else 0
        except ValueError:
            self.lbl_tx_count.setText("S:?")
            return
        self.lbl_tx_count.setText(f"S:{count}" if count else "S:--")

    def _set_rx_hex_line(self, hex_str: str, byte_count: int | None = None) -> None:
        self.rx_hex_edit.setText(hex_str)
        if byte_count is not None:
            self.lbl_rx_count.setText(f"R:{byte_count}")
            return
        try:
            count = len(bytes.fromhex(hex_str.replace(" ", ""))) if hex_str else 0
        except ValueError:
            self.lbl_rx_count.setText("R:?")
            return
        self.lbl_rx_count.setText(f"R:{count}" if count else "R:--")

    def _on_tx_hex_edited(self) -> None:
        text = self.tx_hex_edit.text().strip()
        if not text:
            self.lbl_tx_count.setText("S:--")
            return
        try:
            data = bytes.fromhex(text.replace(" ", ""))
        except ValueError:
            self.lbl_tx_count.setText("S:?")
            return
        self.lbl_tx_count.setText(f"S:{len(data)}")
        if len(data) == TX_FRAME_LEN:
            self._refresh_decode_panel(tx_frame=data)

    def _refresh_decode_panel(self, tx_frame: bytes | None = None, rx_frame: bytes | None = None) -> None:
        if tx_frame is not None:
            try:
                self.decode_tx_text.setPlainText(format_tx_decode(tx_frame))
            except ValueError as exc:
                self.decode_tx_text.setPlainText(f"TX 解析失败: {exc}")
        if rx_frame is not None:
            try:
                self.decode_rx_text.setPlainText(format_rx_decode(rx_frame))
            except ValueError as exc:
                self.decode_rx_text.setPlainText(f"RX 解析失败: {exc}")

    def _resolved_tx_mode(self, raw_mode: int | None = None) -> int:
        if raw_mode is None:
            raw_mode = parse_mode(self.cmd_edit.text())
        return resolve_tx_matrix_mode(raw_mode, self._default_matrix_mode)

    def _update_send_preview(self) -> None:
        try:
            mode = self._resolved_tx_mode()
            channels = self._get_channels_from_table()
            frame = build_tx_frame(channels, mode)
            self._set_tx_hex_line(format_hex(frame), TX_FRAME_LEN)
            self._refresh_decode_panel(tx_frame=frame)
        except (ValueError, TypeError):
            self._set_tx_hex_line("(无效输入)")

    def _active_case(self) -> CaseRecord:
        sim = self._get_sim_outputs_from_table()
        if self._current_case is not None:
            self._current_case.sim_outputs = sim
            return self._current_case
        self._manual_case.mode = self._resolved_tx_mode()
        self._manual_case.channels = self._get_channels_from_table()
        self._manual_case.sim_outputs = sim
        return self._manual_case

    def _display_send_for_case(self, tc: CaseRecord) -> None:
        self.send_table.blockSignals(True)
        self.cmd_edit.setText(str(tc.mode))
        for i, raw in enumerate(tc.channels):
            self.send_table.setItem(i, 1, QTableWidgetItem(f"{raw_to_row_voltage(raw):.6f}"))
            self.send_table.setItem(i, 2, QTableWidgetItem(str(raw)))
            self._sync_send_hex_row(i, raw)
        self.send_table.blockSignals(False)
        tx_mode = resolve_tx_matrix_mode(tc.mode, self._default_matrix_mode)
        frame = build_tx_frame(tc.channels, tx_mode)
        tc.tx_hex = format_hex(frame)
        self._set_tx_hex_line(tc.tx_hex, TX_FRAME_LEN)
        self._refresh_decode_panel(tx_frame=frame)
        self._populate_sim_table(tc.sim_outputs)
        if not tc.actual_currents:
            self._clear_chip_recv_columns()

    def _clear_chip_recv_columns(self) -> None:
        """清空芯片实测列（保留仿真参考输入）。"""
        for i in range(8):
            for j in range(4, 9):
                self.recv_table.setItem(i, j, QTableWidgetItem(""))
        self._set_rx_hex_line("")
        self.lbl_rx_count.setText("R:--")

    def _clear_recv_panel(self) -> None:
        self._populate_sim_table(None)
        self._clear_chip_recv_columns()

    def _display_recv_for_case(self, tc: CaseRecord) -> None:
        if tc.rx_hex:
            self._set_rx_hex_line(tc.rx_hex, RX_FRAME_LEN)

        sim = self._get_sim_outputs_from_table() or tc.sim_outputs or []
        ch_by_idx = {r["channel"]: r for r in tc.channel_results}
        info_bits = tc.info_bits or []
        from analysis.sign_compare import (
            ber_channel_pairs_for_mode,
            ber_meas_out_indices_for_mode,
        )

        ber_idx = set(ber_meas_out_indices_for_mode(tc.mode))
        ref_cb_by_out = {
            out_i: cb_i for out_i, cb_i in ber_channel_pairs_for_mode(tc.mode)
        }
        coded = list(tc.coded_bits or [])

        for i in range(8):
            cr = ch_by_idx.get(i + 1)
            expect = ""
            if i in ref_cb_by_out:
                cb_i = ref_cb_by_out[i]
                if coded and cb_i < len(coded):
                    expect = bit_label(int(coded[cb_i]))
            elif coded and i < len(coded):
                expect = bit_label(int(coded[i]))
            elif info_bits and i < len(info_bits) and i in ber_idx:
                expect = bit_label(info_bits[i])
            elif sim and i < len(sim) and i in ber_idx:
                expect = bit_label(chip_value_to_bit(sim[i]))

            if cr:
                chip_i = cr["chip_current"]
                self.recv_table.setItem(i, 4, QTableWidgetItem(f"{chip_i:.6f}"))
                self.recv_table.setItem(i, 5, QTableWidgetItem(bit_label(cr["chip_bit"])))
                self.recv_table.setItem(i, 6, QTableWidgetItem(bit_label(cr["info_bit"])))
                ok = cr["passed"]
                note = "BER通道" if i in ber_idx else "参考"
            elif i < len(tc.actual_currents):
                chip_i = tc.actual_currents[i]
                self.recv_table.setItem(i, 4, QTableWidgetItem(f"{chip_i:.6f}"))
                chip_bit = chip_value_to_bit(chip_i)
                self.recv_table.setItem(i, 5, QTableWidgetItem(bit_label(chip_bit)))
                self.recv_table.setItem(i, 6, QTableWidgetItem(expect))
                if expect != "" and i in ber_idx:
                    ok = bit_label(chip_bit) == expect
                else:
                    ok = None
                note = "BER通道" if i in ber_idx else "参考"
            else:
                for j in range(4, 7):
                    self.recv_table.setItem(i, j, QTableWidgetItem(""))
                ok = None
                note = ""

            if ok is None:
                icon = QTableWidgetItem("参考" if i not in ber_idx else "—")
            else:
                icon = QTableWidgetItem("✓" if ok else "✗")
                icon.setForeground(qcolor(COLOR_MATCH_OK) if ok else qcolor(COLOR_MATCH_FAIL))
            self.recv_table.setItem(i, 7, icon)
            self.recv_table.setItem(i, 8, QTableWidgetItem(note))

    def _default_csv_path(self) -> str:
        data_dir = testset_dir()
        for name in ("mode1.csv", "mode2.csv", "mode2_79.csv"):
            candidate = data_dir / name
            if candidate.is_file():
                return str(candidate)
        # 任意已有源 CSV
        csvs = sorted(data_dir.glob("*.csv"))
        if csvs:
            return str(csvs[0])
        return str(data_dir)

    def _default_csv_dir(self) -> str:
        return str(Path(self._default_csv_path()).parent)

    def _cancel_csv_load_worker(self) -> None:
        if self._csv_load_worker is None:
            return
        if self._csv_load_worker.isRunning():
            self._csv_load_worker.requestInterruption()
            self._csv_load_worker.wait(3000)
        self._csv_load_worker.deleteLater()
        self._csv_load_worker = None

    def _load_cases(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "打开测试用例", self._default_csv_path(), "CSV (*.csv)"
        )
        if not path:
            return

        self._cancel_csv_load_worker()
        self._cases_building = True
        self._csv_load_path = path
        self._test_cases = []
        self._csv_dataset = None
        self._post_test_path = None
        self._source_sim_coded = {}
        self._mode2_ber_ready = False
        self._charts_dirty = True
        self._charts_drawn_once = False
        self._current_case = None
        self._current_case_index = -1
        self._update_bulk_panel_visibility()
        self.btn_load.setEnabled(False)
        self.btn_run_all.setEnabled(False)
        self._jump_case_spin.setEnabled(False)
        self.btn_jump_case.setEnabled(False)

        self.status_bar.showMessage("CSV 已读入，正在准备…")

        worker = CsvLoadWorker(path)
        worker.csv_parsed.connect(self._on_csv_parsed)
        worker.cases_ready.connect(self._on_cases_ready)
        worker.error.connect(self._on_csv_load_error)
        worker.finished.connect(self._on_csv_worker_finished)
        self._csv_load_worker = worker
        worker.start()

    def _csv_load_summary(self, loaded: TestDataLoad, case_count: int) -> str:
        # 加载时固定「1 仿真 + 1 空白实测占位」= 2×N；重发 Attempt 只在测后导出才变多
        if loaded.interleaved:
            return (
                f"已加载 {case_count} 组（测前内存 {case_count * 2} 行："
                f"每组 1 仿真 + 1 实测占位；重发行数在测后导出才增加）"
            )
        return (
            f"已加载 {case_count} 组 → 测前展开为 {case_count * 2} 行"
            f"（每组 1 仿真 + 1 空白实测占位；非测后最终行数）"
        )

    def _on_csv_parsed(self, loaded: TestDataLoad) -> None:
        """CSV 解析完成：仅状态栏/日志提示，不弹窗（弱机避免卡死感）。"""
        case_count = len(loaded.cases)
        summary = self._csv_load_summary(loaded, case_count)
        self._append_log(f"{summary}: {self._csv_load_path}")
        self.status_bar.showMessage(f"{summary} — 正在构建用例…")
        self._case_table_summary.setVisible(True)
        self._case_table_summary.setText(
            f"共 {case_count} 组，后台构建中…请稍候再点「运行全部」"
        )
        self.case_table.setRowCount(0)
        self._jump_case_spin.setMaximum(max(1, case_count))
        self._jump_case_spin.setValue(1)
        self._set_matrix_mode_selector(loaded.matrix_mode)
        self._update_mode2_workflow_visibility()

    def _on_cases_ready(
        self, test_cases: list, loaded: TestDataLoad, source_sim_coded: object = None
    ) -> None:
        """全部 CaseRecord 就绪：启用批量测试，轻量刷新表。"""
        self._test_cases = test_cases
        self._set_matrix_mode_selector(loaded.matrix_mode)
        self._update_mode2_workflow_visibility()
        self._csv_dataset = loaded.dataset
        self._post_test_path = None
        if isinstance(source_sim_coded, dict):
            self._source_sim_coded = source_sim_coded
        else:
            from analysis.dataset_accuracy import build_source_sim_coded_map

            self._source_sim_coded = build_source_sim_coded_map(
                list(loaded.dataset.rows) if loaded.dataset else []
            )
        self._cases_building = False
        self._update_bulk_panel_visibility()
        self._jump_case_spin.setMaximum(max(1, len(test_cases)))
        self._jump_case_spin.setEnabled(True)
        self.btn_jump_case.setEnabled(True)
        self._update_case_list(preview_only=True)
        self._update_run_buttons()
        summary = self._csv_load_summary(loaded, len(test_cases))
        if self._is_serial_connected:
            self.status_bar.showMessage(f"{summary} — 可运行全部")
        else:
            self.status_bar.showMessage(f"{summary} — 请先连接串口后再「运行全部」")
        n_snap = len(self._source_sim_coded)
        self._append_log(
            f"用例内存就绪: {len(test_cases)} 组，可运行全部或跳转用例"
            f"（已快照 {n_snap} 帧仿真 CodeBit，测后将自动核对）"
        )

    def _on_csv_load_error(self, msg: str) -> None:
        self._cases_building = False
        self.status_bar.showMessage("CSV 加载失败")
        QMessageBox.critical(self, "错误", f"加载失败: {msg}")

    def _on_csv_worker_finished(self) -> None:
        self.btn_load.setEnabled(True)
        if self._csv_load_worker is not None:
            self._csv_load_worker.deleteLater()
            self._csv_load_worker = None

    def _jump_to_case(self) -> None:
        if not self._test_cases:
            QMessageBox.information(self, "跳转", "用例尚未就绪，请稍候")
            return
        idx = self._jump_case_spin.value() - 1
        if idx < 0 or idx >= len(self._test_cases):
            return
        self._current_case_index = idx
        self._current_case = self._test_cases[idx]
        display_count = self._case_table_display_count(preview_only=True)
        if idx < display_count:
            self.case_table.selectRow(self._sim_table_row(idx))
        self._display_send_for_case(self._current_case)
        if has_measured(self._current_case):
            self._display_recv_for_case(self._current_case)
        else:
            self._clear_chip_recv_columns()
        self._update_run_buttons()
        self.status_bar.showMessage(
            f"用例 {idx + 1}/{len(self._test_cases)}: {self._current_case.name}"
        )

    def _schedule_checkpoint_save(self) -> None:
        """将当前 CSV 镜像快照后写入检查点文件（不阻塞 UI）。"""
        if self._csv_dataset is None or not self._post_test_path:
            return
        worker = self._csv_checkpoint_worker
        if worker is not None and worker.isRunning():
            return
        snap = TestCsvDataset.snapshot_rows(self._csv_dataset.rows)
        fieldnames = list(self._csv_dataset.fieldnames)
        path = self._post_test_path
        self._csv_checkpoint_worker = CsvCheckpointWorker(fieldnames, snap, path)
        self._csv_checkpoint_worker.start()

    def _wait_checkpoint_save(self) -> None:
        worker = self._csv_checkpoint_worker
        if worker is not None and worker.isRunning():
            worker.wait()

    def _sync_dataset_measured(self) -> None:
        """测中由 update_measured 维护双行镜像；导出时用 build_export_rows 另建列表。"""
        if self._csv_dataset is None:
            return
        self._csv_dataset.ensure_export_fieldnames()

    def _export_post_test_dataset(
        self,
        path: Path | None = None,
        *,
        log: bool = False,
        async_export: bool = False,
        recompute_mode2: bool = False,
        done_summary: str | None = None,
    ) -> Path | None:
        """导出测后 CSV + 三份 Excel。

        async_export=True：CSV/BER/监测在后台线程，避免弱机卡死 UI。
        """
        if self._csv_dataset is None:
            return None
        out = path or self._post_test_path or post_test_dataset_path(self._csv_dataset.path)
        self._post_test_path = out
        mode = self._default_matrix_mode

        if async_export:
            prev = self._post_test_dataset_worker
            if prev is not None and prev.isRunning():
                self._append_log("等待上一批测后导出写完…")
                prev.wait()
            self._pending_batch_summary = done_summary
            if log:
                self._append_log(f"测后数据集后台导出中: {out}")
                self.status_bar.showMessage("测后导出进行中（勿关程序）…")
            worker = PostTestDatasetWorker(
                self._csv_dataset,
                self._test_cases,
                out,
                mode,
                dict(self._source_sim_coded),
                recompute_mode2=recompute_mode2,
            )
            worker.finished_ok.connect(self._on_post_test_dataset_ready)
            worker.failed.connect(self._on_post_test_dataset_failed)
            self._post_test_dataset_worker = worker
            worker.start()
            return out

        self._sync_dataset_measured()
        full_rows = self._csv_dataset.build_export_rows(self._test_cases)
        ok_rows = self._csv_dataset.build_export_rows(
            self._test_cases, exclude_comm_errors=True
        )
        self._csv_dataset.save_as(out, export_rows=full_rows)
        paths = post_test_excel_paths(out)
        fieldnames = list(self._csv_dataset.fieldnames)
        ber_rows = filter_ber_error_rows(ok_rows, fieldnames, matrix_mode=mode)

        exports = [
            ("①完整记录", paths["full"], full_rows, "full"),
            ("②1:1优选", paths["ok"], ok_rows, "ok"),
            ("③仅误码帧", paths["ber"], ber_rows, "ber"),
        ]
        self._start_post_test_excel_export(fieldnames, mode, exports, log=log)
        self._auto_verify_sim_codedbit(full_rows, fieldnames, mode, out, log=log)

        if log:
            n_err = sum(
                1
                for tc in self._test_cases
                if not tc.hardware_converged
                and (tc.rx_hex or tc.actual_currents or tc.attempt_records)
            )
            self._append_log(f"已导出测后全量 CSV: {out}")
            self._append_log(
                f"三份 Excel 后台生成中：① {paths['full'].name}  "
                f"② {paths['ok'].name}  "
                f"③ {paths['ber'].name}"
                f"（实测 BER 分母=图表每 SNR 帧数；③误码行 {len(ber_rows)}）"
                + (f"；剔除通信错误帧 {n_err}" if n_err else "；无通信错误帧")
            )
        return out

    def _on_post_test_dataset_ready(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        out = Path(payload["out"])
        full_rows = payload["full_rows"]
        ok_rows = payload["ok_rows"]
        ber_rows = payload.get("ber_rows")
        fieldnames = list(payload["fieldnames"])
        mode = int(payload["mode"])
        mode2_n = int(payload.get("mode2_n") or 0)
        tampers = list(payload.get("tampers") or [])
        frames_checked = int(payload.get("frames_checked") or 0)

        if ber_rows is None:
            ber_rows = filter_ber_error_rows(ok_rows, fieldnames, matrix_mode=mode)

        if int(mode) == 2:
            # 后台已重算（mode2_n 可为 0）；允许图表页直接画折线
            self._mode2_ber_ready = True
            if mode2_n:
                self._append_log(
                    f"===== Mode2 BER = Out[3,5,6,7] CodeBit(实测 vs Sim)，已重算 {mode2_n} 帧 ====="
                )

        paths = post_test_excel_paths(out)
        exports = [
            ("①完整记录", paths["full"], full_rows, "full"),
            ("②1:1优选", paths["ok"], ok_rows, "ok"),
            ("③仅误码帧", paths["ber"], ber_rows, "ber"),
        ]
        self._start_post_test_excel_export(fieldnames, mode, exports, log=True)

        n_err = sum(
            1
            for tc in self._test_cases
            if not tc.hardware_converged
            and (tc.rx_hex or tc.actual_currents or tc.attempt_records)
        )
        self._append_log(f"已导出测后全量 CSV: {out}")
        self._append_log(
            f"三份 Excel 后台生成中：① {paths['full'].name}  "
            f"② {paths['ok'].name}  "
            f"③ {paths['ber'].name}"
            f"（实测 BER 分母=图表每 SNR 帧数；③误码行 {len(ber_rows)}）"
            + (f"；剔除通信错误帧 {n_err}" if n_err else "；无通信错误帧")
        )

        if not self._source_sim_coded:
            self._append_log("仿真 CodeBit 监测跳过：无加载快照（请重新加载测试集）")
        else:
            self._report_sim_codedbit_check(tampers, frames_checked, log=True)

        # 测后导出完成：标记需刷新；若图表页已打开则异步画折线（不堵 UI）
        self._charts_dirty = True
        if self._chart_panel is not None and self.tab_widget.currentIndex() == self._viz_tab_index:
            self._schedule_chart_refresh()

        summary = self._pending_batch_summary
        self._pending_batch_summary = None
        if summary:
            summary += (
                f"\n\n测后 CSV:\n{out}\n\n三份 Excel 后台生成中:\n"
                f"① {paths['full'].name}\n"
                f"② {paths['ok'].name}\n"
                f"③ {paths['ber'].name}\n"
                f"（写完后日志会提示；勿立刻关程序）"
            )
            self.status_bar.showMessage("批量完成 — 测后导出进行中")
            QMessageBox.information(self, "完成", summary)
        else:
            self.status_bar.showMessage(f"测后 CSV 已写出: {out.name}")

    def _on_post_test_dataset_failed(self, err: str) -> None:
        self._pending_batch_summary = None
        self._append_log(f"测后导出失败: {err}")
        self.status_bar.showMessage("测后导出失败")
        QMessageBox.critical(self, "测后导出失败", err)

    def _report_sim_codedbit_check(
        self,
        tampers: list,
        frames_checked: int,
        *,
        log: bool,
    ) -> None:
        """输出仿真 CodeBit 监测结果（后台 worker 或同步导出共用）。"""
        if not tampers:
            if log:
                self._append_log(
                    f"仿真 CodeBit 监测通过：{frames_checked} 帧与测试集一致（未改写）"
                )
            return
        preview = "\n".join(
            f"  Frame={t.frame_idx} {t.field}: {t.message}" for t in tampers[:20]
        )
        more = f"\n  …另有 {len(tampers) - 20} 处" if len(tampers) > 20 else ""
        msg = (
            f"仿真行 CodeBit 被改写 {len(tampers)} 处（相对加载时测试集）：\n{preview}{more}"
        )
        self._append_log(f"[监测失败] {msg}")
        QMessageBox.warning(self, "仿真 CodeBit 监测 — 未通过", msg)

    def _auto_verify_sim_codedbit(
        self,
        export_rows: list[dict[str, str]],
        fieldnames: list[str],
        mode: int,
        out_path: Path,
        *,
        log: bool,
    ) -> None:
        """测后自发监测：仿真行 CodeBit 是否相对加载快照被改写。"""
        from analysis.dataset_accuracy import (
            check_export_rows_against_source,
            tamper_issues_only,
        )

        if not self._source_sim_coded:
            if log:
                self._append_log("仿真 CodeBit 监测跳过：无加载快照（请重新加载测试集）")
            return
        report = check_export_rows_against_source(
            export_rows,
            fieldnames,
            self._source_sim_coded,
            mode=mode,
            path=out_path,
        )
        self._report_sim_codedbit_check(
            tamper_issues_only(report),
            report.frames_checked,
            log=log,
        )

    def _start_post_test_excel_export(
        self,
        fieldnames: list[str],
        matrix_mode: int,
        exports: list[tuple[str, Path, list[dict[str, str]], str]],
        *,
        log: bool,
    ) -> None:
        """启动后台 Excel 导出；若上一次仍在写则先等完。"""
        prev = self._post_test_excel_worker
        if prev is not None and prev.isRunning():
            self._append_log("等待上一批 Excel 写完…")
            prev.wait()
        worker = PostTestExcelWorker(fieldnames, matrix_mode, exports)
        if log:
            worker.one_done.connect(
                lambda label, p, n: self._append_log(f"已导出{label} Excel: {p}（{n} 行）")
            )
            worker.one_failed.connect(
                lambda label, err: self._append_log(f"{label} Excel 导出失败: {err}")
            )
            worker.all_done.connect(self._on_post_test_excel_all_done)
        self._post_test_excel_worker = worker
        worker.start()

    def _on_post_test_excel_all_done(self, ok: int, fail: int) -> None:
        if fail:
            self._append_log(f"测后 Excel 完成：成功 {ok}，失败 {fail}（见上方错误）")
            self.status_bar.showMessage(f"测后 Excel：成功 {ok}，失败 {fail}")
        else:
            self._append_log(f"测后四份 Excel 已全部写完（{ok}）")
            self.status_bar.showMessage("测后四份 Excel 已写完")
        self._excerpt_update_export_hint()

    def _wait_post_test_excel_export(self) -> None:
        worker = self._post_test_excel_worker
        if worker is not None and worker.isRunning():
            worker.wait()

    def _check_dataset_accuracy(self) -> None:
        """检查当前测试集 / 测后数据集的 CodeBit·InfoBit 口径。"""
        from analysis.dataset_accuracy import (
            check_csv_file,
            check_dataset_rows,
            check_export_rows_against_source,
            check_post_test_against_source,
            tamper_issues_only,
        )

        if self._csv_dataset is None:
            QMessageBox.warning(self, "检查", "请先加载测试集 CSV")
            return

        mode = self._default_matrix_mode
        reports = []

        # 当前内存镜像：若有加载快照，一并核对仿真 CodeBit 是否被改写
        mem = check_dataset_rows(
            list(self._csv_dataset.rows),
            list(self._csv_dataset.fieldnames),
            mode=mode,
            path=self._csv_dataset.path,
            source_sim_coded=self._source_sim_coded or None,
        )
        reports.append(("当前数据集", mem))

        if self._post_test_path and Path(self._post_test_path).is_file():
            post = check_post_test_against_source(
                self._post_test_path,
                self._csv_dataset.path,
                mode=mode,
                source_sim_coded=self._source_sim_coded or None,
            )
            reports.append(("测后 vs 源测试集", post))
        elif self._csv_dataset.path.is_file():
            file_rep = check_csv_file(self._csv_dataset.path, mode=mode)
            reports.append(("源文件", file_rep))

        # 若内存已是测后交错行，再对导出口径做一次快照比对摘要
        if self._source_sim_coded and self._test_cases:
            export_rows = self._csv_dataset.build_export_rows(self._test_cases)
            export_rep = check_export_rows_against_source(
                export_rows,
                list(self._csv_dataset.fieldnames),
                self._source_sim_coded,
                mode=mode,
                path=self._post_test_path or Path("memory-export"),
            )
            n_tamper = len(tamper_issues_only(export_rep))
            self._append_log(
                f"[准确性检查/仿真CodeBit] 改写 {n_tamper} 处 / 帧 {export_rep.frames_checked}"
            )

        text_parts = []
        any_fail = False
        for title, rep in reports:
            text_parts.append(f"=== {title} ===\n{rep.summary_text()}")
            if not rep.ok:
                any_fail = True
            self._append_log(f"[准确性检查/{title}] 问题 {len(rep.issues)} 条")

        msg = "\n\n".join(text_parts)
        if any_fail:
            QMessageBox.warning(self, "数据准确性检查 — 未通过", msg)
        else:
            QMessageBox.information(self, "数据准确性检查 — 通过", msg)

    def _export_post_test_dataset_dialog(self) -> None:
        if self._csv_dataset is None:
            QMessageBox.warning(self, "导出", "请先加载 CSV")
            return
        default = str(self._post_test_path or post_test_dataset_path(self._csv_dataset.path))
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出测试后数据集",
            default,
            "CSV 文件 (*.csv)",
        )
        if not path:
            return
        try:
            out = self._export_post_test_dataset(Path(path), log=True)
            if out:
                paths = post_test_excel_paths(out)
                QMessageBox.information(
                    self,
                    "导出",
                    "测后 CSV 已保存；三份 Excel 正在后台生成（完成后日志会提示）：\n"
                    f"CSV: {out}\n\n"
                    f"① 完整记录:\n{paths['full']}\n\n"
                    f"② 去未收敛行（无 Out≈2.5）:\n{paths['ok']}\n\n"
                    f"③ 仅误码帧（误码通道高亮）:\n{paths['ber']}",
                )
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def _case_index_from_table_row(self, table_row: int) -> int:
        return table_row // _CASE_ROW_STRIDE

    def _sim_table_row(self, case_index: int) -> int:
        return case_index * _CASE_ROW_STRIDE

    def _measured_table_row(self, case_index: int) -> int:
        return case_index * _CASE_ROW_STRIDE + 1

    def _format_sim_row_status(self, tc: CaseRecord) -> str:
        if tc.iter_ref is not None:
            return f"参考迭代 {tc.iter_ref}"
        if tc.info_bits:
            return "InfoBit 已加载"
        if tc.sim_outputs:
            return "仿真 Out 已加载"
        return "— 无参考"

    def _format_measured_row_status(self, tc: CaseRecord) -> str:
        if not has_measured(tc):
            return ""
        parts: list[str] = []
        if tc.rx_hex:
            preview = tc.rx_hex.replace(" ", "")
            if len(preview) > 16:
                preview = preview[:16] + "…"
            parts.append(f"RX {preview}")
        if tc.iteration_count > 0:
            parts.append(f"iter {tc.iteration_count}")
        match_text = self._format_match_status(tc)
        if match_text:
            parts.append(match_text)
        elif tc.error:
            parts.append(tc.error)
        return " | ".join(parts)

    def _format_match_status(self, tc: CaseRecord) -> str:
        """逐帧显示参与比对的 bit 匹配数；未收敛仍参与 InfoBit 比对与 BER 聚合。"""
        parts: list[str] = []
        if tc.actual_currents and not tc.hardware_converged:
            parts.append("未收敛")
        if not tc.info_bits:
            return " | ".join(parts) if parts else "— 无 InfoBit"
        compare_n = compare_channels_for_mode(tc.mode)
        if tc.passed is not None:
            match = f"✓ {tc.match_count}/{compare_n}" if tc.match_count == compare_n else f"{tc.match_count}/{compare_n}"
            parts.append(match)
            return " | ".join(parts)
        if tc.hardware_converged and tc.match_count:
            return f"{tc.match_count}/{compare_n}"
        return " | ".join(parts) if parts else ""

    def _update_bulk_panel_visibility(self) -> None:
        has_cases = bool(self._test_cases)
        for widget in self._bulk_panel_widgets:
            widget.setVisible(has_cases)

    def _set_case_table_row(self, table_row: int, col: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.case_table.setItem(table_row, col, item)

    def _style_measured_table_row(self, table_row: int, tc: CaseRecord) -> None:
        """实测行背景：未收敛橙色 / 收敛且全匹配浅绿 / 默认浅蓝（需求书浅色标注）。"""
        if not tc.hardware_converged and frame_was_tested(tc):
            bg = qcolor(COLOR_NON_CONVERGED_BG)
        elif tc.hardware_converged and tc.passed:
            bg = qcolor(COLOR_PASS_ROW_BG)
        else:
            bg = qcolor(COLOR_MEASURED_ROW_BG)
        fg = qcolor(_CASE_TABLE_TEXT)
        for col in range(self.case_table.columnCount()):
            item = self.case_table.item(table_row, col)
            if item is None:
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.case_table.setItem(table_row, col, item)
            item.setBackground(bg)
            item.setForeground(fg)

    def _highlight_error_cells(self, case_index: int, tc: CaseRecord) -> None:
        """误码单元格黄色高亮（InfoBit 与芯片 bit 不一致，CH1–4）。"""
        if not tc.info_bits or not tc.channel_results:
            return
        sim_row = self._sim_table_row(case_index)
        meas_row = self._measured_table_row(case_index)
        err_bg = qcolor(COLOR_ERROR_CELL_BG)
        fg = qcolor(_CASE_TABLE_TEXT)
        # 未收敛实测行整行橙色，不在 Chip 列再盖黄色
        non_converged = not tc.hardware_converged and frame_was_tested(tc)
        for ch in tc.channel_results:
            if not ch.get("judged") or ch.get("passed"):
                continue
            ch_idx = ch["channel"] - 1
            info_col = _CASE_COL_OUT1 + ch_idx
            chip_col = _CASE_COL_ICOL1 + ch_idx
            cells = [(sim_row, info_col)]
            if not non_converged:
                cells.append((meas_row, chip_col))
            for row, col in cells:
                item = self.case_table.item(row, col)
                if item is None:
                    item = QTableWidgetItem("")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.case_table.setItem(row, col, item)
                item.setBackground(err_bg)
                item.setForeground(fg)

    def _populate_case_table_rows(self, case_index: int, tc: CaseRecord) -> None:
        sim_row = self._sim_table_row(case_index)
        meas_row = self._measured_table_row(case_index)
        snr_text = f"{tc.snr_db:.1f}" if tc.snr_db is not None else "—"
        info_bits = tc.info_bits or []
        ch_by_idx = {r["channel"]: r for r in tc.channel_results}

        self._set_case_table_row(sim_row, _CASE_COL_TYPE, "仿真行")
        self._set_case_table_row(sim_row, _CASE_COL_NAME, tc.name)
        self._set_case_table_row(sim_row, _CASE_COL_SNR, snr_text)
        self._set_case_table_row(sim_row, _CASE_COL_STATUS, self._format_sim_row_status(tc))
        for i in range(4):
            if i < len(info_bits):
                text = bit_label(info_bits[i])
            else:
                text = ""
            self._set_case_table_row(sim_row, _CASE_COL_OUT1 + i, text)
            self._set_case_table_row(sim_row, _CASE_COL_ICOL1 + i, "")

        self._set_case_table_row(meas_row, _CASE_COL_TYPE, "实测行")
        attempt_n = len(tc.attempt_records) if tc.attempt_records else (1 if has_measured(tc) else 0)
        if attempt_n > 1:
            last_att = tc.attempt_records[-1].attempt if tc.attempt_records else attempt_n
            self._set_case_table_row(meas_row, _CASE_COL_NAME, f"#{last_att}/{attempt_n}")
        else:
            self._set_case_table_row(meas_row, _CASE_COL_NAME, "")
        self._set_case_table_row(meas_row, _CASE_COL_SNR, "")
        self._set_case_table_row(meas_row, _CASE_COL_STATUS, self._format_measured_row_status(tc))
        for i in range(4):
            self._set_case_table_row(meas_row, _CASE_COL_OUT1 + i, "")
            cr = ch_by_idx.get(i + 1)
            if cr and has_measured(tc):
                text = bit_label(cr["chip_bit"])
            elif has_measured(tc) and i < len(tc.actual_currents):
                text = bit_label(chip_value_to_bit(tc.actual_currents[i]))
            else:
                text = ""
            self._set_case_table_row(meas_row, _CASE_COL_ICOL1 + i, text)
        self._style_measured_table_row(meas_row, tc)
        self._highlight_error_cells(case_index, tc)

    def _case_table_display_count(self, *, preview_only: bool) -> int:
        """大 CSV 仅渲染前 N 组（或 0 行仅摘要）；小数据集则全部显示。"""
        total = len(self._test_cases)
        if total == 0:
            return 0
        if total <= _LARGE_CASE_TABLE_THRESHOLD and not preview_only:
            return total
        if total > _LARGE_CASE_TABLE_THRESHOLD:
            if preview_only:
                return 0
            return min(total, _CASE_TABLE_PREVIEW_GROUPS)
        if preview_only:
            return min(total, _CASE_TABLE_PREVIEW_GROUPS)
        return total

    def _update_case_table_summary(self, *, preview_only: bool) -> None:
        total = len(self._test_cases)
        if total == 0:
            self._case_table_summary.setVisible(False)
            return
        display = self._case_table_display_count(preview_only=preview_only)
        truncated = display < total
        self._case_table_summary.setVisible(True)
        if truncated and display == 0:
            self._case_table_summary.setText(
                f"共 {total} 组 / {total * _CASE_ROW_STRIDE} 行，"
                f"表内不渲染（避免卡顿）；请用「跳转用例」选择帧序号，"
                f"批量测试使用全部数据"
            )
        elif truncated:
            self._case_table_summary.setText(
                f"共 {total} 组 / {total * _CASE_ROW_STRIDE} 行，"
                f"仅显示前 {display} 组；请用「跳转用例」定位任意帧，"
                f"批量测试使用全部数据"
            )
        else:
            self._case_table_summary.setText(
                f"共 {total} 组 / {total * _CASE_ROW_STRIDE} 行"
            )

    def _update_case_list(self, *, preview_only: bool = False) -> None:
        has_cases = bool(self._test_cases)
        self._update_bulk_panel_visibility()
        self.case_table.setColumnHidden(_CASE_COL_SNR, not has_cases)
        total = len(self._test_cases)
        display_count = self._case_table_display_count(preview_only=preview_only)
        truncated = display_count < total
        for col in range(_CASE_COL_OUT1, _CASE_TABLE_COLS):
            self.case_table.setColumnHidden(col, truncated)
        self._update_case_table_summary(preview_only=preview_only)
        self.case_table.setUpdatesEnabled(False)
        self.case_table.blockSignals(True)
        try:
            self.case_table.setRowCount(display_count * _CASE_ROW_STRIDE)
            for i in range(display_count):
                self._populate_case_table_rows(i, self._test_cases[i])
        finally:
            self.case_table.blockSignals(False)
            self.case_table.setUpdatesEnabled(True)

    def _on_case_selected(self, row: int, _col: int) -> None:
        case_index = self._case_index_from_table_row(row)
        if case_index < 0 or case_index >= len(self._test_cases):
            return
        self._current_case_index = case_index
        self._current_case = self._test_cases[case_index]
        self._display_send_for_case(self._current_case)
        if has_measured(self._current_case):
            self._display_recv_for_case(self._current_case)
        else:
            self._clear_chip_recv_columns()
        if self._current_case.attempt_records and len(self._current_case.attempt_records) > 1:
            for ar in self._current_case.attempt_records:
                conv = "收敛" if ar.hardware_converged else "未收敛"
                self._append_log(
                    f"  尝试#{ar.attempt} {conv} iter={ar.iteration_count} "
                    f"{ar.match_count}/4 RX {ar.rx_hex[:24]}…"
                )
        self._update_run_buttons()

    def _sync_frames_per_snr_spinboxes(self, value: int) -> None:
        value = set_frames_per_snr(value)
        self._frames_per_snr_spin.blockSignals(True)
        self._frames_per_snr_spin.setValue(value)
        self._frames_per_snr_spin.blockSignals(False)
        panel = self._chart_panel
        if panel is not None and hasattr(panel, "set_frames_per_snr_value"):
            panel.set_frames_per_snr_value(value)

    def _on_frames_per_snr_changed(self, value: int) -> None:
        cap = set_frames_per_snr(value)
        self._sync_frames_per_snr_spinboxes(cap)
        self._chart_live.set_max_per_snr(cap)
        if self._chart_panel is not None:
            self._chart_panel.set_frames_per_snr_footnotes(cap)
        if not self._batch_running:
            self._charts_dirty = True
            if self._chart_panel is not None and self.tab_widget.currentIndex() == self._viz_tab_index:
                self._schedule_chart_refresh()

    def _on_auto_advance_snr_changed(self, checked: bool) -> None:
        set_auto_advance_snr(checked)
        self._chk_auto_advance_snr.blockSignals(True)
        self._chk_auto_advance_snr.setChecked(checked)
        self._chk_auto_advance_snr.blockSignals(False)
        panel = self._chart_panel
        if panel is not None and hasattr(panel, "set_auto_advance_snr_checked"):
            panel.set_auto_advance_snr_checked(checked)

    def _apply_batch_snr_cap_settings(self) -> None:
        cap = get_frames_per_snr()
        enabled = get_auto_advance_snr()
        self._worker.configure_batch_snr_cap(cap=cap, enabled=enabled)
        self._batch_snr_cap_logged.clear()
        if enabled:
            self._append_log(
                f"批量策略：每 SNR BER 基数 {cap}，达标后自动切换下一 Eb/N0"
            )

    def _run_all_block_reason(self) -> str | None:
        """返回阻止「运行全部」的原因；None 表示可点击（串口在点击时再校验）。"""
        if self._batch_running:
            return "批量测试进行中"
        if self._cases_building:
            return "用例正在后台构建"
        if not self._test_cases:
            return "请先加载 CSV"
        return None

    def _update_idle_status_message(self) -> None:
        """非批量运行时，根据连接/用例状态更新状态栏提示。"""
        if self._batch_running:
            return
        reason = self._run_all_block_reason()
        if reason:
            self.status_bar.showMessage(f"「运行全部」不可用：{reason}")
            return
        n = len(self._test_cases)
        if not self._is_serial_connected:
            self.status_bar.showMessage(
                f"已加载 {n} 组 — 请先选择 COM 口并点击「连接」，再运行全部"
            )
        else:
            self.status_bar.showMessage(f"已加载 {n} 组，串口已连接 — 可运行全部")

    def _update_run_buttons(self) -> None:
        connected = self._is_serial_connected
        run_all_reason = self._run_all_block_reason()
        can_run_all = run_all_reason is None

        self.btn_run_one.setEnabled(connected)
        self.btn_run_all.setEnabled(can_run_all)
        self.btn_stop.setEnabled(self._batch_running)
        cap_locked = self._batch_running
        self._frames_per_snr_spin.setEnabled(not cap_locked)
        self._chk_auto_advance_snr.setEnabled(not cap_locked)
        panel = self._chart_panel
        if panel is not None and hasattr(panel, "set_ber_cap_controls_enabled"):
            panel.set_ber_cap_controls_enabled(not cap_locked)

        if not can_run_all:
            self.btn_run_all.setToolTip(run_all_reason or "")
        elif not connected:
            self.btn_run_all.setToolTip("点击后将提示：请先连接串口")
        else:
            self.btn_run_all.setToolTip(f"批量测试全部 {len(self._test_cases)} 帧")

        self._update_idle_status_message()

    def _update_case_row(self, index: int) -> None:
        """仅更新用例对应的两行（批量测试节流用）。"""
        if index < 0 or index >= len(self._test_cases):
            return
        if index >= self._case_table_display_count(preview_only=True):
            return
        self._populate_case_table_rows(index, self._test_cases[index])

    def _store_send_result(self, tc: CaseRecord, result: SendResult, *, case_index: int | None = None) -> None:
        """写入实测行，不刷新 UI / 日志（批量测试热路径）。"""
        fill_measured(tc, result)
        if case_index is None and tc in self._test_cases:
            case_index = self._test_cases.index(tc)
        if case_index is not None and self._csv_dataset is not None:
            self._csv_dataset.update_measured(case_index, tc)

    def _apply_send_result(
        self,
        tc: CaseRecord,
        result: SendResult,
        *,
        verbose_log: bool = True,
        update_recv_panel: bool = True,
    ) -> None:
        self._store_send_result(tc, result)

        if result.success and result.parsed and result.rx_frame:
            parsed = result.parsed
            if verbose_log:
                self._append_log(f"{tc.name}: 发送 {len(result.tx_frame)}B → {tc.tx_hex}")
                self._append_log(f"{tc.name}: 接收 {len(result.rx_frame)}B ← {tc.rx_hex}")
                if result.tx_frame and result.rx_frame:
                    self._refresh_decode_panel(tx_frame=result.tx_frame, rx_frame=result.rx_frame)
                    for line in format_tx_decode(result.tx_frame).splitlines():
                        self._append_log(f"  {line}")
                    self._append_log("  " + "─" * 40)
                    for line in format_rx_decode(result.rx_frame).splitlines():
                        self._append_log(f"  {line}")
                retry_note = ""
                if result.retries > 0:
                    retry_note = f"，PC 侧重发 {result.retries} 次"
                if result.converged:
                    self._append_log(
                        f"{tc.name}: 硬件收敛 ✓（芯片迭代 {parsed['iteration']} 次"
                        f"{retry_note}，CH1–8 raw≥0x{RETRY_THRESHOLD:03X}）"
                    )
                else:
                    self._append_log(
                        f"{tc.name}: 未收敛（已达最大重试，按最后一次回传统计）"
                        f"  芯片迭代 {parsed['iteration']}{retry_note}"
                    )
                iter_ref = tc.iter_ref
                iter_note = f"，参考迭代 {iter_ref}" if iter_ref is not None else ""
                if tc.info_bits:
                    compare_n = compare_channels_for_mode(tc.mode)
                    err = tc.channel_errors if tc.channel_errors else (compare_n - tc.match_count)
                    self._append_log(
                        f"{tc.name}: CH1–{compare_n} bit 匹配 {tc.match_count}/{compare_n}"
                        f"（{err} bit 错误，BER = mismatches / {compare_n}×N_tested）"
                        f"  芯片迭代 {parsed['iteration']}{iter_note}"
                    )
                else:
                    self._append_log(
                        f"{tc.name}: 无 InfoBit，跳过 bit 比对"
                        f"  芯片迭代 {parsed['iteration']}{iter_note}"
                    )
        elif verbose_log:
            self._append_log(f"{tc.name}: 收发失败 ✗ — {tc.error}")

        if update_recv_panel and (self._current_case is tc or tc is self._manual_case):
            self._display_recv_for_case(tc)

    def _run_current(self) -> None:
        if not self._is_serial_connected:
            QMessageBox.warning(self, "警告", "串口未连接")
            return
        tc = self._active_case()
        try:
            raw_mode = parse_mode(self.cmd_edit.text())
            mode = self._resolved_tx_mode(raw_mode)
            channels = self._get_channels_from_table()
        except ValueError as exc:
            QMessageBox.warning(self, "错误", str(exc))
            return

        tc.mode = mode
        tc.channels = channels
        tc.sim_outputs = self._get_sim_outputs_from_table()
        if tc in self._test_cases:
            clear_measured(tc)
            row = self._test_cases.index(tc)
            if self._csv_dataset is not None:
                self._csv_dataset.clear_measured_row(row)
            self._update_case_row(row)
        frame = build_tx_frame(channels, mode)
        tc.tx_hex = format_hex(frame)
        self._set_tx_hex_line(tc.tx_hex, TX_FRAME_LEN)
        self._refresh_decode_panel(tx_frame=frame)

        self._append_log(f"--- 单帧测试 {tc.name} ---")
        self._worker.send_frame(channels, mode, matrix_mode=tc.mode)

    def _run_all(self) -> None:
        if self._cases_building:
            QMessageBox.warning(self, "请稍候", "用例仍在后台构建，请稍后再运行全部")
            return
        if not self._test_cases:
            QMessageBox.warning(self, "错误", "请先加载 CSV")
            return
        if not self._is_serial_connected:
            QMessageBox.warning(self, "提示", "请先连接串口")
            return

        n = len(self._test_cases)
        self._stop_flag = False
        self._batch_running = True
        self._update_run_buttons()
        self._append_log(f"批量测试开始，共 {n} 帧")
        self.status_bar.showMessage(f"批量测试进行中: 0/{n}（等待首帧 RX…）")

        clear_all_measured(self._test_cases)
        self._mode2_ber_ready = False
        self._charts_dirty = True
        self._charts_drawn_once = False
        self._chart_live.clear()
        self._chart_live_timer.stop()
        self._last_live_bar_ms = 0.0
        if self.tab_widget.currentIndex() == self._viz_tab_index:
            panel = self._ensure_chart_panel()
            batch_mode = self._default_matrix_mode
            panel.update_charts([], matrix_mode=batch_mode)
            panel.update_ok_hex_sample([])
            self._schedule_live_chart_refresh()
        if self._csv_dataset is not None:
            self._csv_dataset.clear_all_measured()
            self._csv_dataset.ensure_export_fieldnames()
            self._post_test_path = post_test_dataset_path(self._csv_dataset.path)
            self._append_log(f"测试后数据集将保存至: {self._post_test_path}")
        if self._case_table_display_count(preview_only=True) > 0:
            self._update_case_list(preview_only=True)
        self._append_log("===== 开始批量测试（已清空内存实测行，源 CSV 不变）=====")
        batch_mode = self._default_matrix_mode
        tx_mode = resolve_tx_matrix_mode(0, batch_mode)
        for tc in self._test_cases:
            tc.mode = batch_mode
        self._append_log(
            f"批量矩阵模式: {_MATRIX_MODE_LABELS.get(batch_mode, batch_mode)} "
            f"(CH1 nibble={tx_mode}，比对 {ber_compare_label_for_mode(batch_mode)})"
        )
        self._apply_batch_snr_cap_settings()
        groups = [
            {
                "mode": tx_mode,
                "matrix_mode": batch_mode,
                "channels": tc.channels,
                "group_id": tc.name,
                "ref_coded_bits": sim_coded_bits_for_ber(tc),
                "snr_db": tc.snr_db,
                "frame_idx": tc.frame_idx,
            }
            for tc in self._test_cases
        ]
        self._worker.send_batch(groups)

    def _stop(self) -> None:
        self._stop_flag = True
        self._worker.stop_batch()
        self._append_log("===== 用户停止 =====")

    def _on_tx_log(self, _msg: str) -> None:
        """Worker hex logs are consolidated in _apply_send_result."""
        pass

    def _on_rx_log(self, _msg: str) -> None:
        pass

    def _on_send_complete(self, result: SendResult) -> None:
        tc = self._active_case()
        self._apply_send_result(tc, result)
        if tc in self._test_cases:
            row = self._test_cases.index(tc)
            self._update_case_row(row)
        # 单帧测试：仅当图表页已创建时刷新物理量（避免强制加载 matplotlib）
        if tc.success and tc.actual_currents:
            self._physics_bar.update(tc)

    def _on_batch_progress(self, current: int, total: int) -> None:
        # 首帧完成后立即更新，避免长时间显示 0/N（此前每 25 帧才刷新状态栏）
        if (
            current <= 1
            or current % _BATCH_PROGRESS_INTERVAL == 0
            or current == total
        ):
            self.status_bar.showMessage(f"批量测试进度: {current}/{total}")

    def _on_batch_frame_done(self, idx: int, total: int, item: object) -> None:
        if idx >= len(self._test_cases):
            return
        skipped = isinstance(item, dict) and bool(item.get("skipped"))
        if skipped:
            if idx % 500 == 0 or idx + 1 == total:
                self.status_bar.showMessage(
                    f"批量测试进度: {idx + 1}/{total}（跳过已达基数 SNR 帧）"
                )
            return
        result = item["result"] if isinstance(item, dict) else item  # type: ignore[index]
        tc = self._test_cases[idx]
        self._store_send_result(tc, result, case_index=idx)
        snr_done = self._worker.batch_snr_cap.consume_snr_completed()
        if snr_done is not None and snr_done not in self._batch_snr_cap_logged:
            self._batch_snr_cap_logged.add(snr_done)
            self._append_log(
                f"Eb/N0={snr_done:g} dB 已达 BER 基数 {get_frames_per_snr()}，"
                f"自动切换下一 SNR"
            )
        if not result.success and (idx < 3 or idx % 100 == 0):
            self._append_log(f"{tc.name}: 收发失败 ✗ — {result.error or tc.error}")
        elif idx == 0 and result.success:
            self._append_log(
                f"{tc.name}: 首帧完成"
                + ("（硬件收敛）" if result.converged else "（未收敛，继续批量）")
            )
        self._chart_live.upsert_case(idx, self._test_cases[idx])
        if idx % _BATCH_TABLE_UPDATE_INTERVAL == 0 or idx + 1 == total:
            self._update_case_row(idx)
        if self._csv_dataset is not None and self._post_test_path and (
            idx % _BATCH_CSV_SAVE_INTERVAL == 0 or idx + 1 == total
        ):
            self._schedule_checkpoint_save()
        if self.tab_widget.currentIndex() == self._viz_tab_index:
            self._schedule_live_chart_refresh()
        if idx % _BATCH_CHART_REFRESH_INTERVAL == 0 or idx + 1 == total:
            self._charts_dirty = True
            # 批量进行中仅用 live 折线/柱图；末帧再后台全量聚合（标注/标准差）
            if idx + 1 == total and self.tab_widget.currentIndex() == self._viz_tab_index:
                self._ensure_chart_panel()
                self._schedule_chart_refresh()

    def _schedule_live_chart_refresh(self) -> None:
        """合并批量帧更新：定时取 SnrLiveAccumulator 最新值重绘，避免每帧阻塞主线程。"""
        if self.tab_widget.currentIndex() != self._viz_tab_index:
            return
        if not self._chart_live_timer.isActive():
            self._chart_live_timer.start(_BATCH_BAR_MIN_MS)

    def _flush_live_chart_refresh(self) -> None:
        if self.tab_widget.currentIndex() != self._viz_tab_index:
            return
        self._ensure_chart_panel()
        self._refresh_live_bars_only()
        self._last_live_bar_ms = monotonic()
        if self._batch_running:
            self._chart_live_timer.start(_BATCH_BAR_MIN_MS)

    def _refresh_live_bars_only(self) -> None:
        """主线程轻量刷新折线+柱图（不跑全量 ChartAggWorker）。"""
        panel = self._chart_panel
        if panel is None:
            return
        matrix_mode = (
            int(self._test_cases[0].mode)
            if self._test_cases
            else self._default_matrix_mode
        )
        rows = self._chart_live.bar_rows()
        panel.update_bars_live(rows, matrix_mode=matrix_mode)
        cap = get_frames_per_snr()
        panel.set_live_status(
            f"图表实时 · ok≤{cap}/SNR · 已计入 {self._chart_live.ok_frame_count} 帧"
        )

    def _on_batch_complete(self, results: list) -> None:
        self._batch_running = False
        self._update_run_buttons()
        self._chart_live_timer.stop()
        self._charts_dirty = True
        if self.tab_widget.currentIndex() == self._viz_tab_index:
            self._ensure_chart_panel()
            self._schedule_chart_refresh()

        # 检查点写完后，BER 重算 + CSV 导出放到后台，避免弱机卡死
        self._wait_checkpoint_save()
        batch_mode = self._default_matrix_mode
        self._update_case_list(preview_only=True)
        converged = converged_cases(self._test_cases)
        failed = len(self._test_cases) - len(converged)
        self._append_log(
            f"===== 批量测试完成：收敛 {len(converged)}/{len(self._test_cases)}"
            + (f"，未收敛 {failed}" if failed else "")
            + " ====="
        )
        if self._test_cases and results:
            last_idx = min(len(results), len(self._test_cases)) - 1
            if last_idx >= 0:
                self._current_case_index = last_idx
                self._current_case = self._test_cases[last_idx]
                if last_idx < self._case_table_display_count(preview_only=True):
                    self.case_table.selectRow(self._sim_table_row(last_idx))
                self._display_send_for_case(self._current_case)
                if has_measured(self._current_case):
                    self._display_recv_for_case(self._current_case)
        if batch_mode == 2:
            self._append_log(
                "Mode2：批量 RX 已完成；BER 重算与测后导出在后台进行…"
            )

        done_msg = f"批量测试完成\n收敛: {len(converged)}/{len(self._test_cases)} 帧"
        if batch_mode == 2:
            done_msg += (
                "\n\nMode2 BER：Out[3,5,6,7] CodeBit(实测 vs Sim)；"
                "参考 BER = Sim Out 硬判 vs 指定 CodeBit"
                "\n测后 CSV：每帧 1 仿真行 + 各次 Attempt 实测行（行数随重试次数变化）"
            )
        out_path = self._export_post_test_dataset(
            log=True,
            async_export=True,
            recompute_mode2=(batch_mode == 2),
            done_summary=done_msg,
        )
        if out_path is None:
            QMessageBox.information(self, "完成", done_msg)

    def _on_tab_changed(self, index: int) -> None:
        if index == self._excerpt_tab_index and self._excerpt_panel is not None:
            if self._test_cases:
                self._excerpt_panel.set_cases(self._test_cases)
            self._excerpt_update_export_hint()
            return
        if index != self._viz_tab_index:
            return
        if self._chart_panel_building:
            return
        self._ensure_chart_panel()
        # 仅在有新数据或尚未画过时刷新；异步聚合，切页不卡主线程
        if self._charts_dirty or not self._charts_drawn_once:
            self._schedule_chart_refresh()
        elif self._batch_running and self._chart_live.ok_frame_count > 0:
            self._refresh_live_bars_only()

    def _excerpt_refresh_from_cases(self) -> None:
        if self._excerpt_panel is None:
            return
        if not self._test_cases:
            QMessageBox.information(self, "摘录", "尚无测试用例，请先加载 CSV 并完成测试。")
            return
        self._excerpt_panel.set_cases(self._test_cases)
        self._excerpt_update_export_hint()
        self._append_log(f"批量测试记录表已刷新：{len(self._test_cases)} 帧")

    def _excerpt_sample_three(self) -> None:
        """兼容旧入口：改为刷新整页摘录。"""
        self._excerpt_refresh_from_cases()

    def _excerpt_resolve_paths(self) -> dict[str, Path] | None:
        """当前测后 CSV + 三份 Excel 路径；无关联则 None。"""
        if not self._post_test_path:
            return None
        csv_path = Path(self._post_test_path)
        paths = post_test_excel_paths(csv_path)
        return {"csv": csv_path, **paths}

    def _excerpt_update_export_hint(self) -> None:
        if self._excerpt_panel is None:
            return
        pack = self._excerpt_resolve_paths()
        if pack is None:
            self._excerpt_panel.set_export_status("测后表: （尚未关联本次导出，请先运行全部或导出测试后数据集）")
            return
        parts = []
        for key, label in (
            ("full", "①result"),
            ("ok", "②ok"),
            ("ber", "③ber"),
            ("csv", "CSV"),
        ):
            p = pack[key]
            mark = "✓" if p.is_file() else "✗"
            parts.append(f"{label}{mark}")
        self._excerpt_panel.set_export_status(
            f"测后表: {pack['csv'].name}  [{', '.join(parts)}]  目录: {pack['csv'].parent}"
        )

    def _excerpt_open_workbook(self, kind: str) -> None:
        pack = self._excerpt_resolve_paths()
        if pack is None:
            QMessageBox.information(
                self,
                "打开表格",
                "尚无本次测后路径。请先「运行全部」或「导出测试后数据集」。",
            )
            return
        key = {"full": "full", "ok": "ok", "ber": "ber"}.get(kind, kind)
        path = pack.get(key)
        if path is None:
            return
        if not path.is_file():
            QMessageBox.warning(
                self,
                "打开表格",
                f"文件尚不存在（可能仍在后台写入）：\n{path}\n\n请稍后再试，或看日志是否已提示 Excel 写完。",
            )
            return
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
        if ok:
            self._append_log(f"已打开: {path.name}")
        else:
            QMessageBox.warning(self, "打开表格", f"系统无法打开：\n{path}")

    def _excerpt_copy_pack(self, mode: str) -> None:
        import shutil

        pack = self._excerpt_resolve_paths()
        if pack is None:
            QMessageBox.information(
                self,
                "复制整套",
                "尚无本次测后路径。请先「运行全部」或「导出测试后数据集」。",
            )
            return
        sources = [pack["csv"], pack["full"], pack["ok"], pack["ber"]]
        existing = [p for p in sources if p.is_file()]
        if not existing:
            QMessageBox.warning(
                self,
                "复制整套",
                "测后文件均不存在（可能仍在写入）。请等日志提示 Excel 写完后再复制。",
            )
            return

        if mode == "desktop":
            dest_dir = Path.home() / "Desktop"
            if not dest_dir.is_dir():
                dest_dir = Path.home() / "桌面"
            if not dest_dir.is_dir():
                QMessageBox.warning(
                    self,
                    "复制整套",
                    "找不到桌面目录，请改用「整套复制到…」自选文件夹。",
                )
                return
        else:
            chosen = QFileDialog.getExistingDirectory(
                self, "选择复制目标文件夹", str(Path.home())
            )
            if not chosen:
                return
            dest_dir = Path(chosen)

        dest_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        missing: list[str] = []
        for src in sources:
            if not src.is_file():
                missing.append(src.name)
                continue
            dst = dest_dir / src.name
            shutil.copy2(src, dst)
            copied.append(dst.name)

        msg = f"已复制 {len(copied)} 个文件到:\n{dest_dir}\n\n" + "\n".join(copied)
        if missing:
            msg += "\n\n尚未生成（未复制）:\n" + "\n".join(missing)
        self._append_log(f"测后整套已复制到 {dest_dir}（{len(copied)} 个文件）")
        QMessageBox.information(self, "复制整套", msg)
        self._excerpt_update_export_hint()

    def _schedule_chart_refresh(self) -> None:
        """切页后下一事件循环再聚合，先让标签页显示出来。"""
        if self._chart_refresh_scheduled:
            return
        self._chart_refresh_scheduled = True
        QTimer.singleShot(0, self._start_chart_agg)

    def _start_chart_agg(self) -> None:
        self._chart_refresh_scheduled = False
        if self._chart_panel is None or self._chart_panel_building:
            return
        prev = self._chart_agg_worker
        if prev is not None and prev.isRunning():
            self._charts_dirty = True
            return
        matrix_mode = (
            self._test_cases[0].mode if self._test_cases else self._default_matrix_mode
        )
        need_mode2 = int(matrix_mode) == 2 and not self._mode2_ber_ready
        self.status_bar.showMessage("正在计算 BER 曲线…")
        worker = ChartAggWorker(
            self._test_cases,
            matrix_mode=int(matrix_mode),
            need_mode2_recompute=need_mode2,
            max_per_snr=get_frames_per_snr(),
        )
        worker.finished_ok.connect(self._on_chart_agg_ready)
        worker.failed.connect(self._on_chart_agg_failed)
        self._chart_agg_worker = worker
        worker.start()

    def _on_chart_agg_ready(self, payload: object) -> None:
        if not isinstance(payload, dict) or self._chart_panel is None:
            return
        points = payload.get("points") or []
        executed = payload.get("executed") or []
        mode2_n = int(payload.get("mode2_n") or 0)
        matrix_mode = int(payload.get("matrix_mode") or self._default_matrix_mode)
        if mode2_n > 0:
            self._mode2_ber_ready = True
            self._append_log(
                f"===== Mode2 BER 自动重算 {mode2_n} 帧（图表后台聚合）====="
            )
        elif int(matrix_mode) == 2 and executed:
            self._mode2_ber_ready = True
        self._chart_panel.update_charts(points, matrix_mode=matrix_mode)
        self._chart_panel.update_ok_hex_sample(executed)
        self._chart_panel.set_cases(executed, refresh_table=False)
        self._charts_drawn_once = True
        pending = self._charts_dirty
        self._charts_dirty = False
        from ui.audit_schema import AUDIT_SCHEMA_VERSION

        if pending:
            self._schedule_chart_refresh()
            self.status_bar.showMessage(
                f"图表更新中… · 面板 v{AUDIT_SCHEMA_VERSION}"
            )
        else:
            self.status_bar.showMessage(
                f"BER 曲线已更新 · 面板 v{AUDIT_SCHEMA_VERSION}（折线 + 分子分母柱状图）"
            )

    def _on_chart_agg_failed(self, err: str) -> None:
        self._append_log(f"图表聚合失败: {err}")
        self.status_bar.showMessage("图表聚合失败")

    def _refresh_charts(self) -> None:
        """手动「刷新图表」：标记脏数据并异步重算。"""
        self._charts_dirty = True
        if self._chart_panel is None:
            self._ensure_chart_panel()
        self._schedule_chart_refresh()

    def _export_charts(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出图表", "charts/chart", "PNG prefix")
        if not path:
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_chart_panel().export_charts(path)
        self._append_log(f"图表已导出: {path}_ber.png, {path}_iter.png, {path}_phys.png")

    def _export_report(self) -> None:
        if not self._test_cases:
            QMessageBox.warning(self, "导出", "请先加载 CSV 并完成批量测试")
            return

        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "保存报告",
            "reports/test_report.xlsx",
            "Excel (*.xlsx);;CSV (*.csv)",
        )
        if not path:
            return

        try:
            if path.lower().endswith(".xlsx") or "xlsx" in selected_filter.lower():
                try:
                    write_excel_report(path, self._test_cases)
                except ImportError:
                    QMessageBox.warning(self, "导出", "缺少 openpyxl，已改为 CSV 导出")
                    path = str(Path(path).with_suffix(".csv"))
                    write_csv_report(path, self._test_cases)
            else:
                write_csv_report(path, self._test_cases)
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return

        self._append_log(f"报告已导出: {path}")

    def _screen_available_rect(self):
        screen = self.screen() or QApplication.primaryScreen()
        return screen.availableGeometry() if screen else None

    def _frame_chrome_size(self) -> QSize:
        chrome = QSize(
            self.frameGeometry().width() - self.geometry().width(),
            self.frameGeometry().height() - self.geometry().height(),
        )
        if chrome.width() <= 0 and chrome.height() <= 0:
            return QSize(_EST_FRAME_CHROME)
        return chrome

    def _max_client_size(self) -> QSize | None:
        avail = self._screen_available_rect()
        if avail is None:
            return None
        chrome = self._frame_chrome_size()
        return QSize(
            max(200, avail.width() - chrome.width()),
            max(200, avail.height() - chrome.height()),
        )

    def _relax_layout_minimums_for_screen(self) -> None:
        """Lower child minimums when layout mintrack would exceed usable screen."""
        max_client = self._max_client_size()
        if max_client is None:
            return
        hint = self.minimumSizeHint()
        if hint.height() <= max_client.height() and hint.width() <= max_client.width():
            return
        for panel in (
            getattr(self, "decode_tx_text", None),
            getattr(self, "decode_rx_text", None),
        ):
            if panel is None or hint.height() <= max_client.height():
                break
            spare = max(80, max_client.height() - (hint.height() - panel.minimumHeight()))
            panel.setMinimumHeight(min(panel.minimumHeight(), spare))
            hint = self.minimumSizeHint()
        if hint.height() > max_client.height() or hint.width() > max_client.width():
            self.setMinimumSize(
                min(hint.width(), max_client.width()),
                min(hint.height(), max_client.height()),
            )

    def _fit_window_to_available_screen(self) -> None:
        if self._adjusting_geometry:
            return
        max_client = self._max_client_size()
        avail = self._screen_available_rect()
        if max_client is None or avail is None:
            return
        self._adjusting_geometry = True
        try:
            self._relax_layout_minimums_for_screen()
            min_size = self.minimumSize()
            want = QSize(
                min(self._requested_size.width(), max_client.width()),
                min(self._requested_size.height(), max_client.height()),
            )
            if want.width() < min_size.width() or want.height() < min_size.height():
                self.showMaximized()
                self._geometry_initialized = True
                return
            if (
                not self._geometry_initialized
                or self.width() > max_client.width()
                or self.height() > max_client.height()
            ):
                self.resize(
                    min(self.width(), want.width()) if self._geometry_initialized else want.width(),
                    min(self.height(), want.height()) if self._geometry_initialized else want.height(),
                )
                frame = self.frameGeometry()
                x = avail.x() + max(0, (avail.width() - frame.width()) // 2)
                y = avail.y()
                if self.x() != x or self.y() != y:
                    self.move(x, y)
            self._geometry_initialized = True
        finally:
            self._adjusting_geometry = False

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._geometry_initialized:
            self._fit_window_to_available_screen()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._adjusting_geometry or self.isMaximized() or self.isFullScreen():
            return
        max_client = self._max_client_size()
        if max_client is None:
            return
        if self.width() > max_client.width() or self.height() > max_client.height():
            self._adjusting_geometry = True
            try:
                self.resize(
                    min(self.width(), max_client.width()),
                    min(self.height(), max_client.height()),
                )
            finally:
                self._adjusting_geometry = False

    def closeEvent(self, event) -> None:
        self._port_refresh_timer.stop()
        self._cancel_csv_load_worker()
        self._wait_checkpoint_save()
        worker = self._post_test_dataset_worker
        if worker is not None and worker.isRunning():
            worker.wait()
        self._wait_post_test_excel_export()
        self._worker.shutdown()
        self._thread.quit()
        self._thread.wait(2000)
        super().closeEvent(event)


def run_app() -> None:
    import sys

    app = QApplication(sys.argv)
    apply_app_theme(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
