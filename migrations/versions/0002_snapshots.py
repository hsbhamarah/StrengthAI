"""Retain workbooks inside the encrypted database."""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = depends_on = None

def upgrade():
    op.execute("CREATE TABLE IF NOT EXISTS workbook_snapshots (import_id TEXT PRIMARY KEY REFERENCES import_jobs(import_id), content BLOB NOT NULL)")

def downgrade():
    op.execute("DROP TABLE workbook_snapshots")
