from __future__ import annotations

import sys
from pathlib import Path

# プロジェクト直下で実行する前提
sys.path.append(str(Path(__file__).resolve().parent / "src"))

from check_uniqueness import (  # noqa: E402
    check_uniqueness,
    parse_pattern_mask,
    parse_puzzle_string,
    pretty_grid,
)

# ===== ここを必要に応じて変える =====

# 盤面。空欄は 0。
PUZZLE = """
000000000
000000000
000700100
000600000
007000000
000000000
000000000
000000000
004000000
"""

# 標準数独として解くなら空集合
SPECIAL_POSITIONS = parse_pattern_mask("011100011")

# 特殊3x3ルール込みで解くなら、たとえば次を使う
# SPECIAL_POSITIONS = parse_pattern_mask("011100011")

TIME_LIMIT = 30.0

# ===================================


def main() -> None:
    puzzle_grid = parse_puzzle_string(PUZZLE)

    result = check_uniqueness(
        puzzle_grid=puzzle_grid,
        special_positions=SPECIAL_POSITIONS,
        time_limit=TIME_LIMIT,
    )

    print("puzzle:")
    print(pretty_grid(puzzle_grid))
    print()
    print("classification =", result["classification"])
    print("solver_status   =", result["solver_status"])
    print("solutions_found =", result["solution_count_found"])
    print("wall_time_sec   =", result["wall_time_sec"])

    if result["solutions"]:
        for i, sol in enumerate(result["solutions"], start=1):
            print()
            print(f"solution #{i}")
            print(pretty_grid(sol))


if __name__ == "__main__":
    main()