"""Add CRM models (Contact, Appointment, CallInteraction)

Revision ID: 002_add_crm_models
Revises: 001
Create Date: 2025-11-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_add_crm_models'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create contacts table
    op.create_table(
        'contacts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('first_name', sa.String(length=100), nullable=False),
        sa.Column('last_name', sa.String(length=100), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone_number', sa.String(length=20), nullable=False),
        sa.Column('company_name', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='new'),
        sa.Column('tags', sa.String(length=500), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_contacts_id'), 'contacts', ['id'], unique=False)
    op.create_index(op.f('ix_contacts_user_id'), 'contacts', ['user_id'], unique=False)
    op.create_index(op.f('ix_contacts_email'), 'contacts', ['email'], unique=False)
    op.create_index(op.f('ix_contacts_phone_number'), 'contacts', ['phone_number'], unique=False)
    op.create_index(op.f('ix_contacts_status'), 'contacts', ['status'], unique=False)

    # Create appointments table
    op.create_table(
        'appointments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='scheduled'),
        sa.Column('service_type', sa.String(length=100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by_agent', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_appointments_id'), 'appointments', ['id'], unique=False)
    op.create_index(op.f('ix_appointments_contact_id'), 'appointments', ['contact_id'], unique=False)
    op.create_index(op.f('ix_appointments_scheduled_at'), 'appointments', ['scheduled_at'], unique=False)
    op.create_index(op.f('ix_appointments_status'), 'appointments', ['status'], unique=False)

    # Create call_interactions table
    op.create_table(
        'call_interactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('call_started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('call_ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('agent_name', sa.String(length=255), nullable=True),
        sa.Column('agent_id', sa.String(length=255), nullable=True),
        sa.Column('outcome', sa.String(length=50), nullable=True),
        sa.Column('transcript', sa.Text(), nullable=True),
        sa.Column('ai_summary', sa.Text(), nullable=True),
        sa.Column('sentiment_score', sa.Float(), nullable=True),
        sa.Column('action_items', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_call_interactions_id'), 'call_interactions', ['id'], unique=False)
    op.create_index(op.f('ix_call_interactions_contact_id'), 'call_interactions', ['contact_id'], unique=False)
    op.create_index(op.f('ix_call_interactions_call_started_at'), 'call_interactions', ['call_started_at'], unique=False)
    op.create_index(op.f('ix_call_interactions_agent_id'), 'call_interactions', ['agent_id'], unique=False)
    op.create_index(op.f('ix_call_interactions_outcome'), 'call_interactions', ['outcome'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_call_interactions_outcome'), table_name='call_interactions')
    op.drop_index(op.f('ix_call_interactions_agent_id'), table_name='call_interactions')
    op.drop_index(op.f('ix_call_interactions_call_started_at'), table_name='call_interactions')
    op.drop_index(op.f('ix_call_interactions_contact_id'), table_name='call_interactions')
    op.drop_index(op.f('ix_call_interactions_id'), table_name='call_interactions')
    op.drop_table('call_interactions')

    op.drop_index(op.f('ix_appointments_status'), table_name='appointments')
    op.drop_index(op.f('ix_appointments_scheduled_at'), table_name='appointments')
    op.drop_index(op.f('ix_appointments_contact_id'), table_name='appointments')
    op.drop_index(op.f('ix_appointments_id'), table_name='appointments')
    op.drop_table('appointments')

    op.drop_index(op.f('ix_contacts_status'), table_name='contacts')
    op.drop_index(op.f('ix_contacts_phone_number'), table_name='contacts')
    op.drop_index(op.f('ix_contacts_email'), table_name='contacts')
    op.drop_index(op.f('ix_contacts_user_id'), table_name='contacts')
    op.drop_index(op.f('ix_contacts_id'), table_name='contacts')
    op.drop_table('contacts')
