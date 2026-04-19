from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
)

from check_uniqueness import (
    check_uniqueness,
    collect_completions,
    grid_to_string,
    is_complete_grid,
    parse_pattern_mask,
    parse_puzzle_string,
    solve_one_completion,
)
from generate_puzzle import generate_one_puzzle, validate_full_solution
from puzzle_rules import describe_rules
from rule_visuals import (
    build_default_clone_rule,
    build_default_l_tromino_rule,
    build_fixed_rule_g,
    default_clone_summary,
    default_l_tromino_regions_text,
    fixed_rule_g_summary,
)


Grid9 = list[list[int]]
DEFAULT_AUTO_OUTPUT_DIR = Path("outputs/folder_auto_generated")
EMPTY_PATTERN_MASK = "000000000"
RULE_MODE_SPECIAL = "special_monotone_3x3"
RULE_MODE_HYPER = "hyper_3x3"
RULE_MODE_CHECKERBOARD = "checkerboard_odd"
RULE_MODE_L_TROMINO = "l_tromino_sum"
RULE_MODE_CROSS = "cross_monotone"
RULE_MODE_LOCAL_CONSEC = "local_consecutive_exists"
RULE_MODE_BISHOP = "bishop_meet_digits"
RULE_MODE_ANTI_CLOSE = "anti_close_adjacent_3"
RULE_MODE_CLONE = "clone_regions_set_equal"
FIXED_SPECIAL_COMPLETED_PATTERN_MASK = "101010101"


def _accept_completed_grid_validation(validation: dict[str, Any]) -> bool:
    classification = validation.get("classification")
    return classification in {"unique", "multiple", "solved"}


def _is_playable_generated_result(result: dict[str, Any], solution_string: str | None = None) -> bool:
    puzzle_string = result.get("puzzle_string")
    clue_count = result.get("clue_count")
    accepted_groups = result.get("accepted_groups", [])
    if not isinstance(puzzle_string, str):
        return False
    if "0" not in puzzle_string:
        return False
    if isinstance(solution_string, str) and puzzle_string == solution_string:
        return False
    if isinstance(clue_count, int) and clue_count >= 81:
        return False
    if isinstance(accepted_groups, list) and not accepted_groups:
        return False
    return True


def _rule_slug(rule_mode: str) -> str:
    if rule_mode == RULE_MODE_HYPER:
        return "hyper3x3"
    return rule_mode


def _rule_root_dir(rule_mode: str) -> Path:
    return Path("outputs/rules") / _rule_slug(rule_mode)


def _completed_grid_dir(rule_mode: str) -> Path:
    return _rule_root_dir(rule_mode) / "generated_completed_grid"


def _generated_puzzles_dir(rule_mode: str) -> Path:
    return _rule_root_dir(rule_mode) / "generated_puzzles"


def _stored_rules(
    rule_mode: str,
    pattern_mask: str,
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if rule_mode == RULE_MODE_SPECIAL:
        return [{"type": RULE_MODE_SPECIAL, "pattern_mask": pattern_mask}]
    return _clone_rules(rules)


def _next_unique_path(directory: Path, stem_prefix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(1, 100000):
        candidate = directory / f"{stem_prefix}_{index:03d}.json"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate unique output path under {directory}")


def _ensure_noncolliding_path(path: Path) -> Path:
    if not path.exists():
        return path
    return _next_unique_path(path.parent, path.stem)


def _grid_from_json_value(value: Any) -> Grid9 | None:
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


def _normalize_solution_entry(
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

    solution_grid = _grid_from_json_value(raw.get("solution_grid"))
    if solution_grid is None:
        solution_grid = _grid_from_json_value(raw.get("grid"))

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
    rule_mode = raw.get("rule_mode")
    if isinstance(rule_mode, str):
        entry["rule_mode"] = rule_mode
    rule_name = raw.get("rule_name")
    if isinstance(rule_name, str):
        entry["rule_name"] = rule_name
    rules = raw.get("rules")
    if isinstance(rules, list):
        entry["rules"] = _clone_rules(rules)
    return entry


def _collect_solution_entries_from_json(
    data: Any,
    *,
    fallback_pattern_mask: str | None = None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen_solution_strings: set[str] = set()

    def add_candidate(raw: Any, pattern_mask: str | None = None) -> None:
        normalized = _normalize_solution_entry(raw, fallback_pattern_mask=pattern_mask)
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


def _parse_rule_tromino_regions(text: str) -> list[list[list[int]]]:
    regions: list[list[list[int]]] = []
    for raw_part in text.split(";"):
        part = raw_part.strip()
        if not part:
            continue
        cells: list[list[int]] = []
        for raw_cell in part.split("/"):
            bits = [token.strip() for token in raw_cell.split(",")]
            if len(bits) != 2:
                raise ValueError("rule F regions must use 'r,c/r,c/r,c; ...' format")
            row = int(bits[0])
            col = int(bits[1])
            if not (1 <= row <= 9 and 1 <= col <= 9):
                raise ValueError("rule F region coordinates must be 1-based and inside 1..9")
            cells.append([row, col])
        if len(cells) != 3:
            raise ValueError("rule F requires exactly 3 cells per L-tromino region")
        regions.append(cells)
    return regions


def _parse_rule_digits(text: str) -> list[int]:
    digits: list[int] = []
    for raw_part in text.replace(";", ",").split(","):
        part = raw_part.strip()
        if not part:
            continue
        value = int(part)
        if not (1 <= value <= 9):
            raise ValueError("bishop digits must be in 1..9")
        if value not in digits:
            digits.append(value)
    if not digits:
        raise ValueError("bishop digits must not be empty")
    return digits


def _clone_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return json.loads(json.dumps(rules))


def _rule_mode_from_rules(
    rules: list[dict[str, Any]] | None,
    pattern_mask: str | None = None,
) -> str:
    if rules:
        for rule in rules:
            if rule.get("type") == RULE_MODE_HYPER:
                return RULE_MODE_HYPER
            if rule.get("type") == RULE_MODE_CHECKERBOARD:
                return RULE_MODE_CHECKERBOARD
            if rule.get("type") in {RULE_MODE_L_TROMINO, "sum_2x2_regions"}:
                return RULE_MODE_L_TROMINO
            if rule.get("type") == RULE_MODE_CROSS:
                return RULE_MODE_CROSS
            if rule.get("type") == RULE_MODE_LOCAL_CONSEC:
                return RULE_MODE_LOCAL_CONSEC
            if rule.get("type") == RULE_MODE_BISHOP:
                return RULE_MODE_BISHOP
            if rule.get("type") in {RULE_MODE_ANTI_CLOSE, "anti_close_adjacent_4", "anti_close_adjacent_5"}:
                return RULE_MODE_ANTI_CLOSE
            if rule.get("type") == RULE_MODE_CLONE:
                return RULE_MODE_CLONE
            if rule.get("type") == RULE_MODE_SPECIAL:
                return RULE_MODE_SPECIAL
    if isinstance(pattern_mask, str) and pattern_mask.strip("0"):
        return RULE_MODE_SPECIAL
    return RULE_MODE_SPECIAL


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
            seed_grid: Grid9 = self.params.get("seed_grid", solution_grid)
            pattern_mask: str = self.params["pattern_mask"]
            rule_mode: str = self.params.get("rule_mode", RULE_MODE_SPECIAL)
            symmetry: str = self.params["symmetry"]
            min_clues: int = self.params["min_clues"]
            trials: int = self.params["trials"]
            seed: int = self.params["seed"]
            uniqueness_time_limit: float = self.params["uniqueness_time_limit"]
            validation_time_limit: float = self.params["validation_time_limit"]
            rules = _clone_rules(self.params.get("rules", []))
            stored_rules = _stored_rules(rule_mode, pattern_mask, rules)
            rule_name = _rule_slug(rule_mode)

            if any(solution_grid[r][c] == 0 for r in range(9) for c in range(9)):
                solve_result = solve_one_completion(
                    puzzle_grid=seed_grid,
                    special_positions=parse_pattern_mask(pattern_mask),
                    time_limit=validation_time_limit,
                    rules=rules,
                )
                if solve_result["classification"] != "solved" or solve_result["solution"] is None:
                    raise RuntimeError("failed to discover a completed grid under the selected rule")
                solution_grid = solve_result["solution"]

            validation = validate_full_solution(
                solution_grid=solution_grid,
                pattern_mask=pattern_mask,
                time_limit=validation_time_limit,
                rules=rules,
            )
            if not _accept_completed_grid_validation(validation):
                raise RuntimeError("current solution is not valid under the selected rules")

            best_result: dict[str, Any] | None = None
            for trial_index in range(trials):
                result = generate_one_puzzle(
                    solution_grid=solution_grid,
                    pattern_mask=pattern_mask,
                    symmetry=symmetry,
                    uniqueness_time_limit=uniqueness_time_limit,
                    seed=seed + trial_index,
                    target_clues=min_clues,
                    verbose=False,
                    rules=rules,
                )
                if best_result is None or result["clue_count"] < best_result["clue_count"]:
                    best_result = result
                if best_result["clue_count"] == min_clues:
                    break

            assert best_result is not None
            final_check = check_uniqueness(
                puzzle_grid=best_result["puzzle_grid"],
                special_positions=parse_pattern_mask(pattern_mask),
                time_limit=max(uniqueness_time_limit, 10.0),
                rules=rules,
            )
            self.result.emit(
                {
                    "source_mode": "current_solution",
                    "rule_mode": rule_mode,
                    "rule_name": rule_name,
                    "pattern_mask": pattern_mask,
                    "rules": stored_rules,
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
            )
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
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
        solution_string: str,
        pattern_mask: str,
        symmetry: str,
        min_clues: int,
        trials: int,
        base_seed: int,
        uniqueness_time_limit: float,
        rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        best_result: dict[str, Any] | None = None
        best_playable: dict[str, Any] | None = None
        for t in range(trials):
            result = generate_one_puzzle(
                solution_grid=solution_grid,
                pattern_mask=pattern_mask,
                symmetry=symmetry,
                uniqueness_time_limit=uniqueness_time_limit,
                seed=base_seed + t,
                target_clues=min_clues,
                verbose=False,
                rules=rules,
            )
            if best_result is None or result["clue_count"] < best_result["clue_count"]:
                best_result = result
            if _is_playable_generated_result(result, solution_string):
                if best_playable is None or result["clue_count"] < best_playable["clue_count"]:
                    best_playable = result
            if best_result["clue_count"] == min_clues:
                break
        assert best_result is not None
        return best_playable or best_result

    def run(self) -> None:
        try:
            source_mode: str = self.params.get("source_mode", "current_solution")
            pattern_mask: str = self.params["pattern_mask"]
            rule_mode: str = self.params.get("rule_mode", RULE_MODE_SPECIAL)
            symmetry: str = self.params["symmetry"]
            min_clues: int = self.params["min_clues"]
            trials: int = self.params["trials"]
            seed: int = self.params["seed"]
            batch_count: int = self.params["batch_count"]
            uniqueness_time_limit: float = self.params["uniqueness_time_limit"]
            validation_time_limit: float = self.params["validation_time_limit"]
            dataset_per_solution: int = max(1, int(self.params.get("dataset_per_solution", 1)))
            rules = _clone_rules(self.params.get("rules", []))
            stored_rules = _stored_rules(rule_mode, pattern_mask, rules)
            rule_name = _rule_slug(rule_mode)

            if source_mode == "dataset":
                raw_entries = self.params.get("solution_entries")
                if not isinstance(raw_entries, list) or not raw_entries:
                    raise RuntimeError("dataset mode requires at least one complete solution")
                solution_entries: list[dict[str, Any]] = []
                for raw_entry in raw_entries:
                    normalized = _normalize_solution_entry(raw_entry, fallback_pattern_mask=pattern_mask)
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
                seed_grid: Grid9 = self.params.get("seed_grid", solution_grid)
                if any(solution_grid[r][c] == 0 for r in range(9) for c in range(9)):
                    solve_result = solve_one_completion(
                        puzzle_grid=seed_grid,
                        special_positions=parse_pattern_mask(pattern_mask),
                        time_limit=validation_time_limit,
                        rules=rules,
                    )
                    if solve_result["classification"] != "solved" or solve_result["solution"] is None:
                        raise RuntimeError("failed to discover a completed grid under the selected rule")
                    solution_grid = solve_result["solution"]
                solution_entries = [
                    {
                        "solution_grid": solution_grid,
                        "solution_string": grid_to_string(solution_grid),
                        "source_mode": "current_solution",
                        "source_index": 1,
                    }
                ]
                per_source_limit = batch_count

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
                        validation = validate_full_solution(
                            solution_grid=solution_grid,
                            pattern_mask=pattern_mask,
                            time_limit=validation_time_limit,
                            rules=rules,
                        )
                        validation_cache[solution_string] = validation
                        if not _accept_completed_grid_validation(validation):
                            invalid_sources.add(source_idx)
                            continue

                    best_result = self._generate_best_result(
                        solution_grid=solution_grid,
                        solution_string=solution_string,
                        pattern_mask=pattern_mask,
                        symmetry=symmetry,
                        min_clues=min_clues,
                        trials=trials,
                        base_seed=seed + pass_index * 100000 + source_idx * 1000,
                        uniqueness_time_limit=uniqueness_time_limit,
                        rules=rules,
                    )

                    puzzle_string = best_result["puzzle_string"]
                    if not _is_playable_generated_result(best_result, solution_string):
                        duplicates_skipped += 1
                        continue
                    if puzzle_string in seen_puzzles:
                        duplicates_skipped += 1
                        continue

                    seen_puzzles.add(puzzle_string)
                    final_check = check_uniqueness(
                        puzzle_grid=best_result["puzzle_grid"],
                        special_positions=parse_pattern_mask(pattern_mask),
                        time_limit=max(uniqueness_time_limit, 10.0),
                        rules=rules,
                    )

                    entry = {
                        "index": len(results) + 1,
                        "source_mode": source_mode,
                        "rule_mode": rule_mode,
                        "rule_name": rule_name,
                        "pattern_mask": pattern_mask,
                        "rules": stored_rules,
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
                    for key in ("source_file", "source_pattern_id", "source_feasibility_status"):
                        if key in source_entry:
                            entry[key] = source_entry[key]
                    results.append(entry)
                    generated_per_source[source_idx] += 1
                    progress = True

                pass_index += 1
                no_progress_passes = 0 if progress else no_progress_passes + 1

            payload = {
                "source_mode": source_mode,
                "rule_mode": rule_mode,
                "rule_name": rule_name,
                "pattern_mask": pattern_mask,
                "rules": stored_rules,
                "symmetry": symmetry,
                "requested_batch_count": batch_count,
                "generated_count": len(results),
                "duplicates_skipped": duplicates_skipped,
                "source_solution_count": len(solution_entries),
                "results": results,
            }
            if source_mode == "dataset":
                payload["dataset_per_solution"] = per_source_limit
                for key in ("dataset_manifest_path", "dataset_pattern_file", "dataset_pattern_id"):
                    if key in self.params:
                        payload[key] = self.params[key]
            elif solution_entries:
                payload["validation"] = validation_cache.get(solution_entries[0]["solution_string"])
            self.result.emit(payload)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
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
        solution_string: str,
        pattern_mask: str,
        symmetry: str,
        min_clues: int,
        trials: int,
        base_seed: int,
        uniqueness_time_limit: float,
        rules: list[dict[str, Any]],
        max_wall_time_sec: float,
        max_trials: int,
    ) -> dict[str, Any]:
        best_result: dict[str, Any] | None = None
        best_playable: dict[str, Any] | None = None
        for trial_index in range(max(1, min(trials, max_trials))):
            result = generate_one_puzzle(
                solution_grid=solution_grid,
                pattern_mask=pattern_mask,
                symmetry=symmetry,
                uniqueness_time_limit=uniqueness_time_limit,
                seed=base_seed + trial_index,
                target_clues=min_clues,
                verbose=False,
                rules=rules,
                max_wall_time_sec=max_wall_time_sec,
            )
            if best_result is None or result["clue_count"] < best_result["clue_count"]:
                best_result = result
            if _is_playable_generated_result(result, solution_string):
                if best_playable is None or result["clue_count"] < best_playable["clue_count"]:
                    best_playable = result
            if best_result["clue_count"] == min_clues:
                break
        assert best_result is not None
        return best_playable or best_result

    def run(self) -> None:
        try:
            input_dir = Path(self.params["input_dir"])
            output_dir = Path(self.params["output_dir"])
            fallback_pattern_mask: str = self.params["fallback_pattern_mask"]
            rule_mode: str = self.params.get("rule_mode", RULE_MODE_SPECIAL)
            ignore_entry_pattern_mask: bool = bool(self.params.get("ignore_entry_pattern_mask", False))
            symmetry: str = self.params["symmetry"]
            min_clues: int = self.params["min_clues"]
            trials: int = self.params["trials"]
            seed: int = self.params["seed"]
            uniqueness_time_limit: float = self.params["uniqueness_time_limit"]
            validation_time_limit: float = self.params["validation_time_limit"]
            rules = _clone_rules(self.params.get("rules", []))
            stored_rules = _stored_rules(rule_mode, fallback_pattern_mask, rules)
            rule_name = _rule_slug(rule_mode)
            # Folder auto is meant to run end-to-end over many completed grids, so cap per-entry work.
            per_entry_generation_budget = max(8.0, min(25.0, uniqueness_time_limit * 3.0))
            per_entry_trial_cap = 4

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
                try:
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                except Exception as exc:  # noqa: BLE001
                    skipped_files.append({"source_file": str(json_path), "reason": str(exc)})
                    continue

                entries = _collect_solution_entries_from_json(data, fallback_pattern_mask=fallback_pattern_mask)
                if not entries:
                    skipped_files.append(
                        {"source_file": str(json_path), "reason": "no compatible complete-solution entry found"}
                    )
                    continue

                file_results: list[dict[str, Any]] = []
                skipped_entries: list[dict[str, Any]] = []
                file_duplicate_count = 0

                for entry_index, entry in enumerate(entries, start=1):
                    source_solution_count += 1
                    pattern_mask = fallback_pattern_mask
                    if not ignore_entry_pattern_mask:
                        entry_pattern_mask = entry.get("pattern_mask")
                        if isinstance(entry_pattern_mask, str):
                            pattern_mask = entry_pattern_mask

                    solution_grid = entry["solution_grid"]
                    solution_string = entry["solution_string"]
                    cache_key = (pattern_mask, solution_string)
                    validation = validation_cache.get(cache_key)

                    if validation is None:
                        validation = validate_full_solution(
                            solution_grid=solution_grid,
                            pattern_mask=pattern_mask,
                            time_limit=validation_time_limit,
                            rules=rules,
                        )
                        validation_cache[cache_key] = validation

                    if not _accept_completed_grid_validation(validation):
                        skipped_entries.append(
                            {
                                "entry_index": entry_index,
                                "pattern_mask": pattern_mask,
                                "reason": f"validation={validation['classification']}",
                            }
                        )
                        continue

                    best_result = self._generate_best_result(
                        solution_grid=solution_grid,
                        solution_string=solution_string,
                        pattern_mask=pattern_mask,
                        symmetry=symmetry,
                        min_clues=min_clues,
                        trials=trials,
                        base_seed=seed + file_index * 100000 + entry_index * 1000,
                        uniqueness_time_limit=uniqueness_time_limit,
                        rules=rules,
                        max_wall_time_sec=per_entry_generation_budget,
                        max_trials=per_entry_trial_cap,
                    )

                    puzzle_string = best_result["puzzle_string"]
                    if not _is_playable_generated_result(best_result, solution_string):
                        skipped_entries.append(
                            {
                                "entry_index": entry_index,
                                "pattern_mask": pattern_mask,
                                "reason": "generation produced no playable removals",
                            }
                        )
                        continue
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
                        continue

                    seen_puzzles.add(puzzle_string)
                    final_check = check_uniqueness(
                        puzzle_grid=best_result["puzzle_grid"],
                        special_positions=parse_pattern_mask(pattern_mask),
                        time_limit=uniqueness_time_limit,
                        rules=rules,
                    )

                    payload = {
                        "index": len(results) + 1,
                        "source_mode": "folder_auto",
                        "rule_mode": rule_mode,
                        "rule_name": rule_name,
                        "pattern_mask": pattern_mask,
                        "rules": stored_rules,
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

                output_payload = {
                    "source_mode": "folder_auto_file",
                    "rule_mode": rule_mode,
                    "rule_name": rule_name,
                    "source_file": str(json_path),
                    "pattern_fallback_mask": fallback_pattern_mask,
                    "rules": stored_rules,
                    "symmetry": symmetry,
                    "min_clues": min_clues,
                    "trials": trials,
                    "processed_entry_count": len(entries),
                    "generated_count": len(file_results),
                    "duplicates_skipped": file_duplicate_count,
                    "results": file_results,
                    "skipped_entries": skipped_entries,
                }
                output_path = _next_unique_path(output_dir, f"{rule_name}__{json_path.stem}__generated")
                output_path.write_text(json.dumps(output_payload, ensure_ascii=False, indent=2), encoding="utf-8")
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
                "rule_mode": rule_mode,
                "rule_name": rule_name,
                "input_dir": str(input_dir),
                "output_dir": str(output_dir),
                "pattern_mask": fallback_pattern_mask,
                "rules": stored_rules,
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
            summary_path = _next_unique_path(output_dir, f"{rule_name}__folder_run_summary")
            summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            summary_payload["summary_file"] = str(summary_path)
            self.result.emit(summary_payload)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
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
            result = check_uniqueness(
                puzzle_grid=self.params["puzzle_grid"],
                special_positions=parse_pattern_mask(self.params["pattern_mask"]),
                time_limit=self.params["time_limit"],
                rules=_clone_rules(self.params.get("rules", [])),
            )
            self.result.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class SeedSolveWorker(QObject):
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
            rule_mode: str = self.params.get("rule_mode", RULE_MODE_SPECIAL)
            time_limit: float = self.params["time_limit"]
            max_solutions: int = max(1, int(self.params.get("max_solutions", 1)))
            rules = _clone_rules(self.params.get("rules", []))
            rule_name = _rule_slug(rule_mode)
            rules_variants_raw = self.params.get("rules_variants")
            rules_variants: list[list[dict[str, Any]]] = []
            if isinstance(rules_variants_raw, list):
                for raw_variant in rules_variants_raw:
                    if isinstance(raw_variant, list):
                        rules_variants.append(_clone_rules(raw_variant))
            if not rules_variants:
                rules_variants = [rules]

            special_positions = parse_pattern_mask(pattern_mask)
            deadline = time.perf_counter() + time_limit
            found_solutions: list[Grid9] = []
            found_rulesets: list[list[dict[str, Any]]] = []
            seen_solution_strings: set[str] = set()
            solver_status = "UNKNOWN"
            stalled_passes = 0

            while len(found_solutions) < max_solutions and time.perf_counter() < deadline and stalled_passes < 2:
                progress = False
                for variant_rules in rules_variants:
                    if len(found_solutions) >= max_solutions:
                        break
                    remaining = deadline - time.perf_counter()
                    if remaining <= 0:
                        break
                    result = collect_completions(
                        puzzle_grid=puzzle_grid,
                        special_positions=special_positions,
                        time_limit=remaining,
                        max_solutions=1,
                        rules=variant_rules,
                        forbidden_solutions=found_solutions,
                    )
                    solver_status = result["solver_status"]
                    if result["classification"] != "solved" or not result["solutions"]:
                        continue
                    candidate = result["solutions"][0]
                    if not is_complete_grid(candidate):
                        continue
                    candidate_key = grid_to_string(candidate)
                    if candidate_key in seen_solution_strings:
                        continue
                    seen_solution_strings.add(candidate_key)
                    found_solutions.append(candidate)
                    found_rulesets.append(variant_rules)
                    progress = True
                stalled_passes = 0 if progress else stalled_passes + 1

            if found_solutions:
                classification = "solved"
                feasibility_status = "FEASIBLE"
            elif solver_status == "INFEASIBLE":
                classification = "no_solution"
                feasibility_status = "INFEASIBLE"
            else:
                classification = "unknown"
                feasibility_status = "UNKNOWN"

            solutions_payload: list[dict[str, Any]] = []
            for index, solution in enumerate(found_solutions):
                variant_rules = found_rulesets[index]
                solutions_payload.append(
                    {
                        "grid_string": grid_to_string(solution),
                        "grid": solution,
                        "rules": _stored_rules(rule_mode, pattern_mask, variant_rules),
                    }
                )

            payload = {
                "source_mode": "auto_rule_source",
                "rule_mode": rule_mode,
                "rule_name": rule_name,
                "pattern_mask": pattern_mask,
                "pattern_mask_string": pattern_mask,
                "rules": _stored_rules(rule_mode, pattern_mask, rules),
                "input_puzzle_grid": puzzle_grid,
                "input_puzzle_string": grid_to_string(puzzle_grid),
                "feasibility_status": feasibility_status,
                "classification": classification,
                "solver_status": solver_status,
                "requested_solution_count": max_solutions,
                "solution_count_found": len(solutions_payload),
                "reached_limit": len(solutions_payload) >= max_solutions,
                "wall_time_sec": max(0.0, time_limit - max(0.0, deadline - time.perf_counter())),
                "solutions": solutions_payload,
            }
            self.result.emit(payload)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


def apply(MainWindow) -> None:
    if getattr(MainWindow, "_rule_extension_applied", False):
        return

    original_init = MainWindow.__init__
    original_set_busy = MainWindow._set_busy
    original_load_dataset_entries_for_current_pattern = MainWindow._load_dataset_entries_for_current_pattern

    def current_rule_mode(self) -> str:
        if not hasattr(self, "rule_mode_combo"):
            return RULE_MODE_SPECIAL
        data = self.rule_mode_combo.currentData()
        if isinstance(data, str):
            return data
        return RULE_MODE_SPECIAL

    def current_rule_context(self) -> dict[str, Any]:
        rule_mode = self._current_rule_mode()
        if rule_mode == RULE_MODE_HYPER:
            return {
                "rule_mode": RULE_MODE_HYPER,
                "pattern_mask": EMPTY_PATTERN_MASK,
                "rules": [{"type": RULE_MODE_HYPER}],
                "pattern_enabled": False,
                "dataset_available": False,
            }
        if rule_mode == RULE_MODE_CHECKERBOARD:
            return {
                "rule_mode": RULE_MODE_CHECKERBOARD,
                "pattern_mask": EMPTY_PATTERN_MASK,
                "rules": [{"type": RULE_MODE_CHECKERBOARD}],
                "pattern_enabled": False,
                "dataset_available": False,
            }
        if rule_mode == RULE_MODE_L_TROMINO:
            rule = build_default_l_tromino_rule()
            rule["regions"] = _parse_rule_tromino_regions(self.rule_sum_regions_edit.text())
            rule["target_sum"] = int(self.rule_sum_target_spin.value())
            return {
                "rule_mode": RULE_MODE_L_TROMINO,
                "pattern_mask": EMPTY_PATTERN_MASK,
                "rules": [rule],
                "pattern_enabled": False,
                "dataset_available": False,
            }
        if rule_mode == RULE_MODE_CROSS:
            return {
                "rule_mode": RULE_MODE_CROSS,
                "pattern_mask": EMPTY_PATTERN_MASK,
                "rules": [build_fixed_rule_g()],
                "pattern_enabled": False,
                "dataset_available": False,
            }
        if rule_mode == RULE_MODE_LOCAL_CONSEC:
            return {
                "rule_mode": RULE_MODE_LOCAL_CONSEC,
                "pattern_mask": EMPTY_PATTERN_MASK,
                "rules": [{"type": RULE_MODE_LOCAL_CONSEC}],
                "pattern_enabled": False,
                "dataset_available": False,
            }
        if rule_mode == RULE_MODE_BISHOP:
            return {
                "rule_mode": RULE_MODE_BISHOP,
                "pattern_mask": EMPTY_PATTERN_MASK,
                "rules": [{"type": RULE_MODE_BISHOP, "digits": _parse_rule_digits(self.rule_bishop_digits_edit.text())}],
                "pattern_enabled": False,
                "dataset_available": False,
            }
        if rule_mode == RULE_MODE_ANTI_CLOSE:
            return {
                "rule_mode": RULE_MODE_ANTI_CLOSE,
                "pattern_mask": EMPTY_PATTERN_MASK,
                "rules": [{"type": RULE_MODE_ANTI_CLOSE}],
                "pattern_enabled": False,
                "dataset_available": False,
            }
        if rule_mode == RULE_MODE_CLONE:
            return {
                "rule_mode": RULE_MODE_CLONE,
                "pattern_mask": EMPTY_PATTERN_MASK,
                "rules": [build_default_clone_rule()],
                "pattern_enabled": False,
                "dataset_available": False,
            }

        return {
            "rule_mode": RULE_MODE_SPECIAL,
            "pattern_mask": self._current_pattern_mask(),
            "rules": [],
            "pattern_enabled": True,
            "dataset_available": True,
        }

    def current_seed_rule_context(self) -> dict[str, Any]:
        context = self._current_rule_context()
        if context["rule_mode"] == RULE_MODE_SPECIAL:
            seed_context = dict(context)
            seed_context["pattern_mask"] = FIXED_SPECIAL_COMPLETED_PATTERN_MASK
            return seed_context
        return context

    def empty_grid(self) -> Grid9:
        return [[0 for _ in range(9)] for _ in range(9)]

    def current_seed_search_grid(self) -> Grid9:
        if hasattr(self, "seed_use_puzzle_checkbox") and self.seed_use_puzzle_checkbox.isChecked():
            return self.puzzle_board.get_grid()
        return self._empty_grid()

    def build_search_rule_variants(self, context: dict[str, Any]) -> list[list[dict[str, Any]]]:
        return [context["rules"]]

    def infer_auto_output_dir(self, input_dir: str, rule_mode: str) -> str:
        input_path = Path(input_dir)
        if input_path.name == "generated_completed_grid":
            return str(input_path.parent / "generated_puzzles")
        return str(_generated_puzzles_dir(rule_mode))

    def sync_auto_output_dir(self) -> None:
        try:
            input_dir = self.auto_input_dir_edit.text().strip()
            rule_mode = self._current_rule_mode()
            if input_dir:
                output_dir = self._infer_auto_output_dir(input_dir, rule_mode)
            else:
                output_dir = str(_generated_puzzles_dir(rule_mode))
            self.auto_output_dir_edit.blockSignals(True)
            self.auto_output_dir_edit.setText(output_dir)
            self.auto_output_dir_edit.blockSignals(False)
        except Exception:
            return

    def collect_active_rules(self) -> list[dict[str, Any]]:
        return _clone_rules(self._current_rule_context()["rules"])

    def sync_board_rule_visuals(self) -> None:
        try:
            context = self._current_rule_context()
            self.solution_board.set_rule_visuals(context["pattern_mask"], context["rules"])
            self.puzzle_board.set_rule_visuals(context["pattern_mask"], context["rules"])
        except Exception:
            return

    def apply_rules_to_ui(self, rules: list[dict[str, Any]] | None) -> None:
        try:
            rule_mode = _rule_mode_from_rules(rules)
            if rules:
                for rule in rules:
                    if rule.get("type") in {RULE_MODE_L_TROMINO, "sum_2x2_regions"}:
                        regions = rule.get("regions", [])
                        if isinstance(regions, list):
                            text_parts: list[str] = []
                            for raw in regions:
                                if not isinstance(raw, list | tuple) or len(raw) != 3:
                                    continue
                                cell_texts: list[str] = []
                                for cell in raw:
                                    if isinstance(cell, list | tuple) and len(cell) == 2:
                                        row = int(cell[0])
                                        col = int(cell[1])
                                        if row == 0 or col == 0:
                                            row += 1
                                            col += 1
                                        cell_texts.append(f"{row},{col}")
                                if len(cell_texts) == 3:
                                    text_parts.append("/".join(cell_texts))
                            if text_parts:
                                self.rule_sum_regions_edit.setText("; ".join(text_parts))
                        target_sum = rule.get("target_sum")
                        if isinstance(target_sum, int):
                            self.rule_sum_target_spin.setValue(target_sum)
                    if rule.get("type") == RULE_MODE_BISHOP:
                        digits = rule.get("digits", [])
                        if isinstance(digits, list) and digits:
                            self.rule_bishop_digits_edit.setText(", ".join(str(int(digit)) for digit in digits))
            if hasattr(self, "rule_mode_combo"):
                idx = self.rule_mode_combo.findData(rule_mode)
                if idx >= 0:
                    self.rule_mode_combo.setCurrentIndex(idx)
            if hasattr(self, "rule_crosses_edit"):
                self.rule_crosses_edit.setText(fixed_rule_g_summary())
            if hasattr(self, "rule_clone_edit"):
                self.rule_clone_edit.setText(default_clone_summary())
            self._on_rule_mode_changed()
            self._sync_board_rule_visuals()
            self._refresh_rule_summary()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "UI Error", str(exc))

    def refresh_rule_summary(self) -> None:
        try:
            context = self._current_rule_context()
            lines = [
                f"selected rule: {context['rule_mode']}",
                "active rules:",
            ]
            if context["rules"]:
                lines.extend(describe_rules(context["rules"]))
            else:
                lines.append(
                    f"special_monotone_3x3(pattern_mask={context['pattern_mask']})"
                )
            if context["rule_mode"] == RULE_MODE_CROSS:
                lines.append(f"layout: {fixed_rule_g_summary()}")
            lines.append("TODO: Rule J rank_cells remains intentionally unimplemented.")
            self.rule_summary_edit.setPlainText("\n".join(lines))
        except Exception as exc:  # noqa: BLE001
            self.rule_summary_edit.setPlainText(f"rule parse error: {exc}")

    def on_rule_mode_changed(self) -> None:
        try:
            try:
                context = self._current_rule_context()
            except Exception:
                context = {
                    "rule_mode": RULE_MODE_SPECIAL,
                    "pattern_enabled": True,
                    "dataset_available": True,
                }

            pattern_enabled = bool(context["pattern_enabled"])
            for widget_name in ("pattern_combo", "only_feasible_checkbox", "pattern_preview"):
                widget = getattr(self, widget_name, None)
                if widget is not None:
                    widget.setEnabled(pattern_enabled)

            sum_enabled = context["rule_mode"] == RULE_MODE_L_TROMINO
            self.rule_sum_regions_edit.setEnabled(sum_enabled)
            self.rule_sum_target_spin.setEnabled(sum_enabled)

            cross_enabled = context["rule_mode"] == RULE_MODE_CROSS
            self.rule_crosses_edit.setEnabled(cross_enabled)
            bishop_enabled = context["rule_mode"] == RULE_MODE_BISHOP
            self.rule_bishop_digits_edit.setEnabled(bishop_enabled)
            clone_enabled = context["rule_mode"] == RULE_MODE_CLONE
            self.rule_clone_edit.setEnabled(clone_enabled)

            if context["dataset_available"]:
                self.source_mode_combo.setEnabled(True)
            else:
                self.source_mode_combo.blockSignals(True)
                idx = self.source_mode_combo.findData("current_solution")
                if idx >= 0:
                    self.source_mode_combo.setCurrentIndex(idx)
                self.source_mode_combo.blockSignals(False)
                self.source_mode_combo.setEnabled(False)

            if hasattr(self, "seed_use_puzzle_checkbox"):
                self.seed_use_puzzle_checkbox.setChecked(False)

            self._update_source_mode_ui()
            self._sync_auto_output_dir()
            self._sync_board_rule_visuals()
            self._refresh_rule_summary()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "UI Error", str(exc))

    def update_source_mode_ui(self) -> None:
        try:
            context = self._current_rule_context()
            is_dataset = context["dataset_available"] and self._current_source_mode() == "dataset"
            self.dataset_manifest_edit.setEnabled(is_dataset)
            self.dataset_manifest_browse_btn.setEnabled(is_dataset)
            self.dataset_reload_btn.setEnabled(is_dataset)
            self.dataset_per_solution_spin.setEnabled(is_dataset)
            self.dataset_info.setEnabled(True)
            self._refresh_dataset_summary()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "UI Error", str(exc))

    def refresh_dataset_summary(self) -> None:
        context = self._current_rule_context()
        manifest_path = self._current_manifest_path()
        mode = self._current_source_mode()
        lines = [
            f"selected rule: {context['rule_mode']}",
            f"mode: {mode}",
            f"manifest: {manifest_path}",
        ]

        if not context["dataset_available"]:
            lines.append("dataset_status: unavailable for this rule")
            self._dataset_metadata = {}
            self.dataset_info.setPlainText("\n".join(lines))
            return

        if not manifest_path.exists():
            lines.append("manifest_status: missing")
            self._dataset_metadata = {}
            self.dataset_info.setPlainText("\n".join(lines))
            return

        pattern_mask = context["pattern_mask"]
        try:
            entries, metadata = self._load_dataset_entries_for_current_pattern()
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

    def load_dataset_entries_for_current_pattern(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        context = self._current_rule_context()
        if not context["dataset_available"]:
            raise ValueError("dataset source is available only for special_monotone_3x3")
        return original_load_dataset_entries_for_current_pattern(self)

    def patched_init(self) -> None:
        original_init(self)
        self._current_seed_solve_payload = None
        root_layout = self.centralWidget().layout()
        left_scroll = root_layout.itemAt(0).widget()
        left_panel = left_scroll.widget()
        left_col = left_panel.layout()

        self.rule_box = QGroupBox("rules")
        rule_layout = QFormLayout(self.rule_box)

        self.rule_mode_combo = QComboBox()
        self.rule_mode_combo.addItem("special_monotone_3x3", RULE_MODE_SPECIAL)
        self.rule_mode_combo.addItem("hyper_3x3", RULE_MODE_HYPER)
        self.rule_mode_combo.addItem("checkerboard_odd (white cells odd)", RULE_MODE_CHECKERBOARD)
        self.rule_mode_combo.addItem("l_tromino_sum_13", RULE_MODE_L_TROMINO)
        self.rule_mode_combo.addItem("cross_monotone", RULE_MODE_CROSS)
        self.rule_mode_combo.addItem("local_consecutive_exists", RULE_MODE_LOCAL_CONSEC)
        self.rule_mode_combo.addItem("bishop_meet_digits", RULE_MODE_BISHOP)
        self.rule_mode_combo.addItem("anti_close_adjacent_3", RULE_MODE_ANTI_CLOSE)
        self.rule_mode_combo.addItem("clone_regions_set_equal", RULE_MODE_CLONE)
        rule_layout.addRow("selected", self.rule_mode_combo)

        self.rule_sum_regions_edit = QLineEdit(default_l_tromino_regions_text())
        self.rule_sum_regions_edit.setPlaceholderText("r,c/r,c/r,c; ...")
        rule_layout.addRow("Rule F' trominoes", self.rule_sum_regions_edit)

        self.rule_sum_target_spin = QSpinBox()
        self.rule_sum_target_spin.setRange(1, 36)
        self.rule_sum_target_spin.setValue(13)
        rule_layout.addRow("Rule F' target", self.rule_sum_target_spin)

        self.rule_crosses_edit = QLineEdit(fixed_rule_g_summary())
        self.rule_crosses_edit.setReadOnly(True)
        rule_layout.addRow("Rule G layout", self.rule_crosses_edit)

        self.rule_bishop_digits_edit = QLineEdit("1")
        self.rule_bishop_digits_edit.setPlaceholderText("1, 3, 5")
        rule_layout.addRow("Rule D digits", self.rule_bishop_digits_edit)

        self.rule_clone_edit = QLineEdit(default_clone_summary())
        self.rule_clone_edit.setReadOnly(True)
        rule_layout.addRow("Rule I layout", self.rule_clone_edit)

        self.rule_summary_edit = QPlainTextEdit()
        self.rule_summary_edit.setReadOnly(True)
        self.rule_summary_edit.setMinimumHeight(72)
        rule_layout.addRow(self.rule_summary_edit)

        left_col.insertWidget(5, self.rule_box)

        self.rule_mode_combo.currentIndexChanged.connect(self._on_rule_mode_changed)
        self.rule_sum_regions_edit.editingFinished.connect(self._refresh_rule_summary)
        self.rule_sum_target_spin.valueChanged.connect(self._refresh_rule_summary)
        self.rule_sum_regions_edit.editingFinished.connect(self._sync_board_rule_visuals)
        self.rule_sum_target_spin.valueChanged.connect(self._sync_board_rule_visuals)
        self.rule_bishop_digits_edit.editingFinished.connect(self._refresh_rule_summary)
        self.rule_bishop_digits_edit.editingFinished.connect(self._sync_board_rule_visuals)
        self.pattern_combo.currentIndexChanged.connect(self._sync_board_rule_visuals)

        self.seed_solve_box = QGroupBox("source search")
        seed_layout = QFormLayout(self.seed_solve_box)

        self.seed_solve_hint = QPlainTextEdit()
        self.seed_solve_hint.setReadOnly(True)
        self.seed_solve_hint.setPlainText(
            "Search one completed grid under the selected rule.\n"
            "By default this starts from an empty grid. Turn on the option below only when you want to use the current puzzle board as givens."
        )
        self.seed_solve_hint.setMinimumHeight(64)
        seed_layout.addRow(self.seed_solve_hint)

        self.seed_use_puzzle_checkbox = QCheckBox("Use current puzzle board as givens")
        self.seed_use_puzzle_checkbox.setChecked(False)
        seed_layout.addRow(self.seed_use_puzzle_checkbox)

        self.seed_solution_count_spin = QSpinBox()
        self.seed_solution_count_spin.setRange(1, 500)
        self.seed_solution_count_spin.setValue(50)
        seed_layout.addRow("count", self.seed_solution_count_spin)

        self.solve_seed_btn = QPushButton("Search Full Grids")
        self.solve_seed_btn.clicked.connect(self._solve_current_seed)
        seed_layout.addRow(self.solve_seed_btn)

        self.save_seed_btn = QPushButton("Save Full Grid Sources")
        self.save_seed_btn.clicked.connect(self._save_current_seed_solve)
        self.save_seed_btn.setEnabled(False)
        seed_layout.addRow(self.save_seed_btn)

        left_col.insertWidget(6, self.seed_solve_box)
        self.rule_mode_combo.setMinimumHeight(28)
        self.rule_sum_regions_edit.setMinimumHeight(28)
        self.rule_sum_target_spin.setMinimumHeight(28)
        self.rule_crosses_edit.setMinimumHeight(28)
        self.rule_bishop_digits_edit.setMinimumHeight(28)
        self.rule_clone_edit.setMinimumHeight(28)
        self.seed_use_puzzle_checkbox.setMinimumHeight(28)
        self.seed_solution_count_spin.setMinimumHeight(28)
        self.solve_seed_btn.setMinimumHeight(28)
        self.save_seed_btn.setMinimumHeight(28)
        self.auto_input_dir_edit.textChanged.connect(self._sync_auto_output_dir)
        self._sync_board_rule_visuals()
        self._on_rule_mode_changed()

    def run_worker(self, worker: QObject, result_slot) -> None:
        if self._thread is not None:
            QMessageBox.information(self, "実行中", "すでに別の処理が動いています。")
            return

        thread = QThread(self)
        self._thread = thread
        self._worker = worker
        worker.moveToThread(thread)

        worker.log.connect(self._append_log, Qt.QueuedConnection)
        worker.result.connect(result_slot, Qt.QueuedConnection)
        worker.error.connect(self._on_worker_error, Qt.QueuedConnection)
        worker.finished.connect(self._on_worker_finished, Qt.QueuedConnection)
        thread.started.connect(worker.run, Qt.QueuedConnection)
        thread.start()
        self._set_busy(True)

    def load_solution_from_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open JSON", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            entries = _collect_solution_entries_from_json(data)
            if not entries:
                raise ValueError("No compatible complete-solution entries were found.")
            entry = entries[0]
            self.solution_string_edit.setText(entry["solution_string"])
            self.solution_string_out.setText(entry["solution_string"])
            self.solution_board.set_grid(entry["solution_grid"])

            rules = None
            pattern_mask = None
            if isinstance(data, dict):
                maybe_pattern_mask = data.get("pattern_mask")
                if isinstance(maybe_pattern_mask, str):
                    pattern_mask = maybe_pattern_mask
                if isinstance(data.get("rules"), list):
                    rules = data["rules"]
                elif isinstance(data.get("results"), list) and data["results"]:
                    first = data["results"][0]
                    if isinstance(first, dict):
                        if isinstance(first.get("rules"), list):
                            rules = first["rules"]
                        maybe_pattern_mask = first.get("pattern_mask")
                        if pattern_mask is None and isinstance(maybe_pattern_mask, str):
                            pattern_mask = maybe_pattern_mask

            if pattern_mask is None:
                entry_pattern_mask = entry.get("pattern_mask")
                if isinstance(entry_pattern_mask, str):
                    pattern_mask = entry_pattern_mask

            self._apply_rules_to_ui(rules)
            if self._current_rule_mode() == RULE_MODE_SPECIAL and isinstance(pattern_mask, str):
                idx = self.pattern_combo.findData(pattern_mask)
                if idx >= 0:
                    self.pattern_combo.setCurrentIndex(idx)
            self._append_log(f"loaded solution from JSON: {path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(exc))

    def validate_current_solution(self) -> None:
        try:
            context = self._current_rule_context()
            solution_grid = self.solution_board.get_grid()
            if any(solution_grid[r][c] == 0 for r in range(9) for c in range(9)):
                raise ValueError("solution grid must be fully filled")
            result = validate_full_solution(
                solution_grid=solution_grid,
                pattern_mask=context["pattern_mask"],
                time_limit=self.validation_time_spin.value(),
                rules=context["rules"],
            )
            self.result_summary.setPlainText(
                "\n".join(
                    [
                        "solution validation",
                        f"rule_mode: {context['rule_mode']}",
                        f"pattern_mask: {context['pattern_mask']}",
                        f"rules: {', '.join(describe_rules(context['rules'])) if context['rules'] else '(none)'}",
                        f"classification: {result['classification']}",
                        f"solver_status: {result['solver_status']}",
                        f"wall_time_sec: {result['wall_time_sec']:.3f}",
                    ]
                )
            )
            self.solution_string_out.setText(grid_to_string(solution_grid))
            self._append_log("validated current solution")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(exc))

    def start_generation(self) -> None:
        try:
            solution_grid = self.solution_board.get_grid()
            context = self._current_rule_context()
            if any(solution_grid[r][c] == 0 for r in range(9) for c in range(9)):
                context = self._current_seed_rule_context()
            params = {
                "solution_grid": solution_grid,
                "seed_grid": self._current_seed_search_grid(),
                "rule_mode": context["rule_mode"],
                "pattern_mask": context["pattern_mask"],
                "rules": context["rules"],
                "symmetry": self.symmetry_combo.currentText(),
                "min_clues": self.min_clues_spin.value(),
                "trials": self.trials_spin.value(),
                "seed": self.seed_spin.value(),
                "uniqueness_time_limit": self.uniqueness_time_spin.value(),
                "validation_time_limit": self.validation_time_spin.value(),
            }
            self.log_edit.clear()
            self._append_log("generation start")
            self._run_worker(GeneratorWorker(params), self._on_generation_result)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(exc))

    def start_batch_generation(self) -> None:
        try:
            context = self._current_rule_context()
            source_mode = self._current_source_mode()
            if not context["dataset_available"]:
                source_mode = "current_solution"
            params = {
                "rule_mode": context["rule_mode"],
                "pattern_mask": context["pattern_mask"],
                "rules": context["rules"],
                "symmetry": self.symmetry_combo.currentText(),
                "min_clues": self.min_clues_spin.value(),
                "trials": self.trials_spin.value(),
                "seed": self.seed_spin.value(),
                "batch_count": self.batch_count_spin.value(),
                "uniqueness_time_limit": self.uniqueness_time_spin.value(),
                "validation_time_limit": self.validation_time_spin.value(),
                "source_mode": source_mode,
            }

            if params["source_mode"] == "dataset":
                solution_entries, metadata = self._load_dataset_entries_for_current_pattern()
                if not solution_entries:
                    raise ValueError("dataset mode did not provide any complete solutions")
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
                    context = self._current_seed_rule_context()
                    params["rule_mode"] = context["rule_mode"]
                    params["pattern_mask"] = context["pattern_mask"]
                    params["rules"] = context["rules"]
                params["solution_grid"] = solution_grid
                params["seed_grid"] = self._current_seed_search_grid()

            self.log_edit.clear()
            self._append_log(
                f"batch generation start: mode={params['source_mode']}, count={params['batch_count']}"
            )
            self._run_worker(BatchGeneratorWorker(params), self._on_batch_generation_result)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(exc))

    def start_folder_auto_generation(self) -> None:
        try:
            input_dir = self.auto_input_dir_edit.text().strip()
            if not input_dir:
                raise ValueError("input folder is empty")
            context = self._current_rule_context()
            raw_output_dir = self.auto_output_dir_edit.text().strip()
            if not raw_output_dir or raw_output_dir == str(DEFAULT_AUTO_OUTPUT_DIR):
                output_dir = self._infer_auto_output_dir(input_dir, context["rule_mode"])
                self.auto_output_dir_edit.setText(output_dir)
            else:
                output_dir = raw_output_dir
            params = {
                "input_dir": input_dir,
                "output_dir": output_dir,
                "rule_mode": context["rule_mode"],
                "fallback_pattern_mask": context["pattern_mask"],
                "ignore_entry_pattern_mask": not context["dataset_available"],
                "rules": context["rules"],
                "symmetry": self.symmetry_combo.currentText(),
                "min_clues": self.min_clues_spin.value(),
                "trials": self.trials_spin.value(),
                "seed": self.seed_spin.value(),
                "uniqueness_time_limit": self.uniqueness_time_spin.value(),
                "validation_time_limit": self.validation_time_spin.value(),
            }
            self.log_edit.clear()
            self._append_log(f"folder auto start: input={input_dir}, output={output_dir}")
            self._run_worker(FolderAutoGenerateWorker(params), self._on_batch_generation_result)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(exc))

    def check_current_puzzle(self) -> None:
        try:
            context = self._current_rule_context()
            params = {
                "puzzle_grid": self.puzzle_board.get_grid(),
                "rule_mode": context["rule_mode"],
                "pattern_mask": context["pattern_mask"],
                "rules": context["rules"],
                "time_limit": self.uniqueness_time_spin.value(),
            }
            self._append_log("checking current puzzle uniqueness")
            self._run_worker(UniquenessWorker(params), self._on_uniqueness_result)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(exc))

    def solve_current_seed(self) -> None:
        try:
            self._current_seed_solve_payload = None
            self.save_seed_btn.setEnabled(False)
            context = self._current_seed_rule_context()
            params = {
                "puzzle_grid": self._current_seed_search_grid(),
                "rule_mode": context["rule_mode"],
                "pattern_mask": context["pattern_mask"],
                "rules": context["rules"],
                "rules_variants": self._build_search_rule_variants(context),
                "time_limit": self.validation_time_spin.value(),
                "max_solutions": self.seed_solution_count_spin.value(),
            }
            self._append_log("full-grid source search start")
            self._run_worker(SeedSolveWorker(params), self._on_seed_solve_result)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(exc))

    def patched_set_busy(self, busy: bool) -> None:
        original_set_busy(self, busy)
        if hasattr(self, "solve_seed_btn"):
            self.solve_seed_btn.setEnabled(not busy)
        if hasattr(self, "save_seed_btn"):
            self.save_seed_btn.setEnabled((not busy) and bool(self._current_seed_solve_payload and self._current_seed_solve_payload.get("solutions")))

    def on_seed_solve_result(self, payload: dict[str, Any]) -> None:
        try:
            self._current_seed_solve_payload = payload
            solutions = payload.get("solutions", [])
            self.save_seed_btn.setEnabled(bool(solutions))
            display_rules = payload.get("rules")
            if solutions and isinstance(solutions[0], dict) and isinstance(solutions[0].get("rules"), list):
                display_rules = solutions[0]["rules"]
            self._apply_rules_to_ui(display_rules)
            if payload.get("rule_mode") == RULE_MODE_SPECIAL:
                idx = self.pattern_combo.findData(payload.get("pattern_mask"))
                if idx >= 0:
                    self.pattern_combo.setCurrentIndex(idx)

            if solutions:
                first_solution = solutions[0]
                self.solution_board.set_grid(first_solution["grid"])
                self.solution_string_edit.setText(first_solution["grid_string"])
                self.solution_string_out.setText(first_solution["grid_string"])
            else:
                empty = [[0] * 9 for _ in range(9)]
                self.solution_board.set_grid(empty)
                self.solution_string_edit.clear()
                self.solution_string_out.clear()

            self.result_summary.setPlainText(
                "\n".join(
                    [
                        "full-grid source search",
                        f"rule_mode: {payload.get('rule_mode', RULE_MODE_SPECIAL)}",
                        f"pattern_mask: {payload['pattern_mask']}",
                        f"rules: {', '.join(describe_rules(payload.get('rules', []))) if payload.get('rules') else '(none)'}",
                        f"classification: {payload['classification']}",
                        f"solver_status: {payload['solver_status']}",
                        f"requested: {payload.get('requested_solution_count', 1)}",
                        f"solutions_found: {payload['solution_count_found']}",
                        f"reached_limit: {payload.get('reached_limit', False)}",
                        f"wall_time_sec: {payload['wall_time_sec']:.3f}",
                    ]
                )
            )
            if solutions:
                self._append_log(f"full-grid source search finished: solutions={len(solutions)}")
            else:
                self._append_log(
                    f"full-grid source search finished: no accepted completed grid ({payload['classification']})"
                )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "UI Error", str(exc))

    def save_current_seed_solve(self) -> None:
        if self._current_seed_solve_payload is None or not self._current_seed_solve_payload.get("solutions"):
            QMessageBox.information(self, "No Data", "No solved source is available to save.")
            return

        rule_mode = self._current_seed_solve_payload.get("rule_mode", RULE_MODE_SPECIAL)
        default_dir = _completed_grid_dir(rule_mode)
        default_path = _next_unique_path(default_dir, f"{_rule_slug(rule_mode)}__completed_grids")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save full-grid sources",
            str(default_path),
            "JSON Files (*.json)",
        )
        if not path:
            return

        try:
            save_path = _ensure_noncolliding_path(Path(path))
            save_path.write_text(
                json.dumps(self._current_seed_solve_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._append_log(f"saved solved source: {save_path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save Error", str(exc))

    def on_batch_generation_result(self, payload: dict[str, Any]) -> None:
        try:
            self._current_batch_payload = payload
            self._current_generated_payload = payload["results"][0] if payload["results"] else None
            self._populate_batch_table(payload)
            if payload["results"]:
                self._show_puzzle_payload(payload["results"][0])

            lines = [
                "batch generation",
                f"source_mode: {payload.get('source_mode', 'current_solution')}",
                f"rule_mode: {payload.get('rule_mode', RULE_MODE_SPECIAL)}",
                f"pattern_mask: {payload['pattern_mask']}",
                f"rules: {', '.join(describe_rules(payload.get('rules', []))) if payload.get('rules') else '(none)'}",
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
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "UI Error", str(exc))

    def show_puzzle_payload(self, payload: dict[str, Any]) -> None:
        try:
            self.puzzle_board.set_grid(payload["puzzle_grid"])
            self.solution_board.set_grid(payload["solution_grid"])
            self.puzzle_string_edit.setText(payload["puzzle_string"])
            self.solution_string_out.setText(payload["solution_string"])
            self.solution_string_edit.setText(payload["solution_string"])
            self._apply_rules_to_ui(payload.get("rules"))
            if payload.get("rule_mode") == RULE_MODE_SPECIAL:
                idx = self.pattern_combo.findData(payload.get("pattern_mask"))
                if idx >= 0:
                    self.pattern_combo.setCurrentIndex(idx)

            final_check = payload["final_uniqueness_check"]
            lines = [
                "generated puzzle",
                f"source_mode: {payload.get('source_mode', 'current_solution')}",
                f"rule_mode: {payload.get('rule_mode', RULE_MODE_SPECIAL)}",
                f"pattern_mask: {payload['pattern_mask']}",
                f"rules: {', '.join(describe_rules(payload.get('rules', []))) if payload.get('rules') else '(none)'}",
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
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "UI Error", str(exc))

    MainWindow.__init__ = patched_init
    MainWindow._current_rule_mode = current_rule_mode
    MainWindow._current_rule_context = current_rule_context
    MainWindow._current_seed_rule_context = current_seed_rule_context
    MainWindow._empty_grid = empty_grid
    MainWindow._current_seed_search_grid = current_seed_search_grid
    MainWindow._build_search_rule_variants = build_search_rule_variants
    MainWindow._infer_auto_output_dir = infer_auto_output_dir
    MainWindow._sync_auto_output_dir = sync_auto_output_dir
    MainWindow._collect_active_rules = collect_active_rules
    MainWindow._sync_board_rule_visuals = sync_board_rule_visuals
    MainWindow._apply_rules_to_ui = apply_rules_to_ui
    MainWindow._on_rule_mode_changed = on_rule_mode_changed
    MainWindow._refresh_rule_summary = refresh_rule_summary
    MainWindow._update_source_mode_ui = update_source_mode_ui
    MainWindow._refresh_dataset_summary = refresh_dataset_summary
    MainWindow._load_dataset_entries_for_current_pattern = load_dataset_entries_for_current_pattern
    MainWindow._load_solution_from_json = load_solution_from_json
    MainWindow._validate_current_solution = validate_current_solution
    MainWindow._set_busy = patched_set_busy
    MainWindow._run_worker = run_worker
    MainWindow._start_generation = start_generation
    MainWindow._start_batch_generation = start_batch_generation
    MainWindow._start_folder_auto_generation = start_folder_auto_generation
    MainWindow._check_current_puzzle = check_current_puzzle
    MainWindow._solve_current_seed = solve_current_seed
    MainWindow._on_seed_solve_result = on_seed_solve_result
    MainWindow._save_current_seed_solve = save_current_seed_solve
    MainWindow._on_batch_generation_result = on_batch_generation_result
    MainWindow._show_puzzle_payload = show_puzzle_payload
    MainWindow._rule_extension_applied = True
