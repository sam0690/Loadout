"""Source-vocabulary to Loadout-vocabulary maps for free-exercise-db.

Everything here is a judgement about someone else's labels. Anything not covered goes
to review.csv rather than getting a guess — that file is the deliverable of 0.3, and
0.5's hand-authored edges are built on top of whatever survives review.
"""

from collections.abc import Collection

# free-exercise-db `category`. Everything else is a §3 non-goal: stretching, cardio,
# plyometrics, strongman and olympic weightlifting are not what this app programs.
KEEP_CATEGORIES = {"strength", "powerlifting"}

# free-exercise-db `primaryMuscles` -> D4. `shoulders` is absent on purpose: the source
# does not split the deltoid and we refuse to guess, so it is resolved from the movement
# pattern in normalize.py and sent to review when that fails.
MUSCLES = {
    "abdominals": "abs",
    "biceps": "biceps",
    "calves": "calves",
    "chest": "chest",
    "forearms": "forearms",
    "glutes": "glutes",
    "hamstrings": "hamstrings",
    "lats": "lats",
    "lower back": "spinal_erectors",
    "middle back": "upper_back",
    "quadriceps": "quads",
    "traps": "traps",
    "triceps": "triceps",
    # Hip abduction is glute medius, which D4 folds into glutes.
    "abductors": "glutes",
}
# In the source but with no D4 target. `adductors` and `neck` are real muscles we chose
# not to model; an exercise whose PRIMARY muscle is one of these has no home here.
UNMAPPED_MUSCLES = {"adductors", "neck"}

# Which deltoid head, once the pattern is known.
SHOULDER_BY_PATTERN = {
    "vertical_press": "front_delts",
    "shoulder_abduction": "side_delts",
    "horizontal_pull": "rear_delts",
    "horizontal_press": "front_delts",
}

# free-exercise-db `equipment` -> our slugs. Values are lists because a barbell movement
# needs plates too. `machine` and `cable` are resolved per-exercise in normalize.py.
EQUIPMENT = {
    "body only": [],
    "barbell": ["barbell", "plates"],
    "e-z curl bar": ["barbell", "plates"],
    "dumbbell": ["dumbbells"],
    "kettlebells": ["kettlebell"],
    "bands": ["resistance_bands"],
    "cable": ["cable_stack"],
}
# Grab-bag or missing source values. Not guessable, so they go to review.
UNMAPPED_EQUIPMENT = {"other", "medicine ball", "exercise ball", "foam roll", None}

# `machine` (67 rows) names no specific machine, so pick it from the movement pattern.
MACHINE_BY_PATTERN = {
    "horizontal_pull": "seated_row_machine",
    "vertical_pull": "lat_pulldown",
    "horizontal_press": "chest_press_machine",
    "knee_flexion": "leg_curl_machine",
    "knee_extension": "leg_extension_machine",
}

# Name keyword -> movement pattern, first match wins, so order matters: "leg press" must
# beat "press", and "calf press" must beat "leg press". The source has no pattern field
# at all, so this table is the single largest judgement call in the ingest.
PATTERN_RULES: list[tuple[tuple[str, ...], str]] = [
    # These two beat the generic "push-up" and "press" rules below, which would
    # otherwise claim the canonical bodyweight vertical presses for horizontal_press.
    # "pike push" rather than bare "pike", which would swallow the hanging ab variety.
    (("handstand", "pike push", "pike press"), "vertical_press"),
    (("calf raise", "calf press", "donkey calf", "toe raise"), "calf_raise"),
    (("leg extension", "knee extension"), "knee_extension"),
    (("leg curl", "hamstring curl", "nordic", "glute-ham", "glute ham"), "knee_flexion"),
    (("lateral raise", "side lateral", "side raise", "upright row"), "shoulder_abduction"),
    (("lunge", "split squat", "step-up", "step up"), "lunge"),
    (("pallof", "russian twist", "woodchop", "wood chop", "side plank",
      "side bridge", "oblique"), "core_anti_rotation"),
    (("plank", "ab roller", "ab wheel", "rollout", "crunch", "sit-up", "situp",
      "leg raise", "knee raise", "hollow", "dead bug", "v-up"), "core_anti_extension"),
    (("deadlift", "good morning", "hip thrust", "glute bridge", "swing",
      "back extension", "hyperextension", "pull-through", "romanian",
      "glute kickback"), "hinge"),
    (("squat", "leg press", "hack "), "squat"),
    (("pull-up", "pullup", "chin-up", "chinup", "pulldown", "pull down",
      "lat pull"), "vertical_pull"),
    (("row", "face pull", "rear delt", "reverse fly", "reverse flye"), "horizontal_pull"),
    (("bench press", "push-up", "pushup", "push up", "chest press", "fly", "flye",
      "pec deck", "dip", "floor press"), "horizontal_press"),
    (("overhead press", "shoulder press", "military press", "push press",
      "handstand", "arnold press", "landmine press"), "vertical_press"),
    (("pushdown", "push-down", "skullcrusher", "skull crusher",
      "triceps kickback", "tricep kickback",
      "triceps extension", "tricep extension", "overhead extension",
      "close-grip"), "elbow_extension"),
    (("curl",), "elbow_flexion"),
]

# free-exercise-db `level` -> a difficulty seed in the PRD's 1-10 scale. Coarse by
# construction: `level` is one field and difficulty is meant to be relative within a
# movement pattern. 0.5 corrects these by hand.
DIFFICULTY_BY_LEVEL = {"beginner": 3, "intermediate": 5, "expert": 8}

UNILATERAL_MARKERS = (
    "single-arm", "single arm", "one-arm", "one arm", "single-leg", "single leg",
    "one-leg", "one leg", "unilateral", "alternating", "bulgarian", "pistol",
    "concentration",
)

# The source names one piece of equipment per exercise, so a bench never appears
# alongside the barbell it is loaded with. Infer it from the name.
BENCH_MARKERS = ("bench press", "lying", "incline", "decline", "seated", "supine",
                 "chest supported", "chest-supported", "preacher")
INCLINE_MARKERS = ("incline", "decline", "preacher")


# The source's "body only" means "you lift your own bodyweight", NOT "no apparatus".
# A pull-up needs a bar; a dip needs something to dip on. Without this the catalog hands a
# user with an empty room six sets of chin-ups, and `pull_up_bar` ends up required by no
# exercise at all -- which is how it sat in the minimal_apartment archetype buying nothing.
#
# First match wins, so order matters: "bench dip" must beat the bare "dip" rule, exactly
# as "leg press" must beat "press" in PATTERN_RULES.
APPARATUS_RULES: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("bench dip", "chair dip", "tricep dip"), ("chair",)),
    # Elevating either end of a push-up needs something to elevate onto. Without this the
    # incline variants hold the bodyweight slots and the plain floor push-up -- the one
    # exercise a bare room is definitely capable of -- never reaches the catalog.
    (("incline push", "decline push", "feet elevated", "elevated push"), ("chair",)),
    (("pull-up", "pullup", "pull up", "chin-up", "chinup", "chin up",
      "muscle-up", "muscle up"), ("pull_up_bar",)),
    (("inverted row", "australian pull"), ("sturdy_table",)),
    (("dip",), ("dip_station",)),
]


def apparatus_for(name_lower: str) -> tuple[str, ...]:
    """The apparatus a movement needs regardless of what the source claims."""
    for keywords, required in APPARATUS_RULES:
        if any(k in name_lower for k in keywords):
            return required
    return ()


# Equipment that holds the body up but adds no load of its own, so an exercise using only
# these still progresses by difficulty_step rather than by weight (PRD §8): a bar does not
# make a pull-up loadable.
#
# resistance_bands is deliberately absent even though the seed gives it no increments.
# Whether bands are loadable is an open question in PRD §12, and answering it here would
# resolve it silently.
BODY_SUPPORT = frozenset({
    "bodyweight", "flat_bench", "adjustable_bench", "pull_up_bar",
    "suspension_trainer", "chair", "sturdy_table", "dip_station",
})


# A derived pattern and the source's own primary muscle have to agree. When they do not,
# one of the two is wrong and we cannot tell which — a hybrid the name rules mis-sorted
# ("Push Up to Side Plank"), or a source mislabel ("Cable Deadlifts", tagged quads).
# Either way it is a human's call, so it goes to review rather than into the catalog.
PATTERN_MUSCLES = {
    "horizontal_press": {"chest", "front_delts", "triceps"},
    "vertical_press": {"front_delts", "triceps", "chest"},
    "horizontal_pull": {"upper_back", "lats", "rear_delts", "biceps", "traps"},
    "vertical_pull": {"lats", "upper_back", "biceps"},
    "squat": {"quads", "glutes", "hamstrings", "spinal_erectors"},
    "hinge": {"hamstrings", "glutes", "spinal_erectors", "upper_back", "traps"},
    "lunge": {"quads", "glutes", "hamstrings"},
    "elbow_flexion": {"biceps", "forearms"},
    "elbow_extension": {"triceps"},
    "shoulder_abduction": {"side_delts", "front_delts", "rear_delts", "traps"},
    "knee_flexion": {"hamstrings", "glutes", "calves"},
    "knee_extension": {"quads"},
    "calf_raise": {"calves"},
    "core_anti_extension": {"abs", "spinal_erectors"},
    "core_anti_rotation": {"abs", "spinal_erectors"},
}

# Equipment tiers, used to build a downgrade chain rather than N copies of the simplest
# option. Selection spans these within each pattern: a pattern with only bodyweight rows
# has nothing to downgrade *from*, and one with only machines never reaches a terminal.
EQUIPMENT_TIERS: list[tuple[int, set[str]]] = [
    # Tier 1 is "apparatus that holds the body and adds no load". A chair and a table
    # belong here beside the pull-up bar: they are one step up from the bare floor, not
    # peers of a barbell, and tier() would otherwise sort them to 3 with the machines.
    (1, {"resistance_bands", "pull_up_bar", "suspension_trainer",
         "chair", "sturdy_table", "dip_station"}),
    (2, {"dumbbells", "kettlebell"}),
]
BENCHES = {"flat_bench", "adjustable_bench"}


def tier(equipment: Collection[str]) -> int:
    """0 bodyweight, 1 bands/bar, 2 dumbbell/kettlebell, 3 barbell, machine or cable."""
    items = set(equipment) - BENCHES
    if not items:
        return 0
    for rank, members in EQUIPMENT_TIERS:
        if items <= members:
            return rank
    return 3
