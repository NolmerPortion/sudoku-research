from __future__ import annotations

from itertools import combinations, permutations
import argparse

from search_special_blocks import solve_instance

BlockPos = tuple[int, int]
Pattern = frozenset[BlockPos]


def pattern_to_str(pattern: Pattern) -> str:
    lines = []
    for r in range(3):
        lines.append(" ".join("S" if (r, c) in pattern else "." for c in range(3)))
    return "\n".join(lines)


def apply_transform(pattern: Pattern, row_perm: tuple[int, int, int], col_perm: tuple[int, int, int], transpose: bool) -> Pattern:
    out: set[BlockPos] = set()
    for r, c in pattern:
        if transpose:
            r, c = c, r
        out.add((row_perm[r], col_perm[c]))
    return frozenset(out)


def orbit(pattern: Pattern) -> set[Pattern]:
    out: set[Pattern] = set()
    for row_perm in permutations(range(3)):
        for col_perm in permutations(range(3)):
            for transpose in (False, True):
                out.add(apply_transform(pattern, row_perm, col_perm, transpose))
    return out


def canonical_key(pattern: Pattern) -> tuple[BlockPos, ...]:
    return min(tuple(sorted(p)) for p in orbit(pattern))


def all_raw_5_special_patterns() -> list[Pattern]:
    cells = [(r, c) for r in range(3) for c in range(3)]
    out: list[Pattern] = []

    for comb in combinations(cells, 5):
        pattern = frozenset(comb)

        row_counts = [sum((r, c) in pattern for c in range(3)) for r in range(3)]
        col_counts = [sum((r, c) in pattern for r in range(3)) for c in range(3)]

        # どのブロック行・ブロック列にも特殊ブロック3個は置けない
        if max(row_counts) <= 2 and max(col_counts) <= 2:
            out.append(pattern)

    return out


def classify_patterns() -> list[Pattern]:
    raw = all_raw_5_special_patterns()

    rep_map: dict[tuple[BlockPos, ...], Pattern] = {}
    for p in raw:
        key = canonical_key(p)
        if key not in rep_map:
            rep_map[key] = p

    reps = [rep_map[k] for k in sorted(rep_map)]
    return reps


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--time-limit", type=float, default=60.0)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--log", action="store_true")
    args = parser.parse_args()

    raw = all_raw_5_special_patterns()
    reps = classify_patterns()

    print(f"必要条件を満たす生の5特殊パターン数: {len(raw)}")
    print(f"行列置換＋転置で割った代表元の数: {len(reps)}")
    print()

    for i, rep in enumerate(reps, start=1):
        print(f"=== 型 {i} ===")
        print(pattern_to_str(rep))
        print()
        solve_instance(
            special_positions=set(rep),
            time_limit=args.time_limit,
            num_workers=args.workers,
            log_search_progress=args.log,
        )
        print()
        print("-" * 60)
        print()


if __name__ == "__main__":
    main()