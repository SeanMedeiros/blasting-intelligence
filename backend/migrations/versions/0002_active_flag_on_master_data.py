"""active flag on master data

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-20

Adds an "active" flag so master data in use can be retired without deleting history.
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    
    with op.batch_alter_table('area', schema=None) as batch_op:
        batch_op.add_column(sa.Column('active', sa.Boolean(), server_default=sa.true(), nullable=False))

    with op.batch_alter_table('bench', schema=None) as batch_op:
        batch_op.add_column(sa.Column('active', sa.Boolean(), server_default=sa.true(), nullable=False))

    with op.batch_alter_table('equipment', schema=None) as batch_op:
        batch_op.add_column(sa.Column('active', sa.Boolean(), server_default=sa.true(), nullable=False))

    with op.batch_alter_table('instrument', schema=None) as batch_op:
        batch_op.add_column(sa.Column('active', sa.Boolean(), server_default=sa.true(), nullable=False))

    with op.batch_alter_table('monitor_station', schema=None) as batch_op:
        batch_op.add_column(sa.Column('active', sa.Boolean(), server_default=sa.true(), nullable=False))

    


def downgrade() -> None:
    
    with op.batch_alter_table('monitor_station', schema=None) as batch_op:
        batch_op.drop_column('active')

    with op.batch_alter_table('instrument', schema=None) as batch_op:
        batch_op.drop_column('active')

    with op.batch_alter_table('equipment', schema=None) as batch_op:
        batch_op.drop_column('active')

    with op.batch_alter_table('bench', schema=None) as batch_op:
        batch_op.drop_column('active')

    with op.batch_alter_table('area', schema=None) as batch_op:
        batch_op.drop_column('active')

    
