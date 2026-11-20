"""attachments

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-20

Evidence files (photos, PDFs, documents) linked to records; voided, never deleted.
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    
    op.create_table('attachment',
    sa.Column('entity', sa.String(length=40), nullable=False),
    sa.Column('entity_id', sa.Integer(), nullable=False),
    sa.Column('filename', sa.String(length=200), nullable=False),
    sa.Column('stored_name', sa.String(length=80), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=300), nullable=True),
    sa.Column('uploaded_by', sa.String(length=120), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('voided', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('void_reason', sa.String(length=300), nullable=True),
    sa.Column('voided_by', sa.String(length=120), nullable=True),
    sa.Column('voided_at', sa.DateTime(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stored_name')
    )
    with op.batch_alter_table('attachment', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_attachment_entity'), ['entity'], unique=False)
        batch_op.create_index(batch_op.f('ix_attachment_entity_id'), ['entity_id'], unique=False)

    


def downgrade() -> None:
    
    with op.batch_alter_table('attachment', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_attachment_entity_id'))
        batch_op.drop_index(batch_op.f('ix_attachment_entity'))

    op.drop_table('attachment')
    
