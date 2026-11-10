"""Join lease agreements and outbound-only maintenance histories.

Historical migrations remain unchanged; this revision joins the graph only.
Full lease-only rollback is TWO commands (see ops/staging-integration/README.md):
1. downgrade 20261102_0055 (unmerge only).
2. downgrade 20261009_0051@20261001_0047 (unwind ONLY maintenance 0048-0051).
Never use @base: it also selects the irreversible lease-data correction branch.
"""
revision = "20261110_0062"
down_revision = ("20261102_0055", "20261009_0051")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
