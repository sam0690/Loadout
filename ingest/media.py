"""Stage 5: exercise photos and steps for the app, from the same public-domain source (D32).

    uv run python -m ingest.media

free-exercise-db ships two photos per exercise (start and end position) and numbered
steps. They are copied into the web app's public folder rather than hotlinked, so they
are served from our own origin and the service worker keeps them for a gym with no
signal. Files already on disk are not fetched again, like the raw catalog in fetch.py.
"""

import json
import urllib.request
from pathlib import Path
from typing import Any

from ingest.fetch import RAW
from ingest.load import full_catalog
from ingest.normalize import Exercise

IMAGES = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"
OUT = Path(__file__).resolve().parent.parent / "web" / "public" / "exercises"


def manifest(catalog: list[Exercise], raw: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """slug -> {source, frames, steps}. Exercises with no photos are absent, not empty.

    `source` is the free-exercise-db id the frames come from. `steps` is empty for a
    borrowed photo: the source's instructions describe its exercise, not ours.
    """
    by_id = {r["id"]: r for r in raw}
    out: dict[str, dict[str, Any]] = {}
    for ex in catalog:
        own = by_id.get(ex.source_id)
        source = own or by_id.get(ex.image_from)
        if source is None or not source.get("images"):
            continue
        out[ex.slug] = {
            "source": source["id"],
            "frames": [f"/exercises/{ex.slug}/{i}.jpg" for i in range(len(source["images"]))],
            "steps": own.get("instructions", []) if own else [],
        }
    return dict(sorted(out.items()))


def download(entries: dict[str, dict[str, Any]], raw: list[dict[str, Any]], dest: Path) -> int:
    by_id = {r["id"]: r for r in raw}
    fetched = 0
    for slug, entry in entries.items():
        for i, image in enumerate(by_id[entry["source"]]["images"]):
            target = dest / slug / f"{i}.jpg"
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(IMAGES + image, timeout=60) as r:  # noqa: S310
                target.write_bytes(r.read())
            fetched += 1
    return fetched


def main() -> None:
    raw = json.loads(RAW.read_text())
    entries = manifest(full_catalog(), raw)
    fetched = download(entries, raw, OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.json").write_text(json.dumps(entries, indent=1, ensure_ascii=False) + "\n")
    print(f"media for {len(entries)} exercises ({fetched} images fetched) -> {OUT}")


if __name__ == "__main__":
    main()
