"""review queue and manual return receipts

Revision ID: db362faf2fb0
Revises: 91725f2f8259
Create Date: 2026-11-08 11:44:42.558589

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'db362faf2fb0'
down_revision: Union[str, Sequence[str], None] = '91725f2f8259'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('manual_return_receipts',
    sa.Column('order_id', sa.String(length=40), nullable=False),
    sa.Column('received_on', sa.Date(), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('marked_by', sa.BigInteger(), nullable=False),
    sa.Column('marked_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['marked_by'], ['users.id'], name=op.f('fk_manual_return_receipts_marked_by_users')),
    sa.PrimaryKeyConstraint('order_id', name=op.f('pk_manual_return_receipts'))
    )
    op.create_table('unmatched_lines',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('upload_id', sa.BigInteger(), nullable=False),
    sa.Column('partner_id', sa.BigInteger(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('row_number', sa.Integer(), nullable=False),
    sa.Column('line_date', sa.Date(), nullable=True),
    sa.Column('gross_paise', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('commission_paise', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('fees_paise', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('tcs_paise', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('tds_paise', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('amount_paise', sa.BigInteger(), nullable=False),
    sa.Column('awb', sa.String(length=40), nullable=True),
    sa.Column('reference', sa.String(length=120), nullable=True),
    sa.Column('line_hash', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=10), server_default='open', nullable=False),
    sa.Column('candidates_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('suggested_order_id', sa.String(length=40), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('engine', sa.String(length=10), server_default='rules', nullable=False),
    sa.Column('ai_note', sa.String(length=120), nullable=True),
    sa.Column('resolved_order_id', sa.String(length=40), nullable=True),
    sa.Column('resolved_by', sa.BigInteger(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("engine IN ('rules', 'llm')", name=op.f('ck_unmatched_lines_engine_allowed')),
    sa.CheckConstraint("kind IN ('settlement', 'cod_remittance')", name=op.f('ck_unmatched_lines_kind_allowed')),
    sa.CheckConstraint("status IN ('open', 'accepted', 'rejected')", name=op.f('ck_unmatched_lines_status_allowed')),
    sa.ForeignKeyConstraint(['partner_id'], ['partners.id'], name=op.f('fk_unmatched_lines_partner_id_partners')),
    sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], name=op.f('fk_unmatched_lines_resolved_by_users')),
    sa.ForeignKeyConstraint(['upload_id'], ['uploads.id'], name=op.f('fk_unmatched_lines_upload_id_uploads')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_unmatched_lines')),
    sa.UniqueConstraint('partner_id', 'kind', 'line_hash', name='uq_unmatched_lines_partner_kind_hash')
    )
    op.create_index(op.f('ix_unmatched_lines_partner_id'), 'unmatched_lines', ['partner_id'], unique=False)
    op.create_index(op.f('ix_unmatched_lines_status'), 'unmatched_lines', ['status'], unique=False)
    op.create_index(op.f('ix_unmatched_lines_upload_id'), 'unmatched_lines', ['upload_id'], unique=False)
    op.add_column('uploads', sa.Column('rows_unmatched', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('uploads', 'rows_unmatched')
    op.drop_index(op.f('ix_unmatched_lines_upload_id'), table_name='unmatched_lines')
    op.drop_index(op.f('ix_unmatched_lines_status'), table_name='unmatched_lines')
    op.drop_index(op.f('ix_unmatched_lines_partner_id'), table_name='unmatched_lines')
    op.drop_table('unmatched_lines')
    op.drop_table('manual_return_receipts')
