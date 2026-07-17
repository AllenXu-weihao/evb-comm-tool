"""批量测试记录表 — 整页展示多条用例的 TX/RX 物理量解码（约 10 条/页）。"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analysis.aggregate import CaseRecord, has_measured
from protocol.codec import raw_to_row_voltage
from ui.theme import configure_data_table

# 每页展示条数（尽量多，仍可滚动）
PAGE_SIZE = 10


def _case_title(tc: CaseRecord) -> str:
    snr = "—" if tc.snr_db is None else f"{tc.snr_db:g}"
    fi = "—" if tc.frame_idx is None else str(tc.frame_idx)
    name = tc.name or f"Eb{snr}_F{fi}"
    att_n = len(tc.attempt_records) if tc.attempt_records else (1 if has_measured(tc) else 0)
    hc = ""
    if has_measured(tc):
        hc = " HC=Y" if tc.hardware_converged else " HC=N"
    return f"{name}  |  EbNo={snr} FrameIdx={fi}  |  Attempt×{att_n}{hc}"


class _CasePhysBlock(QFrame):
    """单条用例：发送 hex + 12 路行电压；接收 hex + 8 路 I_col。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        self.lbl_title = QLabel("—")
        self.lbl_title.setObjectName("hexLabel")
        self.lbl_title.setWordWrap(True)
        lay.addWidget(self.lbl_title)

        self.lbl_send_hex = QLabel("发送帧 hex: --")
        self.lbl_send_hex.setObjectName("hexLabel")
        self.lbl_send_hex.setWordWrap(True)
        self.lbl_send_hex.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.lbl_send_hex)

        self.send_table = QTableWidget(1, 12)
        self.send_table.setHorizontalHeaderLabels([f"CH{i}" for i in range(1, 13)])
        self.send_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.send_table.verticalHeader().setVisible(False)
        configure_data_table(self.send_table)
        self.send_table.setFixedHeight(52)
        self.send_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        lay.addWidget(self.send_table)

        self.lbl_recv_hex = QLabel("接收帧 hex: --")
        self.lbl_recv_hex.setObjectName("hexLabel")
        self.lbl_recv_hex.setWordWrap(True)
        self.lbl_recv_hex.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.lbl_recv_hex)

        self.recv_table = QTableWidget(1, 8)
        self.recv_table.setHorizontalHeaderLabels([f"CH{i}" for i in range(1, 9)])
        self.recv_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.recv_table.verticalHeader().setVisible(False)
        configure_data_table(self.recv_table)
        self.recv_table.setFixedHeight(52)
        self.recv_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        lay.addWidget(self.recv_table)

    def clear(self) -> None:
        self.lbl_title.setText("—")
        self.lbl_send_hex.setText("发送帧 hex: --")
        self.lbl_recv_hex.setText("接收帧 hex: --")
        for c in range(12):
            self.send_table.setItem(0, c, QTableWidgetItem(""))
        for c in range(8):
            self.recv_table.setItem(0, c, QTableWidgetItem(""))
        self.setVisible(False)

    def bind(self, tc: CaseRecord) -> None:
        self.setVisible(True)
        self.lbl_title.setText(_case_title(tc))
        if tc.tx_hex:
            self.lbl_send_hex.setText(f"发送帧 hex: {tc.tx_hex}")
        else:
            self.lbl_send_hex.setText("发送帧 hex: --")
        for i in range(12):
            raw = tc.channels[i] if i < len(tc.channels) else 0
            item = QTableWidgetItem(f"{raw_to_row_voltage(raw):.6f}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.send_table.setItem(0, i, item)

        if tc.rx_hex:
            iter_text = f"  (迭代={tc.iteration_count}次)" if tc.iteration_count else ""
            att = ""
            if tc.attempt_records:
                last = tc.attempt_records[-1]
                att = f"  Attempt={last.attempt}"
            self.lbl_recv_hex.setText(f"接收帧 hex: {tc.rx_hex}{iter_text}{att}")
        else:
            self.lbl_recv_hex.setText("接收帧 hex: --（未测或无 RX）")

        currents = list(tc.actual_currents or [])
        for i in range(8):
            if i < len(currents):
                item = QTableWidgetItem(f"{currents[i]:.6f}")
            else:
                item = QTableWidgetItem("")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.recv_table.setItem(0, i, item)


class ExcerptPanel(QWidget):
    """整页批量物理量摘录：每页约 PAGE_SIZE 条用例（发送 12CH + 接收 8CH）。"""

    refresh_requested = pyqtSignal()
    open_workbook_requested = pyqtSignal(str)  # "full" | "ok" | "ber"
    copy_pack_requested = pyqtSignal(str)  # "desktop" | "choose"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cases: list[CaseRecord] = []
        self._page = 0
        self._build_ui()

    def set_export_status(self, text: str) -> None:
        self.lbl_export_hint.setText(text)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        tip = QLabel(
            "批量测后物理量摘录：每条用例一块（发送 hex + CH1–12 行电压；接收 hex + CH1–8 列电流）。"
            f"整页约 {PAGE_SIZE} 条，可翻页。下方可直接打开 / 复制测后 Excel，无需进 data 翻找。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        ctrl = QHBoxLayout()
        self.btn_refresh = QPushButton("从当前测试结果刷新")
        self.btn_prev = QPushButton("← 上一页")
        self.btn_next = QPushButton("下一页 →")
        self.lbl_page = QLabel("第 0/0 页 · 0 条")
        self.lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ctrl.addWidget(self.btn_refresh)
        ctrl.addWidget(QLabel("每页:"))
        self.spin_page_size = QSpinBox()
        self.spin_page_size.setRange(5, 20)
        self.spin_page_size.setValue(PAGE_SIZE)
        self.spin_page_size.setToolTip("一页展示多少条用例（越大越密）")
        ctrl.addWidget(self.spin_page_size)
        ctrl.addStretch()
        ctrl.addWidget(self.btn_prev)
        ctrl.addWidget(self.lbl_page, stretch=1)
        ctrl.addWidget(self.btn_next)
        layout.addLayout(ctrl)

        files = QHBoxLayout()
        self.lbl_export_hint = QLabel("测后表: （尚未关联本次导出）")
        self.lbl_export_hint.setWordWrap(True)
        self.btn_open_full = QPushButton("打开 ①完整 result")
        self.btn_open_ok = QPushButton("打开 ②ok")
        self.btn_open_ber = QPushButton("打开 ③BER")
        self.btn_copy_pack_desktop = QPushButton("整套复制到桌面")
        self.btn_copy_pack_choose = QPushButton("整套复制到…")
        self.btn_open_full.setToolTip("用系统默认程序打开 *_result_*.xlsx")
        self.btn_open_ok.setToolTip(
            "打开 *_ok.xlsx（每帧 1 仿真 + 1 实测：优先末次收敛无误码 Attempt）"
        )
        self.btn_open_ber.setToolTip("打开 *_ber.xlsx（仅误码帧，末次误码 Attempt）")
        self.btn_copy_pack_desktop.setToolTip(
            "从 data 复制 CSV + 三份 Excel 到桌面（不删源文件）"
        )
        self.btn_copy_pack_choose.setToolTip("选择目标文件夹后复制整套测后文件")
        files.addWidget(self.btn_open_full)
        files.addWidget(self.btn_open_ok)
        files.addWidget(self.btn_open_ber)
        files.addWidget(self.btn_copy_pack_desktop)
        files.addWidget(self.btn_copy_pack_choose)
        files.addStretch()
        layout.addLayout(files)
        layout.addWidget(self.lbl_export_hint)

        self.btn_refresh.clicked.connect(self.refresh_requested.emit)
        self.btn_prev.clicked.connect(self._prev_page)
        self.btn_next.clicked.connect(self._next_page)
        self.spin_page_size.valueChanged.connect(self._on_page_size_changed)
        self.btn_open_full.clicked.connect(lambda: self.open_workbook_requested.emit("full"))
        self.btn_open_ok.clicked.connect(lambda: self.open_workbook_requested.emit("ok"))
        self.btn_open_ber.clicked.connect(lambda: self.open_workbook_requested.emit("ber"))
        self.btn_copy_pack_desktop.clicked.connect(
            lambda: self.copy_pack_requested.emit("desktop")
        )
        self.btn_copy_pack_choose.clicked.connect(
            lambda: self.copy_pack_requested.emit("choose")
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_inner = QWidget()
        self._blocks_layout = QVBoxLayout(self._scroll_inner)
        self._blocks_layout.setSpacing(10)
        self._blocks_layout.setContentsMargins(2, 2, 2, 2)
        self._blocks: list[_CasePhysBlock] = []
        for _ in range(20):  # 预建最多 20 块，按每页大小显示
            blk = _CasePhysBlock()
            blk.setVisible(False)
            self._blocks.append(blk)
            self._blocks_layout.addWidget(blk)
        self._blocks_layout.addStretch(1)
        scroll.setWidget(self._scroll_inner)
        layout.addWidget(scroll, stretch=1)

    def _page_size(self) -> int:
        return int(self.spin_page_size.value())

    def set_cases(self, cases: list[CaseRecord]) -> None:
        # 优先已测；否则全部有 FrameIdx 的（加载后也可预览 TX）
        measured = [c for c in cases if c.tx_hex or has_measured(c) or c.actual_currents]
        self._cases = measured if measured else list(cases)
        self._page = 0
        self._reload_page()

    def apply_sample_keys(self, keys: list[str]) -> None:
        """兼容旧接口：忽略，整页翻页模式不再用 3 槽位。"""
        del keys
        self._reload_page()

    def _on_page_size_changed(self, _n: int) -> None:
        self._page = 0
        self._reload_page()

    def _page_count(self) -> int:
        n = len(self._cases)
        ps = self._page_size()
        if n <= 0:
            return 0
        return (n + ps - 1) // ps

    def _prev_page(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._reload_page()

    def _next_page(self) -> None:
        if self._page + 1 < self._page_count():
            self._page += 1
            self._reload_page()

    def _reload_page(self) -> None:
        ps = self._page_size()
        total_pages = self._page_count()
        if total_pages == 0:
            self.lbl_page.setText("第 0/0 页 · 0 条（请先批量测试或点刷新）")
            for blk in self._blocks:
                blk.clear()
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            return

        self._page = max(0, min(self._page, total_pages - 1))
        start = self._page * ps
        chunk = self._cases[start : start + ps]
        self.lbl_page.setText(
            f"第 {self._page + 1}/{total_pages} 页 · "
            f"显示 {start + 1}–{start + len(chunk)} / 共 {len(self._cases)} 条"
        )
        self.btn_prev.setEnabled(self._page > 0)
        self.btn_next.setEnabled(self._page + 1 < total_pages)

        for i, blk in enumerate(self._blocks):
            if i < len(chunk):
                blk.bind(chunk[i])
            else:
                blk.clear()
