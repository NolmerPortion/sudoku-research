from __future__ import annotations

from itertools import combinations
from pathlib import Path
import argparse
import json
from typing import Any

from ortools.sat.python import cp_model

from block_patterns import generate_special_blocks_with_rotations
from search_special_blocks import build_model

BlockPos = tuple[int, int]
Pattern = frozenset[BlockPos]
Grid9 = list[list[int]]


def flatten_block(
    block: tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]
) -> tuple[int, ...]:
    return tuple(block[r][c] for r in range(3) for c in range(3))


def pattern_to_matrix(pattern: Pattern) -> list[list[int]]:
    return [[1 if (r, c) in pattern else 0 for c in range(3)] for r in range(3)]


def pattern_to_mask_string(pattern: Pattern) -> str:
    # 左上から右下へ 9 文字。特殊=S=1, 緩和=.=0
    return "".join("1" if (r, c) in pattern else "0" for r in range(3) for c in range(3))


def pattern_to_pretty_string(pattern: Pattern) -> str:
    return "\n".join(
        " ".join("S" if (r, c) in pattern else "." for c in range(3))
        for r in range(3)
    )


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
            row_parts.append(str(grid[r][c]))
        row_parts.append("|")
        lines.append(" ".join(row_parts))
    lines.append("+-------+-------+-------+")
    return "\n".join(lines)


def extract_grid(solver: cp_model.CpSolver, x: list[list[cp_model.IntVar]]) -> Grid9:
    return [[solver.Value(x[r][c]) for c in range(9)] for r in range(9)]


def all_raw_5_special_patterns() -> list[Pattern]:
    cells = [(r, c) for r in range(3) for c in range(3)]
    out: list[Pattern] = []

    for comb in combinations(cells, 5):
        pattern = frozenset(comb)

        row_counts = [sum((r, c) in pattern for c in range(3)) for r in range(3)]
        col_counts = [sum((r, c) in pattern for r in range(3)) for c in range(3)]

        # 各ブロック行・各ブロック列に特殊3個は不可能
        if max(row_counts) <= 2 and max(col_counts) <= 2:
            out.append(pattern)

    out.sort(key=pattern_to_mask_string)
    return out


class LimitedSolutionCollector(cp_model.CpSolverSolutionCallback):
    def __init__(
        self,
        x: list[list[cp_model.IntVar]],
        limit: int,
        print_every: int = 10,
    ) -> None:
        super().__init__()
        self._x = x
        self._limit = limit
        self._print_every = print_every
        self._solutions: list[dict[str, Any]] = []
        self._seen_strings: set[str] = set()

    @property
    def solutions(self) -> list[dict[str, Any]]:
        return self._solutions

    def OnSolutionCallback(self) -> None:
        grid = [[self.Value(self._x[r][c]) for c in range(9)] for r in range(9)]
        s = grid_to_string(grid)

        # 念のため重複防止
        if s not in self._seen_strings:
            self._seen_strings.add(s)
            self._solutions.append(
                {
                    "grid_string": s,
                    "grid": grid,
                }
            )

            if len(self._solutions) % self._print_every == 0:
                print(
                    f"  [{len(self._solutions)}] solutions collected, wall_time = {self.WallTime():.2f} s"
                )

        if len(self._solutions) >= self._limit:
            self.StopSearch()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="5個特殊ブロック配置の全生パターンを走査し、可解なものから完成盤面を収集する。"
    )
    parser.add_argument("--max-solutions", type=int, default=50)
    parser.add_argument("--feasibility-time-limit", type=float, default=20.0)
    parser.add_argument("--enumeration-time-limit", type=float, default=300.0)
    parser.add_argument("--feasibility-workers", type=int, default=16)
    parser.add_argument(
        "--output-dir",
        type=str,
        default="outputs/dataset_5_special",
    )
    parser.add_argument(
        "--only-feasible",
        action="store_true",
        help="不可解パターンの個別 JSON を出さず、可解なものだけ出力する。",
    )
    args = parser.parse_args()

    patterns = all_raw_5_special_patterns()

    special_blocks = generate_special_blocks_with_rotations()
    allowed_tuples = [flatten_block(b) for b in special_blocks]

    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)

    pattern_dir = root / "patterns"
    pattern_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "dataset_name": "sudoku_5_special_blocks",
        "max_solutions_per_pattern": args.max_solutions,
        "feasibility_time_limit_sec": args.feasibility_time_limit,
        "enumeration_time_limit_sec": args.enumeration_time_limit,
        "pattern_count_checked": 0,
        "feasible_pattern_count": 0,
        "infeasible_pattern_count": 0,
        "partial_pattern_count": 0,
        "patterns": [],
    }

    human_report_lines: list[str] = []

    for idx, pattern in enumerate(patterns, start=1):
        pattern_id = f"pattern_{idx:03d}_{pattern_to_mask_string(pattern)}"

        print(f"[{idx}/{len(patterns)}] checking {pattern_id}")
        human_report_lines.append(f"=== {pattern_id} ===")
        human_report_lines.append(pattern_to_pretty_string(pattern))
        human_report_lines.append("")

        # 1) 可解性判定
        model, x = build_model(set(pattern), allowed_tuples)

        feasibility_solver = cp_model.CpSolver()
        feasibility_solver.parameters.max_time_in_seconds = args.feasibility_time_limit
        feasibility_solver.parameters.num_search_workers = args.feasibility_workers

        feasibility_status = feasibility_solver.Solve(model)
        feasibility_status_name = feasibility_solver.StatusName(feasibility_status)

        entry: dict[str, Any] = {
            "pattern_id": pattern_id,
            "pattern_mask_string": pattern_to_mask_string(pattern),
            "pattern_matrix": pattern_to_matrix(pattern),
            "special_positions": sorted([list(p) for p in pattern]),
            "pretty_pattern": pattern_to_pretty_string(pattern),
            "feasibility_status": feasibility_status_name,
            "feasibility_wall_time_sec": feasibility_solver.WallTime(),
            "solution_count_exported": 0,
            "enumeration_status": None,
            "enumeration_wall_time_sec": None,
            "solutions": [],
        }

        manifest["pattern_count_checked"] += 1

        if feasibility_status == cp_model.INFEASIBLE:
            manifest["infeasible_pattern_count"] += 1
            human_report_lines.append(f"feasibility_status = {feasibility_status_name}")
            human_report_lines.append("")
            human_report_lines.append("-" * 60)
            human_report_lines.append("")

            if not args.only_feasible:
                with (pattern_dir / f"{pattern_id}.json").open("w", encoding="utf-8") as f:
                    json.dump(entry, f, ensure_ascii=False, indent=2)

            manifest["patterns"].append(
                {
                    "pattern_id": pattern_id,
                    "pattern_mask_string": entry["pattern_mask_string"],
                    "feasibility_status": entry["feasibility_status"],
                    "solution_count_exported": 0,
                }
            )
            continue

        if feasibility_status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            # UNKNOWN 等
            manifest["partial_pattern_count"] += 1
            human_report_lines.append(f"feasibility_status = {feasibility_status_name}")
            human_report_lines.append("note = feasibility was not resolved")
            human_report_lines.append("")
            human_report_lines.append("-" * 60)
            human_report_lines.append("")

            if not args.only_feasible:
                with (pattern_dir / f"{pattern_id}.json").open("w", encoding="utf-8") as f:
                    json.dump(entry, f, ensure_ascii=False, indent=2)

            manifest["patterns"].append(
                {
                    "pattern_id": pattern_id,
                    "pattern_mask_string": entry["pattern_mask_string"],
                    "feasibility_status": entry["feasibility_status"],
                    "solution_count_exported": 0,
                }
            )
            continue

        manifest["feasible_pattern_count"] += 1

        # 2) 可解なら完成盤面を列挙
        enum_model, enum_x = build_model(set(pattern), allowed_tuples)

        enum_solver = cp_model.CpSolver()
        enum_solver.parameters.max_time_in_seconds = args.enumeration_time_limit

        # 全解列挙では 1 worker にしておくのが安全
        enum_solver.parameters.num_search_workers = 1

        collector = LimitedSolutionCollector(
            enum_x,
            limit=args.max_solutions,
            print_every=10,
        )
        enum_status = enum_solver.SearchForAllSolutions(enum_model, collector)
        enum_status_name = enum_solver.StatusName(enum_status)

        entry["enumeration_status"] = enum_status_name
        entry["enumeration_wall_time_sec"] = enum_solver.WallTime()
        entry["solution_count_exported"] = len(collector.solutions)
        entry["solutions"] = collector.solutions

        if len(collector.solutions) < args.max_solutions:
            manifest["partial_pattern_count"] += 1

        human_report_lines.append(f"feasibility_status = {feasibility_status_name}")
        human_report_lines.append(f"enumeration_status = {enum_status_name}")
        human_report_lines.append(f"solution_count_exported = {len(collector.solutions)}")

        if collector.solutions:
            first_grid = collector.solutions[0]["grid"]
            human_report_lines.append("first_solution:")
            human_report_lines.append(pretty_grid(first_grid))

        human_report_lines.append("")
        human_report_lines.append("-" * 60)
        human_report_lines.append("")

        with (pattern_dir / f"{pattern_id}.json").open("w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)

        manifest["patterns"].append(
            {
                "pattern_id": pattern_id,
                "pattern_mask_string": entry["pattern_mask_string"],
                "feasibility_status": entry["feasibility_status"],
                "enumeration_status": entry["enumeration_status"],
                "solution_count_exported": entry["solution_count_exported"],
            }
        )

    with (root / "manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    with (root / "report.txt").open("w", encoding="utf-8") as f:
        f.write("\n".join(human_report_lines))

    print()
    print("done")
    print("manifest =", root / "manifest.json")
    print("report   =", root / "report.txt")
    print("patterns =", pattern_dir)


if __name__ == "__main__":
    main()