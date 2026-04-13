"""initial_schema

Revision ID: 5e8f04ccc37e
Revises: 
Create Date: 2026-04-13 13:49:47.851601

Creates all 47 tables for the Polymarket Trader data model.
This is the complete Phase 2 schema from spec Section 25.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '5e8f04ccc37e'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables using model metadata."""
    from data.base import Base

    # Import all models to register them with Base.metadata
    import data  # noqa: F401

    # Create all tables
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Drop all tables in reverse dependency order."""
    from data.base import Base
    import data  # noqa: F401

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
