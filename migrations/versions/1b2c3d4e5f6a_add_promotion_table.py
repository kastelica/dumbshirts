"""add promotion table

Revision ID: 1b2c3d4e5f6a
Revises: 08fea449a44a
Create Date: 2025-10-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1b2c3d4e5f6a'
down_revision = '08fea449a44a'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if 'promotion' not in tables:
        op.create_table(
            'promotion',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('promotion_id', sa.String(length=80), nullable=False),
            sa.Column('long_title', sa.String(length=255), nullable=True),
            sa.Column('generic_redemption_code', sa.String(length=120), nullable=True),
            sa.Column('percent_off', sa.String(length=10), nullable=True),
            sa.Column('start_date', sa.String(length=20), nullable=True),
            sa.Column('end_date', sa.String(length=20), nullable=True),
            sa.Column('display_start_date', sa.String(length=20), nullable=True),
            sa.Column('display_end_date', sa.String(length=20), nullable=True),
            sa.Column('promotion_url', sa.String(length=500), nullable=True),
            sa.Column('promotion_destination', sa.String(length=255), nullable=True),
            sa.Column('redemption_channel', sa.String(length=40), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_promotion_promotion_id'), 'promotion', ['promotion_id'], unique=True)
    else:
        # Ensure unique index exists
        try:
            idx_names = [ix['name'] for ix in insp.get_indexes('promotion')]
        except Exception:
            idx_names = []
        if 'ix_promotion_promotion_id' not in idx_names:
            op.create_index(op.f('ix_promotion_promotion_id'), 'promotion', ['promotion_id'], unique=True)


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if 'promotion' in tables:
        # Drop index if present
        try:
            idx_names = [ix['name'] for ix in insp.get_indexes('promotion')]
        except Exception:
            idx_names = []
        if 'ix_promotion_promotion_id' in idx_names:
            op.drop_index(op.f('ix_promotion_promotion_id'), table_name='promotion')
        op.drop_table('promotion')


