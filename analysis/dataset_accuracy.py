"""测试集 / 测后数据集准确性检查（CodeBit / InfoBit / BER 口径）。

规则：
(1) 仿真行 CodeBit 来自测试集给定；测后导出不得改写
(2) 实测行 InfoBit 应留空，不参与 BER
(3) 实测行 CodeBit = 回传 Out 硬判（负1正0）
(4) BER = 实测 CodeBit vs 仿真 CodeBit（相同正确，不同误码）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from analysis.sign_compare import (
    ber_channel_pairs_for_mode,
    ber_meas_out_indices_for_mode,
    chip_value_to_bit,
)
from csv_loader import (
    ROW_KIND_MEASURED,
    ROW_KIND_SIM,
    coded_bit_keys,
    detect_coded_bit_prefix,
    load_test_csv,
)


@dataclass
class AccuracyIssue:
    row_num: int  # 1-based data row (excluding header) or CSV line approx
    frame_idx: str
    kind: str
    field: str
    message: str


@dataclass
class AccuracyReport:
    path: Path
    mode: int
    frames_checked: int = 0
    measured_rows_checked: int = 0
    issues: list[AccuracyIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def summary_text(self) -> str:
        lines = [
            f"文件: {self.path}",
            f"模式: {self.mode}",
            f"检查帧数: {self.frames_checked}",
            f"实测行数: {self.measured_rows_checked}",
            f"问题数: {len(self.issues)}",
        ]
        if self.ok:
            lines.append("结论: 通过")
        else:
            lines.append("结论: 未通过")
            for iss in self.issues[:50]:
                lines.append(
                    f"  行≈{iss.row_num} Frame={iss.frame_idx} [{iss.kind}] "
                    f"{iss.field}: {iss.message}"
                )
            if len(self.issues) > 50:
                lines.append(f"  …另有 {len(self.issues) - 50} 条")
        return "\n".join(lines)


def _float_cell(row: dict, key: str) -> float | None:
    val = row.get(key, "")
    if val is None or str(val).strip() == "":
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _bit_cell(row: dict, key: str) -> int | None:
    val = row.get(key, "")
    if val is None or str(val).strip() == "":
        return None
    try:
        return int(float(val))
    except ValueError:
        return None


def check_dataset_rows(
    rows: list[dict[str, str]],
    fieldnames: list[str],
    *,
    mode: int,
    path: Path | None = None,
    source_sim_coded: dict[tuple[str, str], dict[str, str]] | None = None,
) -> AccuracyReport:
    """检查交错行列表。

    source_sim_coded: 可选，键=(EbNo, FrameIdx) → 原始测试集仿真行，
    用于核对测后仿真行 CodeBit 是否被改写。
    """
    report = AccuracyReport(path=path or Path("memory"), mode=int(mode))
    prefix = detect_coded_bit_prefix(fieldnames)
    ber_pairs = ber_channel_pairs_for_mode(mode)
    pending_sim: dict[str, str] | None = None
    row_num = 1

    for row in rows:
        row_num += 1
        kind = str(row.get("RowKind", "")).strip()
        frame = str(row.get("FrameIdx", "")).strip()
        ebno = str(row.get("EbNo_dB", "")).strip()

        if kind == ROW_KIND_SIM:
            report.frames_checked += 1
            pending_sim = row
            if prefix:
                for i in range(8):
                    key = f"{prefix}[{i}]"
                    if key not in fieldnames:
                        continue
                    bit = _bit_cell(row, key)
                    out = _float_cell(row, f"Out[{i}]")
                    # 仿真行 CodeBit 允许与 Out 硬判不一致（测试集给定优先）
                    # 仅当缺 CodeBit 且有 Out 时提示可补齐
                    if bit is None and out is not None:
                        report.issues.append(
                            AccuracyIssue(
                                row_num=row_num,
                                frame_idx=frame,
                                kind="仿真行",
                                field=key,
                                message="CodeBit 为空（可用 Out 硬判补齐，但测后不应改写已有值）",
                            )
                        )
                if source_sim_coded is not None:
                    src = source_sim_coded.get((ebno, frame))
                    if src is not None:
                        for i in range(8):
                            key = f"{prefix}[{i}]"
                            if key not in fieldnames:
                                continue
                            src_bit = str(src.get(key, "")).strip()
                            cur_bit = str(row.get(key, "")).strip()
                            if src_bit and cur_bit and src_bit != cur_bit:
                                report.issues.append(
                                    AccuracyIssue(
                                        row_num=row_num,
                                        frame_idx=frame,
                                        kind="仿真行",
                                        field=key,
                                        message=(
                                            f"测后改写了测试集 CodeBit："
                                            f"原={src_bit} 现={cur_bit}"
                                        ),
                                    )
                                )
            continue

        if kind != ROW_KIND_MEASURED:
            pending_sim = None
            continue

        report.measured_rows_checked += 1
        # (2) 实测 InfoBit 应空
        for i in range(4):
            key = f"InfoBit[{i}]"
            if key not in fieldnames:
                continue
            if str(row.get(key, "")).strip() != "":
                report.issues.append(
                    AccuracyIssue(
                        row_num=row_num,
                        frame_idx=frame,
                        kind="实测行",
                        field=key,
                        message="实测行 InfoBit 应留空（不参与 BER）",
                    )
                )

        # (3) 实测 CodeBit = Out 硬判
        if prefix:
            for i in range(8):
                key = f"{prefix}[{i}]"
                if key not in fieldnames:
                    continue
                out = _float_cell(row, f"Out[{i}]")
                bit = _bit_cell(row, key)
                if out is None:
                    continue
                expect = chip_value_to_bit(out)
                if bit is None:
                    report.issues.append(
                        AccuracyIssue(
                            row_num=row_num,
                            frame_idx=frame,
                            kind="实测行",
                            field=key,
                            message=f"CodeBit 为空，期望硬判 {expect}",
                        )
                    )
                elif bit != expect:
                    report.issues.append(
                        AccuracyIssue(
                            row_num=row_num,
                            frame_idx=frame,
                            kind="实测行",
                            field=key,
                            message=f"CodeBit={bit} 与 Out 硬判 {expect} 不一致",
                        )
                    )

        # (4) 信息性：实测 Out 硬判 vs 仿真 CodeBit（BER 配对通道）
        if prefix and pending_sim is not None:
            for out_i, cb_i in ber_pairs:
                cb_key = f"{prefix}[{cb_i}]"
                out_key = f"Out[{out_i}]"
                if cb_key not in fieldnames or out_key not in fieldnames:
                    continue
                sb = _bit_cell(pending_sim, cb_key)
                out_v = _float_cell(row, out_key)
                if sb is None or out_v is None:
                    continue
                del sb, out_v

        # 下一帧前不清除 pending_sim（同帧多 Attempt）

    return report


def check_csv_file(path: str | Path, *, mode: int | None = None) -> AccuracyReport:
    """加载 CSV 并做准确性检查。"""
    path = Path(path)
    loaded = load_test_csv(path)
    m = int(mode) if mode is not None else int(loaded.matrix_mode or 1)
    rows = loaded.dataset.rows if loaded.dataset else []
    fieldnames = (
        list(loaded.dataset.fieldnames)
        if loaded.dataset
        else list(rows[0].keys()) if rows else []
    )
    return check_dataset_rows(rows, fieldnames, mode=m, path=path)


def build_source_sim_coded_map(
    rows: list[dict[str, str]],
) -> dict[tuple[str, str], dict[str, str]]:
    """从交错行提取仿真行快照，键=(EbNo_dB, FrameIdx)。"""
    source_map: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        if str(row.get("RowKind", "")).strip() != ROW_KIND_SIM:
            continue
        key = (
            str(row.get("EbNo_dB", "")).strip(),
            str(row.get("FrameIdx", "")).strip(),
        )
        # 浅拷贝，避免后续 update_measured 改到快照
        source_map[key] = dict(row)
    return source_map


def check_post_test_against_source(
    post_path: str | Path,
    source_path: str | Path,
    *,
    mode: int | None = None,
    source_sim_coded: dict[tuple[str, str], dict[str, str]] | None = None,
) -> AccuracyReport:
    """测后数据集 vs 源测试集：仿真行 CodeBit 不得被改写 + 实测行口径检查。

    source_sim_coded：可选，加载时内存快照；未传则从 source_path 重新读。
    """
    post_path = Path(post_path)
    source_path = Path(source_path)
    post = load_test_csv(post_path)
    m = int(mode) if mode is not None else int(post.matrix_mode or 1)

    if source_sim_coded is None:
        src = load_test_csv(source_path)
        if mode is None:
            m = int(post.matrix_mode or src.matrix_mode or 1)
        source_map = build_source_sim_coded_map(
            src.dataset.rows if src.dataset else []
        )
    else:
        source_map = source_sim_coded

    fieldnames = list(post.dataset.fieldnames) if post.dataset else []
    rows = post.dataset.rows if post.dataset else []
    return check_dataset_rows(
        rows,
        fieldnames,
        mode=m,
        path=post_path,
        source_sim_coded=source_map,
    )


def check_export_rows_against_source(
    export_rows: list[dict[str, str]],
    fieldnames: list[str],
    source_sim_coded: dict[tuple[str, str], dict[str, str]],
    *,
    mode: int,
    path: Path | None = None,
) -> AccuracyReport:
    """对即将/已写出的测后行做仿真 CodeBit 篡改检查（不读盘）。"""
    return check_dataset_rows(
        export_rows,
        fieldnames,
        mode=int(mode),
        path=path or Path("export"),
        source_sim_coded=source_sim_coded,
    )


def tamper_issues_only(report: AccuracyReport) -> list[AccuracyIssue]:
    """只保留「测后改写了测试集 CodeBit」类问题。"""
    return [i for i in report.issues if "测后改写了测试集 CodeBit" in i.message]
