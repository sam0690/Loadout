"""Hand-authored catalog entries the source cannot supply.

free-exercise-db has no bodyweight calf raise, no sissy squat and no pike push-up — only
stretches with those words in the name — so seven movement patterns had no zero-equipment
terminal and a user with nothing got NoSubstituteFound for half the catalog (D12, D22).

These are authored, not ingested, so they live beside the pipeline rather than inside it.
"""

from pathlib import Path

import yaml

from ingest.normalize import Exercise

SEED = Path(__file__).resolve().parent.parent / "seeds" / "exercise_terminals.yaml"


def read_terminals(path: Path = SEED) -> list[Exercise]:
    entries = yaml.safe_load(path.read_text()) or []
    out = []
    for e in entries:
        notes = ["hand-authored terminal"]
        if e.get("weak"):
            notes.append(
                "weak: no genuine zero-equipment option exists for this pattern"
            )
        out.append(
            Exercise(
                slug=e["slug"],
                name=e["name"],
                movement_pattern=e["movement_pattern"],
                primary_muscles=e["primary_muscles"],
                secondary_muscles=e.get("secondary_muscles", []),
                equipment=[],
                difficulty=e["difficulty"],
                unilateral=e["unilateral"],
                # Nothing to add weight to: these progress by walking a difficulty_step
                # edge, which is the graph earning its keep a second time (PRD §8).
                loadable=False,
                source_id="",
                notes=notes,
            )
        )
    return out
