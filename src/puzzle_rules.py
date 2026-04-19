from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ortools.sat.python import cp_model

from block_patterns import generate_special_blocks_with_rotations


GridVars = list[list[cp_model.IntVar]]
RuleConfig = dict[str, Any]


def block_cells(x: GridVars, br: int, bc: int) -> list[cp_model.IntVar]:
    return [x[3 * br + dr][3 * bc + dc] for dr in range(3) for dc in range(3)]


def flatten_block(
    block: tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]
) -> tuple[int, ...]:
    return tuple(block[r][c] for r in range(3) for c in range(3))


def parse_pattern_mask(mask: str) -> list[tuple[int, int]]:
    mask = mask.strip()
    if len(mask) != 9 or any(ch not in "01" for ch in mask):
        raise ValueError("pattern mask must be a 9-character string over {0,1}")
    out: list[tuple[int, int]] = []
    for index, ch in enumerate(mask):
        if ch == "1":
            out.append(divmod(index, 3))
    return out


def _copy_rule(rule: RuleConfig) -> RuleConfig:
    copied: RuleConfig = {}
    for key, value in rule.items():
        if isinstance(value, list):
            copied[key] = [
                item.copy() if isinstance(item, dict) else item[:] if isinstance(item, list) else item
                for item in value
            ]
        elif isinstance(value, dict):
            copied[key] = value.copy()
        else:
            copied[key] = value
    return copied


def normalize_rules(rules: list[RuleConfig] | None, pattern_mask: str | None = None) -> list[RuleConfig]:
    normalized: list[RuleConfig] = []
    if pattern_mask:
        normalized.append({"type": "special_monotone_3x3", "pattern_mask": pattern_mask})
    if rules:
        normalized.extend(_copy_rule(rule) for rule in rules)
    return normalized


def describe_rules(rules: list[RuleConfig]) -> list[str]:
    return [describe_rule(rule) for rule in rules]


def describe_rule(rule: RuleConfig) -> str:
    rule_type = rule.get("type")
    if rule_type == "special_monotone_3x3":
        if isinstance(rule.get("pattern_mask"), str):
            return f"special_monotone_3x3(pattern_mask={rule['pattern_mask']})"
        return "special_monotone_3x3"
    if rule_type == "checkerboard_odd":
        return "checkerboard_odd(white cells odd; top-left black)"
    if rule_type == "hyper_3x3":
        return "hyper_3x3"
    if rule_type == "l_tromino_sum":
        return f"l_tromino_sum(target_sum={rule.get('target_sum', 13)})"
    if rule_type == "sum_2x2_regions":
        return "l_tromino_sum(migration placeholder)"
    if rule_type == "cross_monotone":
        return f"cross_monotone(count={len(rule.get('crosses', []))})"
    if rule_type == "anti_close_adjacent_3":
        return "anti_close_adjacent_3"
    if rule_type == "anti_close_adjacent_4":
        return "anti_close_adjacent_3(legacy alias loaded)"
    if rule_type == "anti_close_adjacent_5":
        return "anti_close_adjacent_3(legacy alias loaded)"
    if rule_type == "kropki_white_only":
        return f"kropki_white_only(count={len(rule.get('edges', []))})"
    if rule_type == "clone_regions_set_equal":
        return f"clone_regions_set_equal(groups={len(rule.get('groups', []))})"
    if rule_type == "local_consecutive_exists":
        return "local_consecutive_exists"
    if rule_type == "bishop_meet_digits":
        return f"bishop_meet_digits(digits={rule.get('digits', [1])})"
    if rule_type == "rank_cells":
        return "rank_cells(TODO)"
    return str(rule_type)


def validate_rules(rules: list[RuleConfig]) -> None:
    for rule in rules:
        rule_type = rule.get("type")
        if not isinstance(rule_type, str):
            raise ValueError("each rule must include string field 'type'")
        spec = RULE_REGISTRY.get(rule_type)
        if spec is None:
            raise ValueError(f"unknown rule type: {rule_type}")
        spec.validate_params(rule)


def add_rules_constraints(
    model: cp_model.CpModel,
    x: GridVars,
    rules: list[RuleConfig],
    *,
    context: dict[str, Any] | None = None,
) -> None:
    validate_rules(rules)
    safe_context = context or {}
    for rule in rules:
        rule_type = rule["type"]
        spec = RULE_REGISTRY[rule_type]
        spec.add_constraints(model, x, rule, safe_context)


def _validate_special_monotone(params: RuleConfig) -> None:
    has_mask = isinstance(params.get("pattern_mask"), str)
    has_blocks = isinstance(params.get("blocks"), list)
    if not has_mask and not has_blocks:
        raise ValueError("special_monotone_3x3 requires pattern_mask or blocks")
    blocks = _blocks_from_params(params)
    for br, bc in blocks:
        if not (0 <= br < 3 and 0 <= bc < 3):
            raise ValueError(f"special block out of range: {(br, bc)}")


def _blocks_from_params(params: RuleConfig) -> list[tuple[int, int]]:
    if isinstance(params.get("pattern_mask"), str):
        return parse_pattern_mask(params["pattern_mask"])
    raw_blocks = params.get("blocks")
    if not isinstance(raw_blocks, list):
        raise ValueError("blocks must be a list")
    blocks: list[tuple[int, int]] = []
    for raw in raw_blocks:
        if not isinstance(raw, list | tuple) or len(raw) != 2:
            raise ValueError("each block must be [block_row, block_col]")
        br = int(raw[0])
        bc = int(raw[1])
        blocks.append((br, bc))
    return blocks


def _add_special_monotone(
    model: cp_model.CpModel,
    x: GridVars,
    params: RuleConfig,
    context: dict[str, Any],
) -> None:
    allowed_tuples = context.get("special_allowed_tuples")
    if not isinstance(allowed_tuples, list):
        special_blocks = generate_special_blocks_with_rotations()
        allowed_tuples = [flatten_block(block) for block in special_blocks]
    for br, bc in _blocks_from_params(params):
        model.AddAllowedAssignments(block_cells(x, br, bc), allowed_tuples)


def _validate_checkerboard_odd(params: RuleConfig) -> None:
    return


def _add_checkerboard_odd(
    model: cp_model.CpModel,
    x: GridVars,
    params: RuleConfig,
    context: dict[str, Any],
) -> None:
    allowed = [(1,), (3,), (5,), (7,), (9,)]
    for r in range(9):
        for c in range(9):
            # With top-left treated as black, white cells are exactly r+c odd in 0-based indexing.
            if (r + c) % 2 == 1:
                model.AddAllowedAssignments([x[r][c]], allowed)


def _validate_hyper_3x3(params: RuleConfig) -> None:
    return


def _add_hyper_3x3(
    model: cp_model.CpModel,
    x: GridVars,
    params: RuleConfig,
    context: dict[str, Any],
) -> None:
    anchors = [(1, 1), (1, 5), (5, 1), (5, 5)]
    for r0, c0 in anchors:
        cells = [x[r][c] for r in range(r0, r0 + 3) for c in range(c0, c0 + 3)]
        model.AddAllDifferent(cells)


def _normalize_l_tromino_regions(params: RuleConfig) -> list[list[tuple[int, int]]]:
    regions = params.get("regions")
    if not isinstance(regions, list) or not regions:
        raise ValueError("l_tromino_sum requires non-empty regions")
    normalized: list[list[tuple[int, int]]] = []
    for raw in regions:
        if not isinstance(raw, list) or len(raw) != 3:
            raise ValueError("each L-tromino region must contain exactly 3 cells")
        raw_cells: list[tuple[int, int]] = []
        uses_one_based = True
        for cell in raw:
            if not isinstance(cell, list | tuple) or len(cell) != 2:
                raise ValueError("each L-tromino cell must be [row, col]")
            row = int(cell[0])
            col = int(cell[1])
            if row == 0 or col == 0:
                uses_one_based = False
            raw_cells.append((row, col))
        cells = [(row - 1, col - 1) for row, col in raw_cells] if uses_one_based else raw_cells
        unique_cells = {(row, col) for row, col in cells}
        if len(unique_cells) != 3:
            raise ValueError("L-tromino cells must be distinct")
        for row, col in cells:
            if not (0 <= row < 9 and 0 <= col < 9):
                raise ValueError(f"L-tromino cell out of bounds: {(row, col)}")
        rows = {row for row, _ in cells}
        cols = {col for _, col in cells}
        if len(rows) != 2 or len(cols) != 2:
            raise ValueError("L-tromino cells must fit in a 2x2 box with one missing cell")
        normalized.append(cells)
    return normalized


def _validate_l_tromino_sum(params: RuleConfig) -> None:
    target_sum = params.get("target_sum", 13)
    if not isinstance(target_sum, int):
        raise ValueError("target_sum must be int")
    _normalize_l_tromino_regions(params)


def _add_l_tromino_sum(
    model: cp_model.CpModel,
    x: GridVars,
    params: RuleConfig,
    context: dict[str, Any],
) -> None:
    target_sum = int(params.get("target_sum", 13))
    for cells in _normalize_l_tromino_regions(params):
        model.Add(sum(x[row][col] for row, col in cells) == target_sum)


def _validate_cross_monotone(params: RuleConfig) -> None:
    crosses = params.get("crosses")
    if not isinstance(crosses, list) or not crosses:
        raise ValueError("cross_monotone requires non-empty crosses")
    for cross in crosses:
        if not isinstance(cross, dict):
            raise ValueError("each cross must be object")
        center = cross.get("center")
        if not isinstance(center, list | tuple) or len(center) != 2:
            raise ValueError("cross center must be [row, col]")
        r = int(center[0])
        c = int(center[1])
        if not (0 <= r < 9 and 0 <= c < 9):
            raise ValueError(f"cross center out of bounds: {(r, c)}")
        for key in ("up_len", "down_len", "left_len", "right_len"):
            value = int(cross.get(key, 0))
            if value < 0:
                raise ValueError(f"{key} must be >= 0")
        if r - int(cross.get("up_len", 0)) < 0:
            raise ValueError("cross up arm goes out of bounds")
        if r + int(cross.get("down_len", 0)) > 8:
            raise ValueError("cross down arm goes out of bounds")
        if c - int(cross.get("left_len", 0)) < 0:
            raise ValueError("cross left arm goes out of bounds")
        if c + int(cross.get("right_len", 0)) > 8:
            raise ValueError("cross right arm goes out of bounds")


def _add_cross_monotone(
    model: cp_model.CpModel,
    x: GridVars,
    params: RuleConfig,
    context: dict[str, Any],
) -> None:
    for cross in params["crosses"]:
        r = int(cross["center"][0])
        c = int(cross["center"][1])
        for offset in range(1, int(cross.get("up_len", 0)) + 1):
            prev_r = r - offset + 1
            curr_r = r - offset
            model.Add(x[prev_r][c] < x[curr_r][c])
        for offset in range(1, int(cross.get("down_len", 0)) + 1):
            prev_r = r + offset - 1
            curr_r = r + offset
            model.Add(x[prev_r][c] < x[curr_r][c])
        for offset in range(1, int(cross.get("left_len", 0)) + 1):
            prev_c = c - offset + 1
            curr_c = c - offset
            model.Add(x[r][prev_c] < x[r][curr_c])
        for offset in range(1, int(cross.get("right_len", 0)) + 1):
            prev_c = c + offset - 1
            curr_c = c + offset
            model.Add(x[r][prev_c] < x[r][curr_c])


def _validate_kropki_white_only(params: RuleConfig) -> None:
    edges = params.get("edges")
    if not isinstance(edges, list):
        raise ValueError("kropki_white_only requires edges list")
    for edge in edges:
        if not isinstance(edge, list | tuple) or len(edge) != 2:
            raise ValueError("each edge must be [[r1,c1],[r2,c2]]")
        a, b = edge
        if not isinstance(a, list | tuple) or not isinstance(b, list | tuple):
            raise ValueError("edge endpoints must be coordinate pairs")
        r1, c1 = int(a[0]), int(a[1])
        r2, c2 = int(b[0]), int(b[1])
        if abs(r1 - r2) + abs(c1 - c2) != 1:
            raise ValueError(f"kropki edge must be orthogonally adjacent: {edge}")


def _add_kropki_white_only(
    model: cp_model.CpModel,
    x: GridVars,
    params: RuleConfig,
    context: dict[str, Any],
) -> None:
    allowed_pairs = [(a, b) for a in range(1, 10) for b in range(1, 10) if abs(a - b) == 1]
    for edge in params["edges"]:
        (r1, c1), (r2, c2) = edge
        model.AddAllowedAssignments([x[int(r1)][int(c1)], x[int(r2)][int(c2)]], allowed_pairs)


def _validate_anti_close_adjacent_3(params: RuleConfig) -> None:
    return


def _add_anti_close_adjacent_3(
    model: cp_model.CpModel,
    x: GridVars,
    params: RuleConfig,
    context: dict[str, Any],
) -> None:
    for r in range(9):
        for c in range(9):
            for dr, dc in ((1, 0), (0, 1)):
                nr = r + dr
                nc = c + dc
                if nr >= 9 or nc >= 9:
                    continue
                diff = model.NewIntVar(-8, 8, f"anti_close_diff_{r}_{c}_{nr}_{nc}")
                abs_diff = model.NewIntVar(0, 8, f"anti_close_absdiff_{r}_{c}_{nr}_{nc}")
                model.Add(diff == x[r][c] - x[nr][nc])
                model.AddAbsEquality(abs_diff, diff)
                model.Add(abs_diff >= 3)


def _validate_clone_regions_set_equal(params: RuleConfig) -> None:
    groups = params.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("clone_regions_set_equal requires groups")
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("each clone group must be object")
        regions = group.get("regions")
        if not isinstance(regions, list) or len(regions) < 2:
            raise ValueError("clone group needs at least two regions")
        region_sizes: set[int] = set()
        for region in regions:
            if not isinstance(region, list) or not region:
                raise ValueError("each clone region must be non-empty cell list")
            region_sizes.add(len(region))
            uses_one_based = any(
                isinstance(cell, (list, tuple)) and len(cell) == 2 and (int(cell[0]) > 0 and int(cell[1]) > 0)
                for cell in region
            )
            for cell in region:
                if not isinstance(cell, list | tuple) or len(cell) != 2:
                    raise ValueError("clone region cells must be [row, col]")
                r = int(cell[0])
                c = int(cell[1])
                if uses_one_based:
                    r -= 1
                    c -= 1
                if not (0 <= r < 9 and 0 <= c < 9):
                    raise ValueError(f"clone cell out of bounds: {(r, c)}")
        if len(region_sizes) != 1:
            raise ValueError("all clone regions inside a group must have same size")


def _cell_equals_digit_var(
    model: cp_model.CpModel,
    x: GridVars,
    r: int,
    c: int,
    digit: int,
    cache: dict[tuple[int, int, int], cp_model.BoolVar],
) -> cp_model.BoolVar:
    key = (r, c, digit)
    cached = cache.get(key)
    if cached is not None:
        return cached
    var = model.NewBoolVar(f"is_{digit}_{r}_{c}")
    model.Add(x[r][c] == digit).OnlyEnforceIf(var)
    model.Add(x[r][c] != digit).OnlyEnforceIf(var.Not())
    cache[key] = var
    return var


def _add_clone_regions_set_equal(
    model: cp_model.CpModel,
    x: GridVars,
    params: RuleConfig,
    context: dict[str, Any],
) -> None:
    cache: dict[tuple[int, int, int], cp_model.BoolVar] = {}
    for group_index, group in enumerate(params["groups"]):
        regions = group["regions"]
        for digit in range(1, 10):
            region_presence: list[cp_model.BoolVar] = []
            for region_index, region in enumerate(regions):
                uses_one_based = any(
                    isinstance(cell, (list, tuple)) and len(cell) == 2 and (int(cell[0]) > 0 and int(cell[1]) > 0)
                    for cell in region
                )
                presence = model.NewBoolVar(f"clone_g{group_index}_r{region_index}_d{digit}")
                hit_vars = [
                    _cell_equals_digit_var(
                        model,
                        x,
                        int(cell[0]) - 1 if uses_one_based else int(cell[0]),
                        int(cell[1]) - 1 if uses_one_based else int(cell[1]),
                        digit,
                        cache,
                    )
                    for cell in region
                ]
                model.AddMaxEquality(presence, hit_vars)
                region_presence.append(presence)
            first = region_presence[0]
            for other in region_presence[1:]:
                model.Add(first == other)


def _validate_local_consecutive_exists(params: RuleConfig) -> None:
    return


def _add_local_consecutive_exists(
    model: cp_model.CpModel,
    x: GridVars,
    params: RuleConfig,
    context: dict[str, Any],
) -> None:
    incident: dict[tuple[int, int], list[cp_model.BoolVar]] = {(r, c): [] for r in range(9) for c in range(9)}
    for r in range(9):
        for c in range(9):
            for dr, dc in ((1, 0), (0, 1)):
                nr = r + dr
                nc = c + dc
                if nr >= 9 or nc >= 9:
                    continue
                diff = model.NewIntVar(-8, 8, f"diff_{r}_{c}_{nr}_{nc}")
                abs_diff = model.NewIntVar(0, 8, f"absdiff_{r}_{c}_{nr}_{nc}")
                edge_ok = model.NewBoolVar(f"consec_{r}_{c}_{nr}_{nc}")
                model.Add(diff == x[r][c] - x[nr][nc])
                model.AddAbsEquality(abs_diff, diff)
                model.Add(abs_diff == 1).OnlyEnforceIf(edge_ok)
                model.Add(abs_diff != 1).OnlyEnforceIf(edge_ok.Not())
                incident[(r, c)].append(edge_ok)
                incident[(nr, nc)].append(edge_ok)
    for vars_for_cell in incident.values():
        model.Add(sum(vars_for_cell) >= 1)


def _validate_bishop_meet_digits(params: RuleConfig) -> None:
    digits = params.get("digits", [1])
    if not isinstance(digits, list) or not digits:
        raise ValueError("bishop_meet_digits requires non-empty digits")
    for digit in digits:
        if not isinstance(digit, int) or not (1 <= digit <= 9):
            raise ValueError(f"invalid bishop_meet digit: {digit}")


def _add_bishop_meet_digits(
    model: cp_model.CpModel,
    x: GridVars,
    params: RuleConfig,
    context: dict[str, Any],
) -> None:
    digits = [int(digit) for digit in params.get("digits", [1])]
    cache: dict[tuple[int, int, int], cp_model.BoolVar] = {}
    for digit in digits:
        root_vars: list[cp_model.BoolVar] = []
        depth_vars: dict[tuple[int, int], cp_model.IntVar] = {}
        incoming_vars: dict[tuple[int, int], list[cp_model.BoolVar]] = {
            (r, c): [] for r in range(9) for c in range(9)
        }
        for r in range(9):
            for c in range(9):
                is_digit = _cell_equals_digit_var(model, x, r, c, digit, cache)
                root = model.NewBoolVar(f"bishop_root_d{digit}_{r}_{c}")
                depth = model.NewIntVar(0, 8, f"bishop_depth_d{digit}_{r}_{c}")
                root_vars.append(root)
                depth_vars[(r, c)] = depth

                model.AddImplication(root, is_digit)
                model.Add(depth == 0).OnlyEnforceIf(root)

        model.Add(sum(root_vars) == 1)

        for r in range(9):
            for c in range(9):
                is_digit = _cell_equals_digit_var(model, x, r, c, digit, cache)
                diagonal_neighbors = [
                    (rr, cc)
                    for rr in range(9)
                    for cc in range(9)
                    if (rr, cc) != (r, c) and abs(rr - r) == abs(cc - c)
                ]

                for rr, cc in diagonal_neighbors:
                    parent = model.NewBoolVar(f"bishop_parent_d{digit}_{rr}_{cc}_to_{r}_{c}")
                    parent_is_digit = _cell_equals_digit_var(model, x, rr, cc, digit, cache)
                    incoming_vars[(r, c)].append(parent)
                    model.AddImplication(parent, parent_is_digit)
                    model.AddImplication(parent, is_digit)
                    model.Add(depth_vars[(r, c)] >= depth_vars[(rr, cc)] + 1).OnlyEnforceIf(parent)

                model.Add(sum(incoming_vars[(r, c)]) + root_vars[r * 9 + c] == is_digit)


def _validate_rank_cells(params: RuleConfig) -> None:
    raise ValueError(
        "rank_cells is TODO: under standard Sudoku row/column permutation constraints the "
        "current definition risks becoming trivial."
    )


def _add_rank_cells(
    model: cp_model.CpModel,
    x: GridVars,
    params: RuleConfig,
    context: dict[str, Any],
) -> None:
    raise NotImplementedError("rank_cells is intentionally not implemented yet")


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    display_name: str
    params_schema: dict[str, Any]
    validate_params: Callable[[RuleConfig], None]
    add_constraints: Callable[[cp_model.CpModel, GridVars, RuleConfig, dict[str, Any]], None]
    describe: Callable[[RuleConfig], str] | None = None


RULE_REGISTRY: dict[str, RuleSpec] = {
    "special_monotone_3x3": RuleSpec(
        rule_id="special_monotone_3x3",
        display_name="Special Monotone 3x3",
        params_schema={"pattern_mask": "string", "blocks": "list[[br, bc]]"},
        validate_params=_validate_special_monotone,
        add_constraints=_add_special_monotone,
    ),
    "checkerboard_odd": RuleSpec(
        rule_id="checkerboard_odd",
        display_name="Checkerboard Odd (White Cells)",
        params_schema={},
        validate_params=_validate_checkerboard_odd,
        add_constraints=_add_checkerboard_odd,
    ),
    "hyper_3x3": RuleSpec(
        rule_id="hyper_3x3",
        display_name="Hyper 3x3",
        params_schema={},
        validate_params=_validate_hyper_3x3,
        add_constraints=_add_hyper_3x3,
    ),
    "l_tromino_sum": RuleSpec(
        rule_id="l_tromino_sum",
        display_name="L Tromino Sum 13",
        params_schema={"regions": "list[[[row, col], [row, col], [row, col]]]", "target_sum": "int"},
        validate_params=_validate_l_tromino_sum,
        add_constraints=_add_l_tromino_sum,
    ),
    "sum_2x2_regions": RuleSpec(
        rule_id="sum_2x2_regions",
        display_name="L Tromino Sum 13 (Legacy Alias)",
        params_schema={"regions": "legacy alias"},
        validate_params=_validate_l_tromino_sum,
        add_constraints=_add_l_tromino_sum,
    ),
    "cross_monotone": RuleSpec(
        rule_id="cross_monotone",
        display_name="Cross Monotone",
        params_schema={"crosses": "list[{center, up_len, down_len, left_len, right_len}]"},
        validate_params=_validate_cross_monotone,
        add_constraints=_add_cross_monotone,
    ),
    "anti_close_adjacent_3": RuleSpec(
        rule_id="anti_close_adjacent_3",
        display_name="Anti Close Adjacent 3",
        params_schema={},
        validate_params=_validate_anti_close_adjacent_3,
        add_constraints=_add_anti_close_adjacent_3,
    ),
    "anti_close_adjacent_4": RuleSpec(
        rule_id="anti_close_adjacent_4",
        display_name="Anti Close Adjacent 3 (Legacy Alias)",
        params_schema={},
        validate_params=_validate_anti_close_adjacent_3,
        add_constraints=_add_anti_close_adjacent_3,
    ),
    "anti_close_adjacent_5": RuleSpec(
        rule_id="anti_close_adjacent_5",
        display_name="Anti Close Adjacent 3 (Legacy Alias)",
        params_schema={},
        validate_params=_validate_anti_close_adjacent_3,
        add_constraints=_add_anti_close_adjacent_3,
    ),
    "kropki_white_only": RuleSpec(
        rule_id="kropki_white_only",
        display_name="Kropki White Only",
        params_schema={"edges": "list[[[r1,c1],[r2,c2]]]"},
        validate_params=_validate_kropki_white_only,
        add_constraints=_add_kropki_white_only,
    ),
    "clone_regions_set_equal": RuleSpec(
        rule_id="clone_regions_set_equal",
        display_name="Clone Regions Set Equal",
        params_schema={"groups": "list[{regions: list[list[[r,c]]]}]"},
        validate_params=_validate_clone_regions_set_equal,
        add_constraints=_add_clone_regions_set_equal,
    ),
    "local_consecutive_exists": RuleSpec(
        rule_id="local_consecutive_exists",
        display_name="Local Consecutive Exists",
        params_schema={},
        validate_params=_validate_local_consecutive_exists,
        add_constraints=_add_local_consecutive_exists,
    ),
    "bishop_meet_digits": RuleSpec(
        rule_id="bishop_meet_digits",
        display_name="Bishop Meet Digits",
        params_schema={"digits": "list[int]"},
        validate_params=_validate_bishop_meet_digits,
        add_constraints=_add_bishop_meet_digits,
    ),
    "rank_cells": RuleSpec(
        rule_id="rank_cells",
        display_name="Rank Cells (TODO)",
        params_schema={"rank_cells": "TODO"},
        validate_params=_validate_rank_cells,
        add_constraints=_add_rank_cells,
    ),
}
