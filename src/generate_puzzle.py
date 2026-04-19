from __future__ import annotations

from pathlib import Path
import argparse
import json
import random
import time
from typing import Any

from check_uniqueness import (
    check_uniqueness,
    parse_pattern_mask,
    parse_puzzle_string,
    grid_to_string,
    pretty_grid,
    solve_one_completion,
)


Grid9 = list[list[int]]
Cell = tuple[int, int]
CellGroup = tuple[Cell, ...]
RuleConfig = dict[str, Any]


def copy_grid(grid: Grid9) -> Grid9:
    return [row[:] for row in grid]


def clue_count(grid: Grid9) -> int:
    return sum(1 for r in range(9) for c in range(9) if grid[r][c] != 0)


def load_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def validate_full_solution(
    solution_grid: Grid9,
    pattern_mask: str,
    time_limit: float,
    rules: list[RuleConfig] | None = None,
) -> dict[str, Any]:
    if any(solution_grid[r][c] == 0 for r in range(9) for c in range(9)):
        raise ValueError("solution grid must not contain 0 or '.'")

    result = solve_one_completion(
        puzzle_grid=solution_grid,
        special_positions=parse_pattern_mask(pattern_mask),
        time_limit=time_limit,
        rules=rules,
    )
    if result["classification"] == "solved" and result.get("solution") == solution_grid:
        return {
            "classification": "unique",
            "solver_status": result["solver_status"],
            "solution_count_found": 1,
            "solutions": [solution_grid],
            "wall_time_sec": result["wall_time_sec"],
        }
    return {
        "classification": "no_solution" if result["classification"] == "no_solution" else "unknown",
        "solver_status": result["solver_status"],
        "solution_count_found": 0,
        "solutions": [],
        "wall_time_sec": result["wall_time_sec"],
    }


def canonical_pair(a: Cell, b: Cell) -> CellGroup:
    return tuple(sorted((a, b)))


def build_removal_groups(symmetry: str) -> list[CellGroup]:
    groups: set[CellGroup] = set()

    for r in range(9):
        for c in range(9):
            a = (r, c)

            if symmetry == "none":
                groups.add((a,))
            elif symmetry == "rot180":
                b = (8 - r, 8 - c)
                groups.add(canonical_pair(a, b) if a != b else (a,))
            elif symmetry == "main_diag":
                b = (c, r)
                groups.add(canonical_pair(a, b) if a != b else (a,))
            elif symmetry == "anti_diag":
                b = (8 - c, 8 - r)
                groups.add(canonical_pair(a, b) if a != b else (a,))
            else:
                raise ValueError(f"unknown symmetry: {symmetry}")

    return sorted(groups)


def try_remove_group(grid: Grid9, group: CellGroup) -> tuple[Grid9, bool]:
    if all(grid[r][c] == 0 for r, c in group):
        return copy_grid(grid), False

    new_grid = copy_grid(grid)
    for r, c in group:
        new_grid[r][c] = 0
    return new_grid, True


def generate_one_puzzle(
    solution_grid: Grid9,
    pattern_mask: str,
    symmetry: str,
    uniqueness_time_limit: float,
    seed: int,
    target_clues: int | None,
    verbose: bool = False,
    rules: list[RuleConfig] | None = None,
    max_wall_time_sec: float | None = None,
) -> dict[str, Any]:
    rng = random.Random(seed)
    groups = build_removal_groups(symmetry)
    rng.shuffle(groups)

    puzzle = copy_grid(solution_grid)
    special_positions = parse_pattern_mask(pattern_mask)
    deadline = time.perf_counter() + max_wall_time_sec if max_wall_time_sec and max_wall_time_sec > 0 else None

    accepted_groups: list[CellGroup] = []
    rejected_groups: list[CellGroup] = []

    for idx, group in enumerate(groups, start=1):
        if deadline is not None and time.perf_counter() >= deadline:
            break
        current_clues = clue_count(puzzle)
        remove_size = sum(1 for r, c in group if puzzle[r][c] != 0)

        if remove_size == 0:
            continue

        if target_clues is not None and current_clues - remove_size < target_clues:
            rejected_groups.append(group)
            continue

        candidate, changed = try_remove_group(puzzle, group)
        if not changed:
            continue

        result = check_uniqueness(
            puzzle_grid=candidate,
            special_positions=special_positions,
            time_limit=(
                max(0.1, min(uniqueness_time_limit, deadline - time.perf_counter()))
                if deadline is not None
                else uniqueness_time_limit
            ),
            rules=rules,
        )

        if result["classification"] == "unique":
            puzzle = candidate
            accepted_groups.append(group)
            if verbose:
                print(
                    f"[accept {idx:02d}] remove {group}, "
                    f"clues={clue_count(puzzle)}, wall_time={result['wall_time_sec']:.3f}s"
                )
            if target_clues is not None and clue_count(puzzle) == target_clues:
                break
        else:
            rejected_groups.append(group)
            if verbose:
                print(
                    f"[reject {idx:02d}] remove {group}, "
                    f"classification={result['classification']}, "
                    f"wall_time={result['wall_time_sec']:.3f}s"
                )

    return {
        "puzzle_grid": puzzle,
        "puzzle_string": grid_to_string(puzzle),
        "clue_count": clue_count(puzzle),
        "accepted_groups": [list(map(list, group)) for group in accepted_groups],
        "rejected_group_count": len(rejected_groups),
        "symmetry": symmetry,
        "seed": seed,
        "rules": [dict(rule) for rule in rules] if rules else [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a unique puzzle from a solved grid.")

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--solution", type=str)
    input_group.add_argument("--solution-file", type=str)

    parser.add_argument("--pattern-mask", type=str, required=True)
    parser.add_argument("--symmetry", choices=["none", "rot180", "main_diag", "anti_diag"], default="none")
    parser.add_argument("--target-clues", type=int, default=None)
    parser.add_argument("--trials", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--uniqueness-time-limit", type=float, default=5.0)
    parser.add_argument("--validation-time-limit", type=float, default=10.0)
    parser.add_argument("--output-file", type=str, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    solution_text = args.solution if args.solution is not None else load_text(args.solution_file)
    solution_grid = parse_puzzle_string(solution_text)

    validation = validate_full_solution(
        solution_grid=solution_grid,
        pattern_mask=args.pattern_mask,
        time_limit=args.validation_time_limit,
    )

    print("validation classification =", validation["classification"])
    print("validation solver_status  =", validation["solver_status"])
    print("validation wall_time_sec  =", validation["wall_time_sec"])

    if validation["classification"] != "unique":
        raise SystemExit("input solution is not uniquely valid under the selected rules")

    best_result: dict[str, Any] | None = None
    for trial in range(args.trials):
        trial_seed = args.seed + trial
        result = generate_one_puzzle(
            solution_grid=solution_grid,
            pattern_mask=args.pattern_mask,
            symmetry=args.symmetry,
            uniqueness_time_limit=args.uniqueness_time_limit,
            seed=trial_seed,
            target_clues=args.target_clues,
            verbose=args.verbose,
        )
        if best_result is None or result["clue_count"] < best_result["clue_count"]:
            best_result = result

    assert best_result is not None
    print()
    print("solution:")
    print(pretty_grid(solution_grid))
    print()
    print("puzzle:")
    print(pretty_grid(best_result["puzzle_grid"]))
    print()
    print("clue_count =", best_result["clue_count"])

    payload = {
        "pattern_mask": args.pattern_mask,
        "solution_string": grid_to_string(solution_grid),
        "puzzle_string": best_result["puzzle_string"],
        "solution_grid": solution_grid,
        "puzzle_grid": best_result["puzzle_grid"],
        "clue_count": best_result["clue_count"],
        "symmetry": args.symmetry,
        "seed": best_result["seed"],
        "accepted_groups": best_result["accepted_groups"],
        "final_uniqueness_check": check_uniqueness(
            puzzle_grid=best_result["puzzle_grid"],
            special_positions=parse_pattern_mask(args.pattern_mask),
            time_limit=max(args.uniqueness_time_limit, 10.0),
            rules=best_result["rules"],
        ),
        "rules": best_result["rules"],
    }

    if args.output_file:
        Path(args.output_file).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
