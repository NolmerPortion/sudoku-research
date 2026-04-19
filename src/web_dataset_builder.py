from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

from check_uniqueness import grid_to_string, parse_puzzle_string
from generate_puzzle import generate_one_puzzle
from rule_visuals import (
    build_default_clone_rule,
    build_default_l_tromino_rule,
    build_fixed_rule_g,
    build_rule_visual_state,
)


Grid9 = list[list[int]]
RuleConfig = dict[str, Any]


@dataclass(frozen=True)
class DifficultyProfile:
    key: str
    label: str
    min_clues: int


DIFFICULTY_PROFILES = [
    DifficultyProfile("easy", "Easy", 24),
    DifficultyProfile("normal", "Normal", 12),
    DifficultyProfile("hard", "Hard", 6),
]

RULE_METADATA: dict[str, dict[str, str]] = {
    "standard": {
        "short_name": "Standard",
        "description_ja": "通常の数独です。各行・各列・各3x3ブロックに1から9を一度ずつ入れます。",
    },
    "special_monotone_3x3": {
        "short_name": "Special 3x3",
        "description_ja": "色付きの3x3ブロックは、ある90度回転をすると、各行が左から右へ、各列が上から下へ厳密に増加する並びになります。",
    },
    "hyper_3x3": {
        "short_name": "Hyper 3x3",
        "description_ja": "通常の数独の条件に加えて、中央寄りの4つの色付き3x3領域にも1から9を一度ずつ入れます。",
    },
    "checkerboard_odd": {
        "short_name": "Checkerboard Odd",
        "description_ja": "左上を黒とした市松模様で、色付きの白マスには奇数だけが入ります。",
    },
    "l_tromino_sum": {
        "short_name": "L Tromino 13",
        "description_ja": "色付きのL字3マス領域ごとに、3マスの数字の和が13になります。",
    },
    "cross_monotone": {
        "short_name": "Cross Monotone",
        "description_ja": "色付きの5つの十字で、各中心から上下左右へ外側に進むと数字が厳密に増加します。",
    },
    "local_consecutive_exists": {
        "short_name": "Consecutive Touch",
        "description_ja": "すべてのマスは、上下左右のどれか1つ以上の隣接マスと差がちょうど1になります。",
    },
    "bishop_meet_digits": {
        "short_name": "Bishop Meet",
        "description_ja": "指定数字の出現位置は、角の動きと同じ斜め移動でたどったとき、飛び地にならず一つながりになります。",
    },
    "anti_close_adjacent_3": {
        "short_name": "Far Neighbors",
        "description_ja": "上下左右に隣り合う2マスの数字の差は、常に3以上です。",
    },
    "clone_regions_set_equal": {
        "short_name": "Clone Sets",
        "description_ja": "対応する色付き領域どうしには、順番ではなく数字の集合が同じように入ります。",
    },
}

RULE_SLUG_ALIASES = {
    "hyper3x3": "hyper_3x3",
}


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


def _clone_jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _normalize_solution_entry(raw: Any, *, fallback_pattern_mask: str | None = None) -> dict[str, Any] | None:
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

    rule_mode = raw.get("rule_mode")
    if not isinstance(rule_mode, str):
        rule_mode = _rule_mode_from_payload(pattern_mask, raw.get("rules"))

    return {
        "solution_grid": solution_grid,
        "solution_string": solution_string,
        "pattern_mask": pattern_mask or "000000000",
        "rule_mode": rule_mode,
        "rule_name": raw.get("rule_name") or rule_mode,
        "rules": _clone_jsonable(raw.get("rules", [])) if isinstance(raw.get("rules"), list) else [],
        "source_file": raw.get("source_file", ""),
        "source_file_name": raw.get("source_file_name", ""),
    }


def _collect_solution_entries_from_json(data: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_candidate(raw: Any, fallback_pattern_mask: str | None = None) -> None:
        normalized = _normalize_solution_entry(raw, fallback_pattern_mask=fallback_pattern_mask)
        if normalized is None:
            return
        key = normalized["solution_string"]
        if key in seen:
            return
        seen.add(key)
        entries.append(normalized)

    if isinstance(data, dict):
        root_mask = data.get("pattern_mask")
        if not isinstance(root_mask, str):
            root_mask = data.get("pattern_mask_string")
        add_candidate(data, root_mask if isinstance(root_mask, str) else None)
        for item in data.get("solutions", []):
            add_candidate(item, root_mask if isinstance(root_mask, str) else None)
        for item in data.get("results", []):
            add_candidate(item, root_mask if isinstance(root_mask, str) else None)
    return entries


def _rule_mode_from_payload(pattern_mask: str | None, rules: Any) -> str:
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rule_type = rule.get("type")
            if isinstance(rule_type, str) and rule_type not in {"anti_close_adjacent_4", "anti_close_adjacent_5"}:
                return rule_type
            if rule_type in {"anti_close_adjacent_4", "anti_close_adjacent_5"}:
                return "anti_close_adjacent_3"
    if isinstance(pattern_mask, str) and pattern_mask.strip("0"):
        return "special_monotone_3x3"
    return "standard"


def _inferred_rules_for_mode(rule_mode: str, pattern_mask: str) -> list[RuleConfig]:
    if rule_mode == "standard":
        return []
    if rule_mode == "special_monotone_3x3":
        return [{"type": "special_monotone_3x3", "pattern_mask": pattern_mask}]
    if rule_mode == "hyper_3x3":
        return [{"type": "hyper_3x3"}]
    if rule_mode == "checkerboard_odd":
        return [{"type": "checkerboard_odd"}]
    if rule_mode == "l_tromino_sum":
        return [build_default_l_tromino_rule()]
    if rule_mode == "cross_monotone":
        return [build_fixed_rule_g()]
    if rule_mode == "local_consecutive_exists":
        return [{"type": "local_consecutive_exists"}]
    if rule_mode == "bishop_meet_digits":
        return [{"type": "bishop_meet_digits", "digits": [1]}]
    if rule_mode == "anti_close_adjacent_3":
        return [{"type": "anti_close_adjacent_3"}]
    if rule_mode == "clone_regions_set_equal":
        return [build_default_clone_rule()]
    return []


def _normalize_rule_identity(
    *,
    rule_slug: str,
    pattern_mask: str,
    rule_mode: str,
    rule_name: str,
    rules: list[RuleConfig],
) -> tuple[str, str, list[RuleConfig]]:
    canonical_mode = RULE_SLUG_ALIASES.get(rule_slug, rule_slug)
    if rule_mode == "standard" and canonical_mode != "standard":
        rule_mode = canonical_mode
    if not rules and rule_mode != "standard":
        rules = _inferred_rules_for_mode(rule_mode, pattern_mask)
    if not rule_name or rule_name == "standard" and rule_mode != "standard":
        rule_name = rule_mode
    return rule_mode, rule_name, rules


def _rule_slug(rule_mode: str) -> str:
    return "hyper3x3" if rule_mode == "hyper_3x3" else rule_mode


def _difficulty_cookie_key(difficulty_id: str, rule_mode: str) -> str:
    return f"history__{difficulty_id}__{_rule_slug(rule_mode)}"


def _json_visual_state(pattern_mask: str, rules: list[RuleConfig]) -> dict[str, Any]:
    state = build_rule_visual_state(pattern_mask, rules)
    out: dict[str, Any] = {}
    for key, value in state.items():
        if isinstance(value, set):
            out[key] = [list(item) for item in sorted(value)]
        elif isinstance(value, list):
            items: list[Any] = []
            for entry in value:
                if isinstance(entry, dict):
                    normalized = {}
                    for k, v in entry.items():
                        if isinstance(v, set):
                            normalized[k] = [list(item) for item in sorted(v)]
                        elif isinstance(v, list) and v and isinstance(v[0], tuple):
                            normalized[k] = [list(item) for item in v]
                        elif isinstance(v, tuple):
                            normalized[k] = list(v)
                        else:
                            normalized[k] = v
                    items.append(normalized)
                else:
                    items.append(entry)
            out[key] = items
        else:
            out[key] = value
    return out


def _groups_for_hidden_singles(pattern_mask: str, rules: list[RuleConfig]) -> list[list[tuple[int, int]]]:
    groups: list[list[tuple[int, int]]] = []
    for r in range(9):
        groups.append([(r, c) for c in range(9)])
    for c in range(9):
        groups.append([(r, c) for r in range(9)])
    for br in range(3):
        for bc in range(3):
            groups.append([(3 * br + dr, 3 * bc + dc) for dr in range(3) for dc in range(3)])
    for rule in rules:
        rule_type = rule.get("type")
        if rule_type == "hyper_3x3":
            for r0, c0 in ((1, 1), (1, 5), (5, 1), (5, 5)):
                groups.append([(r, c) for r in range(r0, r0 + 3) for c in range(c0, c0 + 3)])
        elif rule_type == "l_tromino_sum":
            for region in rule.get("regions", []):
                cells: list[tuple[int, int]] = []
                for cell in region:
                    if isinstance(cell, (list, tuple)) and len(cell) == 2:
                        row = int(cell[0])
                        col = int(cell[1])
                        if row > 0 and col > 0:
                            row -= 1
                            col -= 1
                        cells.append((row, col))
                if len(cells) == 3:
                    groups.append(cells)
        elif rule_type == "clone_regions_set_equal":
            for group in rule.get("groups", []):
                if not isinstance(group, dict):
                    continue
                for region in group.get("regions", []):
                    cells: list[tuple[int, int]] = []
                    for cell in region:
                        if isinstance(cell, (list, tuple)) and len(cell) == 2:
                            row = int(cell[0])
                            col = int(cell[1])
                            if row > 0 and col > 0:
                                row -= 1
                                col -= 1
                            cells.append((row, col))
                    if cells:
                        groups.append(cells)
    return groups


def _orth_neighbors(row: int, col: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nr = row + dr
        nc = col + dc
        if 0 <= nr < 9 and 0 <= nc < 9:
            out.append((nr, nc))
    return out


def _cell_in_hyper_region(row: int, col: int) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    for r0, c0 in ((1, 1), (1, 5), (5, 1), (5, 5)):
        if r0 <= row < r0 + 3 and c0 <= col < c0 + 3:
            regions.append((r0, c0))
    return regions


def _cross_relationships(rules: list[RuleConfig], row: int, col: int) -> list[tuple[tuple[int, int] | None, tuple[int, int] | None]]:
    relationships: list[tuple[tuple[int, int] | None, tuple[int, int] | None]] = []
    for rule in rules:
        if rule.get("type") != "cross_monotone":
            continue
        for cross in rule.get("crosses", []):
            if not isinstance(cross, dict):
                continue
            center = cross.get("center", [0, 0])
            if not isinstance(center, (list, tuple)) or len(center) != 2:
                continue
            cr = int(center[0])
            cc = int(center[1])
            if row == cr and col == cc:
                for dr, dc, length in (
                    (-1, 0, int(cross.get("up_len", 0))),
                    (1, 0, int(cross.get("down_len", 0))),
                    (0, -1, int(cross.get("left_len", 0))),
                    (0, 1, int(cross.get("right_len", 0))),
                ):
                    if length >= 1:
                        relationships.append((None, (cr + dr, cc + dc)))
                continue
            if col == cc and row < cr:
                offset = cr - row
                if offset <= int(cross.get("up_len", 0)):
                    inward = (row + 1, col) if offset > 1 else (cr, cc)
                    outward = (row - 1, col) if offset < int(cross.get("up_len", 0)) else None
                    relationships.append((inward, outward))
            if col == cc and row > cr:
                offset = row - cr
                if offset <= int(cross.get("down_len", 0)):
                    inward = (row - 1, col) if offset > 1 else (cr, cc)
                    outward = (row + 1, col) if offset < int(cross.get("down_len", 0)) else None
                    relationships.append((inward, outward))
            if row == cr and col < cc:
                offset = cc - col
                if offset <= int(cross.get("left_len", 0)):
                    inward = (row, col + 1) if offset > 1 else (cr, cc)
                    outward = (row, col - 1) if offset < int(cross.get("left_len", 0)) else None
                    relationships.append((inward, outward))
            if row == cr and col > cc:
                offset = col - cc
                if offset <= int(cross.get("right_len", 0)):
                    inward = (row, col - 1) if offset > 1 else (cr, cc)
                    outward = (row, col + 1) if offset < int(cross.get("right_len", 0)) else None
                    relationships.append((inward, outward))
    return relationships


def _candidate_values(
    grid: Grid9,
    row: int,
    col: int,
    pattern_mask: str,
    rules: list[RuleConfig],
) -> set[int]:
    if grid[row][col] != 0:
        return {grid[row][col]}

    used = set(grid[row][c] for c in range(9) if grid[row][c] != 0)
    used.update(grid[r][col] for r in range(9) if grid[r][col] != 0)
    br = row // 3
    bc = col // 3
    for rr in range(3 * br, 3 * br + 3):
        for cc in range(3 * bc, 3 * bc + 3):
            if grid[rr][cc] != 0:
                used.add(grid[rr][cc])
    candidates = {value for value in range(1, 10) if value not in used}

    for rule in rules:
        rule_type = rule.get("type")
        if rule_type == "hyper_3x3":
            for r0, c0 in _cell_in_hyper_region(row, col):
                used_hyper = {
                    grid[r][c]
                    for r in range(r0, r0 + 3)
                    for c in range(c0, c0 + 3)
                    if grid[r][c] != 0
                }
                candidates = {value for value in candidates if value not in used_hyper}
        elif rule_type == "checkerboard_odd":
            if (row + col) % 2 == 1:
                candidates = {value for value in candidates if value % 2 == 1}
        elif rule_type == "l_tromino_sum":
            for region in rule.get("regions", []):
                cells: list[tuple[int, int]] = []
                for cell in region:
                    if isinstance(cell, (list, tuple)) and len(cell) == 2:
                        rr = int(cell[0])
                        cc = int(cell[1])
                        if rr > 0 and cc > 0:
                            rr -= 1
                            cc -= 1
                        cells.append((rr, cc))
                if (row, col) not in cells:
                    continue
                target_sum = int(rule.get("target_sum", 13))
                other_assigned = [grid[rr][cc] for rr, cc in cells if (rr, cc) != (row, col) and grid[rr][cc] != 0]
                remaining_slots = sum(1 for rr, cc in cells if (rr, cc) != (row, col) and grid[rr][cc] == 0)
                kept: set[int] = set()
                for value in candidates:
                    remaining_total = target_sum - (sum(other_assigned) + value)
                    if remaining_slots == 0:
                        if remaining_total == 0:
                            kept.add(value)
                    else:
                        min_sum = remaining_slots
                        max_sum = remaining_slots * 9
                        if min_sum <= remaining_total <= max_sum:
                            kept.add(value)
                candidates = kept
        elif rule_type == "cross_monotone":
            relationships = _cross_relationships(rules, row, col)
            kept: set[int] = set()
            for value in candidates:
                ok = True
                for inward, outward in relationships:
                    if inward is not None:
                        iv = grid[inward[0]][inward[1]]
                        if iv != 0 and not (iv < value):
                            ok = False
                            break
                    if outward is not None:
                        ov = grid[outward[0]][outward[1]]
                        if ov != 0 and not (value < ov):
                            ok = False
                            break
                if ok:
                    kept.add(value)
            candidates = kept
        elif rule_type == "anti_close_adjacent_3":
            kept = set()
            for value in candidates:
                if all(grid[nr][nc] == 0 or abs(value - grid[nr][nc]) >= 3 for nr, nc in _orth_neighbors(row, col)):
                    kept.add(value)
            candidates = kept
        elif rule_type == "local_consecutive_exists":
            kept = set()
            neighbors = _orth_neighbors(row, col)
            for value in candidates:
                assigned = [grid[nr][nc] for nr, nc in neighbors if grid[nr][nc] != 0]
                if any(abs(value - neighbor) == 1 for neighbor in assigned) or any(grid[nr][nc] == 0 for nr, nc in neighbors):
                    kept.add(value)
            candidates = kept

    if not candidates:
        return set(range(1, 10))
    return candidates


def _pick_next_step(
    grid: Grid9,
    solution_grid: Grid9,
    pattern_mask: str,
    rules: list[RuleConfig],
) -> dict[str, Any] | None:
    empty_cells = [(r, c) for r in range(9) for c in range(9) if grid[r][c] == 0]
    if not empty_cells:
        return None

    candidate_map: dict[tuple[int, int], set[int]] = {}
    for row, col in empty_cells:
        candidates = _candidate_values(grid, row, col, pattern_mask, rules)
        solution_value = solution_grid[row][col]
        if solution_value not in candidates:
            candidates = set(candidates)
            candidates.add(solution_value)
        candidate_map[(row, col)] = candidates

    for row, col in empty_cells:
        candidates = candidate_map[(row, col)]
        if len(candidates) == 1:
            return {
                "row": row,
                "col": col,
                "value": solution_grid[row][col],
                "reason": "naked_single",
                "candidate_count": 1,
            }

    for group in _groups_for_hidden_singles(pattern_mask, rules):
        candidate_cells = [(row, col) for row, col in group if grid[row][col] == 0]
        for digit in range(1, 10):
            matches = [(row, col) for row, col in candidate_cells if digit in candidate_map[(row, col)]]
            if len(matches) == 1:
                row, col = matches[0]
                return {
                    "row": row,
                    "col": col,
                    "value": solution_grid[row][col],
                    "reason": "hidden_single",
                    "candidate_count": len(candidate_map[(row, col)]),
                }

    row, col = min(
        empty_cells,
        key=lambda cell: (len(candidate_map[cell]), cell[0], cell[1]),
    )
    return {
        "row": row,
        "col": col,
        "value": solution_grid[row][col],
        "reason": "guided_min_candidate",
        "candidate_count": len(candidate_map[(row, col)]),
    }


def build_guide_steps(
    puzzle_grid: Grid9,
    solution_grid: Grid9,
    pattern_mask: str,
    rules: list[RuleConfig],
) -> list[dict[str, Any]]:
    working = [row[:] for row in puzzle_grid]
    steps: list[dict[str, Any]] = []
    while True:
        step = _pick_next_step(working, solution_grid, pattern_mask, rules)
        if step is None:
            break
        steps.append(step)
        working[step["row"]][step["col"]] = step["value"]
    return steps


def _example_circle_cells(
    rule_mode: str,
    visual_state: dict[str, Any],
    solution_grid: Grid9,
    rules: list[RuleConfig],
) -> list[list[int]]:
    if rule_mode == "special_monotone_3x3":
        return visual_state.get("special_cells", [])[:]
    if rule_mode == "hyper_3x3":
        return visual_state.get("hyper_cells", [])[:]
    if rule_mode == "checkerboard_odd":
        return visual_state.get("checkerboard_cells", [])[:]
    if rule_mode == "l_tromino_sum":
        return visual_state.get("sum_cells", [])[:]
    if rule_mode == "cross_monotone":
        return visual_state.get("cross_cells", [])[:]
    if rule_mode == "clone_regions_set_equal":
        return visual_state.get("clone_cells", [])[:]
    if rule_mode == "bishop_meet_digits":
        digits = [1]
        for rule in rules:
            if rule.get("type") == "bishop_meet_digits":
                digits = [int(digit) for digit in rule.get("digits", [1])]
                break
        cells: list[list[int]] = []
        for row in range(9):
            for col in range(9):
                if solution_grid[row][col] in digits:
                    cells.append([row, col])
        return cells
    if rule_mode == "local_consecutive_exists":
        for row in range(9):
            for col in range(9):
                for nr, nc in _orth_neighbors(row, col):
                    if abs(solution_grid[row][col] - solution_grid[nr][nc]) == 1:
                        return [[row, col], [nr, nc]]
    if rule_mode == "anti_close_adjacent_3":
        for row in range(9):
            for col in range(9):
                for nr, nc in _orth_neighbors(row, col):
                    if abs(solution_grid[row][col] - solution_grid[nr][nc]) >= 3:
                        return [[row, col], [nr, nc]]
    return []


def _build_dataset_entry(
    *,
    puzzle_grid: Grid9,
    solution_grid: Grid9,
    pattern_mask: str,
    rule_mode: str,
    rule_name: str,
    rules: list[RuleConfig],
    clue_count: int,
    entry_index: int,
    difficulty: DifficultyProfile,
    source_file: str,
) -> dict[str, Any]:
    guide_steps = build_guide_steps(puzzle_grid, solution_grid, pattern_mask, rules)
    visual_state = _json_visual_state(pattern_mask, rules)
    return {
        "id": f"{difficulty.key}__{_rule_slug(rule_mode)}__{entry_index:04d}",
        "difficulty_id": difficulty.key,
        "difficulty_label": difficulty.label,
        "min_clues": difficulty.min_clues,
        "pattern_mask": pattern_mask,
        "rule_mode": rule_mode,
        "rule_name": rule_name,
        "short_name": RULE_METADATA.get(rule_mode, RULE_METADATA["standard"])["short_name"],
        "rules": _clone_jsonable(rules),
        "puzzle_string": grid_to_string(puzzle_grid),
        "solution_string": grid_to_string(solution_grid),
        "puzzle_grid": puzzle_grid,
        "solution_grid": solution_grid,
        "clue_count": clue_count,
        "guide_steps": guide_steps,
        "visual_state": visual_state,
        "source_file": source_file,
    }


def _load_completed_entries(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = _collect_solution_entries_from_json(data)
    for entry in entries:
        entry["source_file"] = str(path)
        if not entry.get("source_file_name"):
            entry["source_file_name"] = path.name
    return entries


def _build_rule_dataset(
    *,
    rule_slug: str,
    completed_entries: list[dict[str, Any]],
    difficulty: DifficultyProfile,
    trials: int,
    uniqueness_time_limit: float,
    seed: int,
    target_puzzle_count: int,
    per_puzzle_time_limit: float,
) -> dict[str, Any] | None:
    if not completed_entries:
        return None

    first = completed_entries[0]
    pattern_mask = first.get("pattern_mask") or "000000000"
    rules = _clone_jsonable(first.get("rules", []))
    rule_mode = first.get("rule_mode") or _rule_mode_from_payload(pattern_mask, rules)
    rule_name = first.get("rule_name") or rule_mode
    rule_mode, rule_name, rules = _normalize_rule_identity(
        rule_slug=rule_slug,
        pattern_mask=pattern_mask,
        rule_mode=rule_mode,
        rule_name=rule_name,
        rules=rules,
    )
    rule_meta = RULE_METADATA.get(rule_mode, RULE_METADATA["standard"])
    example_solution = first["solution_grid"]
    example_visual_state = _json_visual_state(pattern_mask, rules)

    puzzles: list[dict[str, Any]] = []
    seen_puzzles: set[str] = set()
    total_sources = len(completed_entries)
    print(
        f"[build] rule={rule_slug} difficulty={difficulty.key} "
        f"target={target_puzzle_count} sources={total_sources}",
        flush=True,
    )
    for index, entry in enumerate(completed_entries, start=1):
        if len(puzzles) >= target_puzzle_count:
            break
        solution_grid = entry["solution_grid"]
        result: dict[str, Any] | None = None
        deadline = time.perf_counter() + per_puzzle_time_limit
        print(
            f"[source {index}/{total_sources}] start collected={len(puzzles)}/{target_puzzle_count}",
            flush=True,
        )
        for trial_index in range(max(1, trials)):
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                print(
                    f"[source {index}/{total_sources}] timeout after {per_puzzle_time_limit:.1f}s",
                    flush=True,
                )
                break
            candidate = generate_one_puzzle(
                solution_grid=solution_grid,
                pattern_mask=pattern_mask,
                symmetry="none",
                uniqueness_time_limit=uniqueness_time_limit,
                seed=seed + index * 1000 + difficulty.min_clues + trial_index,
                target_clues=difficulty.min_clues,
                verbose=False,
                rules=rules,
                max_wall_time_sec=remaining,
            )
            if result is None or candidate["clue_count"] < result["clue_count"]:
                result = candidate
            print(
                f"[source {index}/{total_sources}] trial={trial_index + 1}/{max(1, trials)} "
                f"clues={candidate['clue_count']}",
                flush=True,
            )
            if result["clue_count"] == difficulty.min_clues:
                break
        if result is None:
            continue
        puzzle_string = result["puzzle_string"]
        if puzzle_string in seen_puzzles or "0" not in puzzle_string:
            print(
                f"[source {index}/{total_sources}] skipped duplicate_or_solved clues={result['clue_count']}",
                flush=True,
            )
            continue
        seen_puzzles.add(puzzle_string)
        puzzles.append(
            _build_dataset_entry(
                puzzle_grid=result["puzzle_grid"],
                solution_grid=solution_grid,
                pattern_mask=pattern_mask,
                rule_mode=rule_mode,
                rule_name=rule_name,
                rules=rules,
                clue_count=result["clue_count"],
                entry_index=index,
                difficulty=difficulty,
                source_file=entry.get("source_file", ""),
            )
        )
        print(
            f"[source {index}/{total_sources}] accepted collected={len(puzzles)}/{target_puzzle_count} "
            f"clues={result['clue_count']}",
            flush=True,
        )

    if not puzzles:
        print(f"[build] rule={rule_slug} difficulty={difficulty.key} generated=0", flush=True)
        return None

    print(
        f"[build] rule={rule_slug} difficulty={difficulty.key} generated={len(puzzles)}",
        flush=True,
    )

    return {
        "difficulty_id": difficulty.key,
        "difficulty_label": difficulty.label,
        "min_clues": difficulty.min_clues,
        "rule_mode": rule_mode,
        "rule_slug": rule_slug,
        "rule_name": rule_name,
        "short_name": rule_meta["short_name"],
        "description_ja": rule_meta["description_ja"],
        "history_cookie_key": _difficulty_cookie_key(difficulty.key, rule_mode),
        "pattern_mask": pattern_mask,
        "rules": rules,
        "example": {
            "solution_string": grid_to_string(example_solution),
            "solution_grid": example_solution,
            "visual_state": example_visual_state,
            "circle_cells": _example_circle_cells(rule_mode, example_visual_state, example_solution, rules),
        },
        "puzzles": puzzles,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_web_datasets(
    *,
    rules_root: Path,
    outputs_root: Path,
    docs_data_root: Path,
    target_puzzle_count: int,
    trials: int,
    uniqueness_time_limit: float,
    seed: int,
    per_puzzle_time_limit: float,
) -> None:
    catalog = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "difficulties": [
            {"id": profile.key, "label": profile.label, "min_clues": profile.min_clues}
            for profile in DIFFICULTY_PROFILES
        ],
        "rules": [],
        "datasets": [],
    }
    standard_sources: list[dict[str, Any]] = []

    for rule_dir in sorted(path for path in rules_root.iterdir() if path.is_dir()):
        completed_dir = rule_dir / "generated_completed_grid"
        if not completed_dir.exists():
            continue
        print(f"[rule] scanning {rule_dir.name}", flush=True)
        completed_entries: list[dict[str, Any]] = []
        for json_path in sorted(completed_dir.glob("*.json")):
            print(f"[rule] loading completed grids from {json_path}", flush=True)
            completed_entries.extend(_load_completed_entries(json_path))
        if not completed_entries:
            print(f"[rule] skip {rule_dir.name}: no completed entries", flush=True)
            continue

        rule_slug = rule_dir.name
        available_difficulties: list[str] = []
        first_entry = completed_entries[0]
        first_pattern_mask = first_entry.get("pattern_mask") or "000000000"
        first_rules = _clone_jsonable(first_entry.get("rules", []))
        rule_mode = first_entry.get("rule_mode") or _rule_mode_from_payload(first_pattern_mask, first_rules)
        rule_name = first_entry.get("rule_name") or rule_mode
        rule_mode, rule_name, first_rules = _normalize_rule_identity(
            rule_slug=rule_slug,
            pattern_mask=first_pattern_mask,
            rule_mode=rule_mode,
            rule_name=rule_name,
            rules=first_rules,
        )
        rule_meta = RULE_METADATA.get(rule_mode, RULE_METADATA["standard"])
        for entry in completed_entries:
            standard_sources.append(
                {
                    "solution_grid": entry["solution_grid"],
                    "solution_string": entry["solution_string"],
                    "pattern_mask": "000000000",
                    "rule_mode": "standard",
                    "rule_name": "standard",
                    "rules": [],
                    "source_file": entry.get("source_file", ""),
                }
            )

        for profile in DIFFICULTY_PROFILES:
            dataset = _build_rule_dataset(
                rule_slug=rule_slug,
                completed_entries=completed_entries,
                difficulty=profile,
                trials=trials,
                uniqueness_time_limit=uniqueness_time_limit,
                seed=seed,
                target_puzzle_count=target_puzzle_count,
                per_puzzle_time_limit=per_puzzle_time_limit,
            )
            if dataset is None:
                continue
            available_difficulties.append(profile.key)
            relative_path = Path(profile.key) / f"{rule_slug}.json"
            output_path = outputs_root / relative_path
            docs_path = docs_data_root / relative_path
            _write_json(output_path, dataset)
            _write_json(docs_path, dataset)
            catalog["datasets"].append(
                {
                    "difficulty_id": profile.key,
                    "rule_mode": dataset["rule_mode"],
                    "rule_slug": rule_slug,
                    "path": relative_path.as_posix(),
                    "count": len(dataset["puzzles"]),
                }
            )

        if available_difficulties:
            catalog["rules"].append(
                {
                    "rule_mode": rule_mode,
                    "rule_slug": rule_slug,
                    "rule_name": rule_name,
                    "short_name": rule_meta["short_name"],
                    "description_ja": rule_meta["description_ja"],
                    "available_difficulties": available_difficulties,
                }
            )

    if standard_sources:
        available_difficulties: list[str] = []
        for profile in DIFFICULTY_PROFILES:
            dataset = _build_rule_dataset(
                rule_slug="standard",
                completed_entries=standard_sources,
                difficulty=profile,
                trials=trials,
                uniqueness_time_limit=uniqueness_time_limit,
                seed=seed,
                target_puzzle_count=target_puzzle_count,
                per_puzzle_time_limit=per_puzzle_time_limit,
            )
            if dataset is None:
                continue
            available_difficulties.append(profile.key)
            relative_path = Path(profile.key) / "standard.json"
            _write_json(outputs_root / relative_path, dataset)
            _write_json(docs_data_root / relative_path, dataset)
            catalog["datasets"].append(
                {
                    "difficulty_id": profile.key,
                    "rule_mode": dataset["rule_mode"],
                    "rule_slug": "standard",
                    "path": relative_path.as_posix(),
                    "count": len(dataset["puzzles"]),
                }
            )
        if available_difficulties:
            standard_meta = RULE_METADATA["standard"]
            catalog["rules"].append(
                {
                    "rule_mode": "standard",
                    "rule_slug": "standard",
                    "rule_name": "standard",
                    "short_name": standard_meta["short_name"],
                    "description_ja": standard_meta["description_ja"],
                    "available_difficulties": available_difficulties,
                }
            )

    _write_json(docs_data_root / "catalog.json", catalog)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build GitHub Pages puzzle datasets from completed-grid JSON files.")
    parser.add_argument("--rules-root", type=Path, default=Path("outputs/rules"))
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs/web_datasets"))
    parser.add_argument("--docs-data-root", type=Path, default=Path("docs/data"))
    parser.add_argument("--target-puzzle-count", type=int, default=15)
    parser.add_argument("--trials", type=int, default=12)
    parser.add_argument("--uniqueness-time-limit", type=float, default=5.0)
    parser.add_argument("--per-puzzle-time-limit", type=float, default=20.0)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    print("[start] building web datasets", flush=True)
    build_web_datasets(
        rules_root=args.rules_root,
        outputs_root=args.outputs_root,
        docs_data_root=args.docs_data_root,
        target_puzzle_count=max(1, args.target_puzzle_count),
        trials=max(1, args.trials),
        uniqueness_time_limit=max(0.1, args.uniqueness_time_limit),
        seed=args.seed,
        per_puzzle_time_limit=max(0.1, args.per_puzzle_time_limit),
    )
    print("[done] web dataset build finished", flush=True)


if __name__ == "__main__":
    main()
