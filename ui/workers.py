"""后台 QThread Worker — 与 UI 解耦的重计算 / IO 任务。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from analysis.aggregate import case_from_csv_group
from analysis.report_export import filter_ber_error_rows, write_styled_dataset_xlsx
from csv_loader import TestCsvDataset, load_test_csv, write_csv_snapshot


class ChartAggWorker(QThread):
    """后台聚合 BER/迭代点，避免切到可视化页时主线程扫 7000 帧卡顿。"""

    finished_ok = pyqtSignal(object)  # dict: points, executed, mode2_n, matrix_mode
    failed = pyqtSignal(str)

    def __init__(
        self,
        test_cases: list,
        *,
        matrix_mode: int,
        need_mode2_recompute: bool,
        max_per_snr: int | None = None,
    ) -> None:
        super().__init__()
        self._test_cases = test_cases
        self._matrix_mode = int(matrix_mode)
        self._need_mode2_recompute = need_mode2_recompute
        self._max_per_snr = max_per_snr

    def run(self) -> None:
        try:
            from analysis.aggregate import (
                analyze_by_snr,
                frame_was_tested,
                recompute_measured_bit_compare,
            )

            mode2_n = 0
            if self._need_mode2_recompute and self._matrix_mode == 2:
                mode2_n = recompute_measured_bit_compare(self._test_cases)
            executed = [
                tc
                for tc in self._test_cases
                if frame_was_tested(tc) and tc.actual_currents
            ]
            points = (
                analyze_by_snr(self._test_cases, max_per_snr=self._max_per_snr)
                if executed
                else []
            )
            self.finished_ok.emit(
                {
                    "points": points,
                    "executed": executed,
                    "mode2_n": mode2_n,
                    "matrix_mode": self._matrix_mode,
                }
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class CsvCheckpointWorker(QThread):
    """后台写入批量测试检查点，避免 save_as 阻塞主线程。"""

    def __init__(
        self,
        fieldnames: list[str],
        rows: list[dict[str, str]],
        path: Path,
    ) -> None:
        super().__init__()
        self._fieldnames = fieldnames
        self._rows = rows
        self._path = path

    def run(self) -> None:
        write_csv_snapshot(self._path, self._fieldnames, self._rows)


class PostTestExcelWorker(QThread):
    """后台写三份测后 Excel，避免 openpyxl 阻塞 UI。"""

    one_done = pyqtSignal(str, str, int)  # label, path, nrows
    one_failed = pyqtSignal(str, str)  # label, error
    all_done = pyqtSignal(int, int)  # ok_count, fail_count

    def __init__(
        self,
        fieldnames: list[str],
        matrix_mode: int,
        exports: list[tuple[str, Path, list[dict[str, str]], str]],
    ) -> None:
        super().__init__()
        self._fieldnames = fieldnames
        self._matrix_mode = matrix_mode
        self._exports = exports

    def run(self) -> None:
        ok = 0
        fail = 0
        for label, xlsx_path, rows, dataset_style in self._exports:
            try:
                write_styled_dataset_xlsx(
                    xlsx_path,
                    self._fieldnames,
                    rows,
                    matrix_mode=self._matrix_mode,
                    dataset_style=dataset_style,
                )
                ok += 1
                self.one_done.emit(label, str(xlsx_path), len(rows))
            except ImportError:
                fail += 1
                self.one_failed.emit(label, "缺少 openpyxl，请运行 setup.bat / pip install openpyxl")
            except Exception as exc:
                fail += 1
                self.one_failed.emit(label, str(exc))
        self.all_done.emit(ok, fail)


class PostTestDatasetWorker(QThread):
    """后台：Mode2 BER 重算 + build_export_rows + 写 CSV + CodeBit 监测（不碰 UI）。"""

    finished_ok = pyqtSignal(object)  # dict
    failed = pyqtSignal(str)

    def __init__(
        self,
        dataset: TestCsvDataset,
        test_cases: list,
        out_path: Path,
        matrix_mode: int,
        source_sim_coded: dict,
        *,
        recompute_mode2: bool,
    ) -> None:
        super().__init__()
        self._dataset = dataset
        self._test_cases = test_cases
        self._out_path = out_path
        self._matrix_mode = matrix_mode
        self._source_sim_coded = source_sim_coded
        self._recompute_mode2 = recompute_mode2

    def run(self) -> None:
        try:
            from analysis.aggregate import recompute_measured_bit_compare
            from analysis.dataset_accuracy import (
                check_export_rows_against_source,
                tamper_issues_only,
            )

            mode2_n = 0
            if self._recompute_mode2 and self._test_cases:
                mode2_n = recompute_measured_bit_compare(self._test_cases)

            self._dataset.ensure_export_fieldnames()
            full_rows = self._dataset.build_export_rows(self._test_cases)
            ok_rows = self._dataset.build_export_rows(
                self._test_cases, exclude_comm_errors=True
            )
            ber_rows = filter_ber_error_rows(
                ok_rows, list(self._dataset.fieldnames), matrix_mode=self._matrix_mode
            )
            self._dataset.save_as(self._out_path, export_rows=full_rows)
            fieldnames = list(self._dataset.fieldnames)

            tampers: list = []
            frames_checked = 0
            if self._source_sim_coded:
                report = check_export_rows_against_source(
                    full_rows,
                    fieldnames,
                    self._source_sim_coded,
                    mode=self._matrix_mode,
                    path=self._out_path,
                )
                tampers = tamper_issues_only(report)
                frames_checked = report.frames_checked

            self.finished_ok.emit(
                {
                    "out": self._out_path,
                    "full_rows": full_rows,
                    "ok_rows": ok_rows,
                    "ber_rows": ber_rows,
                    "fieldnames": fieldnames,
                    "mode": self._matrix_mode,
                    "mode2_n": mode2_n,
                    "tampers": tampers,
                    "frames_checked": frames_checked,
                }
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class CsvLoadWorker(QThread):
    """后台读取 CSV 并构建 CaseRecord，避免 7000 组阻塞主线程。"""

    csv_parsed = pyqtSignal(object)  # TestDataLoad
    cases_ready = pyqtSignal(list, object, object)  # cases, loaded, source_sim_coded
    error = pyqtSignal(str)

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path

    def run(self) -> None:
        try:
            from analysis.dataset_accuracy import build_source_sim_coded_map

            loaded = load_test_csv(self._path)
            if not loaded.cases:
                raise ValueError("CSV 无有效数据行")
            self.csv_parsed.emit(loaded)
            test_cases = [case_from_csv_group(g) for g in loaded.cases]
            snap = build_source_sim_coded_map(
                list(loaded.dataset.rows) if loaded.dataset else []
            )
            self.cases_ready.emit(test_cases, loaded, snap)
        except Exception as exc:
            self.error.emit(str(exc))
