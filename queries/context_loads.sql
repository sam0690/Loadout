-- Resolve one training context to the loads each piece of its equipment can express.
--
-- Called by the caller, never by the engine (CLAUDE.md constraint 1). The engine's
-- expressible_loads() takes this output and composes it per exercise.
--
-- Params: :training_context_id
--
-- Applies D10's merge -- (archetype preset | equipment_added) - equipment_removed,
-- removal last -- and D21's override, where a training_context_loads row wins over the
-- catalog default and its absence means the default is fine.

WITH ctx AS (
    SELECT id, archetype_id, equipment_added, equipment_removed
    FROM training_contexts
    WHERE id = :training_context_id
),
resolved AS (
    SELECT DISTINCT eid AS equipment_id
    FROM ctx
    CROSS JOIN LATERAL unnest(
        COALESCE(
            (SELECT a.equipment_ids FROM gym_archetypes a WHERE a.id = ctx.archetype_id),
            ARRAY[]::uuid[]
        ) || ctx.equipment_added
    ) AS eid
    WHERE NOT (eid = ANY (ctx.equipment_removed))
)
SELECT
    e.slug,
    e.class,
    e.is_fixed_path,
    -- D21: the override wins, its absence means the catalog default stands. COALESCE is
    -- wrong for a column where NULL is meaningful, so test the row's presence instead.
    CASE
        WHEN l.training_context_id IS NOT NULL AND l.load_increments IS NOT NULL
            THEN l.load_increments
        ELSE e.load_increments
    END AS load_increments,
    l.bar_weight
FROM resolved r
JOIN equipment e ON e.id = r.equipment_id
LEFT JOIN training_context_loads l
       ON l.equipment_id = r.equipment_id
      AND l.training_context_id = :training_context_id
ORDER BY e.slug;
