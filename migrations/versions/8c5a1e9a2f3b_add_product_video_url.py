"""add product.video_url

Revision ID: 8c5a1e9a2f3b
Revises: 1b2c3d4e5f6a
Create Date: 2025-11-09
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '8c5a1e9a2f3b'
down_revision = '1b2c3d4e5f6a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('product') as batch_op:
        batch_op.add_column(sa.Column('video_url', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('product') as batch_op:
        batch_op.drop_column('video_url')


