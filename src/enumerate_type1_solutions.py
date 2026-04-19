from __future__ import annotations

from pathlib import Path

from ortools.sat.python import cp_model

from search_special_blocks import build_model

Grid9 = list[list[int]]
BlockPos = tuple[int, int]


TYPE1_SPECIAL_POSITIONS: set[BlockPos] = {
    (0, 2),
    (1, 1), (1, 2),
    (2, 0), (2, 1),
}


def grid_to_text(grid: Grid9) -> str:
    lines: list[str] = []
    for r in range(9):
        if r % 3 == 0:
            lines.append("+-------+-------+-------+")
        row = []
        for c in range(9):
            if c % 3 == 0:
                row.append("|")
            row.append(str(grid[r][c]))
        row.append("|")
        lines.append(" ".join(row))
    lines.append("+-------+-------+-------+")
    return "\n".join(lines)


class Type1SolutionCollector(cp_model.CpSolverSolutionCallback):
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
        return [[self.value(self._x[r][c]) for c in range(9)] for r in range(9)]

    def on_solution_callback(self) -> None:
        self._count += 1
        grid = self.current_grid()

        with self._out_path.open("a", encoding="utf-8") as f:
            f.write(f"=== Solution {self._count} ===\n")
            f.write(grid_to_text(grid))
            f.write("\n\n")

        if self._count % self._print_every == 0:
            print(f"[{self._count}] solutions found, wall_time = {self.wall_time():.2f} s")

        if self._limit is not None and self._count >= self._limit:
            print(f"Stop search after {self._limit} solutions")
            self.stop_search()


def main() -> None:
    from block_patterns import generate_special_blocks_with_rotations

    special_blocks = generate_special_blocks_with_rotations()
    allowed_tuples = [
        tuple(block[r][c] for r in range(3) for c in range(3))
        for block in special_blocks
    ]

    model, x = build_model(TYPE1_SPECIAL_POSITIONS, allowed_tuples)

    solver = cp_model.CpSolver()

    # 全解列挙モード
    solver.parameters.enumerate_all_solutions = True

    # 最初は安全側にしておく
    solver.parameters.max_time_in_seconds = 300.0

    # 私は最初は 1 worker を勧めます。列挙の再現性が高く、挙動を追いやすいからです。
    solver.parameters.num_search_workers = 1

    out_path = Path("outputs/solutions/type1_raw_solutions.txt")
    cb = Type1SolutionCollector(
        x=x,
        out_path=out_path,
        limit=100,
        print_every=10,
    )

    status = solver.solve(model, cb)

    print()
    print("status =", solver.status_name(status))
    print("solution_count =", cb.solution_count)
    print("wall_time_sec =", solver.wall_time)
    print("output_file =", out_path)


if __name__ == "__main__":
    main()