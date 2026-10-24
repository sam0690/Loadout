"""The media manifest: which exercises get photos and steps, and from where (D32)."""

from typing import Any

from ingest.media import manifest
from ingest.normalize import Exercise


def exercise(slug: str, source_id: str = "", image_from: str = "") -> Exercise:
    return Exercise(
        slug=slug,
        name=slug,
        movement_pattern="squat",
        primary_muscles=["quads"],
        secondary_muscles=[],
        equipment=[],
        difficulty=1,
        unilateral=False,
        loadable=False,
        source_id=source_id,
        image_from=image_from,
    )


RAW: list[dict[str, Any]] = [
    {"id": "Goblet_Squat", "images": ["Goblet_Squat/0.jpg", "Goblet_Squat/1.jpg"],
     "instructions": ["Hold the bell.", "Sit down."]},
    {"id": "Walking_Lunge", "images": ["Walking_Lunge/0.jpg", "Walking_Lunge/1.jpg"],
     "instructions": ["Step forward."]},
    {"id": "No_Pictures", "images": [], "instructions": ["Something."]},
]


def test_a_sourced_exercise_gets_its_frames_and_steps() -> None:
    got = manifest([exercise("goblet_squat", source_id="Goblet_Squat")], RAW)
    assert got == {
        "goblet_squat": {
            "source": "Goblet_Squat",
            "frames": ["/exercises/goblet_squat/0.jpg", "/exercises/goblet_squat/1.jpg"],
            "steps": ["Hold the bell.", "Sit down."],
        }
    }


def test_a_borrowed_photo_brings_no_steps() -> None:
    got = manifest([exercise("bodyweight_lunge", image_from="Walking_Lunge")], RAW)
    assert got["bodyweight_lunge"]["source"] == "Walking_Lunge"
    assert got["bodyweight_lunge"]["steps"] == []


def test_exercises_without_photos_are_absent_rather_than_empty() -> None:
    got = manifest([exercise("pike_push_up"), exercise("odd", source_id="No_Pictures")], RAW)
    assert got == {}


def test_the_real_catalog_has_media_for_every_sourced_exercise() -> None:
    import json

    from ingest.fetch import RAW as RAW_PATH
    from ingest.load import full_catalog

    catalog = full_catalog()
    got = manifest(catalog, json.loads(RAW_PATH.read_text()))
    sourced = [e.slug for e in catalog if e.source_id]
    assert all(len(got[s]["frames"]) == 2 and got[s]["steps"] for s in sourced)
    assert list(got) == sorted(got), "sorted, so a re-run is a stable diff"
