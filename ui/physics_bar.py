"""单帧物理量柱状图 — TX 行电压 vs RX 列电流。"""

from __future__ import annotations

import matplotlib

matplotlib.use("QtAgg")

from analysis.aggregate import CaseRecord
from protocol.codec import raw_to_row_voltage
from ui.chart_panel import configure_matplotlib
from ui.perf_settings import CHART_DPI
from ui.theme import COLOR_BG_PANEL, COLOR_BG_TABLE, COLOR_TEXT_PRIMARY

configure_matplotlib()

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QWidget


class PhysicsBarPanel(QWidget):
    """单帧测试：TX 行电压 CH1–12 与 RX 列电流 CH1–8 柱状图。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        group = QGroupBox("物理量柱状图 (单帧测试: TX 行电压 vs RX 列电流)")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        inner = QVBoxLayout(group)
        self.fig = Figure(figsize=(10, 3.2), dpi=CHART_DPI)
        self.fig.patch.set_facecolor(COLOR_BG_PANEL)
        self.canvas = FigureCanvas(self.fig)
        self.ax_tx = self.fig.add_subplot(121)
        self.ax_rx = self.fig.add_subplot(122)
        for ax in (self.ax_tx, self.ax_rx):
            ax.set_facecolor(COLOR_BG_TABLE)
            ax.tick_params(colors=COLOR_TEXT_PRIMARY)
            ax.title.set_color(COLOR_TEXT_PRIMARY)
            ax.xaxis.label.set_color(COLOR_TEXT_PRIMARY)
            ax.yaxis.label.set_color(COLOR_TEXT_PRIMARY)
        inner.addWidget(self.canvas)
        layout.addWidget(group)
        self.clear()

    def clear(self) -> None:
        self.ax_tx.clear()
        self.ax_rx.clear()
        self.ax_tx.set_title("TX 行电压 V_row (单帧)")
        self.ax_tx.set_xlabel("通道")
        self.ax_tx.set_ylabel("V_row (V)")
        self.ax_tx.text(
            0.5,
            0.5,
            "运行单帧测试后显示",
            ha="center",
            va="center",
            transform=self.ax_tx.transAxes,
            color=COLOR_TEXT_PRIMARY,
        )
        self.ax_rx.set_title("RX 列电流 I_col (单帧)")
        self.ax_rx.set_xlabel("通道")
        self.ax_rx.set_ylabel("I_col")
        self.ax_rx.text(
            0.5,
            0.5,
            "运行单帧测试后显示",
            ha="center",
            va="center",
            transform=self.ax_rx.transAxes,
            color=COLOR_TEXT_PRIMARY,
        )
        self.fig.tight_layout()
        self.canvas.draw()

    def update(self, tc: CaseRecord | None) -> None:
        self.ax_tx.clear()
        self.ax_rx.clear()
        if tc is None or not tc.success or not tc.actual_currents:
            self.clear()
            return

        tx_labels = [f"CH{i}" for i in range(1, 13)]
        tx_vals = [raw_to_row_voltage(r) for r in tc.channels[:12]]
        while len(tx_vals) < 12:
            tx_vals.append(0.0)

        rx_labels = [f"CH{i}" for i in range(1, 9)]
        rx_vals = list(tc.actual_currents[:8])
        while len(rx_vals) < 8:
            rx_vals.append(0.0)

        x_tx = range(len(tx_labels))
        x_rx = range(len(rx_labels))
        self.ax_tx.bar(x_tx, tx_vals, color="#e67e22", width=0.7)
        self.ax_tx.set_xticks(list(x_tx))
        self.ax_tx.set_xticklabels(tx_labels, fontsize=7, rotation=45)
        self.ax_tx.set_title(f"TX 行电压 V_row\n{tc.name}")
        self.ax_tx.set_ylabel("V_row (V)")
        self.ax_tx.grid(True, axis="y", linestyle="--", alpha=0.5)

        colors = ["#3498db" if v >= 0 else "#9b59b6" for v in rx_vals]
        self.ax_rx.bar(x_rx, rx_vals, color=colors, width=0.7)
        self.ax_rx.axhline(0, color="#888888", linewidth=0.8)
        self.ax_rx.set_xticks(list(x_rx))
        self.ax_rx.set_xticklabels(rx_labels, fontsize=8)
        self.ax_rx.set_title(f"RX 列电流 I_col\n迭代={tc.iteration_count}")
        self.ax_rx.set_ylabel("I_col (与 Out 同量纲)")
        self.ax_rx.grid(True, axis="y", linestyle="--", alpha=0.5)

        self.fig.tight_layout()
        self.canvas.draw()
