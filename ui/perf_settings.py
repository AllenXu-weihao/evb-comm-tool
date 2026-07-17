"""跨机性能默认值：弱机可用环境变量 EVB_UI_LITE=1 进一步节流。"""

from __future__ import annotations

import os


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


# 弱机 / 远程桌面：减少 UI 刷新与图表开销
UI_LITE = _env_flag("EVB_UI_LITE")

# 批量 UI 节流
BATCH_TABLE_UPDATE_INTERVAL = _env_int(
    "EVB_BATCH_TABLE_INTERVAL", 100 if UI_LITE else 50
)
BATCH_PROGRESS_INTERVAL = _env_int(
    "EVB_BATCH_PROGRESS_INTERVAL", 50 if UI_LITE else 25
)
BATCH_CSV_SAVE_INTERVAL = _env_int(
    "EVB_BATCH_CSV_INTERVAL", 5000 if UI_LITE else 2000
)
BATCH_CHART_REFRESH_INTERVAL = _env_int(
    "EVB_BATCH_CHART_INTERVAL", 120 if UI_LITE else 80
)
# 柱状图 + 折线增量：主线程合并刷新（debounce，避免每帧 4 图重绘阻塞 UI）
BATCH_BAR_REFRESH_INTERVAL = _env_int(
    "EVB_BATCH_BAR_INTERVAL", 3 if UI_LITE else 1
)
BATCH_BAR_MIN_MS = _env_int("EVB_BATCH_BAR_MIN_MS", 80 if UI_LITE else 16)

# 串口列表轮询（未连接时）
PORT_REFRESH_MS = _env_int("EVB_PORT_REFRESH_MS", 5000 if UI_LITE else 3000)

# 日志最大行数（防止长时间运行卡死）
LOG_MAX_BLOCKS = _env_int("EVB_LOG_MAX_BLOCKS", 1500 if UI_LITE else 3000)

# matplotlib DPI（首次打开「可视化分析」时生效）
CHART_DPI = _env_int("EVB_CHART_DPI", 72 if UI_LITE else 90)


def lite_banner() -> str:
    if not UI_LITE:
        return ""
    return (
        f"弱机模式 EVB_UI_LITE：进度/{BATCH_PROGRESS_INTERVAL} 帧，"
        f"live图 debounce {BATCH_BAR_MIN_MS}ms，"
        f"全量折线仅末帧，检查点/{BATCH_CSV_SAVE_INTERVAL} 帧，图表 dpi={CHART_DPI}，"
        f"端口轮询 {PORT_REFRESH_MS}ms"
    )
