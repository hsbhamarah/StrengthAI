"""Client portal accounts, templates, assignments, and revision history."""
from alembic import op
from strengthos.db import Base

revision = "0003"
down_revision = "0002"
branch_labels = depends_on = None

TABLES = ["accounts", "auth_sessions", "client_invites", "program_templates", "template_imports", "program_versions",
          "program_assignments", "actual_revisions", "recovery_checkins", "recovery_revisions", "audit_events"]


def upgrade():
    bind = op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind=bind)


def downgrade():
    bind = op.get_bind()
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(bind=bind)
