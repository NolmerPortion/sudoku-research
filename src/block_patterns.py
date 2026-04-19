from __future__ import annotations

from itertools import combinations
from typing import Iterable

Grid3 = tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]


def is_row_col_increasing(grid: Grid3) -> bool:
    # 行方向
    for r in range(3):
        if not (grid[r][0] < grid[r][1] < grid[r][2]):
            return False

    # 列方向
    for c in range(3):
        if not (grid[0][c] < grid[1][c] < grid[2][c]):
            return False

    return True


def rotate90(grid: Grid3) -> Grid3:
    # 時計回り 90 度回転
    return tuple(
        tuple(grid[2 - r][c] for r in range(3))
        for c in range(3)
    )  # type: ignore


def all_rotations(grid: Grid3) -> list[Grid3]:
    out: list[Grid3] = []
    cur = grid
    for _ in range(4):
        if cur not in out:
            out.append(cur)
        cur = rotate90(cur)
    return out


def generate_increasing_3x3_patterns() -> list[Grid3]:
    """
    1..9 を 1 回ずつ使い、
    各行が左から右へ増加し、
    各列が上から下へ増加する 3x3 配置を全列挙する。
    """
    nums = tuple(range(1, 10))
    out: list[Grid3] = []

    for row1 in combinations(nums, 3):
        rem1 = [x for x in nums if x not in row1]

        for row2 in combinations(rem1, 3):
            row3 = tuple(x for x in rem1 if x not in row2)

            g: Grid3 = (
                tuple(sorted(row1)),  # type: ignore
                tuple(sorted(row2)),  # type: ignore
                tuple(sorted(row3)),  # type: ignore
            )

            if is_row_col_increasing(g):
                out.append(g)

    return out


def generate_special_blocks_with_rotations() -> list[Grid3]:
    """
    「増加型 3x3」を 90 度刻み回転込みで集めた集合を返す。
    """
    base = generate_increasing_3x3_patterns()
    seen: set[Grid3] = set()

    for g in base:
        for h in all_rotations(g):
            seen.add(h)

    return sorted(seen)


def format_grid(grid: Grid3) -> str:
    return "\n".join(" ".join(f"{x}" for x in row) for row in grid)


def main() -> None:
    base = generate_increasing_3x3_patterns()
    special = generate_special_blocks_with_rotations()

    print(f"増加型 3x3 の個数: {len(base)}")
    print(f"回転込み特殊ブロック個数: {len(special)}")
    print()

    print("最初の 5 個の増加型 3x3:")
    for i, g in enumerate(base[:5], start=1):
        print(f"[{i}]")
        print(format_grid(g))
        print()


if __name__ == "__main__":
    main()