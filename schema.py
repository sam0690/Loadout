"""Phase 0 catalog tables. Table definitions only — no ORM models, no queries.

This is the live schema and alembic's autogenerate target. Migrations under
migrations/versions/ are frozen snapshots and deliberately repeat these definitions;
tests/test_migrations.py asserts the two have not drifted.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

metadata = sa.MetaData()

# D3. Stored as text + CHECK rather than a Postgres enum: adding a value to an enum in
# a migration is painful and we will add patterns.
MOVEMENT_PATTERNS = (
    "horizontal_press", "vertical_press", "horizontal_pull", "vertical_pull",
    "squat", "hinge", "lunge",
    "elbow_flexion", "elbow_extension", "shoulder_abduction",
    "knee_flexion", "knee_extension", "calf_raise",
    "core_anti_extension", "core_anti_rotation",
)

EQUIPMENT_CLASSES = ("free_weight", "machine", "bodyweight", "band", "bench", "bar")

EDGE_TYPES = ("equipment_downgrade", "difficulty_step", "lateral_equivalent")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


def _subset(col: str, values: tuple[str, ...]) -> str:
    return f"{col} <@ ARRAY[{', '.join(repr(v) for v in values)}]::text[]"


muscle_groups = sa.Table(
    "muscle_groups", metadata,
    sa.Column("slug", sa.Text, primary_key=True),
    sa.Column("mev", sa.SmallInteger, nullable=False),
    sa.Column("mav", sa.SmallInteger, nullable=False),
    sa.Column("mrv", sa.SmallInteger, nullable=False),
    sa.CheckConstraint("mev <= mav AND mav <= mrv", name="ck_muscle_groups_ordered"),
)

equipment = sa.Table(
    "equipment", metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("slug", sa.Text, nullable=False, unique=True),
    sa.Column("class", sa.Text, nullable=False),
    sa.Column("movement_patterns", ARRAY(sa.Text), nullable=False),
    sa.Column("is_fixed_path", sa.Boolean, nullable=False),
    # D17. NULL = derived (barbell: bar weight + context's plates, computed at 1.1).
    # {} = genuinely not loadable. Populated = an enumerated rack.
    sa.Column("load_increments", ARRAY(sa.Numeric), nullable=True),
    sa.CheckConstraint(_in("class", EQUIPMENT_CLASSES), name="ck_equipment_class"),
    sa.CheckConstraint(
        _subset("movement_patterns", MOVEMENT_PATTERNS), name="ck_equipment_patterns"
    ),
)

equipment_aliases = sa.Table(
    "equipment_aliases", metadata,
    sa.Column(
        "equipment_id", UUID(as_uuid=True),
        sa.ForeignKey("equipment.id", ondelete="CASCADE"), primary_key=True,
    ),
    sa.Column("alias", sa.Text, primary_key=True),
    sa.Column("source", sa.Text, nullable=False),
    # Ingest resolves a brand name to a canonical row on every row it reads (0.2, 0.3).
    # Unique so two canonical rows cannot both claim "Hammer Strength Iso-Lateral Row".
    sa.Index("uq_equipment_aliases_lower", sa.text("lower(alias)"), unique=True),
)

exercises = sa.Table(
    "exercises", metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("slug", sa.Text, nullable=False, unique=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("movement_pattern", sa.Text, nullable=False),
    sa.Column("primary_muscles", ARRAY(sa.Text), nullable=False),
    sa.Column("secondary_muscles", ARRAY(sa.Text), nullable=False),
    # D1. Canonical equipment.slug values, never free text. Empty = bodyweight.
    # Not FK-able: Postgres cannot foreign-key array elements, so the loader validates
    # and raises on an unknown slug.
    sa.Column("equipment", ARRAY(sa.Text), nullable=False),
    sa.Column("difficulty", sa.SmallInteger, nullable=False),
    sa.Column("unilateral", sa.Boolean, nullable=False),
    sa.Column("loadable", sa.Boolean, nullable=False),
    sa.CheckConstraint(
        _in("movement_pattern", MOVEMENT_PATTERNS), name="ck_exercises_pattern"
    ),
    sa.CheckConstraint("difficulty BETWEEN 1 AND 10", name="ck_exercises_difficulty"),
    # 0.3 acceptance: every exercise has non-empty primary_muscles.
    sa.CheckConstraint(
        "cardinality(primary_muscles) > 0", name="ck_exercises_has_primary_muscle"
    ),
    # Traversal filters to a single movement pattern on every hop.
    sa.Index("ix_exercises_movement_pattern", "movement_pattern"),
    # equipment <@ available — the equipment-subset invariant, checked per candidate.
    sa.Index("ix_exercises_equipment", "equipment", postgresql_using="gin"),
    # Weekly hard-set counting per muscle group (1.3).
    sa.Index("ix_exercises_primary_muscles", "primary_muscles", postgresql_using="gin"),
)

exercise_edges = sa.Table(
    "exercise_edges", metadata,
    sa.Column(
        "from_id", UUID(as_uuid=True),
        sa.ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True,
    ),
    sa.Column(
        "to_id", UUID(as_uuid=True),
        sa.ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True,
    ),
    sa.Column("edge_type", sa.Text, primary_key=True),
    # D6. difficulty(to) - difficulty(from), signed.
    sa.Column("delta", sa.SmallInteger, nullable=False),
    sa.CheckConstraint(_in("edge_type", EDGE_TYPES), name="ck_edges_type"),
    # D6 defines lateral_equivalent as zero-delta by definition, so refuse anything else.
    sa.CheckConstraint(
        "edge_type <> 'lateral_equivalent' OR delta = 0", name="ck_edges_lateral_zero"
    ),
    sa.CheckConstraint("from_id <> to_id", name="ck_edges_no_self_loop"),
    # Reverse reachability: 0.5's "every exercise reachable from at least one other
    # node, no orphans". Forward traversal is served by the PK's from_id prefix.
    sa.Index("ix_exercise_edges_to_id", "to_id"),
)

gym_archetypes = sa.Table(
    "gym_archetypes", metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("slug", sa.Text, nullable=False, unique=True),
    sa.Column("name", sa.Text, nullable=False),
    # Not FK-able (array). Loader validates against equipment.id.
    sa.Column("equipment_ids", ARRAY(UUID(as_uuid=True)), nullable=False),
)

training_contexts = sa.Table(
    "training_contexts", metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    # D2. No FK until the users table lands with auth in Phase 2.
    sa.Column("user_id", UUID(as_uuid=True), nullable=False),
    sa.Column("label", sa.Text, nullable=False),
    sa.Column(
        "archetype_id", UUID(as_uuid=True),
        sa.ForeignKey("gym_archetypes.id", ondelete="SET NULL"), nullable=True,
    ),
    # D10. resolved = (preset | added) - removed, removal last.
    sa.Column("equipment_added", ARRAY(UUID(as_uuid=True)), nullable=False),
    sa.Column("equipment_removed", ARRAY(UUID(as_uuid=True)), nullable=False),
    sa.Column("is_default", sa.Boolean, nullable=False),
    # Load a user's contexts at session start.
    sa.Index("ix_training_contexts_user_id", "user_id"),
)

training_context_loads = sa.Table(
    "training_context_loads", metadata,
    sa.Column(
        "training_context_id", UUID(as_uuid=True),
        sa.ForeignKey("training_contexts.id", ondelete="CASCADE"), primary_key=True,
    ),
    sa.Column(
        "equipment_id", UUID(as_uuid=True),
        sa.ForeignKey("equipment.id", ondelete="CASCADE"), primary_key=True,
    ),
    # D21. Sparse: a row exists only where the context differs from the catalog. Null
    # here means "the catalog default is fine", not "not loadable".
    sa.Column("load_increments", ARRAY(sa.Numeric), nullable=True),
    # Only meaningful for a bar. 20kg men's, 15kg women's, 7kg aluminium.
    sa.Column("bar_weight", sa.Numeric, nullable=True),
    sa.CheckConstraint(
        "load_increments IS NOT NULL OR bar_weight IS NOT NULL",
        name="ck_context_loads_says_something",
    ),
)

# --- Events: append-only, the source of truth (CLAUDE.md constraint 2) ------------

EVENT_TYPES = (
    "set_logged", "exercise_swapped", "workout_completed", "workout_abandoned",
    "feedback_submitted",
)

events = sa.Table(
    "events", metadata,
    # CLIENT-generated, and the idempotency key (constraint 3). The server never assigns
    # one, so a retry is free.
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("user_id", UUID(as_uuid=True), nullable=False),
    sa.Column("type", sa.Text, nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    # Constraint 6: UTC plus the user's IANA zone, never naive local time. "Did I train
    # today" is computed in their zone (D14).
    sa.Column("client_ts", sa.DateTime(timezone=True), nullable=False),
    sa.Column("server_ts", sa.DateTime(timezone=True), nullable=False,
              server_default=sa.func.now()),
    sa.Column("user_tz", sa.Text, nullable=False),
    sa.CheckConstraint(_in("type", EVENT_TYPES), name="ck_events_type"),
    # Replay walks the log in order, per user.
    sa.Index("ix_events_user_client_ts", "user_id", "client_ts"),
)

# --- Projections: derived, rebuildable, never patched ----------------------------

exercise_state = sa.Table(
    "exercise_state", metadata,
    sa.Column("user_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "exercise_id", UUID(as_uuid=True),
        sa.ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True,
    ),
    sa.Column("current_load", sa.Numeric, nullable=True),
    sa.Column("current_reps", sa.SmallInteger, nullable=True),
    sa.Column("e1rm", sa.Numeric, nullable=True),
    sa.Column("consecutive_successes", sa.SmallInteger, nullable=False, server_default="0"),
    sa.Column("consecutive_failures", sa.SmallInteger, nullable=False, server_default="0"),
    # D15: seeded across a graph edge, never trained against yet.
    sa.Column("is_estimated", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("last_performed_at", sa.DateTime(timezone=True), nullable=True),
)
