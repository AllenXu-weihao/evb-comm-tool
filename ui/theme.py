"""Centralized dark-theme QSS — explicit fg/bg pairs for WCAG-friendly contrast.

Qt Fusion on Windows may inherit a dark system palette while partial QSS leaves
table alternate rows light (#fafafa) with light text. All data surfaces here set
both background and foreground explicitly.
"""

from __future__ import annotations

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QTableWidget

# Programmatic colors (status icons, match markers — not overridden by QSS)
# 用例表行/单元格标注使用需求书浅色 hex（#fff3e0 / #fff9c4 / #e3f2fd / #e8f5e9）
COLOR_TEXT_PRIMARY = "#e8e8e8"
COLOR_TEXT_SECONDARY = "#b0b0b0"
COLOR_STATUS_OK = "#4ade80"
COLOR_STATUS_ERR = "#f87171"
COLOR_MATCH_OK = "#4ade80"
COLOR_MATCH_FAIL = "#f87171"
COLOR_MEASURED_ROW_BG = "#e3f2fd"
COLOR_NON_CONVERGED_BG = "#fff3e0"
COLOR_PASS_ROW_BG = "#e8f5e9"
COLOR_ERROR_CELL_BG = "#fff9c4"

# Surface palette
COLOR_BG_WINDOW = "#1e1e1e"
COLOR_BG_PANEL = "#252526"
COLOR_BG_INPUT = "#3c3c3c"
COLOR_BG_TABLE = "#2d2d2d"
COLOR_BG_TABLE_ALT = "#1e1e1e"
COLOR_BG_HEADER = "#404040"
COLOR_BG_BUTTON = "#454545"
COLOR_BG_BUTTON_HOVER = "#505050"
COLOR_BG_BUTTON_PRESSED = "#5a5a5a"
COLOR_BG_BUTTON_DISABLED = "#2f2f2f"
COLOR_TEXT_DISABLED = "#9ca3af"
COLOR_BORDER = "#555555"
COLOR_GRID = "#484848"
COLOR_SELECTION = "#264f78"
COLOR_SELECTION_TEXT = "#ffffff"
COLOR_LOG_BG = "#1a1a1a"
COLOR_LOG_TEXT = "#d4d4d4"

APP_STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {COLOR_BG_WINDOW};
    color: {COLOR_TEXT_PRIMARY};
}}

QGroupBox {{
    font-weight: bold;
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 10px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: {COLOR_TEXT_PRIMARY};
}}

QLabel {{
    color: {COLOR_TEXT_PRIMARY};
    background: transparent;
}}
QLabel#hexLabel {{
    font-family: Consolas, "Courier New", monospace;
    font-size: 10pt;
    color: {COLOR_LOG_TEXT};
    background: transparent;
}}
QLabel#statusConnected {{
    color: {COLOR_STATUS_OK};
    font-weight: bold;
    background: transparent;
}}
QLabel#statusDisconnected {{
    color: {COLOR_STATUS_ERR};
    font-weight: bold;
    background: transparent;
}}

QTabWidget::pane {{
    border: 1px solid {COLOR_BORDER};
    background: {COLOR_BG_PANEL};
}}
QTabBar::tab {{
    background: {COLOR_BG_BUTTON};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    padding: 6px 14px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {COLOR_BG_PANEL};
    border-bottom-color: {COLOR_BG_PANEL};
}}
QTabBar::tab:hover {{
    background: {COLOR_BG_BUTTON_HOVER};
}}

QPushButton {{
    min-height: 26px;
    padding: 4px 12px;
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    background-color: {COLOR_BG_BUTTON};
    color: {COLOR_TEXT_PRIMARY};
}}
QPushButton:hover {{
    background-color: {COLOR_BG_BUTTON_HOVER};
}}
QPushButton:pressed {{
    background-color: {COLOR_BG_BUTTON_PRESSED};
}}
QPushButton:disabled {{
    background-color: {COLOR_BG_BUTTON_DISABLED};
    color: {COLOR_TEXT_DISABLED};
    border: 1px solid {COLOR_GRID};
}}

QLineEdit, QSpinBox, QComboBox {{
    background-color: {COLOR_BG_INPUT};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    padding: 3px 6px;
    min-height: 22px;
}}
QLineEdit#hexFrameEdit {{
    font-family: Consolas, "Courier New", monospace;
    font-size: 10pt;
    background-color: {COLOR_LOG_BG};
    color: {COLOR_LOG_TEXT};
}}
QLineEdit#hexFrameEdit:read-only {{
    background-color: {COLOR_BG_TABLE};
    color: {COLOR_TEXT_SECONDARY};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
    background-color: {COLOR_BG_BUTTON_DISABLED};
    color: {COLOR_TEXT_DISABLED};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {COLOR_BG_INPUT};
    color: {COLOR_TEXT_PRIMARY};
    selection-background-color: {COLOR_SELECTION};
    selection-color: {COLOR_SELECTION_TEXT};
    border: 1px solid {COLOR_BORDER};
}}

QTableWidget {{
    background-color: {COLOR_BG_TABLE};
    alternate-background-color: {COLOR_BG_TABLE_ALT};
    color: {COLOR_TEXT_PRIMARY};
    gridline-color: {COLOR_GRID};
    border: 1px solid {COLOR_BORDER};
    selection-background-color: {COLOR_SELECTION};
    selection-color: {COLOR_SELECTION_TEXT};
}}
QTableWidget::item {{
    color: {COLOR_TEXT_PRIMARY};
    padding: 2px 4px;
}}
QTableWidget::item:alternate {{
    background-color: {COLOR_BG_TABLE_ALT};
    color: #ffffff;
}}
QTableWidget::item:selected {{
    background-color: {COLOR_SELECTION};
    color: {COLOR_SELECTION_TEXT};
}}

QHeaderView::section {{
    background-color: {COLOR_BG_HEADER};
    color: {COLOR_TEXT_PRIMARY};
    padding: 5px;
    border: 1px solid {COLOR_GRID};
    font-weight: bold;
}}

QTextEdit#logPanel {{
    background-color: {COLOR_LOG_BG};
    color: {COLOR_LOG_TEXT};
    font-family: Consolas, "Courier New", monospace;
    font-size: 9pt;
    border: 1px solid {COLOR_BORDER};
}}

QStatusBar {{
    background-color: {COLOR_BG_PANEL};
    color: {COLOR_TEXT_SECONDARY};
    border-top: 1px solid {COLOR_BORDER};
}}

QSplitter::handle {{
    background-color: {COLOR_BORDER};
}}
"""


def apply_app_theme(app: QApplication) -> None:
    """Apply global dark stylesheet so all windows/widgets share one palette."""
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)


def configure_data_table(table: QTableWidget) -> None:
    """Enable alternating rows; QSS supplies explicit fg/bg for each band."""
    table.setAlternatingRowColors(True)
    table.setShowGrid(True)


def qcolor(name: str) -> QColor:
    """Build QColor from theme hex constant."""
    return QColor(name)
