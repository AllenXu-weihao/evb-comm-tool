"""批量测试可视化分析面板结构版本（无 matplotlib 依赖，便于脚本自检）。"""



from __future__ import annotations



# 改 ChartPanel 布局/口径时递增；主窗口据此重建面板

AUDIT_SCHEMA_VERSION = 31



AUDIT_COLUMN_HEADERS: list[tuple[str, str]] = [

    ("Eb/N0", "SNR (dB)"),

    ("chart帧", "图表该 SNR 帧数（ok 表按 FrameIdx 裁至 BER 基数 N；1 仿真 + 1 实测/帧）"),

    ("ber误码帧", "ber 表该 SNR 含误码的帧数"),

    ("误码bit", "实测误码 bit 总数（ok 逐帧比对）"),

    ("总bit", "实测 BER 分母 bit = chart帧 × 通道数（图表每 SNR ≤ BER基数）"),

    ("实测BER(图)", "折线图实测 BER"),

    ("实测BER(表)", "ok 图表裁剪子集验算 BER = 误码bit÷总bit"),

    ("实测✓", "图表与 ok 验算是否一致"),

    ("参考误码bit", "仿真行 Sim Out 硬判 vs CodeBit 误码 bit"),

    ("参考总bit", "参考 BER 分母 bit = 图表仿真行数(=帧数) × 通道数"),

    ("参考BER(图)", "折线图参考 BER"),

    ("参考BER(表)", "ok 仿真行验算参考 BER"),

    ("参考✓", "图表与 ok 仿真行验算是否一致"),

    ("result实测行", "完整 result 该 SNR 实测行数（多 Attempt）"),

    ("ok实测行", "ok 表实测行数（≥ chart帧）"),

    ("ok仿真行", "ok 表仿真行数（≥ chart帧）"),

    ("帧核对✓", "chart帧 = 裁剪子集内实测/仿真；且 chart帧 ≤ ok 全量"),

    ("ber帧", "ber 表该 SNR 误码帧数"),

]



ITER_AUDIT_COLUMN_HEADERS: list[tuple[str, str]] = [

    ("Eb/N0", "SNR (dB)"),

    ("chart帧", "图表该 SNR 帧数（ok 裁剪后；迭代均值分母；≤BER基数）"),

    ("实测迭代加和", "ok 实测行 IterNum 之和"),

    ("参考迭代加和", "ok 仿真行 IterNum 之和"),

    ("实测均值(图)", "迭代折线图芯片平均迭代"),

    ("实测均值(表)", "ok 验算：实测迭代加和 ÷ chart帧"),

    ("实测✓", "图表与 ok 表是否一致"),

    ("参考均值(图)", "迭代折线图仿真参考平均"),

    ("参考均值(表)", "ok 验算：参考迭代加和 ÷ chart帧"),

    ("参考✓", "图表与 ok 表是否一致"),

]

