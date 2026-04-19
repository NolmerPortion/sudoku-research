from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QAbstractItemView,
)
from PySide6.QtGui import QColor

from check_uniqueness import (
    check_uniqueness,
    grid_to_string,
    parse_pattern_mask,
    parse_puzzle_string,
    pretty_grid,
)
from generate_puzzle import generate_one_puzzle, validate_full_solution
from export_special_dataset import all_raw_5_special_patterns
from puzzle_rules import describe_rules
from rule_visuals import build_rule_visual_state
import workbench_rule_extensions


Grid9 = list[list[int]]
PatternMask = str

# 実際に可解と確認された例の完成盤面
DEFAULT_SOLUTION_STRING = (
    "348125679"
    "791346258"
    "652789134"
    "123658497"
    "467293815"
    "589417362"
    "836974521"
    "915862743"
    "274531986"
)

# 既知の可解な特殊配置の例
DEFAULT_PATTERN_MASK = "011100011"

# 事前計算済みデータセットの manifest
DEFAULT_MANIFEST_PATH = Path("outputs/dataset_5_special/manifest.json")
DEFAULT_AUTO_OUTPUT_DIR = Path("outputs/folder_auto_generated")


def mask_to_pretty(mask: PatternMask) -> str:
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            row.append("S" if mask[3 * r + c] == "1" else ".")
        rows.append(" ".join(row))
    return "\n".join(rows)


def load_pattern_status_map(manifest_path: Path) -> dict[str, str]:
    """
    manifest.json があれば
      mask -> feasibility_status
    の辞書を返す。
    無ければ空辞書を返す。
    """
    if not manifest_path.exists():
        return {}

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(data, dict):
        return {}

    patterns = data.get("patterns")
    if not isinstance(patterns, list):
        return {}

    out: dict[str, str] = {}
    for entry in patterns:
        if not isinstance(entry, dict):
            continue
        mask = entry.get("pattern_mask_string")
        status = entry.get("feasibility_status")
        if isinstance(mask, str) and isinstance(status, str):
            out[mask] = status
    return out


def grid_from_json_value(value: Any) -> Grid9 | None:
    if not isinstance(value, list) or len(value) != 9:
        return None

    grid: Grid9 = []
    for row in value:
        if not isinstance(row, list) or len(row) != 9:
            return None
        out_row: list[int] = []
        for cell in row:
            if not isinstance(cell, int):
                return None
            out_row.append(cell)
        grid.append(out_row)
    return grid


def normalize_solution_entry(
    raw: Any,
    *,
    fallback_pattern_mask: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    solution_string = raw.get("solution_string")
    if not isinstance(solution_string, str):
        grid_string = raw.get("grid_string")
        if isinstance(grid_string, str):
            solution_string = grid_string

    solution_grid = grid_from_json_value(raw.get("solution_grid"))
    if solution_grid is None:
        solution_grid = grid_from_json_value(raw.get("grid"))

    if isinstance(solution_string, str):
        solution_grid = parse_puzzle_string(solution_string)
    elif solution_grid is not None:
        solution_string = grid_to_string(solution_grid)
    else:
        return None

    if any(solution_grid[r][c] == 0 for r in range(9) for c in range(9)):
        return None

    pattern_mask = raw.get("pattern_mask")
    if not isinstance(pattern_mask, str):
        pattern_mask = raw.get("pattern_mask_string")
    if not isinstance(pattern_mask, str):
        pattern_mask = fallback_pattern_mask

    entry: dict[str, Any] = {
        "solution_grid": solution_grid,
        "solution_string": solution_string,
    }
    if isinstance(pattern_mask, str):
        entry["pattern_mask"] = pattern_mask
    return entry


def collect_solution_entries_from_json(
    data: Any,
    *,
    fallback_pattern_mask: str | None = None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen_solution_strings: set[str] = set()

    def add_candidate(raw: Any, pattern_mask: str | None = None) -> None:
        normalized = normalize_solution_entry(raw, fallback_pattern_mask=pattern_mask)
        if normalized is None:
            return
        solution_string = normalized["solution_string"]
        if solution_string in seen_solution_strings:
            return
        seen_solution_strings.add(solution_string)
        entries.append(normalized)

    if isinstance(data, dict):
        root_mask = data.get("pattern_mask")
        if not isinstance(root_mask, str):
            root_mask = data.get("pattern_mask_string")
        if not isinstance(root_mask, str):
            root_mask = fallback_pattern_mask

        add_candidate(data, root_mask)

        solutions = data.get("solutions")
        if isinstance(solutions, list):
            for item in solutions:
                add_candidate(item, root_mask)

        results = data.get("results")
        if isinstance(results, list):
            for item in results:
                child_mask = root_mask
                if isinstance(item, dict):
                    item_mask = item.get("pattern_mask")
                    if isinstance(item_mask, str):
                        child_mask = item_mask
                add_candidate(item, child_mask)

    return entries


def load_dataset_pattern_data(
    manifest_path: Path,
    pattern_mask: str,
) -> tuple[dict[str, Any], Path]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest_data, dict):
        raise ValueError("manifest JSON must be an object")

    pattern_id: str | None = None
    patterns = manifest_data.get("patterns")
    if isinstance(patterns, list):
        for entry in patterns:
            if not isinstance(entry, dict):
                continue
            if entry.get("pattern_mask_string") == pattern_mask:
                maybe_pattern_id = entry.get("pattern_id")
                if isinstance(maybe_pattern_id, str):
                    pattern_id = maybe_pattern_id
                break

    pattern_dir = manifest_path.parent / "patterns"
    candidate_paths: list[Path] = []
    if pattern_id is not None:
        candidate_paths.append(pattern_dir / f"{pattern_id}.json")
    candidate_paths.extend(sorted(pattern_dir.glob(f"pattern_*_{pattern_mask}.json")))

    seen_paths: set[Path] = set()
    unique_paths: list[Path] = []
    for path in candidate_paths:
        if path in seen_paths:
            continue
        seen_paths.add(path)
        unique_paths.append(path)

    pattern_path = next((path for path in unique_paths if path.exists()), None)
    if pattern_path is None:
        raise FileNotFoundError(
            f"pattern JSON for mask {pattern_mask} was not found under {pattern_dir}"
        )

    pattern_data = json.loads(pattern_path.read_text(encoding="utf-8"))
    if not isinstance(pattern_data, dict):
        raise ValueError(f"pattern JSON must be an object: {pattern_path}")
    return pattern_data, pattern_path


def load_dataset_solution_entries(
    manifest_path: Path,
    pattern_mask: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pattern_data, pattern_path = load_dataset_pattern_data(manifest_path, pattern_mask)
    entries = collect_solution_entries_from_json(pattern_data, fallback_pattern_mask=pattern_mask)

    pattern_id = pattern_data.get("pattern_id")
    feasibility_status = pattern_data.get("feasibility_status")

    for index, entry in enumerate(entries, start=1):
        entry["source_mode"] = "dataset"
        entry["source_index"] = index
        entry["source_file"] = str(pattern_path)
        if isinstance(pattern_id, str):
            entry["source_pattern_id"] = pattern_id
        if isinstance(feasibility_status, str):
            entry["source_feasibility_status"] = feasibility_status

    metadata = {
        "pattern_path": str(pattern_path),
        "pattern_id": pattern_id,
        "feasibility_status": feasibility_status,
        "solution_count": len(entries),
    }
    return entries, metadata


class BoardTable(QTableWidget):
    def __init__(self, editable: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(9, 9, parent)
        self._editable = editable
        self._updating = False
        self._pattern_mask = "000000000"
        self._rules: list[dict[str, Any]] = []
        self._visual_state = build_rule_visual_state(self._pattern_mask, self._rules)
        self._setup_ui()
        self.itemChanged.connect(self._sanitize_item)

    def _setup_ui(self) -> None:
        self.horizontalHeader().setVisible(False)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.setMinimumSize(420, 420)
        self.setShowGrid(True)
        self.setAlternatingRowColors(False)
        self.setSelectionMode(QTableWidget.SingleSelection)

        for r in range(9):
            for c in range(9):
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignCenter)
                if not self._editable:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.setItem(r, c, item)

        self._refresh_headers()

    def _refresh_headers(self) -> None:
        self.setStyleSheet(
            "QTableWidget { gridline-color: #666; font-size: 18px; }"
            "QTableWidget::item { padding: 0px; }"
        )

    def _sanitize_item(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        text = item.text().strip()
        if text == "" or text == "." or text == "0":
            normalized = ""
        elif text and text[0] in "123456789":
            normalized = text[0]
        else:
            normalized = ""

        if normalized != text:
            self._updating = True
            item.setText(normalized)
            self._updating = False

    def set_grid(self, grid: Grid9) -> None:
        self._updating = True
        try:
            for r in range(9):
                for c in range(9):
                    val = grid[r][c]
                    self.item(r, c).setText("" if val == 0 else str(val))
        finally:
            self._updating = False
        self._refresh_visuals()

    def get_grid(self) -> Grid9:
        out: Grid9 = []
        for r in range(9):
            row: list[int] = []
            for c in range(9):
                text = self.item(r, c).text().strip()
                if text in {"", ".", "0"}:
                    row.append(0)
                elif text in "123456789":
                    row.append(int(text))
                else:
                    row.append(0)
            out.append(row)
        return out

    def set_editable(self, editable: bool) -> None:
        self._editable = editable
        for r in range(9):
            for c in range(9):
                item = self.item(r, c)
                if editable:
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)

    def set_rule_visuals(self, pattern_mask: str, rules: list[dict[str, Any]] | None = None) -> None:
        self._pattern_mask = pattern_mask if isinstance(pattern_mask, str) else "000000000"
        self._rules = list(rules or [])
        self._visual_state = build_rule_visual_state(self._pattern_mask, self._rules)
        self._refresh_visuals()

    def _cell_background_color(self, row: int, col: int) -> QColor:
        if (row, col) in self._visual_state["special_cells"]:
            return QColor("#fff0a8")
        if (row, col) in self._visual_state["hyper_cells"]:
            return QColor("#fff6c9")
        if (row, col) in self._visual_state["checkerboard_cells"]:
            return QColor("#fffbe8")
        if (row, col) in self._visual_state["sum_cells"]:
            return QColor("#ffe9bf")
        if (row, col) in self._visual_state["clone_cells"]:
            return QColor("#eef0b8")
        if (row, col) in self._visual_state["cross_centers"]:
            return QColor("#ffe38a")
        if (row, col) in self._visual_state["cross_cells"]:
            return QColor("#fff2c7")
        return QColor("#ffffff")

    def _cell_tooltip(self, row: int, col: int) -> str:
        parts: list[str] = []
        if (row, col) in self._visual_state["special_cells"]:
            parts.append("special monotone 3x3")
        if (row, col) in self._visual_state["hyper_cells"]:
            parts.append("hyper 3x3 region")
        if (row, col) in self._visual_state["checkerboard_cells"]:
            parts.append("checkerboard odd cell")
        if (row, col) in self._visual_state["clone_cells"]:
            parts.append("clone region")
        if (row, col) in self._visual_state["cross_centers"]:
            parts.append("cross monotone center")
        elif (row, col) in self._visual_state["cross_cells"]:
            parts.append("cross monotone arm")
        for region in self._visual_state["sum_regions"]:
            cells = region.get("cells", [])
            if any((row, col) == (int(cell_row), int(cell_col)) for cell_row, cell_col in cells):
                parts.append(f"L tromino sum={int(region['target_sum'])}")
        return ", ".join(parts)

    def _refresh_visuals(self) -> None:
        for r in range(9):
            for c in range(9):
                item = self.item(r, c)
                if item is None:
                    continue
                item.setBackground(self._cell_background_color(r, c))
                item.setToolTip(self._cell_tooltip(r, c))


class GeneratorWorker(QObject):
    log = Signal(str)
    result = Signal(dict)
    error = Signal(str)
    finished = Signal()

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__()
        self.params = params

    def run(self) -> None:
        try:
            solution_grid: Grid9 = self.params["solution_grid"]
            pattern_mask: str = self.params["pattern_mask"]
            symmetry: str = self.params["symmetry"]
            min_clues: int = self.params["min_clues"]
            trials: int = self.params["trials"]
            seed: int = self.params["seed"]
            uniqueness_time_limit: float = self.params["uniqueness_time_limit"]
            validation_time_limit: float = self.params["validation_time_limit"]

            self.log.emit("完成盤面を検証しています。")
            validation = validate_full_solution(
                solution_grid=solution_grid,
                pattern_mask=pattern_mask,
                time_limit=validation_time_limit,
            )

            if validation["classification"] != "unique":
                raise RuntimeError(
                    "この完成盤面は、指定した特殊配置のもとで一意完成盤面として検証に通りません。"
                )

            best_result: dict[str, Any] | None = None

            for t in range(trials):
                trial_seed = seed + t
                self.log.emit(f"trial {t + 1}/{trials} を実行しています。 seed={trial_seed}")

                result = generate_one_puzzle(
                    solution_grid=solution_grid,
                    pattern_mask=pattern_mask,
                    symmetry=symmetry,
                    uniqueness_time_limit=uniqueness_time_limit,
                    seed=trial_seed,
                    target_clues=min_clues,
                    verbose=False,
                )

                self.log.emit(
                    f"  -> clue_count={result['clue_count']}, accepted_groups={len(result['accepted_groups'])}"
                )

                if best_result is None or result["clue_count"] < best_result["clue_count"]:
                    best_result = result
                    self.log.emit("  -> 現在の最良結果を更新しました。")

                if best_result["clue_count"] == min_clues:
                    self.log.emit("最低ヒント数に到達したので打ち切ります。")
                    break

            assert best_result is not None

            self.log.emit("最終一意性を再確認しています。")
            final_check = check_uniqueness(
                puzzle_grid=best_result["puzzle_grid"],
                special_positions=parse_pattern_mask(pattern_mask),
                time_limit=max(uniqueness_time_limit, 10.0),
            )

            payload = {
                "source_mode": "current_solution",
                "pattern_mask": pattern_mask,
                "solution_grid": solution_grid,
                "solution_string": grid_to_string(solution_grid),
                "puzzle_grid": best_result["puzzle_grid"],
                "puzzle_string": best_result["puzzle_string"],
                "clue_count": best_result["clue_count"],
                "symmetry": symmetry,
                "seed": best_result["seed"],
                "accepted_groups": best_result["accepted_groups"],
                "final_uniqueness_check": final_check,
                "validation": validation,
            }
            self.result.emit(payload)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))
        finally:
            self.finished.emit()


class BatchGeneratorWorker(QObject):
    log = Signal(str)
    result = Signal(dict)
    error = Signal(str)
    finished = Signal()

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__()
        self.params = params

    def run(self) -> None:
        try:
            solution_grid: Grid9 = self.params["solution_grid"]
            pattern_mask: str = self.params["pattern_mask"]
            symmetry: str = self.params["symmetry"]
            min_clues: int = self.params["min_clues"]
            trials: int = self.params["trials"]
            seed: int = self.params["seed"]
            batch_count: int = self.params["batch_count"]
            uniqueness_time_limit: float = self.params["uniqueness_time_limit"]
            validation_time_limit: float = self.params["validation_time_limit"]

            self.log.emit("完成盤面を検証しています。")
            validation = validate_full_solution(
                solution_grid=solution_grid,
                pattern_mask=pattern_mask,
                time_limit=validation_time_limit,
            )

            if validation["classification"] != "unique":
                raise RuntimeError(
                    "この完成盤面は、指定した特殊配置のもとで一意完成盤面として検証に通りません。"
                )

            results: list[dict[str, Any]] = []
            seen_puzzles: set[str] = set()
            duplicates_skipped = 0

            for i in range(batch_count):
                batch_seed = seed + i * 1000
                self.log.emit(f"batch {i + 1}/{batch_count} を実行しています。 base_seed={batch_seed}")

                best_result: dict[str, Any] | None = None
                for t in range(trials):
                    trial_seed = batch_seed + t
                    result = generate_one_puzzle(
                        solution_grid=solution_grid,
                        pattern_mask=pattern_mask,
                        symmetry=symmetry,
                        uniqueness_time_limit=uniqueness_time_limit,
                        seed=trial_seed,
                        target_clues=min_clues,
                        verbose=False,
                    )

                    if best_result is None or result["clue_count"] < best_result["clue_count"]:
                        best_result = result

                    if best_result["clue_count"] == min_clues:
                        break

                assert best_result is not None

                puzzle_string = best_result["puzzle_string"]
                if puzzle_string in seen_puzzles:
                    duplicates_skipped += 1
                    self.log.emit("  -> 重複問題だったのでスキップしました。")
                    continue

                seen_puzzles.add(puzzle_string)
                final_check = check_uniqueness(
                    puzzle_grid=best_result["puzzle_grid"],
                    special_positions=parse_pattern_mask(pattern_mask),
                    time_limit=max(uniqueness_time_limit, 10.0),
                )

                entry = {
                    "index": len(results) + 1,
                    "pattern_mask": pattern_mask,
                    "solution_grid": solution_grid,
                    "solution_string": grid_to_string(solution_grid),
                    "puzzle_grid": best_result["puzzle_grid"],
                    "puzzle_string": best_result["puzzle_string"],
                    "clue_count": best_result["clue_count"],
                    "symmetry": symmetry,
                    "seed": best_result["seed"],
                    "accepted_groups": best_result["accepted_groups"],
                    "final_uniqueness_check": final_check,
                    "validation": validation,
                }
                results.append(entry)
                self.log.emit(
                    f"  -> 採用しました。 clue_count={entry['clue_count']}, seed={entry['seed']}"
                )

            payload = {
                "pattern_mask": pattern_mask,
                "symmetry": symmetry,
                "requested_batch_count": batch_count,
                "generated_count": len(results),
                "duplicates_skipped": duplicates_skipped,
                "results": results,
                "validation": validation,
            }
            self.result.emit(payload)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))
        finally:
            self.finished.emit()

class BatchGeneratorWorker(QObject):
    log = Signal(str)
    result = Signal(dict)
    error = Signal(str)
    finished = Signal()

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__()
        self.params = params

    def _generate_best_result(
        self,
        *,
        solution_grid: Grid9,
        pattern_mask: str,
        symmetry: str,
        min_clues: int,
        trials: int,
        base_seed: int,
        uniqueness_time_limit: float,
    ) -> dict[str, Any]:
        best_result: dict[str, Any] | None = None

        for t in range(trials):
            trial_seed = base_seed + t
            result = generate_one_puzzle(
                solution_grid=solution_grid,
                pattern_mask=pattern_mask,
                symmetry=symmetry,
                uniqueness_time_limit=uniqueness_time_limit,
                seed=trial_seed,
                target_clues=min_clues,
                verbose=False,
            )

            if best_result is None or result["clue_count"] < best_result["clue_count"]:
                best_result = result

            if best_result["clue_count"] == min_clues:
                break

        assert best_result is not None
        return best_result

    def run(self) -> None:
        try:
            source_mode: str = self.params.get("source_mode", "current_solution")
            pattern_mask: str = self.params["pattern_mask"]
            symmetry: str = self.params["symmetry"]
            min_clues: int = self.params["min_clues"]
            trials: int = self.params["trials"]
            seed: int = self.params["seed"]
            batch_count: int = self.params["batch_count"]
            uniqueness_time_limit: float = self.params["uniqueness_time_limit"]
            validation_time_limit: float = self.params["validation_time_limit"]
            dataset_per_solution: int = max(1, int(self.params.get("dataset_per_solution", 1)))

            if source_mode == "dataset":
                raw_entries = self.params.get("solution_entries")
                if not isinstance(raw_entries, list) or not raw_entries:
                    raise RuntimeError("dataset mode requires at least one complete solution")

                solution_entries: list[dict[str, Any]] = []
                for raw_entry in raw_entries:
                    normalized = normalize_solution_entry(
                        raw_entry,
                        fallback_pattern_mask=pattern_mask,
                    )
                    if normalized is None:
                        continue
                    merged = dict(raw_entry)
                    merged.update(normalized)
                    solution_entries.append(merged)

                if not solution_entries:
                    raise RuntimeError("dataset mode did not provide any valid complete solutions")
                per_source_limit = dataset_per_solution
            else:
                solution_grid: Grid9 = self.params["solution_grid"]
                solution_entries = [
                    {
                        "solution_grid": solution_grid,
                        "solution_string": grid_to_string(solution_grid),
                        "source_mode": "current_solution",
                        "source_index": 1,
                    }
                ]
                per_source_limit = batch_count

            self.log.emit(f"source_mode={source_mode}, source_count={len(solution_entries)}")

            results: list[dict[str, Any]] = []
            seen_puzzles: set[str] = set()
            duplicates_skipped = 0
            validation_cache: dict[str, dict[str, Any]] = {}
            invalid_sources: set[int] = set()
            generated_per_source = [0 for _ in solution_entries]
            max_passes = max(batch_count * 5, per_source_limit * 3, 5)
            pass_index = 0
            no_progress_passes = 0

            while len(results) < batch_count and pass_index < max_passes and no_progress_passes < 3:
                progress = False

                for source_idx, source_entry in enumerate(solution_entries):
                    if len(results) >= batch_count:
                        break
                    if source_idx in invalid_sources:
                        continue
                    if generated_per_source[source_idx] >= per_source_limit:
                        continue

                    solution_grid = source_entry["solution_grid"]
                    solution_string = source_entry["solution_string"]
                    validation = validation_cache.get(solution_string)

                    if validation is None:
                        self.log.emit(
                            f"source {source_idx + 1}/{len(solution_entries)} validation start"
                        )
                        validation = validate_full_solution(
                            solution_grid=solution_grid,
                            pattern_mask=pattern_mask,
                            time_limit=validation_time_limit,
                        )
                        validation_cache[solution_string] = validation

                        if validation["classification"] != "unique":
                            invalid_sources.add(source_idx)
                            self.log.emit(
                                f"  -> skipped source {source_idx + 1}: "
                                f"classification={validation['classification']}"
                            )
                            continue

                    base_seed = seed + pass_index * 100000 + source_idx * 1000
                    self.log.emit(
                        f"source {source_idx + 1}/{len(solution_entries)} "
                        f"attempt {generated_per_source[source_idx] + 1}/{per_source_limit} "
                        f"base_seed={base_seed}"
                    )
                    best_result = self._generate_best_result(
                        solution_grid=solution_grid,
                        pattern_mask=pattern_mask,
                        symmetry=symmetry,
                        min_clues=min_clues,
                        trials=trials,
                        base_seed=base_seed,
                        uniqueness_time_limit=uniqueness_time_limit,
                    )

                    puzzle_string = best_result["puzzle_string"]
                    if puzzle_string in seen_puzzles:
                        duplicates_skipped += 1
                        self.log.emit("  -> duplicate puzzle skipped")
                        continue

                    seen_puzzles.add(puzzle_string)
                    final_check = check_uniqueness(
                        puzzle_grid=best_result["puzzle_grid"],
                        special_positions=parse_pattern_mask(pattern_mask),
                        time_limit=max(uniqueness_time_limit, 10.0),
                    )

                    entry = {
                        "index": len(results) + 1,
                        "source_mode": source_mode,
                        "pattern_mask": pattern_mask,
                        "solution_grid": solution_grid,
                        "solution_string": solution_string,
                        "puzzle_grid": best_result["puzzle_grid"],
                        "puzzle_string": best_result["puzzle_string"],
                        "clue_count": best_result["clue_count"],
                        "symmetry": symmetry,
                        "seed": best_result["seed"],
                        "accepted_groups": best_result["accepted_groups"],
                        "final_uniqueness_check": final_check,
                        "validation": validation,
                        "source_index": source_entry.get("source_index", source_idx + 1),
                    }
                    for key in (
                        "source_file",
                        "source_pattern_id",
                        "source_feasibility_status",
                    ):
                        if key in source_entry:
                            entry[key] = source_entry[key]

                    results.append(entry)
                    generated_per_source[source_idx] += 1
                    progress = True
                    self.log.emit(
                        f"  -> accepted clue_count={entry['clue_count']}, seed={entry['seed']}"
                    )

                pass_index += 1
                if progress:
                    no_progress_passes = 0
                else:
                    no_progress_passes += 1

            payload = {
                "source_mode": source_mode,
                "pattern_mask": pattern_mask,
                "symmetry": symmetry,
                "requested_batch_count": batch_count,
                "generated_count": len(results),
                "duplicates_skipped": duplicates_skipped,
                "source_solution_count": len(solution_entries),
                "results": results,
            }
            if source_mode == "dataset":
                payload["dataset_per_solution"] = per_source_limit
                if "dataset_manifest_path" in self.params:
                    payload["dataset_manifest_path"] = self.params["dataset_manifest_path"]
                if "dataset_pattern_file" in self.params:
                    payload["dataset_pattern_file"] = self.params["dataset_pattern_file"]
                if "dataset_pattern_id" in self.params:
                    payload["dataset_pattern_id"] = self.params["dataset_pattern_id"]
            elif solution_entries:
                payload["validation"] = validation_cache.get(solution_entries[0]["solution_string"])
            self.result.emit(payload)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))
        finally:
            self.finished.emit()

class FolderAutoGenerateWorker(QObject):
    log = Signal(str)
    result = Signal(dict)
    error = Signal(str)
    finished = Signal()

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__()
        self.params = params

    def _generate_best_result(
        self,
        *,
        solution_grid: Grid9,
        pattern_mask: str,
        symmetry: str,
        min_clues: int,
        trials: int,
        base_seed: int,
        uniqueness_time_limit: float,
    ) -> dict[str, Any]:
        best_result: dict[str, Any] | None = None

        for t in range(trials):
            trial_seed = base_seed + t
            result = generate_one_puzzle(
                solution_grid=solution_grid,
                pattern_mask=pattern_mask,
                symmetry=symmetry,
                uniqueness_time_limit=uniqueness_time_limit,
                seed=trial_seed,
                target_clues=min_clues,
                verbose=False,
            )

            if best_result is None or result["clue_count"] < best_result["clue_count"]:
                best_result = result

            if best_result["clue_count"] == min_clues:
                break

        assert best_result is not None
        return best_result

    def run(self) -> None:
        try:
            input_dir = Path(self.params["input_dir"])
            output_dir = Path(self.params["output_dir"])
            fallback_pattern_mask: str = self.params["fallback_pattern_mask"]
            symmetry: str = self.params["symmetry"]
            min_clues: int = self.params["min_clues"]
            trials: int = self.params["trials"]
            seed: int = self.params["seed"]
            uniqueness_time_limit: float = self.params["uniqueness_time_limit"]
            validation_time_limit: float = self.params["validation_time_limit"]

            if not input_dir.exists() or not input_dir.is_dir():
                raise RuntimeError(f"input directory not found: {input_dir}")

            output_dir.mkdir(parents=True, exist_ok=True)
            json_files = sorted(path for path in input_dir.glob("*.json") if path.is_file())
            if not json_files:
                raise RuntimeError(f"no json files found in: {input_dir}")

            results: list[dict[str, Any]] = []
            file_summaries: list[dict[str, Any]] = []
            skipped_files: list[dict[str, Any]] = []
            validation_cache: dict[tuple[str, str], dict[str, Any]] = {}
            seen_puzzles: set[str] = set()
            duplicates_skipped = 0
            source_solution_count = 0

            for file_index, json_path in enumerate(json_files, start=1):
                self.log.emit(f"[{file_index}/{len(json_files)}] scanning {json_path.name}")
                try:
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                except Exception as exc:  # noqa: BLE001
                    skipped_files.append({"source_file": str(json_path), "reason": str(exc)})
                    self.log.emit(f"  -> skipped unreadable file: {exc}")
                    continue

                entries = collect_solution_entries_from_json(
                    data,
                    fallback_pattern_mask=fallback_pattern_mask,
                )
                if not entries:
                    skipped_files.append(
                        {
                            "source_file": str(json_path),
                            "reason": "no compatible complete-solution entry found",
                        }
                    )
                    self.log.emit("  -> skipped incompatible file")
                    continue

                file_results: list[dict[str, Any]] = []
                skipped_entries: list[dict[str, Any]] = []
                file_duplicate_count = 0

                for entry_index, entry in enumerate(entries, start=1):
                    source_solution_count += 1
                    pattern_mask = entry.get("pattern_mask")
                    if not isinstance(pattern_mask, str):
                        pattern_mask = fallback_pattern_mask

                    solution_grid = entry["solution_grid"]
                    solution_string = entry["solution_string"]
                    cache_key = (pattern_mask, solution_string)
                    validation = validation_cache.get(cache_key)

                    if validation is None:
                        validation = validate_full_solution(
                            solution_grid=solution_grid,
                            pattern_mask=pattern_mask,
                            time_limit=validation_time_limit,
                        )
                        validation_cache[cache_key] = validation

                    if validation["classification"] != "unique":
                        skipped_entries.append(
                            {
                                "entry_index": entry_index,
                                "pattern_mask": pattern_mask,
                                "reason": f"validation={validation['classification']}",
                            }
                        )
                        self.log.emit(
                            f"  -> skipped entry {entry_index}: "
                            f"validation={validation['classification']}"
                        )
                        continue

                    base_seed = seed + file_index * 100000 + entry_index * 1000
                    best_result = self._generate_best_result(
                        solution_grid=solution_grid,
                        pattern_mask=pattern_mask,
                        symmetry=symmetry,
                        min_clues=min_clues,
                        trials=trials,
                        base_seed=base_seed,
                        uniqueness_time_limit=uniqueness_time_limit,
                    )

                    puzzle_string = best_result["puzzle_string"]
                    if puzzle_string in seen_puzzles:
                        duplicates_skipped += 1
                        file_duplicate_count += 1
                        skipped_entries.append(
                            {
                                "entry_index": entry_index,
                                "pattern_mask": pattern_mask,
                                "reason": "duplicate puzzle skipped",
                            }
                        )
                        self.log.emit(f"  -> skipped duplicate entry {entry_index}")
                        continue

                    seen_puzzles.add(puzzle_string)
                    final_check = check_uniqueness(
                        puzzle_grid=best_result["puzzle_grid"],
                        special_positions=parse_pattern_mask(pattern_mask),
                        time_limit=max(uniqueness_time_limit, 10.0),
                    )

                    payload = {
                        "index": len(results) + 1,
                        "source_mode": "folder_auto",
                        "pattern_mask": pattern_mask,
                        "solution_grid": solution_grid,
                        "solution_string": solution_string,
                        "puzzle_grid": best_result["puzzle_grid"],
                        "puzzle_string": best_result["puzzle_string"],
                        "clue_count": best_result["clue_count"],
                        "symmetry": symmetry,
                        "seed": best_result["seed"],
                        "accepted_groups": best_result["accepted_groups"],
                        "final_uniqueness_check": final_check,
                        "validation": validation,
                        "source_file": str(json_path),
                        "source_file_name": json_path.name,
                        "source_index": entry_index,
                    }
                    file_results.append(payload)
                    results.append(payload)
                    self.log.emit(
                        f"  -> generated entry {entry_index}: clues={payload['clue_count']}, "
                        f"seed={payload['seed']}"
                    )

                output_payload = {
                    "source_mode": "folder_auto_file",
                    "source_file": str(json_path),
                    "pattern_fallback_mask": fallback_pattern_mask,
                    "symmetry": symmetry,
                    "min_clues": min_clues,
                    "trials": trials,
                    "processed_entry_count": len(entries),
                    "generated_count": len(file_results),
                    "duplicates_skipped": file_duplicate_count,
                    "results": file_results,
                    "skipped_entries": skipped_entries,
                }
                output_path = output_dir / f"{json_path.stem}__generated.json"
                output_path.write_text(
                    json.dumps(output_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                file_summaries.append(
                    {
                        "source_file": str(json_path),
                        "output_file": str(output_path),
                        "processed_entry_count": len(entries),
                        "generated_count": len(file_results),
                        "duplicates_skipped": file_duplicate_count,
                    }
                )

            summary_payload = {
                "source_mode": "folder_auto",
                "input_dir": str(input_dir),
                "output_dir": str(output_dir),
                "pattern_mask": fallback_pattern_mask,
                "symmetry": symmetry,
                "min_clues": min_clues,
                "trials": trials,
                "requested_batch_count": source_solution_count,
                "generated_count": len(results),
                "duplicates_skipped": duplicates_skipped,
                "source_solution_count": source_solution_count,
                "processed_file_count": len(file_summaries),
                "skipped_file_count": len(skipped_files),
                "file_summaries": file_summaries,
                "skipped_files": skipped_files,
                "results": results,
            }
            summary_path = output_dir / "folder_run_summary.json"
            summary_path.write_text(
                json.dumps(summary_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            summary_payload["summary_file"] = str(summary_path)
            self.result.emit(summary_payload)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))
        finally:
            self.finished.emit()


class UniquenessWorker(QObject):
    log = Signal(str)
    result = Signal(dict)
    error = Signal(str)
    finished = Signal()

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__()
        self.params = params

    def run(self) -> None:
        try:
            puzzle_grid: Grid9 = self.params["puzzle_grid"]
            pattern_mask: str = self.params["pattern_mask"]
            time_limit: float = self.params["time_limit"]

            self.log.emit("一意性を判定しています。")
            result = check_uniqueness(
                puzzle_grid=puzzle_grid,
                special_positions=parse_pattern_mask(pattern_mask),
                time_limit=time_limit,
            )
            self.result.emit(result)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Special Sudoku Workbench")
        self.resize(1560, 980)

        self._current_generated_payload: dict[str, Any] | None = None
        self._current_batch_payload: dict[str, Any] | None = None
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self._pattern_status_map: dict[str, str] = load_pattern_status_map(DEFAULT_MANIFEST_PATH)
        self._dataset_metadata: dict[str, Any] = {}

        self._build_ui()
        self._populate_patterns()
        self._set_defaults()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(520)
        left_scroll.setStyleSheet("QScrollArea { border: none; }")

        left_panel = QWidget()
        left_col = QVBoxLayout(left_panel)
        left_col.setContentsMargins(4, 4, 4, 4)
        left_col.setSpacing(10)
        left_scroll.setWidget(left_panel)
        root.addWidget(left_scroll, 0)

        right_col = QVBoxLayout()
        right_col.setSpacing(10)
        root.addLayout(right_col, 1)
        root.setStretch(0, 0)
        root.setStretch(1, 1)

        pattern_box = QGroupBox("特殊配置")
        pattern_layout = QVBoxLayout(pattern_box)
        self.pattern_combo = QComboBox()
        self.pattern_combo.currentIndexChanged.connect(self._update_pattern_preview)
        pattern_layout.addWidget(self.pattern_combo)

        self.only_feasible_checkbox = QCheckBox("可解な配置のみ表示")
        self.only_feasible_checkbox.setChecked(True)
        self.only_feasible_checkbox.stateChanged.connect(self._populate_patterns)
        pattern_layout.addWidget(self.only_feasible_checkbox)

        self.pattern_preview = QLabel()
        self.pattern_preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.pattern_preview.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.pattern_preview.setStyleSheet("font-family: Consolas, monospace; font-size: 16px;")
        pattern_layout.addWidget(self.pattern_preview)
        left_col.addWidget(pattern_box)

        source_box = QGroupBox("source")
        source_layout = QFormLayout(source_box)

        self.source_mode_combo = QComboBox()
        self.source_mode_combo.addItem("current_solution", "current_solution")
        self.source_mode_combo.addItem("dataset", "dataset")
        self.source_mode_combo.currentIndexChanged.connect(self._update_source_mode_ui)
        source_layout.addRow("mode", self.source_mode_combo)

        self.dataset_manifest_edit = QLineEdit(str(DEFAULT_MANIFEST_PATH))
        self.dataset_manifest_edit.editingFinished.connect(self._reload_dataset_manifest)
        source_layout.addRow("manifest", self.dataset_manifest_edit)

        dataset_button_row = QHBoxLayout()
        self.dataset_manifest_browse_btn = QPushButton("Browse")
        self.dataset_manifest_browse_btn.clicked.connect(self._browse_dataset_manifest)
        dataset_button_row.addWidget(self.dataset_manifest_browse_btn)

        self.dataset_reload_btn = QPushButton("Reload")
        self.dataset_reload_btn.clicked.connect(self._reload_dataset_manifest)
        dataset_button_row.addWidget(self.dataset_reload_btn)
        source_layout.addRow("", dataset_button_row)

        self.dataset_per_solution_spin = QSpinBox()
        self.dataset_per_solution_spin.setRange(1, 20)
        self.dataset_per_solution_spin.setValue(1)
        source_layout.addRow("per solution", self.dataset_per_solution_spin)

        self.dataset_info = QPlainTextEdit()
        self.dataset_info.setReadOnly(True)
        self.dataset_info.setMinimumHeight(100)
        self.dataset_info.setMaximumHeight(120)
        source_layout.addRow(self.dataset_info)
        left_col.addWidget(source_box)

        auto_box = QGroupBox("auto folder")
        auto_layout = QFormLayout(auto_box)

        self.auto_input_dir_edit = QLineEdit()
        auto_layout.addRow("input dir", self.auto_input_dir_edit)

        auto_input_buttons = QHBoxLayout()
        self.auto_input_dir_browse_btn = QPushButton("Browse Input")
        self.auto_input_dir_browse_btn.clicked.connect(self._browse_auto_input_dir)
        auto_input_buttons.addWidget(self.auto_input_dir_browse_btn)
        auto_layout.addRow("", auto_input_buttons)

        self.auto_output_dir_edit = QLineEdit(str(DEFAULT_AUTO_OUTPUT_DIR))
        auto_layout.addRow("output dir", self.auto_output_dir_edit)

        auto_output_buttons = QHBoxLayout()
        self.auto_output_dir_browse_btn = QPushButton("Browse Output")
        self.auto_output_dir_browse_btn.clicked.connect(self._browse_auto_output_dir)
        auto_output_buttons.addWidget(self.auto_output_dir_browse_btn)

        self.auto_generate_btn = QPushButton("Run Folder Auto")
        self.auto_generate_btn.clicked.connect(self._start_folder_auto_generation)
        auto_output_buttons.addWidget(self.auto_generate_btn)
        auto_layout.addRow("", auto_output_buttons)
        left_col.addWidget(auto_box)

        solution_box = QGroupBox("完成盤面")
        solution_layout = QVBoxLayout(solution_box)

        form = QFormLayout()
        self.solution_string_edit = QLineEdit()
        self.solution_string_edit.setPlaceholderText("81文字の完成盤面を入力")
        form.addRow("solution string", self.solution_string_edit)
        solution_layout.addLayout(form)

        button_row = QHBoxLayout()
        self.load_solution_json_btn = QPushButton("JSON読込")
        self.load_solution_json_btn.clicked.connect(self._load_solution_from_json)
        button_row.addWidget(self.load_solution_json_btn)

        self.load_solution_string_btn = QPushButton("文字列から反映")
        self.load_solution_string_btn.clicked.connect(self._load_solution_from_string)
        button_row.addWidget(self.load_solution_string_btn)

        self.validate_solution_btn = QPushButton("完成盤面を検証")
        self.validate_solution_btn.clicked.connect(self._validate_current_solution)
        button_row.addWidget(self.validate_solution_btn)
        solution_layout.addLayout(button_row)
        left_col.addWidget(solution_box)

        params_box = QGroupBox("生成条件")
        params_layout = QFormLayout(params_box)

        self.symmetry_combo = QComboBox()
        self.symmetry_combo.addItems(["none", "rot180", "main_diag", "anti_diag"])
        params_layout.addRow("削除対称性", self.symmetry_combo)

        self.min_clues_spin = QSpinBox()
        self.min_clues_spin.setRange(0, 81)
        self.min_clues_spin.setValue(24)
        params_layout.addRow("最低ヒント数", self.min_clues_spin)

        self.trials_spin = QSpinBox()
        self.trials_spin.setRange(1, 10000)
        self.trials_spin.setValue(20)
        params_layout.addRow("trial数", self.trials_spin)

        self.batch_count_spin = QSpinBox()
        self.batch_count_spin.setRange(1, 10000)
        self.batch_count_spin.setValue(10)
        params_layout.addRow("バッチ件数", self.batch_count_spin)

        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 10**9)
        self.seed_spin.setValue(0)
        params_layout.addRow("seed", self.seed_spin)

        self.uniqueness_time_spin = QDoubleSpinBox()
        self.uniqueness_time_spin.setRange(0.1, 120.0)
        self.uniqueness_time_spin.setDecimals(1)
        self.uniqueness_time_spin.setSingleStep(0.5)
        self.uniqueness_time_spin.setValue(5.0)
        params_layout.addRow("一意性判定上限(秒)", self.uniqueness_time_spin)

        self.validation_time_spin = QDoubleSpinBox()
        self.validation_time_spin.setRange(0.1, 120.0)
        self.validation_time_spin.setDecimals(1)
        self.validation_time_spin.setSingleStep(0.5)
        self.validation_time_spin.setValue(10.0)
        params_layout.addRow("完成盤面検証上限(秒)", self.validation_time_spin)

        self.verbose_checkbox = QCheckBox("詳細ログ")
        params_layout.addRow("", self.verbose_checkbox)
        left_col.addWidget(params_box)

        action_box = QGroupBox("操作")
        action_layout = QHBoxLayout(action_box)
        self.generate_btn = QPushButton("問題生成")
        self.generate_btn.clicked.connect(self._start_generation)
        action_layout.addWidget(self.generate_btn)

        self.batch_generate_btn = QPushButton("バッチ生成")
        self.batch_generate_btn.clicked.connect(self._start_batch_generation)
        action_layout.addWidget(self.batch_generate_btn)

        self.check_puzzle_btn = QPushButton("現在の問題を判定")
        self.check_puzzle_btn.clicked.connect(self._check_current_puzzle)
        action_layout.addWidget(self.check_puzzle_btn)

        self.save_result_btn = QPushButton("結果を保存")
        self.save_result_btn.clicked.connect(self._save_current_result)
        action_layout.addWidget(self.save_result_btn)

        self.save_batch_btn = QPushButton("バッチ保存")
        self.save_batch_btn.clicked.connect(self._save_current_batch)
        action_layout.addWidget(self.save_batch_btn)
        left_col.addWidget(action_box)

        result_box = QGroupBox("結果")
        result_layout = QFormLayout(result_box)
        self.result_summary = QPlainTextEdit()
        self.result_summary.setReadOnly(True)
        self.result_summary.setMinimumHeight(150)
        result_layout.addRow(self.result_summary)
        left_col.addWidget(result_box)

        log_box = QGroupBox("ログ")
        log_layout = QVBoxLayout(log_box)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMinimumHeight(220)
        log_layout.addWidget(self.log_edit)
        left_col.addWidget(log_box)

        boards_layout = QGridLayout()
        right_col.addLayout(boards_layout)

        solution_board_box = QGroupBox("完成盤面")
        solution_board_layout = QVBoxLayout(solution_board_box)
        self.solution_board = BoardTable(editable=False)
        solution_board_layout.addWidget(self.solution_board)
        boards_layout.addWidget(solution_board_box, 0, 0)

        puzzle_board_box = QGroupBox("問題盤面")
        puzzle_board_layout = QVBoxLayout(puzzle_board_box)
        self.puzzle_board = BoardTable(editable=True)
        puzzle_board_layout.addWidget(self.puzzle_board)
        boards_layout.addWidget(puzzle_board_box, 0, 1)

        string_box = QGroupBox("文字列表現")
        string_layout = QFormLayout(string_box)
        self.puzzle_string_edit = QLineEdit()
        self.puzzle_string_edit.setReadOnly(True)
        self.solution_string_out = QLineEdit()
        self.solution_string_out.setReadOnly(True)
        string_layout.addRow("puzzle", self.puzzle_string_edit)
        string_layout.addRow("solution", self.solution_string_out)
        right_col.addWidget(string_box)

        batch_box = QGroupBox("バッチ結果")
        batch_layout = QVBoxLayout(batch_box)
        self.batch_table = QTableWidget(0, 5)
        self.batch_table.setHorizontalHeaderLabels(["#", "clues", "seed", "status", "puzzle"])
        self.batch_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.batch_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.batch_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.batch_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.batch_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.batch_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.batch_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.batch_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.batch_table.itemSelectionChanged.connect(self._load_selected_batch_result)
        batch_layout.addWidget(self.batch_table)
        right_col.addWidget(batch_box)

        left_col.addStretch(1)

        compact_widgets = (
            self.pattern_combo,
            self.source_mode_combo,
            self.dataset_manifest_edit,
            self.dataset_per_solution_spin,
            self.solution_string_edit,
            self.load_solution_json_btn,
            self.load_solution_string_btn,
            self.validate_solution_btn,
            self.symmetry_combo,
            self.min_clues_spin,
            self.trials_spin,
            self.batch_count_spin,
            self.seed_spin,
            self.uniqueness_time_spin,
            self.validation_time_spin,
            self.generate_btn,
            self.batch_generate_btn,
            self.check_puzzle_btn,
            self.save_result_btn,
            self.save_batch_btn,
            self.puzzle_string_edit,
            self.solution_string_out,
            self.dataset_manifest_browse_btn,
            self.dataset_reload_btn,
            self.auto_input_dir_edit,
            self.auto_input_dir_browse_btn,
            self.auto_output_dir_edit,
            self.auto_output_dir_browse_btn,
            self.auto_generate_btn,
        )
        for widget in compact_widgets:
            widget.setMinimumHeight(28)

        self.pattern_preview.setMinimumHeight(88)
        self.result_summary.setMinimumHeight(170)
        self.log_edit.setMinimumHeight(220)

    def _append_log(self, text: str) -> None:
        self.log_edit.appendPlainText(text)

    def _pattern_status(self, mask: str) -> str:
        status = self._pattern_status_map.get(mask)
        if status == "INFEASIBLE":
            return "不可解"
        if status in {"FEASIBLE", "OPTIMAL"}:
            return "可解"
        return "未判定"

    def _pattern_is_known_infeasible(self, mask: str) -> bool:
        return self._pattern_status_map.get(mask) == "INFEASIBLE"

    def _current_source_mode(self) -> str:
        data = self.source_mode_combo.currentData()
        if isinstance(data, str):
            return data
        return "current_solution"

    def _current_manifest_path(self) -> Path:
        return Path(self.dataset_manifest_edit.text().strip() or str(DEFAULT_MANIFEST_PATH))

    def _browse_dataset_manifest(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select manifest.json", "", "JSON Files (*.json)")
        if not path:
            return
        self.dataset_manifest_edit.setText(path)
        self._reload_dataset_manifest()

    def _reload_dataset_manifest(self) -> None:
        manifest_path = self._current_manifest_path()
        self._pattern_status_map = load_pattern_status_map(manifest_path)
        self._populate_patterns()
        self._refresh_dataset_summary()

    def _update_source_mode_ui(self) -> None:
        is_dataset = self._current_source_mode() == "dataset"
        self.dataset_manifest_edit.setEnabled(is_dataset)
        self.dataset_manifest_browse_btn.setEnabled(is_dataset)
        self.dataset_reload_btn.setEnabled(is_dataset)
        self.dataset_per_solution_spin.setEnabled(is_dataset)
        self.dataset_info.setEnabled(True)
        self._refresh_dataset_summary()

    def _refresh_dataset_summary(self) -> None:
        mode = self._current_source_mode()
        manifest_path = self._current_manifest_path()

        lines = [
            f"mode: {mode}",
            f"manifest: {manifest_path}",
        ]

        if not manifest_path.exists():
            lines.append("manifest_status: missing")
            self._dataset_metadata = {}
            self.dataset_info.setPlainText("\n".join(lines))
            return

        try:
            pattern_mask = self._current_pattern_mask()
        except Exception:
            pattern_mask = DEFAULT_PATTERN_MASK

        try:
            entries, metadata = load_dataset_solution_entries(manifest_path, pattern_mask)
            self._dataset_metadata = metadata
            lines.append(f"pattern_mask: {pattern_mask}")
            lines.append(f"pattern_file: {metadata.get('pattern_path', '')}")
            lines.append(f"pattern_id: {metadata.get('pattern_id', '')}")
            lines.append(f"feasibility_status: {metadata.get('feasibility_status', '')}")
            lines.append(f"solution_count: {len(entries)}")
        except Exception as exc:  # noqa: BLE001
            self._dataset_metadata = {}
            lines.append(f"pattern_mask: {pattern_mask}")
            lines.append(f"dataset_status: {exc}")

        self.dataset_info.setPlainText("\n".join(lines))

    def _load_dataset_entries_for_current_pattern(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        manifest_path = self._current_manifest_path()
        pattern_mask = self._current_pattern_mask()
        return load_dataset_solution_entries(manifest_path, pattern_mask)

    def _browse_auto_input_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select input folder")
        if path:
            self.auto_input_dir_edit.setText(path)

    def _browse_auto_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select output folder")
        if path:
            self.auto_output_dir_edit.setText(path)

    def _populate_patterns(self) -> None:
        current = self.pattern_combo.currentData()
        self.pattern_combo.blockSignals(True)
        self.pattern_combo.clear()

        masks: list[tuple[str, str]] = []
        for pattern in all_raw_5_special_patterns():
            mask = "".join("1" if (r, c) in pattern else "0" for r in range(3) for c in range(3))
            status_label = self._pattern_status(mask)

            if self.only_feasible_checkbox.isChecked() and self._pattern_is_known_infeasible(mask):
                continue

            masks.append((mask, status_label))

        for mask, status_label in masks:
            label = f"{mask} | {status_label} | {mask_to_pretty(mask).replace(chr(10), ' / ')}"
            self.pattern_combo.addItem(label, mask)

        if current is not None:
            idx = self.pattern_combo.findData(current)
            if idx >= 0:
                self.pattern_combo.setCurrentIndex(idx)
            else:
                idx = self.pattern_combo.findData(DEFAULT_PATTERN_MASK)
                self.pattern_combo.setCurrentIndex(max(idx, 0))
        else:
            idx = self.pattern_combo.findData(DEFAULT_PATTERN_MASK)
            self.pattern_combo.setCurrentIndex(max(idx, 0))

        self.pattern_combo.blockSignals(False)
        self._update_pattern_preview()

    def _set_defaults(self) -> None:
        self.solution_string_edit.setText(DEFAULT_SOLUTION_STRING)
        self.solution_string_out.setText(DEFAULT_SOLUTION_STRING)
        self.auto_output_dir_edit.setText(str(DEFAULT_AUTO_OUTPUT_DIR))
        self.solution_board.set_grid(parse_puzzle_string(DEFAULT_SOLUTION_STRING))
        self.puzzle_board.set_grid([[0] * 9 for _ in range(9)])
        self.result_summary.setPlainText("まだ結果はありません。")
        self.batch_table.setRowCount(0)

        idx = self.pattern_combo.findData(DEFAULT_PATTERN_MASK)
        if idx >= 0:
            self.pattern_combo.setCurrentIndex(idx)

        self._update_pattern_preview()
        self._update_source_mode_ui()

    def _current_pattern_mask(self) -> str:
        data = self.pattern_combo.currentData()
        if not isinstance(data, str):
            raise ValueError("特殊配置が選択されていません。")
        return data

    def _update_pattern_preview(self) -> None:
        try:
            mask = self._current_pattern_mask()
        except Exception:
            self.pattern_preview.setText("")
            return

        status = self._pattern_status(mask)
        self.pattern_preview.setText(f"{status}\n\n{mask_to_pretty(mask)}")
        self._refresh_dataset_summary()

    def _load_solution_from_string(self) -> None:
        try:
            grid = parse_puzzle_string(self.solution_string_edit.text())
            if any(grid[r][c] == 0 for r in range(9) for c in range(9)):
                raise ValueError("完成盤面には空欄を含められません。")
            self.solution_board.set_grid(grid)
            self.solution_string_out.setText(grid_to_string(grid))
            self._append_log("完成盤面を文字列から反映しました。")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "エラー", str(e))

    def _load_solution_from_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "JSONを開く", "", "JSON Files (*.json)")
        if not path:
            return

        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))

            solution_string = None
            if isinstance(data, dict):
                if isinstance(data.get("solution_string"), str):
                    solution_string = data["solution_string"]
                elif isinstance(data.get("solutions"), list) and data["solutions"]:
                    first = data["solutions"][0]
                    if isinstance(first, dict) and isinstance(first.get("grid_string"), str):
                        solution_string = first["grid_string"]

            if not solution_string:
                raise ValueError("solution_string か solutions[0].grid_string を見つけられませんでした。")

            grid = parse_puzzle_string(solution_string)
            if any(grid[r][c] == 0 for r in range(9) for c in range(9)):
                raise ValueError("読み込んだ盤面が完成盤面ではありません。")

            self.solution_string_edit.setText(solution_string)
            self.solution_string_out.setText(solution_string)
            self.solution_board.set_grid(grid)
            self._append_log(f"JSONから完成盤面を読み込みました: {path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "エラー", str(e))

    def _load_solution_from_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open JSON", "", "JSON Files (*.json)")
        if not path:
            return

        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            entries = collect_solution_entries_from_json(data)
            if not entries:
                raise ValueError(
                    "solution_string / solution_grid / solutions[*] / results[*] の完成盤面を見つけられませんでした。"
                )

            entry = entries[0]
            self.solution_string_edit.setText(entry["solution_string"])
            self.solution_string_out.setText(entry["solution_string"])
            self.solution_board.set_grid(entry["solution_grid"])

            pattern_mask = entry.get("pattern_mask")
            if isinstance(pattern_mask, str):
                idx = self.pattern_combo.findData(pattern_mask)
                if idx >= 0:
                    self.pattern_combo.setCurrentIndex(idx)

            self._append_log(
                f"JSON から完成盤面を読み込みました: {path} (candidates={len(entries)})"
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(e))

    def _validate_current_solution(self) -> None:
        try:
            pattern_mask = self._current_pattern_mask()
            solution_grid = self.solution_board.get_grid()
            if any(solution_grid[r][c] == 0 for r in range(9) for c in range(9)):
                raise ValueError("完成盤面に空欄があります。")

            result = validate_full_solution(
                solution_grid=solution_grid,
                pattern_mask=pattern_mask,
                time_limit=self.validation_time_spin.value(),
            )
            self.result_summary.setPlainText(
                "完成盤面検証\n"
                f"pattern_mask: {pattern_mask}\n"
                f"classification: {result['classification']}\n"
                f"solver_status: {result['solver_status']}\n"
                f"wall_time_sec: {result['wall_time_sec']:.3f}\n"
            )
            self.solution_string_out.setText(grid_to_string(solution_grid))
            self._append_log("完成盤面の検証を実行しました。")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "エラー", str(e))

    def _set_busy(self, busy: bool) -> None:
        self.generate_btn.setEnabled(not busy)
        self.batch_generate_btn.setEnabled(not busy)
        self.auto_generate_btn.setEnabled(not busy)
        self.check_puzzle_btn.setEnabled(not busy)
        self.validate_solution_btn.setEnabled(not busy)
        self.save_result_btn.setEnabled(not busy)
        self.save_batch_btn.setEnabled(not busy)
        self.auto_input_dir_edit.setEnabled(not busy)
        self.auto_output_dir_edit.setEnabled(not busy)
        self.auto_input_dir_browse_btn.setEnabled(not busy)
        self.auto_output_dir_browse_btn.setEnabled(not busy)

    def _start_generation(self) -> None:
        try:
            pattern_mask = self._current_pattern_mask()
            solution_grid = self.solution_board.get_grid()
            if any(solution_grid[r][c] == 0 for r in range(9) for c in range(9)):
                raise ValueError("完成盤面に空欄があります。")

            params = {
                "solution_grid": solution_grid,
                "pattern_mask": pattern_mask,
                "symmetry": self.symmetry_combo.currentText(),
                "min_clues": self.min_clues_spin.value(),
                "trials": self.trials_spin.value(),
                "seed": self.seed_spin.value(),
                "uniqueness_time_limit": self.uniqueness_time_spin.value(),
                "validation_time_limit": self.validation_time_spin.value(),
            }

            self.log_edit.clear()
            self._append_log("問題生成を開始します。")
            self._run_worker(GeneratorWorker(params), self._on_generation_result)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "エラー", str(e))

    def _start_batch_generation(self) -> None:
        try:
            pattern_mask = self._current_pattern_mask()
            solution_grid = self.solution_board.get_grid()
            if any(solution_grid[r][c] == 0 for r in range(9) for c in range(9)):
                raise ValueError("完成盤面に空欄があります。")

            params = {
                "solution_grid": solution_grid,
                "pattern_mask": pattern_mask,
                "symmetry": self.symmetry_combo.currentText(),
                "min_clues": self.min_clues_spin.value(),
                "trials": self.trials_spin.value(),
                "seed": self.seed_spin.value(),
                "batch_count": self.batch_count_spin.value(),
                "uniqueness_time_limit": self.uniqueness_time_spin.value(),
                "validation_time_limit": self.validation_time_spin.value(),
            }

            self.log_edit.clear()
            self._append_log("バッチ生成を開始します。")
            self._run_worker(BatchGeneratorWorker(params), self._on_batch_generation_result)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "エラー", str(e))

    def _start_batch_generation(self) -> None:
        try:
            pattern_mask = self._current_pattern_mask()
            params = {
                "pattern_mask": pattern_mask,
                "symmetry": self.symmetry_combo.currentText(),
                "min_clues": self.min_clues_spin.value(),
                "trials": self.trials_spin.value(),
                "seed": self.seed_spin.value(),
                "batch_count": self.batch_count_spin.value(),
                "uniqueness_time_limit": self.uniqueness_time_spin.value(),
                "validation_time_limit": self.validation_time_spin.value(),
                "source_mode": self._current_source_mode(),
            }

            if params["source_mode"] == "dataset":
                solution_entries, metadata = self._load_dataset_entries_for_current_pattern()
                if not solution_entries:
                    raise ValueError("dataset から利用できる完成盤面がありません。")
                params.update(
                    {
                        "solution_entries": solution_entries,
                        "dataset_per_solution": self.dataset_per_solution_spin.value(),
                        "dataset_manifest_path": str(self._current_manifest_path()),
                        "dataset_pattern_file": metadata.get("pattern_path", ""),
                        "dataset_pattern_id": metadata.get("pattern_id", ""),
                    }
                )
            else:
                solution_grid = self.solution_board.get_grid()
                if any(solution_grid[r][c] == 0 for r in range(9) for c in range(9)):
                    raise ValueError("完成盤面に空欄があります。")
                params["solution_grid"] = solution_grid

            self.log_edit.clear()
            self._append_log(
                f"batch generation start: mode={params['source_mode']}, "
                f"count={params['batch_count']}"
            )
            self._run_worker(BatchGeneratorWorker(params), self._on_batch_generation_result)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(e))

    def _start_folder_auto_generation(self) -> None:
        try:
            input_dir = self.auto_input_dir_edit.text().strip()
            output_dir = self.auto_output_dir_edit.text().strip() or str(DEFAULT_AUTO_OUTPUT_DIR)
            if not input_dir:
                raise ValueError("input folder is empty")

            params = {
                "input_dir": input_dir,
                "output_dir": output_dir,
                "fallback_pattern_mask": self._current_pattern_mask(),
                "symmetry": self.symmetry_combo.currentText(),
                "min_clues": self.min_clues_spin.value(),
                "trials": self.trials_spin.value(),
                "seed": self.seed_spin.value(),
                "uniqueness_time_limit": self.uniqueness_time_spin.value(),
                "validation_time_limit": self.validation_time_spin.value(),
            }

            self.log_edit.clear()
            self._append_log(
                f"folder auto start: input={params['input_dir']}, output={params['output_dir']}"
            )
            self._run_worker(FolderAutoGenerateWorker(params), self._on_batch_generation_result)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(e))

    def _check_current_puzzle(self) -> None:
        try:
            pattern_mask = self._current_pattern_mask()
            puzzle_grid = self.puzzle_board.get_grid()
            params = {
                "puzzle_grid": puzzle_grid,
                "pattern_mask": pattern_mask,
                "time_limit": self.uniqueness_time_spin.value(),
            }
            self._append_log("現在の問題盤面の一意性判定を開始します。")
            self._run_worker(UniquenessWorker(params), self._on_uniqueness_result)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "エラー", str(e))

    def _run_worker(self, worker: QObject, result_slot) -> None:
        if self._thread is not None:
            QMessageBox.information(self, "実行中", "すでに別の処理が動いています。")
            return

        thread = QThread(self)
        self._thread = thread
        self._worker = worker
        worker.moveToThread(thread)

        worker.log.connect(self._append_log)
        worker.result.connect(result_slot)
        worker.error.connect(self._on_worker_error)
        worker.finished.connect(self._on_worker_finished)
        thread.started.connect(worker.run)
        thread.start()
        self._set_busy(True)

    def _on_generation_result(self, payload: dict[str, Any]) -> None:
        self._current_generated_payload = payload
        self._current_batch_payload = None
        self.batch_table.setRowCount(0)
        self._show_puzzle_payload(payload)
        self._append_log("問題生成が完了しました。")

    def _on_batch_generation_result(self, payload: dict[str, Any]) -> None:
        self._current_batch_payload = payload
        self._current_generated_payload = payload["results"][0] if payload["results"] else None
        self._populate_batch_table(payload)

        if payload["results"]:
            self._show_puzzle_payload(payload["results"][0])

        self.result_summary.setPlainText(
            "バッチ生成結果\n"
            f"pattern_mask: {payload['pattern_mask']}\n"
            f"symmetry: {payload['symmetry']}\n"
            f"requested_batch_count: {payload['requested_batch_count']}\n"
            f"generated_count: {payload['generated_count']}\n"
            f"duplicates_skipped: {payload['duplicates_skipped']}\n"
        )
        self._append_log("バッチ生成が完了しました。")

    def _show_puzzle_payload(self, payload: dict[str, Any]) -> None:
        self.puzzle_board.set_grid(payload["puzzle_grid"])
        self.solution_board.set_grid(payload["solution_grid"])
        self.puzzle_string_edit.setText(payload["puzzle_string"])
        self.solution_string_out.setText(payload["solution_string"])

        final_check = payload["final_uniqueness_check"]
        self.result_summary.setPlainText(
            "問題生成結果\n"
            f"pattern_mask: {payload['pattern_mask']}\n"
            f"symmetry: {payload['symmetry']}\n"
            f"seed: {payload['seed']}\n"
            f"clue_count: {payload['clue_count']}\n"
            f"classification: {final_check['classification']}\n"
            f"solver_status: {final_check['solver_status']}\n"
            f"wall_time_sec: {final_check['wall_time_sec']:.3f}\n"
        )

    def _on_batch_generation_result(self, payload: dict[str, Any]) -> None:
        self._current_batch_payload = payload
        self._current_generated_payload = payload["results"][0] if payload["results"] else None
        self._populate_batch_table(payload)

        if payload["results"]:
            self._show_puzzle_payload(payload["results"][0])

        lines = [
            "batch generation",
            f"source_mode: {payload.get('source_mode', 'current_solution')}",
            f"pattern_mask: {payload['pattern_mask']}",
            f"symmetry: {payload['symmetry']}",
            f"requested_batch_count: {payload['requested_batch_count']}",
            f"generated_count: {payload['generated_count']}",
            f"duplicates_skipped: {payload['duplicates_skipped']}",
            f"source_solution_count: {payload.get('source_solution_count', '')}",
        ]
        if payload.get("source_mode") == "dataset":
            lines.append(f"dataset_per_solution: {payload.get('dataset_per_solution', '')}")
            lines.append(f"dataset_pattern_file: {payload.get('dataset_pattern_file', '')}")
        if payload.get("source_mode") == "folder_auto":
            lines.append(f"processed_file_count: {payload.get('processed_file_count', '')}")
            lines.append(f"skipped_file_count: {payload.get('skipped_file_count', '')}")
            lines.append(f"output_dir: {payload.get('output_dir', '')}")
            lines.append(f"summary_file: {payload.get('summary_file', '')}")
        self.result_summary.setPlainText("\n".join(lines))
        self._append_log("batch generation finished")

    def _show_puzzle_payload(self, payload: dict[str, Any]) -> None:
        self.puzzle_board.set_grid(payload["puzzle_grid"])
        self.solution_board.set_grid(payload["solution_grid"])
        self.puzzle_string_edit.setText(payload["puzzle_string"])
        self.solution_string_out.setText(payload["solution_string"])
        self.solution_string_edit.setText(payload["solution_string"])

        final_check = payload["final_uniqueness_check"]
        lines = [
            "generated puzzle",
            f"source_mode: {payload.get('source_mode', 'current_solution')}",
            f"pattern_mask: {payload['pattern_mask']}",
            f"symmetry: {payload['symmetry']}",
            f"seed: {payload['seed']}",
            f"clue_count: {payload['clue_count']}",
            f"classification: {final_check['classification']}",
            f"solver_status: {final_check['solver_status']}",
            f"wall_time_sec: {final_check['wall_time_sec']:.3f}",
        ]
        if "source_index" in payload:
            lines.append(f"source_index: {payload['source_index']}")
        if "source_file_name" in payload:
            lines.append(f"source_file: {payload['source_file_name']}")
        self.result_summary.setPlainText("\n".join(lines))

    def _populate_batch_table(self, payload: dict[str, Any]) -> None:
        results = payload.get("results", [])
        self.batch_table.setRowCount(len(results))

        for r, entry in enumerate(results):
            status = entry["final_uniqueness_check"].get("classification", "")
            row_values = [
                str(entry.get("index", r + 1)),
                str(entry.get("clue_count", "")),
                str(entry.get("seed", "")),
                status,
                entry.get("puzzle_string", ""),
            ]
            for c, value in enumerate(row_values):
                self.batch_table.setItem(r, c, QTableWidgetItem(value))

        if results:
            self.batch_table.selectRow(0)

    def _load_selected_batch_result(self) -> None:
        if self._current_batch_payload is None:
            return

        selected_rows = self.batch_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        results = self._current_batch_payload.get("results", [])
        if row < 0 or row >= len(results):
            return

        entry = results[row]
        self._current_generated_payload = entry
        self._show_puzzle_payload(entry)

    def _on_uniqueness_result(self, result: dict[str, Any]) -> None:
        self.result_summary.setPlainText(
            "問題盤面判定\n"
            f"classification: {result['classification']}\n"
            f"solver_status: {result['solver_status']}\n"
            f"solutions_found: {result['solution_count_found']}\n"
            f"wall_time_sec: {result['wall_time_sec']:.3f}\n"
        )
        self._append_log("一意性判定が完了しました。")

    def _on_worker_error(self, message: str) -> None:
        QMessageBox.critical(self, "エラー", message)
        self._append_log(f"エラー: {message}")

    def _on_worker_finished(self) -> None:
        if self._thread is None:
            return

        thread = self._thread
        worker = self._worker
        self._thread = None
        self._worker = None

        if worker is not None:
            worker.deleteLater()
        thread.quit()
        thread.wait()
        thread.deleteLater()
        self._set_busy(False)

    def _save_current_result(self) -> None:
        if self._current_generated_payload is None:
            QMessageBox.information(self, "未生成", "保存できる生成結果がありません。")
            return

        path, _ = QFileDialog.getSaveFileName(self, "結果を保存", "generated_puzzle.json", "JSON Files (*.json)")
        if not path:
            return

        try:
            Path(path).write_text(
                json.dumps(self._current_generated_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._append_log(f"結果を保存しました: {path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "保存エラー", str(e))

    def _save_current_batch(self) -> None:
        if self._current_batch_payload is None:
            QMessageBox.information(self, "未生成", "保存できるバッチ結果がありません。")
            return

        path, _ = QFileDialog.getSaveFileName(self, "バッチ結果を保存", "generated_batch.json", "JSON Files (*.json)")
        if not path:
            return

        try:
            Path(path).write_text(
                json.dumps(self._current_batch_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._append_log(f"バッチ結果を保存しました: {path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "保存エラー", str(e))
workbench_rule_extensions.apply(MainWindow)


def main() -> None:
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
