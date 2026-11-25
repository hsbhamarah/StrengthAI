"""Retain workbooks inside the encrypted database."""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = depends_on = None

def upgrade():
    blob = "BYTEA" if op.get_bind().dialect.name == "postgresql" else "BLOB"
    op.execute(f"CREATE TABLE IF NOT EXISTS workbook_snapshots (import_id VARCHAR(36) PRIMARY KEY REFERENCES import_jobs(import_id), content {blob} NOT NULL)")

def downgrade():
    op.execute("DROP TABLE workbook_snapshots")
