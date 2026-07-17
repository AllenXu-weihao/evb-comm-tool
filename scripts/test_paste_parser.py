"""粘贴解析器冒烟测试 — 从 Excel / UART 日志复制的一行 mode1 数据。

这不是对 parse_pasted_testdata() 入参/出参的单元测试，而是一次**贴近现场**的
端到端冒烟：工程师从 mode1.csv 或串口抓包工具里复制一行 Tab/逗号分隔文本，
粘贴进工具后，期望能正确解析字段并组出可下发的 TX 帧。

覆盖链路
--------
  剪贴板文本  →  paste_parser.parse_pasted_testdata  →  protocol.codec.build_tx_frame

典型数据来源
------------
- Excel：选中 mode1.csv 某一行后 Ctrl+C（列间多为 Tab，本脚本用逗号等价模拟）
- UART / 日志：单行 CSV 格式的测试记录

mode1 完整行（27 列）字段布局
-----------------------------
  列序   字段              本脚本样例值
  ----   ----              ----------
  0      SNR (EbNo_dB)     0.0000
  1      frame_idx         1
  2–13   In[0..11] DAC     -0.7188 … 1.5000  （12 路，电压 → raw）
  14–21  Out[0..7]         -0.7310 … 0.0000  （8 路仿真电流，仅解析不落帧）
  22–25  InfoBit[0..3]     1, 1, 1, 0
  26     iter_ref (IterNum) 2

运行方式
--------
  python scripts/test_paste_parser.py

失败时先看 print 输出的 channels / sim / info_bits / meta / TX hex，
再对照上方列布局定位是「分列」「类型转换」还是「组帧」环节出错。

Author: Xander
Date:   2026-06-30
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# §1 路径引导 — 允许从 scripts/ 目录直接 python 运行，无需 pip install -e .
# ---------------------------------------------------------------------------
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from paste_parser import parse_pasted_testdata
from protocol.codec import raw_to_row_voltage, format_hex, build_tx_frame

# ---------------------------------------------------------------------------
# §2 样例行 — 取自 mode1.csv 第 1 条数据行（27 列完整格式）
#
# 故意保留浮点字符串形式，模拟 Excel「复制为文本」或 UART 日志原文，
# 而不是在测试里预先转成 int/list，以验证 parse 层的分列与类型转换。
# ---------------------------------------------------------------------------
row1 = (
    "0.0000,1,-0.7188,-1.0000,-0.4375,0.6562,-1.0000,0.0938,0.0938,0.4688,"
    "0.0000,0.0000,0.0000,1.5000,-0.7310,-0.1013,-0.0818,0.3116,"
    "0.0000,0.0000,0.0000,0.0000,1,1,1,0,2"
)

# ---------------------------------------------------------------------------
# §3 解析 + 组帧 — 端到端主路径
#
# parse_pasted_testdata：分列 → 识别 27 列 mode1 布局 → 填 PasteRowResult
# build_tx_frame：取 12 路 DAC raw + frame_idx 生成 UART 下发帧
# print 输出便于人工 diff：改 parser/codec 后 rerun，一眼看出哪段字段漂移
# ---------------------------------------------------------------------------
r = parse_pasted_testdata(row1)
print("channels:", r.channels)
print("sim:", r.sim_outputs)
print("info_bits:", r.info_bits)
print("meta:", r.snr_db, r.frame_idx, r.iter_ref)
frame = build_tx_frame(r.channels, 1)
print("TX hex:", format_hex(frame))

# ---------------------------------------------------------------------------
# §4 回归断言 — 每条对应一个曾出过错或易回归的分支
# ---------------------------------------------------------------------------

# 12 路 In：mode1 最短有效格式也是 12 列；少列或 DAC 截断会导致组帧长度不对
assert len(r.channels) == 12

# 8 路 Out：27 列格式必须解析仿真电流；若误当 20 列短格式，sim_outputs 会变 None
assert len(r.sim_outputs or []) == 8

# InfoBit[0..3]：mode1 尾部 4 位；与 sign_compare / 报告导出共用，顺序错则比对全错
assert r.info_bits == [1, 1, 1, 0]

# SNR=0.0：EbNo 列在「跳过多余前缀、取末尾 27 列」逻辑下不能丢或错位
assert r.snr_db == 0.0

# frame_idx=1：meta 第二列；UI 进度与 TX 帧序号依赖此值
assert r.frame_idx == 1

# iter_ref=2：IterNum 末列；迭代公式与重测逻辑读此字段，缺失会导致 iter 统计异常
assert r.iter_ref == 2

# ---------------------------------------------------------------------------
# §5 通过
# ---------------------------------------------------------------------------
print("OK")
