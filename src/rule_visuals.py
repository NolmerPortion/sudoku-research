from __future__ import annotations

from typing import Any

from puzzle_rules import describe_rules, parse_pattern_mask


GridCell = tuple[int, int]

FIXED_RULE_G_CENTERS_1_BASE: list[tuple[int, int]] = [
    (5, 5),
    (2, 2),
    (8, 8),
    (8, 2),
    (2, 8),
]

DEFAULT_L_TROMINO_REGIONS_1_BASE: list[list[tuple[int, int]]] = [
    [(1, 1), (1, 2), (2, 1)],
    [(1, 8), (2, 8), (2, 9)],
    [(2, 3), (3, 2), (3, 3)],
    [(3, 6), (3, 7), (4, 7)],
    [(4, 4), (4, 5), (5, 4)],
    [(5, 6), (6, 5), (6, 6)],
    [(6, 3), (7, 3), (7, 4)],
    [(7, 7), (7, 8), (8, 7)],
    [(8, 1), (8, 2), (9, 2)],
    [(8, 9), (9, 8), (9, 9)],
]

DEFAULT_CLONE_GROUPS_1_BASE: list[list[list[tuple[int, int]]]] = [
    [
        [(2, 2), (2, 3), (3, 2), (3, 3)],
        [(7, 7), (7, 8), (8, 7), (8, 8)],
    ],
    [
        [(1, 9), (2, 8), (3, 7), (4, 6)],
        [(6, 4), (7, 3), (8, 2), (9, 1)],
    ],
]


def build_fixed_rule_g_crosses() -> list[dict[str, Any]]:
    crosses: list[dict[str, Any]] = []
    for row_1, col_1 in FIXED_RULE_G_CENTERS_1_BASE:
        row = row_1 - 1
        col = col_1 - 1
        crosses.append(
            {
                "center": [row, col],
                "up_len": min(2, row),
                "down_len": min(2, 8 - row),
                "left_len": min(2, col),
                "right_len": min(2, 8 - col),
            }
        )
    return crosses


def build_fixed_rule_g() -> dict[str, Any]:
    return {
        "type": "cross_monotone",
        "crosses": build_fixed_rule_g_crosses(),
    }


def fixed_rule_g_summary() -> str:
    return "fixed centers: (5,5), (2,2), (8,8), (8,2), (2,8); arm length up to 2"


def build_default_l_tromino_rule() -> dict[str, Any]:
    return {
        "type": "l_tromino_sum",
        "target_sum": 13,
        "regions": [
            [[row, col] for row, col in region]
            for region in DEFAULT_L_TROMINO_REGIONS_1_BASE
        ],
    }


def build_default_clone_rule() -> dict[str, Any]:
    return {
        "type": "clone_regions_set_equal",
        "groups": [
            {
                "regions": [
                    [[row, col] for row, col in region]
                    for region in group
                ]
            }
            for group in DEFAULT_CLONE_GROUPS_1_BASE
        ],
    }


def default_clone_summary() -> str:
    return "square TL<->BR, diagonal TR<->BL"


def default_l_tromino_regions_text() -> str:
    return "; ".join(
        "/".join(f"{row},{col}" for row, col in region)
        for region in DEFAULT_L_TROMINO_REGIONS_1_BASE
    )


def _normalize_region_cells(raw_region: Any) -> list[GridCell]:
    if not isinstance(raw_region, list) or len(raw_region) != 3:
        return []
    cells: list[GridCell] = []
    uses_one_based = True
    for cell in raw_region:
        if not isinstance(cell, list | tuple) or len(cell) != 2:
            return []
        row = int(cell[0])
        col = int(cell[1])
        if row == 0 or col == 0:
            uses_one_based = False
        cells.append((row, col))
    if uses_one_based:
        return [(row - 1, col - 1) for row, col in cells]
    return cells


def _block_cells(block_row: int, block_col: int) -> set[GridCell]:
    return {
        (3 * block_row + dr, 3 * block_col + dc)
        for dr in range(3)
        for dc in range(3)
    }


def _cross_cells(cross: dict[str, Any]) -> tuple[set[GridCell], GridCell]:
    center = cross.get("center", [0, 0])
    row = int(center[0])
    col = int(center[1])
    cells: set[GridCell] = {(row, col)}
    for offset in range(1, int(cross.get("up_len", 0)) + 1):
        cells.add((row - offset, col))
    for offset in range(1, int(cross.get("down_len", 0)) + 1):
        cells.add((row + offset, col))
    for offset in range(1, int(cross.get("left_len", 0)) + 1):
        cells.add((row, col - offset))
    for offset in range(1, int(cross.get("right_len", 0)) + 1):
        cells.add((row, col + offset))
    return cells, (row, col)


def _effective_rules(pattern_mask: str | None, rules: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    effective = [rule for rule in (rules or []) if isinstance(rule, dict)]
    if effective:
        return effective
    if isinstance(pattern_mask, str) and pattern_mask.strip("0"):
        return [{"type": "special_monotone_3x3", "pattern_mask": pattern_mask}]
    return []


def build_rule_visual_state(
    pattern_mask: str | None,
    rules: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    state = {
        "special_blocks": set(),
        "special_cells": set(),
        "hyper_cells": set(),
        "checkerboard_cells": set(),
        "sum_cells": set(),
        "sum_regions": [],
        "cross_cells": set(),
        "cross_centers": set(),
        "crosses": [],
        "clone_cells": set(),
        "clone_regions": [],
        "has_bishop_rule": False,
    }

    if isinstance(pattern_mask, str) and pattern_mask.strip("0"):
        blocks = set(parse_pattern_mask(pattern_mask))
        state["special_blocks"].update(blocks)
        for block_row, block_col in blocks:
            state["special_cells"].update(_block_cells(block_row, block_col))

    for rule in _effective_rules(pattern_mask, rules):
        rule_type = rule.get("type")
        if rule_type == "special_monotone_3x3":
            mask = rule.get("pattern_mask")
            if isinstance(mask, str) and mask.strip("0"):
                blocks = set(parse_pattern_mask(mask))
                state["special_blocks"].update(blocks)
                for block_row, block_col in blocks:
                    state["special_cells"].update(_block_cells(block_row, block_col))
        elif rule_type == "hyper_3x3":
            for row0, col0 in ((1, 1), (1, 5), (5, 1), (5, 5)):
                for row in range(row0, row0 + 3):
                    for col in range(col0, col0 + 3):
                        state["hyper_cells"].add((row, col))
        elif rule_type == "checkerboard_odd":
            for row in range(9):
                for col in range(9):
                    if (row + col) % 2 == 1:
                        state["checkerboard_cells"].add((row, col))
        elif rule_type == "l_tromino_sum":
            target_sum = int(rule.get("target_sum", 13))
            for raw_region in rule.get("regions", []):
                cells = _normalize_region_cells(raw_region)
                if len(cells) != 3:
                    continue
                state["sum_regions"].append({"cells": cells, "target_sum": target_sum})
                for row, col in cells:
                    state["sum_cells"].add((row, col))
        elif rule_type == "cross_monotone":
            for cross in rule.get("crosses", []):
                if not isinstance(cross, dict):
                    continue
                cells, center = _cross_cells(cross)
                state["cross_cells"].update(cells)
                state["cross_centers"].add(center)
                state["crosses"].append(cross)
        elif rule_type == "clone_regions_set_equal":
            for group_index, group in enumerate(rule.get("groups", [])):
                if not isinstance(group, dict):
                    continue
                for region_index, raw_region in enumerate(group.get("regions", [])):
                    cells = _normalize_region_cells(raw_region) if isinstance(raw_region, list) and len(raw_region) == 3 else []
                    if not cells and isinstance(raw_region, list):
                        cells = []
                        uses_one_based = any(
                            isinstance(cell, (list, tuple)) and len(cell) == 2 and (int(cell[0]) > 0 and int(cell[1]) > 0)
                            for cell in raw_region
                        )
                        for cell in raw_region:
                            if not isinstance(cell, (list, tuple)) or len(cell) != 2:
                                cells = []
                                break
                            row = int(cell[0])
                            col = int(cell[1])
                            if uses_one_based:
                                row -= 1
                                col -= 1
                            cells.append((row, col))
                    if not cells:
                        continue
                    state["clone_regions"].append(
                        {"cells": cells, "group_index": group_index, "region_index": region_index}
                    )
                    state["clone_cells"].update(cells)
        elif rule_type == "bishop_meet_digits":
            state["has_bishop_rule"] = True

    return state


def build_rule_explanation(
    pattern_mask: str | None,
    rules: list[dict[str, Any]] | None,
    *,
    rule_name: str | None = None,
) -> str:
    effective_rules = _effective_rules(pattern_mask, rules)
    if not effective_rules:
        return "No extra rule metadata was found for this puzzle."

    lines: list[str] = []
    if isinstance(rule_name, str) and rule_name:
        lines.append(f"Current rule: {rule_name}")
        lines.append("")

    lines.append("Applied rules:")
    for text in describe_rules(effective_rules):
        lines.append(f"- {text}")

    for rule in effective_rules:
        rule_type = rule.get("type")
        lines.append("")
        if rule_type == "special_monotone_3x3":
            mask = rule.get("pattern_mask", pattern_mask)
            blocks = parse_pattern_mask(mask) if isinstance(mask, str) and mask.strip("0") else []
            lines.append("Special Monotone 3x3")
            lines.append("Highlighted 3x3 blocks become strictly increasing in rows and columns after some 90-degree rotation.")
            if blocks:
                positions = ", ".join(f"({row + 1},{col + 1})" for row, col in blocks)
                lines.append(f"Special block positions (block coordinates): {positions}")
        elif rule_type == "hyper_3x3":
            lines.append("Hyper 3x3")
            lines.append("The four highlighted inner 3x3 regions must each contain 1 to 9 exactly once.")
        elif rule_type == "checkerboard_odd":
            lines.append("Checkerboard Odd")
            lines.append("With the top-left cell treated as black, every highlighted white cell must contain an odd number.")
        elif rule_type == "l_tromino_sum":
            target_sum = int(rule.get("target_sum", 13))
            regions = []
            for raw_region in rule.get("regions", []):
                cells = _normalize_region_cells(raw_region)
                if len(cells) == 3:
                    regions.append(
                        "{" + ", ".join(f"({row + 1},{col + 1})" for row, col in cells) + "}"
                    )
            lines.append("L Tromino Sum 13")
            lines.append(f"Each highlighted L-shaped 3-cell region must sum to {target_sum}.")
            if regions:
                lines.append(f"Regions: {', '.join(regions)}")
        elif rule_type == "cross_monotone":
            crosses = [cross for cross in rule.get("crosses", []) if isinstance(cross, dict)]
            lines.append("Cross Monotone")
            lines.append("From each highlighted center, numbers must increase strictly as you move outward along each arm.")
            if crosses:
                centers = ", ".join(
                    f"({int(cross['center'][0]) + 1},{int(cross['center'][1]) + 1})"
                    for cross in crosses
                    if isinstance(cross.get("center"), list | tuple) and len(cross["center"]) == 2
                )
                if centers:
                    lines.append(f"Centers: {centers}")
                lines.append("Arms extend up to 2 cells and are shortened automatically near the board edge.")
        elif rule_type == "local_consecutive_exists":
            lines.append("Local Consecutive Exists")
            lines.append("Every cell must have at least one orthogonally adjacent neighbor whose value differs by exactly 1.")
        elif rule_type == "bishop_meet_digits":
            digits = [int(digit) for digit in rule.get("digits", [1])]
            lines.append("Bishop Meet Digits")
            lines.append("For each listed digit, all occurrences of that digit must form one connected set under bishop moves on diagonals.")
            lines.append("Separated islands are not allowed, even if each cell individually sees another same digit on a diagonal.")
            lines.append(f"Target digits: {digits}")
        elif rule_type == "anti_close_adjacent_5":
            lines.append("Anti Close Adjacent 3")
            lines.append("Any two orthogonally adjacent cells must differ by at least 3.")
        elif rule_type == "anti_close_adjacent_4":
            lines.append("Anti Close Adjacent 3")
            lines.append("Any two orthogonally adjacent cells must differ by at least 3.")
        elif rule_type == "anti_close_adjacent_3":
            lines.append("Anti Close Adjacent 3")
            lines.append("Any two orthogonally adjacent cells must differ by at least 3.")
        elif rule_type == "clone_regions_set_equal":
            lines.append("Clone Regions Set Equal")
            lines.append("Each paired highlighted region must contain the same set of digits, regardless of order.")

    return "\n".join(lines)
