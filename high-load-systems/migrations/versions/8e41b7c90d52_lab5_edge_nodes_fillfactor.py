"""Lab5 - make HOT updates possible on edge_nodes.

Lab 5 measured `pg_stat_user_tables` around a Scenario B run: of 17 609 updates to
`edge_nodes`, **0.0 % were HOT**, and the table carried 2 994 dead tuples while its row count
never changed. docs/bottlenecks.md #2 predicted exactly that - every heartbeat rewrites the row
*and* `ix_edge_nodes_status_last_heartbeat_at`, because two of the columns it mutates are in
that index.

A HOT (heap-only tuple) update writes the new row version on the same page as the old one and
skips the index write entirely. PostgreSQL can only do that when the page has free space, and
the default fillfactor of 100 leaves none - every update has to go to a new page, which means
a new index entry. Dropping the fillfactor reserves room on each page for the updated versions
of the rows already there, which is the whole point for a table that is updated constantly and
almost never grows.

70 rather than 90: this table is updated far more often than it is inserted into - one row per
edge node, rewritten on every heartbeat, forever - so trading 30 % of the page for a chance at
HOT is the right way round. The cost is a larger table on disk and slightly more pages per
sequential scan; the table has one row per node, so that cost is negligible here.

The aggressive autovacuum settings go with it. The default scale factor of 0.2 means autovacuum
waits until 20 % of the table is dead before running, and on a 12-row table that is two rows -
but on a fleet-sized table it is a long wait during which the dead versions that HOT cannot
reclaim keep accumulating. 0.02 keeps the page free space that HOT depends on actually free.

Verify the effect by re-running Scenario B and reading the same counter:

    docker exec cdn-control-plane-postgres-1 psql -U cdn -d cdn_control_plane \\
        -c "SELECT n_tup_upd, n_tup_hot_upd, n_dead_tup FROM pg_stat_user_tables
            WHERE relname = 'edge_nodes'"

Revision ID: 8e41b7c90d52
Revises: 2c3af01d0235
"""

from alembic import op

revision: str = "8e41b7c90d52"
down_revision: str | None = "2c3af01d0235"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE edge_nodes SET (fillfactor = 70)")
    op.execute(
        "ALTER TABLE edge_nodes SET ("
        "autovacuum_vacuum_scale_factor = 0.02, "
        "autovacuum_analyze_scale_factor = 0.02)"
    )
    # No VACUUM here: it cannot run inside a transaction block and Alembic wraps every
    # migration in one. It is not needed either - existing rows keep their current packing
    # until they are next rewritten, and on this table that is one heartbeat away. VACUUM FULL
    # would repack immediately but takes an ACCESS EXCLUSIVE lock, which is not something a
    # migration should do to a table sitting on the read path.


def downgrade() -> None:
    op.execute("ALTER TABLE edge_nodes RESET (fillfactor)")
    op.execute(
        "ALTER TABLE edge_nodes RESET ("
        "autovacuum_vacuum_scale_factor, autovacuum_analyze_scale_factor)"
    )
