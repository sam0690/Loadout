"""Stage 1: pull the raw catalog and cache it. Re-running normalize must not re-fetch.

    uv run python -m ingest.fetch [--force]
"""

import sys
import urllib.request
from pathlib import Path

SOURCE = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "exercises.json"


def fetch(force: bool = False, dest: Path = RAW) -> Path:
    if dest.exists() and not force:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(SOURCE, timeout=60) as r:  # noqa: S310
        dest.write_bytes(r.read())
    return dest


def main() -> None:
    path = fetch(force="--force" in sys.argv)
    print(f"raw catalog at {path} ({path.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
