-- Load the substitution subgraph around one exercise, for engine/graph to traverse.
--
-- Called by the caller, never by the engine: the engine is pure and takes the loaded
-- graph as an argument (CLAUDE.md constraint 1). Bounded to depth 3 per PRD §7.
--
-- Params: :exercise_id, :max_depth
--
-- Returns every node reachable within :max_depth, plus the edges among them. The
-- movement-pattern filter is applied here as well as in the engine — the engine cannot
-- assume its input is well-formed, and the database should not ship rows it knows are
-- irrelevant.

WITH RECURSIVE origin AS (
    SELECT id, movement_pattern
    FROM exercises
    WHERE id = :exercise_id
),
reachable AS (
    -- Depth 0: the exercise being substituted.
    SELECT
        e.id,
        0 AS depth
    FROM exercises e
    JOIN origin o ON o.id = e.id

    UNION ALL

    -- Walk forward one edge at a time, never leaving the origin's movement pattern.
    -- UNION (not UNION ALL) at the outer level would not terminate a cycle on its own,
    -- so the depth bound is what guarantees termination; the catalog is a small DAG in
    -- practice but nothing in the schema forbids a cycle.
    SELECT
        edge.to_id AS id,
        r.depth + 1 AS depth
    FROM reachable r
    JOIN exercise_edges edge ON edge.from_id = r.id
    JOIN exercises target ON target.id = edge.to_id
    JOIN origin o ON o.movement_pattern = target.movement_pattern
    WHERE r.depth < :max_depth
),
nodes AS (
    SELECT DISTINCT ON (id) id, depth
    FROM reachable
    ORDER BY id, depth   -- shallowest wins, so depth is the true shortest-path distance
)
SELECT
    x.id,
    x.slug,
    x.movement_pattern,
    x.equipment,
    x.difficulty,
    n.depth,
    COALESCE(
        (
            SELECT json_agg(json_build_object(
                       'to_id', edge.to_id,
                       'edge_type', edge.edge_type,
                       'delta', edge.delta
                   ) ORDER BY edge.edge_type, edge.to_id)
            FROM exercise_edges edge
            WHERE edge.from_id = x.id
              AND edge.to_id IN (SELECT id FROM nodes)
        ),
        '[]'::json
    ) AS out_edges
FROM nodes n
JOIN exercises x ON x.id = n.id
ORDER BY n.depth, x.slug;
