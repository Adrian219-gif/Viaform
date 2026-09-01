"""Explicitly export one successful runtime programme snapshot to tracked seed JSON."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.programme_cache import (  # noqa: E402
    ProgrammeCache,
    normalized_programme_identity,
    programme_cache_key,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export one runtime Requirements or Timeline snapshot to a tracked seed JSON."
    )
    parser.add_argument("--kind", choices=("requirements", "timeline"), required=True)
    parser.add_argument("--university", required=True)
    parser.add_argument("--programme", required=True)
    parser.add_argument("--official-program-url", required=True)
    parser.add_argument("--entry-year", type=int, required=True)
    parser.add_argument(
        "--entry-term",
        choices=("fall", "spring", "summer", "winter"),
        required=True,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    identity = normalized_programme_identity(
        university=args.university,
        programme=args.programme,
        official_program_url=args.official_program_url,
        intended_entry_year=args.entry_year,
        intended_entry_term=args.entry_term,
    )
    cache_key = programme_cache_key(identity)
    cache = ProgrammeCache(
        runtime_db=BACKEND_DIR / "data" / "runtime" / "programme_cache.sqlite",
        seed_dir=BACKEND_DIR / "data" / "seed" / "programme_cache",
    )
    output_path = cache.export_runtime_to_seed(args.kind, cache_key, identity)
    print(f"Exported {args.kind} seed: {output_path}")


if __name__ == "__main__":
    main()
