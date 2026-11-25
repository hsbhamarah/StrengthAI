"""Initial canonical schema.

Revision ID: 0001
Revises:
"""
from alembic import op
from strengthos.db import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    names = {"athletes", "training_blocks", "training_weeks", "sessions", "exercises", "exercise_prescriptions", "prescribed_sets", "actual_sets", "data_sources", "mapping_profiles", "import_jobs", "source_records", "record_revisions", "job_queue"}
    Base.metadata.create_all(bind=op.get_bind(), tables=[Base.metadata.tables[name] for name in names])

def downgrade():
    names = {"athletes", "training_blocks", "training_weeks", "sessions", "exercises", "exercise_prescriptions", "prescribed_sets", "actual_sets", "data_sources", "mapping_profiles", "import_jobs", "source_records", "record_revisions", "job_queue"}
    Base.metadata.drop_all(bind=op.get_bind(), tables=[Base.metadata.tables[name] for name in names])
