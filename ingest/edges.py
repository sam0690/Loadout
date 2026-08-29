"""Generate a starter edge set for review, and load it once it has been corrected.

    uv run python -m ingest.edges            # write seeds/exercise_edges.yaml
    uv run python -m ingest.edges --force    # overwrite a file already reviewed

Generation never overwrites an existing file without --force: the whole point is that a
human corrects it by hand, and silently regenerating would throw that work away. Loading
is a separate step and always reads the file on disk, never the generator.

Anything the generator is unsure about carries a `# ?` comment rather than being dropped
or silently resolved.
"""

import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
import yaml
from sqlalchemy.dialects.postgresql import insert

from db import DATABASE_URL
from ingest import taxonomy as tx
from schema import equipment, exercise_edges, exercises

SEED = Path(__file__).resolve().parent.parent / "seeds" / "exercise_edges.yaml"


@dataclass(frozen=True)
class Row:
    slug: str
    pattern: str
    equipment: tuple[str, ...]
    difficulty: int


@dataclass
class GeneratedEdge:
    from_slug: str
    to_slug: str
    edge_type: str
    delta: int
    doubts: list[str]


def read_catalog(conn: sa.Connection) -> tuple[list[Row], set[str]]:
    rows = [
        Row(r.slug, r.movement_pattern, tuple(sorted(r.equipment)), r.difficulty)
        for r in conn.execute(
            sa.select(
                exercises.c.slug,
                exercises.c.movement_pattern,
                exercises.c.equipment,
                exercises.c.difficulty,
            ).order_by(exercises.c.slug)
        )
    ]
    fixed = {
        r.slug
        for r in conn.execute(
            sa.select(equipment.c.slug).where(equipment.c.is_fixed_path.is_(True))
        )
    }
    return rows, fixed


def generate(rows: list[Row], fixed_path: set[str]) -> list[GeneratedEdge]:
    by_pattern: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_pattern[r.pattern].append(r)

    edges: list[GeneratedEdge] = []
    for pattern in sorted(by_pattern):
        members = by_pattern[pattern]
        tiers: dict[int, list[Row]] = defaultdict(list)
        for r in members:
            tiers[tx.tier(r.equipment)].append(r)
        for t in tiers:
            tiers[t].sort(key=lambda r: (r.difficulty, r.slug))

        # Equipment downgrade: every node reaches the tier below it, so each pattern is a
        # chain from most-equipped down to whatever terminal it has.
        for high in sorted(tiers, reverse=True):
            below = next((t for t in sorted(tiers, reverse=True) if t < high), None)
            if below is None:
                continue
            for a in tiers[high]:
                for b in tiers[below]:
                    doubts = []
                    crosses = set(a.equipment) & fixed_path and not (
                        set(b.equipment) & fixed_path
                    )
                    if crosses:
                        doubts.append(
                            "crosses is_fixed_path: a machine and a free weight are not "
                            "the same strength, so D15 seeds rather than carries"
                        )
                    if b.difficulty >= a.difficulty:
                        doubts.append(
                            f"downgrade is not easier (d{a.difficulty} -> "
                            f"d{b.difficulty}); difficulty is seeded from the source's "
                            "`level` and is coarse"
                        )
                    edges.append(
                        GeneratedEdge(
                            a.slug, b.slug, "equipment_downgrade",
                            b.difficulty - a.difficulty, doubts,
                        )
                    )

        # Difficulty step: same equipment, adjacent difficulty, both directions. This is
        # how a non-loadable exercise progresses (PRD §8).
        same_kit: dict[tuple[str, ...], list[Row]] = defaultdict(list)
        for r in members:
            same_kit[r.equipment].append(r)
        for group in same_kit.values():
            ordered = sorted(group, key=lambda r: (r.difficulty, r.slug))
            for a, b in zip(ordered, ordered[1:], strict=False):
                if a.difficulty == b.difficulty:
                    continue
                step = b.difficulty - a.difficulty
                edges.append(
                    GeneratedEdge(a.slug, b.slug, "difficulty_step", step, [])
                )
                edges.append(
                    GeneratedEdge(b.slug, a.slug, "difficulty_step", -step, [])
                )

        # Lateral equivalent: same difficulty, different equipment. Zero delta by
        # definition (D6), which the database also enforces.
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                if a.difficulty != b.difficulty:
                    continue
                if tx.tier(a.equipment) != tx.tier(b.equipment):
                    continue
                doubt = [
                    "equal difficulty may only mean both inherited the same `level`; "
                    "these are the edges most worth checking by hand"
                ]
                if a.equipment == b.equipment:
                    doubt.append(
                        "same equipment, so PRD §7's definition of lateral_equivalent "
                        "(different equipment) does not strictly cover this. Generated "
                        "because without it these nodes have no edges at all. Delete it, "
                        "or widen the definition -- but decide, do not leave it"
                    )
                edges.append(GeneratedEdge(a.slug, b.slug, "lateral_equivalent", 0, list(doubt)))
                edges.append(GeneratedEdge(b.slug, a.slug, "lateral_equivalent", 0, list(doubt)))

    edges.sort(key=lambda e: (e.from_slug, e.edge_type, e.to_slug))
    return edges


def render(edges: list[GeneratedEdge], rows: list[Row], gaps: list[str]) -> str:
    out = [
        "# Substitution graph edges. GENERATED, then corrected by hand.",
        "#",
        "#   uv run python -m ingest.edges --force   # regenerate, discarding corrections",
        "#   uv run python -m ingest.edges --load    # load this file as it stands",
        "#",
        "# delta is difficulty(to) - difficulty(from), signed; lateral edges are 0 by",
        "# definition (D6) and the database rejects anything else.",
        "#",
        "# Lines marked `# ?` are the generator's doubts. They are the point of this file:",
        "# correct or delete them rather than trusting them.",
        "#",
        f"# {len(edges)} edges over {len(rows)} exercises.",
    ]
    if gaps:
        out += [
            "#",
            "# PATTERNS WITH NO ZERO-EQUIPMENT TERMINAL (D12). The catalog has no",
            "# bodyweight option for these, so a user with no equipment cannot be given",
            "# one. Hand-authoring a terminal for each is the fix:",
        ] + [f"#   - {g}" for g in gaps]
    out.append("")

    current = None
    for e in edges:
        if e.from_slug != current:
            current = e.from_slug
            out.append(f"\n# --- from {current}")
        out.append(f"- from: {e.from_slug}")
        out.append(f"  to: {e.to_slug}")
        out.append(f"  type: {e.edge_type}")
        out.append(f"  delta: {e.delta}")
        for d in e.doubts:
            out.append(f"  # ? {d}")
    return "\n".join(out) + "\n"


def find_gaps(rows: list[Row]) -> list[str]:
    by_pattern: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_pattern[r.pattern].append(r)
    return [
        p for p in sorted(by_pattern) if not any(not r.equipment for r in by_pattern[p])
    ]


def find_orphans(
    rows: list[Row], edges: list[GeneratedEdge]
) -> tuple[list[str], list[str]]:
    """Returns (isolated, source_only).

    Isolated means no edges at all, which is always a defect. Source-only means the node
    has outgoing edges but no incoming one, which is what the most-equipped exercise in a
    pattern looks like: there is no `equipment_upgrade` edge type, and nothing ever needs
    to substitute *into* the hardest option. Expected, not broken.
    """
    incoming = {e.to_slug for e in edges}
    outgoing = {e.from_slug for e in edges}
    isolated = sorted(r.slug for r in rows if r.slug not in incoming | outgoing)
    source_only = sorted(
        r.slug for r in rows if r.slug in outgoing and r.slug not in incoming
    )
    return isolated, source_only


def load_edges(conn: sa.Connection, path: Path = SEED) -> int:
    parsed = yaml.safe_load(path.read_text()) or []
    ids: dict[str, uuid.UUID] = {
        r.slug: r.id
        for r in conn.execute(sa.select(exercises.c.slug, exercises.c.id))
    }
    conn.execute(sa.delete(exercise_edges))
    for e in parsed:
        missing = {e["from"], e["to"]} - ids.keys()
        if missing:
            raise KeyError(f"edge references an exercise not in the catalog: {missing}")
        stmt = insert(exercise_edges).values(
            from_id=ids[e["from"]], to_id=ids[e["to"]],
            edge_type=e["type"], delta=e["delta"],
        )
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["from_id", "to_id", "edge_type"],
                set_={"delta": stmt.excluded.delta},
            )
        )
    return len(parsed)


def main() -> None:
    engine = sa.create_engine(DATABASE_URL)
    if "--load" in sys.argv:
        with engine.begin() as conn:
            print(f"loaded {load_edges(conn)} edges from {SEED.name}")
        return

    if SEED.exists() and "--force" not in sys.argv:
        raise SystemExit(
            f"{SEED} already exists and may contain hand corrections. "
            "Pass --force to regenerate, or --load to load it as it stands."
        )
    with engine.connect() as conn:
        rows, fixed = read_catalog(conn)
    edges = generate(rows, fixed)
    gaps = find_gaps(rows)
    SEED.write_text(render(edges, rows, gaps))
    isolated, source_only = find_orphans(rows, edges)
    print(f"{len(edges)} edges over {len(rows)} exercises -> {SEED.name}")
    print(f"isolated (no edges at all, always a defect): {isolated or 'none'}")
    print(f"source-only (top of a chain, expected): {len(source_only)}")
    print(f"patterns with no zero-equipment terminal: {gaps or 'none'}")


if __name__ == "__main__":
    main()
