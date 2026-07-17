"""TX/RX 通道表 — 供「可视化分析」页单帧联调与用例对照。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.theme import configure_data_table


class ChannelTablesPanel(QWidget):
    """12 路 TX + 8 路 RX 明细表（可编辑仿真/行电压，供主窗口接线）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        mid = QGroupBox("12 通道行电压 (TX)")
        mid_layout = QVBoxLayout(mid)
        cmd_row = QHBoxLayout()
        cmd_row.addWidget(QLabel("矩阵模式:"))
        self.cmd_edit = QLineEdit("1")
        self.cmd_edit.setMaximumWidth(64)
        self.cmd_edit.setToolTip("CH1 高 4 bit；0=沿用批量选择器模式")
        cmd_row.addWidget(self.cmd_edit)
        cmd_row.addStretch()
        mid_layout.addLayout(cmd_row)

        self.send_table = QTableWidget(12, 4)
        self.send_table.setHorizontalHeaderLabels(["CH", "行电压(V)", "DAC", "hex字节"])
        self.send_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        configure_data_table(self.send_table)
        for i in range(12):
            ch_item = QTableWidgetItem(str(i + 1))
            ch_item.setFlags(ch_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.send_table.setItem(i, 0, ch_item)
        mid_layout.addWidget(self.send_table)
        root.addWidget(mid, stretch=1)

        right = QGroupBox("8 通道仿真电流 (参考) / 接收")
        right_layout = QVBoxLayout(right)
        self.recv_table = QTableWidget(8, 9)
        self.recv_table.setHorizontalHeaderLabels(
            [
                "CH",
                "仿真Out",
                "ADC",
                "hex",
                "芯片I_col",
                "CodeBit芯片",
                "CodeBit期望",
                "匹配",
                "备注",
            ]
        )
        self.recv_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        configure_data_table(self.recv_table)
        for i in range(8):
            ch_label = str(i + 1) + ("†" if i >= 4 else "")
            ch_item = QTableWidgetItem(ch_label)
            ch_item.setFlags(ch_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.recv_table.setItem(i, 0, ch_item)
            self.recv_table.setItem(i, 1, QTableWidgetItem(""))
        right_layout.addWidget(self.recv_table)
        root.addWidget(right, stretch=1)
