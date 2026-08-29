"""Acceptance for 0.3: every exercise is well-formed, ambiguity lands in review.csv."""

import json
from pathlib import Path

import pytest
import sqlalchemy as sa

from db import DATABASE_URL
from ingest import taxonomy as tx
from ingest.equipment import UnknownEquipment
from ingest.load import full_catalog, load
from ingest.normalize import Exercise, match_pattern, normalize_one, run, select
from schema import exercises


@pytest.fixture(scope="module")
def catalog() -> list[Exercise]:
    """Everything the loader converges on: ingested plus hand-authored terminals."""
    return full_catalog()


def test_every_exercise_has_a_pattern_and_a_primary_muscle(
    catalog: list[Exercise],
) -> None:
    for e in catalog:
        assert e.movement_pattern in tx.PATTERN_MUSCLES, e.name
        assert e.primary_muscles, e.name


def test_pattern_and_primary_muscle_never_disagree(catalog: list[Exercise]) -> None:
    """The gate that caught 'Glute Kickback' as elbow_extension."""
    for e in catalog:
        stray = set(e.primary_muscles) - tx.PATTERN_MUSCLES[e.movement_pattern]
        assert not stray, f"{e.name}: {stray} is not a {e.movement_pattern} muscle"


def test_every_movement_pattern_is_covered(catalog: list[Exercise]) -> None:
    missing = set(tx.PATTERN_MUSCLES) - {e.movement_pattern for e in catalog}
    assert not missing, f"no exercise for {missing}"


def test_ambiguous_rows_go_to_review_not_the_catalog() -> None:
    chosen, review = run()
    reasons = {r[2] for r in review}
    assert any("no movement pattern" in r for r in reasons)
    assert any("not mappable" in r for r in reasons)
    chosen_names = {e.name for e in chosen}
    assert not (chosen_names & {r[0] for r in review}), "a row cannot be both"


def test_a_source_mislabel_is_reviewed_rather_than_guessed() -> None:
    ex, why = normalize_one(
        {"name": "Cable Deadlifts", "category": "strength", "equipment": "cable",
         "primaryMuscles": ["quadriceps"], "level": "beginner", "id": "x"}
    )
    assert ex is None
    assert why is not None and "disagrees" in why


def test_unmodelled_muscles_are_reviewed() -> None:
    ex, why = normalize_one(
        {"name": "Barbell Squat", "category": "strength", "equipment": "barbell",
         "primaryMuscles": ["adductors"], "level": "beginner", "id": "x"}
    )
    assert ex is None
    assert why is not None and "adductors" in why


def test_specific_keywords_beat_general_ones() -> None:
    assert match_pattern("Glute Kickback") == "hinge"
    assert match_pattern("Handstand Push-Ups") == "vertical_press", "beats 'push-up'"
    assert match_pattern("Step-up with Knee Raise") == "lunge", "beats 'knee raise'"
    assert match_pattern("Hanging Pike") is None, "'pike push' must not catch this"
    assert match_pattern("Triceps Kickback") == "elbow_extension"
    assert match_pattern("Calf Press") == "calf_raise"
    assert match_pattern("Leg Press") == "squat"
    assert match_pattern("Leg Extension") == "knee_extension"


def test_selection_is_capped_per_pattern() -> None:
    many = [
        Exercise(f"s{i}", f"n{i}", "squat", ["quads"], [], [], 3, False, True)
        for i in range(50)
    ]
    assert len(select(many)) <= 8


def test_load_is_idempotent_and_resolves_equipment_through_aliases(
    catalog: list[Exercise],
) -> None:
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as c:
        load(c, catalog)
        first = c.execute(sa.select(exercises).order_by(exercises.c.slug)).all()
        load(c, catalog)
        assert c.execute(sa.select(exercises).order_by(exercises.c.slug)).all() == first


def test_load_rejects_an_equipment_slug_the_taxonomy_does_not_know() -> None:
    engine = sa.create_engine(DATABASE_URL)
    bogus = [
        Exercise("x", "X", "squat", ["quads"], [], ["ThighMaster 3000"], 3, False, True)
    ]
    with engine.begin() as c, pytest.raises(UnknownEquipment):
        load(c, bogus)


def test_review_file_is_written_with_a_header(tmp_path: Path) -> None:
    from ingest.normalize import REVIEW
    assert REVIEW.exists(), "run `uv run python -m ingest.normalize` first"
    assert REVIEW.read_text().splitlines()[0] == "name,equipment,reason"


def test_normalized_json_matches_what_was_loaded() -> None:
    """The ingested half stays at 80; terminals are authored separately (D22)."""
    from ingest.normalize import NORMALIZED
    on_disk = json.loads(NORMALIZED.read_text())
    assert len(on_disk) == 80
    assert len(full_catalog()) == 89


def test_a_row_dropped_from_the_selection_is_dropped_from_the_catalog(
    catalog: list[Exercise],
) -> None:
    """The equipment loader had this bug too; both loaders must converge, not append."""
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as c:
        load(c, catalog)
        load(c, catalog[:10])
        assert c.execute(
            sa.select(sa.func.count()).select_from(exercises)
        ).scalar_one() == 10
        load(c, catalog)
        assert c.execute(
            sa.select(sa.func.count()).select_from(exercises)
        ).scalar_one() == len(catalog)
    # Narrowing the catalog cascaded the dropped exercises' edges away. Restoring the
    # rows does not restore those, so put the graph back for whatever runs next.
    from ingest.edges import SEED as EDGE_SEED
    from ingest.edges import load_edges

    with engine.begin() as c:
        load_edges(c, EDGE_SEED)
