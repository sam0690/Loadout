"""Run the whole pipeline: fetch (cached) -> normalize -> load.

    uv run python -m ingest

Each stage also runs on its own; see the module docstrings.
"""

from ingest import equipment, fetch, load, normalize


def main() -> None:
    fetch.main()
    equipment.main()
    normalize.main()
    load.main()


if __name__ == "__main__":
    main()
