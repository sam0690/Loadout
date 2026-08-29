"""Stage 2: source vocabulary -> ours. Ambiguity goes to review.csv, never to a guess.

    uv run python -m ingest.normalize

Reads the cached raw file, writes data/normalized.json and review.csv. Touches no
database except to resolve equipment aliases (0.2), which is the one lookup that has to
go through the alias table rather than a local map.
"""

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from ingest import taxonomy as tx
from ingest.fetch import RAW

ROOT = Path(__file__).resolve().parent.parent
NORMALIZED = ROOT / "data" / "normalized.json"
REVIEW = ROOT / "review.csv"

# Enough to cover every pattern with alternatives, without importing 600 rows we would
# never hand-check. PRD §7: 80 well-modeled exercises, not 800 badly-tagged ones.
TARGET = 80
PER_PATTERN_CAP = 8


@dataclass
class Exercise:
    slug: str
    name: str
    movement_pattern: str
    primary_muscles: list[str]
    secondary_muscles: list[str]
    equipment: list[str]
    difficulty: int
    unilateral: bool
    loadable: bool
    source_id: str = ""
    notes: list[str] = field(default_factory=list)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def match_pattern(name: str) -> str | None:
    low = name.lower()
    for keywords, pattern in tx.PATTERN_RULES:
        if any(k in low for k in keywords):
            return pattern
    return None


def resolve_muscles(raw: list[str], pattern: str) -> tuple[list[str], str | None]:
    """Map source muscles to D4. Returns (muscles, reason_to_review)."""
    out: list[str] = []
    for m in raw:
        if m in tx.UNMAPPED_MUSCLES:
            return [], f"muscle {m!r} has no D4 equivalent"
        if m == "shoulders":
            head = tx.SHOULDER_BY_PATTERN.get(pattern)
            if head is None:
                return [], f"'shoulders' is ambiguous for pattern {pattern}"
            out.append(head)
            continue
        mapped = tx.MUSCLES.get(m)
        if mapped is None:
            return [], f"unknown source muscle {m!r}"
        out.append(mapped)
    return list(dict.fromkeys(out)), None


def resolve_equipment(raw: str | None, name: str, pattern: str) -> tuple[list[str], str | None]:
    low = name.lower()
    if raw in tx.UNMAPPED_EQUIPMENT:
        return [], f"equipment {raw!r} is not mappable"
    if raw == "machine":
        machine = tx.MACHINE_BY_PATTERN.get(pattern)
        if machine is None:
            return [], f"'machine' names no specific machine for pattern {pattern}"
        return [machine], None
    slugs = list(tx.EQUIPMENT.get(raw or "", []))
    if raw not in tx.EQUIPMENT:
        return [], f"unknown source equipment {raw!r}"
    if any(b in low for b in tx.BENCH_MARKERS) and slugs:
        slugs.append(
            "adjustable_bench" if any(i in low for i in tx.INCLINE_MARKERS) else "flat_bench"
        )
    return slugs, None


def normalize_one(row: dict[str, Any]) -> tuple[Exercise | None, str | None]:
    name = row["name"]
    pattern = match_pattern(name)
    if pattern is None:
        return None, "no movement pattern matched the name"

    primary, why = resolve_muscles(row.get("primaryMuscles", []), pattern)
    if why:
        return None, why
    if not primary:
        return None, "no primary muscles in source"
    stray = set(primary) - tx.PATTERN_MUSCLES[pattern]
    if stray:
        return None, (
            f"pattern {pattern} disagrees with source primary muscle "
            f"{sorted(stray)} — one of the two is wrong"
        )
    secondary, _ = resolve_muscles(row.get("secondaryMuscles", []), pattern)

    equipment, why = resolve_equipment(row.get("equipment"), name, pattern)
    if why:
        return None, why

    low = name.lower()
    return Exercise(
        slug=slugify(name),
        name=name,
        movement_pattern=pattern,
        primary_muscles=primary,
        secondary_muscles=[m for m in secondary if m not in primary],
        equipment=equipment,
        difficulty=tx.DIFFICULTY_BY_LEVEL.get(row.get("level", ""), 5),
        unilateral=any(u in low for u in tx.UNILATERAL_MARKERS),
        # Bodyweight-only movements progress by difficulty_step, not by load (PRD §8).
        loadable=bool(equipment) and equipment != ["flat_bench"],
        source_id=row.get("id", ""),
    ), None


def dedupe(
    rows: list[Exercise], threshold: float = 0.85
) -> tuple[list[Exercise], list[tuple[Exercise, str]]]:
    """Collapse near-identical names within the same (pattern, equipment)."""
    kept: list[Exercise] = []
    dropped: list[tuple[Exercise, str]] = []
    for ex in sorted(rows, key=lambda e: (e.movement_pattern, e.name)):
        key = (ex.movement_pattern, tuple(sorted(ex.equipment)))
        twin = next(
            (
                k for k in kept
                if (k.movement_pattern, tuple(sorted(k.equipment))) == key
                and SequenceMatcher(None, k.name.lower(), ex.name.lower()).ratio() >= threshold
            ),
            None,
        )
        if twin is not None:
            dropped.append((ex, f"near-duplicate of {twin.slug!r}"))
        else:
            kept.append(ex)
    return kept, dropped


def select(rows: list[Exercise]) -> list[Exercise]:
    """Cap per pattern, simplest equipment first, so every pattern reaches bodyweight."""
    by_pattern: dict[str, list[Exercise]] = {}
    for ex in sorted(rows, key=lambda e: (len(e.equipment), e.difficulty, e.name)):
        by_pattern.setdefault(e_p := ex.movement_pattern, [])
        if len(by_pattern[e_p]) < PER_PATTERN_CAP:
            by_pattern[e_p].append(ex)
    # Round-robin across patterns so a cap cut never starves one of them.
    out: list[Exercise] = []
    rank = 0
    while len(out) < TARGET and any(len(v) > rank for v in by_pattern.values()):
        for pattern in sorted(by_pattern):
            if len(by_pattern[pattern]) > rank and len(out) < TARGET:
                out.append(by_pattern[pattern][rank])
        rank += 1
    return out


def run(raw_path: Path = RAW) -> tuple[list[Exercise], list[tuple[str, str, str]]]:
    source: list[dict[str, Any]] = json.loads(raw_path.read_text())
    review: list[tuple[str, str, str]] = []
    accepted: list[Exercise] = []

    for row in source:
        if row.get("category") not in tx.KEEP_CATEGORIES:
            continue
        ex, why = normalize_one(row)
        if ex is None:
            review.append((row["name"], str(row.get("equipment")), why or "unknown"))
        else:
            accepted.append(ex)

    kept, dropped = dedupe(accepted)
    review.extend((e.name, ",".join(e.equipment), why) for e, why in dropped)
    chosen = select(kept)
    chosen_slugs = {e.slug for e in chosen}
    review.extend(
        (e.name, ",".join(e.equipment), "normalized cleanly but over the per-pattern cap")
        for e in kept
        if e.slug not in chosen_slugs
    )
    return chosen, review


def main() -> None:
    chosen, review = run()
    NORMALIZED.parent.mkdir(parents=True, exist_ok=True)
    NORMALIZED.write_text(json.dumps([asdict(e) for e in chosen], indent=2))
    with REVIEW.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "equipment", "reason"])
        w.writerows(review)
    patterns = {e.movement_pattern for e in chosen}
    print(f"{len(chosen)} exercises across {len(patterns)} patterns -> {NORMALIZED.name}")
    print(f"{len(review)} rows need a human -> {REVIEW.name}")


if __name__ == "__main__":
    main()
