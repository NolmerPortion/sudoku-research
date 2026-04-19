from __future__ import annotations

from pathlib import Path

from ortools.sat.python import cp_model

from block_patterns import generate_special_blocks_with_rotations
from search_special_blocks import build_model

Grid9 = list[list[int]]
BlockPos = tuple[int, int]


# 実際に可解と確認済みの配置をそのまま使う
FEASIBLE_SPECIAL_POSITIONS: set[BlockPos] = {
    (0, 1), (0, 2),
    (1, 0),
    (2, 1), (2, 2),
}


def flatten_block(block: tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]) -> tuple[int, ...]:
    return tuple(block[r][c] for r in range(3) for c in range(3))


def extract_grid(solver: cp_model.CpSolver, x: list[list[cp_model.IntVar]]) -> Grid9:
    return [[solver.Value(x[r][c]) for c in range(9)] for r in range(9)]


def pretty_grid(grid: Grid9) -> str:
    lines: list[str] = []
    for r in range(9):
        if r % 3 == 0:
            lines.append("+-------+-------+-------+")
        row_parts = []
        for c in range(9):
            if c % 3 == 0:
                row_parts.append("|")
            row_parts.append(str(grid[r][c]))
        row_parts.append("|")
        lines.append(" ".join(row_parts))
    lines.append("+-------+-------+-------+")
    return "\n".join(lines)


class SolutionCollector(cp_model.CpSolverSolutionCallback):
    def __init__(
        self,
        x: list[list[cp_model.IntVar]],
        out_path: Path,
        limit: int | None = None,
        print_every: int = 10,
    ) -> None:
        super().__init__()
        self._x = x
        self._out_path = out_path
        self._limit = limit
        self._print_every = print_every
        self._count = 0

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("", encoding="utf-8")

    @property
    def solution_count(self) -> int:
        return self._count

    def current_grid(self) -> Grid9:
        return [[self.Value(self._x[r][c]) for c in range(9)] for r in range(9)]

    def OnSolutionCallback(self) -> None:
        self._count += 1
        grid = self.current_grid()

        with self._out_path.open("a", encoding="utf-8") as f:
            f.write(f"=== Solution {self._count} ===\n")
            f.write(pretty_grid(grid))
            f.write("\n\n")

        if self._count % self._print_every == 0:
            print(f"[{self._count}] solutions found, wall_time = {self.WallTime():.2f} s")

        if self._limit is not None and self._count >= self._limit:
            print(f"Stop search after {self._limit} solutions")
            self.StopSearch()


def main() -> None:
    special_blocks = generate_special_blocks_with_rotations()
    allowed_tuples = [flatten_block(b) for b in special_blocks]

    model, x = build_model(FEASIBLE_SPECIAL_POSITIONS, allowed_tuples)

    print("特殊ブロック配置:")
    for br in range(3):
        print(" ".join("S" if (br, bc) in FEASIBLE_SPECIAL_POSITIONS else "." for bc in range(3)))
    print()

    # まず 1 解だけ取れるか確認する
    sanity_solver = cp_model.CpSolver()
    sanity_solver.parameters.max_time_in_seconds = 30.0

    sanity_status = sanity_solver.Solve(model)
    print("sanity status =", sanity_solver.StatusName(sanity_status))
    print("sanity wall_time_sec =", sanity_solver.WallTime())
    print()

    if sanity_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("この配置では 1 解も見つかりません。")
        print("配置指定かモデル指定が食い違っています。")
        return

    first_grid = extract_grid(sanity_solver, x)
    print("最初の1解:")
    print(pretty_grid(first_grid))
    print()

    # 次に全解列挙
    enum_solver = cp_model.CpSolver()
    enum_solver.parameters.max_time_in_seconds = 300.0
    enum_solver.parameters.num_search_workers = 1

    out_path = Path("outputs/solutions/feasible_pattern_raw_solutions.txt")
    cb = SolutionCollector(
        x=x,
        out_path=out_path,
        limit=100,
        print_every=10,
    )

    status = enum_solver.SearchForAllSolutions(model, cb)

    print()
    print("enumeration status =", enum_solver.StatusName(status))
    print("solution_count =", cb.solution_count)
    print("wall_time_sec =", enum_solver.WallTime())
    print("output_file =", out_path)


if __name__ == "__main__":
    main()