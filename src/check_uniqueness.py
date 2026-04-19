from __future__ import annotations

from pathlib import Path
import argparse
import time
from typing import Any

from ortools.sat.python import cp_model

from block_patterns import generate_special_blocks_with_rotations
from search_special_blocks import build_model


BlockPos = tuple[int, int]
Grid9 = list[list[int]]
RuleConfig = dict[str, Any]


def is_complete_grid(grid: Grid9 | None) -> bool:
    if grid is None or len(grid) != 9:
        return False
    return all(len(row) == 9 and all(1 <= cell <= 9 for cell in row) for row in grid)


def flatten_block(
    block: tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]
) -> tuple[int, ...]:
    return tuple(block[r][c] for r in range(3) for c in range(3))


def parse_pattern_mask(mask: str) -> set[BlockPos]:
    mask = mask.strip()
    if len(mask) != 9 or any(ch not in "01" for ch in mask):
        raise ValueError("pattern mask must be a 9-character string over {0,1}")

    out: set[BlockPos] = set()
    for i, ch in enumerate(mask):
        if ch == "1":
            out.add(divmod(i, 3))
    return out


def parse_puzzle_string(puzzle: str) -> Grid9:
    s = "".join(ch for ch in puzzle if not ch.isspace())
    if len(s) != 81:
        raise ValueError("puzzle must have exactly 81 non-whitespace characters")

    vals: list[int] = []
    for ch in s:
        if ch in "0.":
            vals.append(0)
        elif ch in "123456789":
            vals.append(int(ch))
        else:
            raise ValueError("puzzle must contain only digits 1..9, 0, or '.'")

    return [vals[9 * r : 9 * (r + 1)] for r in range(9)]


def grid_to_string(grid: Grid9) -> str:
    return "".join(str(grid[r][c]) for r in range(9) for c in range(9))


def pretty_grid(grid: Grid9) -> str:
    lines: list[str] = []
    for r in range(9):
        if r % 3 == 0:
            lines.append("+-------+-------+-------+")
        row_parts: list[str] = []
        for c in range(9):
            if c % 3 == 0:
                row_parts.append("|")
            v = grid[r][c]
            row_parts.append("." if v == 0 else str(v))
        row_parts.append("|")
        lines.append(" ".join(row_parts))
    lines.append("+-------+-------+-------+")
    return "\n".join(lines)


def apply_givens(
    model: cp_model.CpModel,
    x: list[list[cp_model.IntVar]],
    puzzle_grid: Grid9,
) -> None:
    for r in range(9):
        for c in range(9):
            v = puzzle_grid[r][c]
            if v != 0:
                model.Add(x[r][c] == v)


def extract_grid(
    solver: cp_model.CpSolver,
    x: list[list[cp_model.IntVar]],
) -> Grid9:
    return [[solver.Value(x[r][c]) for c in range(9)] for r in range(9)]


class UpToTwoSolutionsCollector(cp_model.CpSolverSolutionCallback):
    def __init__(self, x: list[list[cp_model.IntVar]], limit: int = 2) -> None:
        super().__init__()
        self._x = x
        self._limit = limit
        self._solutions: list[Grid9] = []

    @property
    def solution_count(self) -> int:
        return len(self._solutions)

    @property
    def solutions(self) -> list[Grid9]:
        return self._solutions

    def OnSolutionCallback(self) -> None:
        grid = [[self.Value(self._x[r][c]) for c in range(9)] for r in range(9)]
        self._solutions.append(grid)
        if len(self._solutions) >= self._limit:
            self.StopSearch()


def collect_completions(
    puzzle_grid: Grid9,
    special_positions: set[BlockPos] | None = None,
    time_limit: float = 30.0,
    max_solutions: int = 50,
    rules: list[RuleConfig] | None = None,
    forbidden_solutions: list[Grid9] | None = None,
) -> dict[str, Any]:
    if max_solutions <= 0:
        raise ValueError("max_solutions must be >= 1")

    special_blocks = generate_special_blocks_with_rotations()
    allowed_tuples = [flatten_block(block) for block in special_blocks]
    solutions: list[Grid9] = []
    seen_solution_strings: set[str] = set()
    blocked_solutions = forbidden_solutions or []
    deadline = time.perf_counter() + time_limit
    status_name = "UNKNOWN"
    hit_infeasible = False

    for solve_index in range(max_solutions):
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            break

        model, x = build_model(special_positions or set(), allowed_tuples, rules=rules)
        apply_givens(model, x, puzzle_grid)

        flat_vars = [x[r][c] for r in range(9) for c in range(9)]
        forbidden_rows = [
            [solution[r][c] for r in range(9) for c in range(9)]
            for solution in blocked_solutions
            if is_complete_grid(solution)
        ]
        forbidden_rows.extend(
            [
            [solution[r][c] for r in range(9) for c in range(9)]
            for solution in solutions
            if is_complete_grid(solution)
            ]
        )
        if forbidden_rows:
            model.AddForbiddenAssignments(flat_vars, forbidden_rows)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = remaining
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = solve_index + 1

        status = solver.Solve(model)
        status_name = solver.StatusName(status)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            candidate = extract_grid(solver, x)
            if not is_complete_grid(candidate):
                continue
            candidate_key = grid_to_string(candidate)
            if candidate_key in seen_solution_strings:
                continue
            seen_solution_strings.add(candidate_key)
            solutions.append(candidate)
            continue
        if status == cp_model.INFEASIBLE:
            hit_infeasible = True
            break
        break

    if hit_infeasible and not solutions:
        classification = "no_solution"
    elif solutions:
        classification = "solved"
    else:
        classification = "unknown"

    return {
        "classification": classification,
        "solver_status": status_name,
        "solution_count_found": len(solutions),
        "solutions": solutions,
        "reached_limit": len(solutions) >= max_solutions,
        "wall_time_sec": max(0.0, time_limit - max(0.0, deadline - time.perf_counter())),
    }


def check_uniqueness(
    puzzle_grid: Grid9,
    special_positions: set[BlockPos] | None = None,
    time_limit: float = 30.0,
    rules: list[RuleConfig] | None = None,
) -> dict[str, Any]:
    special_blocks = generate_special_blocks_with_rotations()
    allowed_tuples = [flatten_block(block) for block in special_blocks]
    deadline = time.perf_counter() + time_limit
    solutions: list[Grid9] = []
    status_name = "UNKNOWN"
    hit_infeasible = False

    for solve_index in range(2):
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            break

        model, x = build_model(special_positions or set(), allowed_tuples, rules=rules)
        apply_givens(model, x, puzzle_grid)

        if solutions:
            flat_vars = [x[r][c] for r in range(9) for c in range(9)]
            forbidden_rows = [
                [solution[r][c] for r in range(9) for c in range(9)]
                for solution in solutions
                if is_complete_grid(solution)
            ]
            if forbidden_rows:
                model.AddForbiddenAssignments(flat_vars, forbidden_rows)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = remaining
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = solve_index + 1

        status = solver.Solve(model)
        status_name = solver.StatusName(status)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            candidate = extract_grid(solver, x)
            if not is_complete_grid(candidate):
                break
            solutions.append(candidate)
            continue
        if status == cp_model.INFEASIBLE:
            hit_infeasible = True
            break
        break

    if hit_infeasible and not solutions:
        classification = "no_solution"
    elif len(solutions) >= 2:
        classification = "multiple"
    elif len(solutions) == 1:
        classification = "unique"
    else:
        classification = "unknown"

    return {
        "classification": classification,
        "solver_status": status_name,
        "solution_count_found": len(solutions),
        "solutions": solutions,
        "wall_time_sec": max(0.0, time_limit - max(0.0, deadline - time.perf_counter())),
    }


def solve_one_completion(
    puzzle_grid: Grid9,
    special_positions: set[BlockPos] | None = None,
    time_limit: float = 30.0,
    rules: list[RuleConfig] | None = None,
) -> dict[str, Any]:
    special_blocks = generate_special_blocks_with_rotations()
    allowed_tuples = [flatten_block(block) for block in special_blocks]

    model, x = build_model(special_positions or set(), allowed_tuples, rules=rules)
    apply_givens(model, x, puzzle_grid)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 1

    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        solution = extract_grid(solver, x)
        classification = "solved" if is_complete_grid(solution) else "unknown"
    elif status == cp_model.INFEASIBLE:
        solution = None
        classification = "no_solution"
    else:
        solution = None
        classification = "unknown"

    return {
        "classification": classification,
        "solver_status": status_name,
        "solution": solution,
        "wall_time_sec": solver.WallTime(),
    }


def load_puzzle_from_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check uniqueness under the current Sudoku rule set.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--puzzle", type=str)
    group.add_argument("--puzzle-file", type=str)

    parser.add_argument("--pattern-mask", type=str, required=True)
    parser.add_argument("--time-limit", type=float, default=30.0)
    parser.add_argument("--show-solutions", action="store_true")
    args = parser.parse_args()

    puzzle_text = args.puzzle if args.puzzle is not None else load_puzzle_from_file(args.puzzle_file)
    puzzle_grid = parse_puzzle_string(puzzle_text)
    special_positions = parse_pattern_mask(args.pattern_mask)

    result = check_uniqueness(
        puzzle_grid=puzzle_grid,
        special_positions=special_positions,
        time_limit=args.time_limit,
    )

    print("pattern_mask =", args.pattern_mask)
    print("puzzle:")
    print(pretty_grid(puzzle_grid))
    print()
    print("classification =", result["classification"])
    print("solver_status   =", result["solver_status"])
    print("solutions_found =", result["solution_count_found"])
    print("wall_time_sec   =", result["wall_time_sec"])

    if args.show_solutions and result["solutions"]:
        for i, sol in enumerate(result["solutions"], start=1):
            print()
            print(f"solution #{i}")
            print(pretty_grid(sol))


if __name__ == "__main__":
    main()
