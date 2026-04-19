from __future__ import annotations

import argparse
from typing import Any

from ortools.sat.python import cp_model

from block_patterns import generate_special_blocks_with_rotations
from puzzle_rules import add_rules_constraints


Grid9 = list[list[int]]
BlockPos = tuple[int, int]
RuleConfig = dict[str, Any]


def flatten_block(block: tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]) -> tuple[int, ...]:
    return tuple(block[r][c] for r in range(3) for c in range(3))


def pretty_grid(grid: Grid9) -> str:
    lines: list[str] = []
    for r in range(9):
        if r % 3 == 0:
            lines.append("+-------+-------+-------+")
        row_parts: list[str] = []
        for c in range(9):
            if c % 3 == 0:
                row_parts.append("|")
            row_parts.append(str(grid[r][c]))
        row_parts.append("|")
        lines.append(" ".join(row_parts))
    lines.append("+-------+-------+-------+")
    return "\n".join(lines)


def block_cells(x: list[list[cp_model.IntVar]], br: int, bc: int) -> list[cp_model.IntVar]:
    return [x[3 * br + dr][3 * bc + dc] for dr in range(3) for dc in range(3)]


def extract_grid(solver: cp_model.CpSolver, x: list[list[cp_model.IntVar]]) -> Grid9:
    return [[solver.Value(x[r][c]) for c in range(9)] for r in range(9)]


def is_special_block_values(vals: list[int], allowed_tables: set[tuple[int, ...]]) -> bool:
    return tuple(vals) in allowed_tables


def special_block_map(grid: Grid9, allowed_tables: set[tuple[int, ...]]) -> list[list[bool]]:
    out = [[False] * 3 for _ in range(3)]
    for br in range(3):
        for bc in range(3):
            vals = [grid[3 * br + dr][3 * bc + dc] for dr in range(3) for dc in range(3)]
            out[br][bc] = is_special_block_values(vals, allowed_tables)
    return out


def pretty_block_map(block_map: list[list[bool]]) -> str:
    return "\n".join(
        " ".join("S" if block_map[br][bc] else "." for bc in range(3))
        for br in range(3)
    )


def _pattern_mask_from_positions(special_positions: set[BlockPos]) -> str | None:
    if not special_positions:
        return None
    return "".join("1" if (r, c) in special_positions else "0" for r in range(3) for c in range(3))


def build_model(
    special_positions: set[BlockPos],
    allowed_tuples: list[tuple[int, ...]],
    rules: list[RuleConfig] | None = None,
) -> tuple[cp_model.CpModel, list[list[cp_model.IntVar]]]:
    model = cp_model.CpModel()

    x: list[list[cp_model.IntVar]] = [
        [model.NewIntVar(1, 9, f"x_{r}_{c}") for c in range(9)]
        for r in range(9)
    ]

    for r in range(9):
        model.AddAllDifferent(x[r])

    for c in range(9):
        model.AddAllDifferent([x[r][c] for r in range(9)])

    for br in range(3):
        for bc in range(3):
            model.AddAllDifferent(block_cells(x, br, bc))

    normalized_rules: list[RuleConfig] = []
    if rules:
        normalized_rules.extend(dict(rule) for rule in rules)

    has_special_rule = any(rule.get("type") == "special_monotone_3x3" for rule in normalized_rules)
    pattern_mask = _pattern_mask_from_positions(special_positions)
    if pattern_mask and not has_special_rule:
        normalized_rules.insert(0, {"type": "special_monotone_3x3", "pattern_mask": pattern_mask})

    add_rules_constraints(
        model,
        x,
        normalized_rules,
        context={"special_allowed_tuples": allowed_tuples},
    )
    return model, x


def solve_instance(
    special_positions: set[BlockPos],
    time_limit: float,
    num_workers: int,
    log_search_progress: bool,
) -> None:
    special_blocks = generate_special_blocks_with_rotations()
    allowed_tuples = [flatten_block(block) for block in special_blocks]
    allowed_set = set(allowed_tuples)

    print("special block positions:")
    for br in range(3):
        print(" ".join("S" if (br, bc) in special_positions else "." for bc in range(3)))
    print()

    model, x = build_model(special_positions, allowed_tuples)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = num_workers
    solver.parameters.log_search_progress = log_search_progress

    status = solver.Solve(model)

    print("status =", solver.StatusName(status))
    print("wall_time_sec =", solver.WallTime())
    print("branches =", solver.NumBranches())
    print("conflicts =", solver.NumConflicts())
    print()

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        grid = extract_grid(solver, x)
        print(pretty_grid(grid))
        print()
        print("special blocks in solved grid:")
        print(pretty_block_map(special_block_map(grid, allowed_set)))
    else:
        print("No solution found.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["test5", "search6"], required=True)
    parser.add_argument("--time-limit", type=float, default=60.0)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--log", action="store_true")
    args = parser.parse_args()

    if args.mode == "test5":
        special_positions: set[BlockPos] = {
            (0, 1), (0, 2),
            (1, 0),
            (2, 1), (2, 2),
        }
    else:
        special_positions = {
            (0, 1), (0, 2),
            (1, 0), (1, 2),
            (2, 0), (2, 1),
        }

    solve_instance(
        special_positions=special_positions,
        time_limit=args.time_limit,
        num_workers=args.workers,
        log_search_progress=args.log,
    )


if __name__ == "__main__":
    main()
