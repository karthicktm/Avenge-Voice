"""add_multi_tenant_user_management

Adds multi-tenant user management with organizations, workspace members,
invitations, user profiles, and agent assignments.

Revision ID: 17635397a860
Revises: 017_fix_documents_column_types
Create Date: 2026-02-03 11:20:27.863564

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '17635397a860'
down_revision: Union[str, Sequence[str], None] = '017_fix_documents_column_types'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    # Create organizations table
    op.create_table(
        'organizations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False, comment='Organization name'),
        sa.Column('slug', sa.String(length=100), nullable=False, comment='URL-friendly identifier'),
        sa.Column('owner_id', sa.Integer(), nullable=False, comment='Organization owner user ID'),
        
        # Subscription & Billing
        sa.Column('plan_type', sa.String(length=50), nullable=False, server_default='free', comment='Current subscription plan'),
        sa.Column('subscription_status', sa.String(length=50), nullable=False, server_default='trial', comment='Current subscription status'),
        sa.Column('trial_ends_at', sa.DateTime(timezone=True), nullable=True, comment='Trial period end date'),
        sa.Column('subscription_started_at', sa.DateTime(timezone=True), nullable=True, comment='Subscription start date'),
        sa.Column('subscription_ends_at', sa.DateTime(timezone=True), nullable=True, comment='Subscription end date'),
        
        # Plan Limits
        sa.Column('max_users', sa.Integer(), nullable=False, server_default='1', comment='Maximum users allowed'),
        sa.Column('max_agents', sa.Integer(), nullable=False, server_default='2', comment='Maximum agents allowed'),
        sa.Column('max_workspaces', sa.Integer(), nullable=False, server_default='1', comment='Maximum workspaces allowed'),
        sa.Column('max_call_minutes_per_month', sa.Integer(), nullable=False, server_default='100', comment='Maximum call minutes per month'),
        sa.Column('max_storage_gb', sa.Integer(), nullable=False, server_default='1', comment='Maximum storage in GB'),
        
        # Usage Tracking
        sa.Column('current_users_count', sa.Integer(), nullable=False, server_default='0', comment='Current number of users'),
        sa.Column('current_agents_count', sa.Integer(), nullable=False, server_default='0', comment='Current number of agents'),
        sa.Column('current_workspaces_count', sa.Integer(), nullable=False, server_default='0', comment='Current number of workspaces'),
        sa.Column('current_month_call_minutes', sa.Integer(), nullable=False, server_default='0', comment='Call minutes used this month'),
        sa.Column('current_month_storage_gb', sa.Float(), nullable=False, server_default='0.0', comment='Storage used in GB'),
        sa.Column('usage_reset_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='Last monthly usage reset'),
        
        # Feature Flags
        sa.Column('features_enabled', postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default='[]', comment='List of enabled feature flags'),
        
        # Payment Integration
        sa.Column('stripe_customer_id', sa.String(length=100), nullable=True, comment='Stripe customer ID'),
        sa.Column('stripe_subscription_id', sa.String(length=100), nullable=True, comment='Stripe subscription ID'),
        sa.Column('payment_method_last4', sa.String(length=4), nullable=True, comment='Last 4 digits of payment method'),
        sa.Column('next_billing_date', sa.DateTime(timezone=True), nullable=True, comment='Next billing date'),
        
        # Status
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true', comment='Whether organization is active'),
        
        # Metadata
        sa.Column('signup_metadata', postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default='{}', comment='Signup metadata'),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for organizations
    op.create_index('ix_organizations_slug', 'organizations', ['slug'], unique=True)
    op.create_index('ix_organizations_owner_id', 'organizations', ['owner_id'])
    op.create_index('ix_organizations_plan_type', 'organizations', ['plan_type'])
    
    # Add new columns to users table
    op.add_column('users', sa.Column('provider', sa.String(length=50), nullable=False, server_default='email', comment='Authentication provider'))
    op.add_column('users', sa.Column('provider_id', sa.String(length=255), nullable=True, comment='Unique ID from OAuth provider'))
    op.add_column('users', sa.Column('organization_id', sa.UUID(), nullable=True, comment="User's organization"))
    op.add_column('users', sa.Column('role', sa.String(length=50), nullable=False, server_default='user', comment='System-level role'))
    
    # Email Verification & OTP
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), nullable=False, server_default='false', comment='Whether email is verified'))
    op.add_column('users', sa.Column('email_verification_token', sa.String(length=64), nullable=True, comment='Email verification token'))
    op.add_column('users', sa.Column('email_verification_sent_at', sa.DateTime(timezone=True), nullable=True, comment='When verification email was sent'))
    op.add_column('users', sa.Column('otp_secret', sa.String(length=255), nullable=True, comment='Encrypted OTP secret'))
    op.add_column('users', sa.Column('otp_expires_at', sa.DateTime(timezone=True), nullable=True, comment='OTP expiration time'))
    op.add_column('users', sa.Column('last_otp_sent_at', sa.DateTime(timezone=True), nullable=True, comment='Last OTP send time'))
    
    # Security
    op.add_column('users', sa.Column('failed_login_attempts', sa.Integer(), nullable=False, server_default='0', comment='Failed login attempt counter'))
    op.add_column('users', sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True, comment='Account lock expiration'))
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True, comment='Last successful login'))
    
    # Make hashed_password nullable for OAuth users
    op.alter_column('users', 'hashed_password', nullable=True)
    
    # Create indexes for users
    op.create_index('ix_users_provider_id', 'users', ['provider_id'], unique=True)
    op.create_index('ix_users_organization_id', 'users', ['organization_id'])
    op.create_index('ix_users_email_verification_token', 'users', ['email_verification_token'], unique=True)
    
    # Add foreign key for organization
    op.create_foreign_key('fk_users_organization_id', 'users', 'organizations', ['organization_id'], ['id'], ondelete='CASCADE')
    
    # Add organization_id to workspaces
    op.add_column('workspaces', sa.Column('organization_id', sa.UUID(), nullable=True, comment='Organization this workspace belongs to'))
    op.create_index('ix_workspaces_organization_id', 'workspaces', ['organization_id'])
    op.create_foreign_key('fk_workspaces_organization_id', 'workspaces', 'organizations', ['organization_id'], ['id'], ondelete='CASCADE')
    
    # Create user_profiles table
    op.create_table(
        'user_profiles',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('phone_number', sa.String(length=20), nullable=True, comment='User phone number'),
        sa.Column('avatar_url', sa.String(length=500), nullable=True, comment='User avatar URL'),
        sa.Column('job_title', sa.String(length=100), nullable=True, comment='User job title'),
        sa.Column('department', sa.String(length=100), nullable=True, comment='User department'),
        sa.Column('signup_metadata', postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default='{}', comment='Signup metadata'),
        sa.Column('preferences', postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default='{}', comment='User preferences'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id')
    )
    op.create_index('ix_user_profiles_user_id', 'user_profiles', ['user_id'], unique=True)
    op.create_index('ix_user_profiles_organization_id', 'user_profiles', ['organization_id'])
    
    # Create workspace_members table
    op.create_table(
        'workspace_members',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False, server_default='member', comment="User's role in workspace"),
        sa.Column('invited_by', sa.Integer(), nullable=True, comment='User who invited'),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='When user joined workspace'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invited_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', 'user_id', name='uq_workspace_user')
    )
    op.create_index('ix_workspace_members_workspace_id', 'workspace_members', ['workspace_id'])
    op.create_index('ix_workspace_members_user_id', 'workspace_members', ['user_id'])
    
    # Create workspace_invitations table
    op.create_table(
        'workspace_invitations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False, comment='Email of invited user'),
        sa.Column('role', sa.String(length=50), nullable=False, server_default='member', comment='Role to assign'),
        sa.Column('token', sa.String(length=64), nullable=False, comment='Unique invitation token'),
        sa.Column('invited_by', sa.Integer(), nullable=False, comment='User who sent invitation'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending', comment='Invitation status'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, comment='Invitation expiration'),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True, comment='When invitation was accepted'),
        sa.Column('accepted_by_user_id', sa.Integer(), nullable=True, comment='User who accepted'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invited_by'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['accepted_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token')
    )
    op.create_index('ix_workspace_invitations_workspace_id', 'workspace_invitations', ['workspace_id'])
    op.create_index('ix_workspace_invitations_email', 'workspace_invitations', ['email'])
    op.create_index('ix_workspace_invitations_token', 'workspace_invitations', ['token'], unique=True)
    op.create_index('ix_workspace_invitations_status', 'workspace_invitations', ['status'])
    
    # Create agent_assignments table
    op.create_table(
        'agent_assignments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('agent_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('assigned_by', sa.Integer(), nullable=False, comment='User who made assignment'),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='When assignment was made'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['assigned_by'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_id', 'user_id', 'workspace_id', name='uq_agent_user_workspace')
    )
    op.create_index('ix_agent_assignments_agent_id', 'agent_assignments', ['agent_id'])
    op.create_index('ix_agent_assignments_user_id', 'agent_assignments', ['user_id'])
    op.create_index('ix_agent_assignments_workspace_id', 'agent_assignments', ['workspace_id'])
    
    # Data migration: Create default organization for existing users
    # This will be handled in a separate data migration script


def downgrade() -> None:
    """Downgrade schema."""
    
    # Drop agent_assignments table
    op.drop_index('ix_agent_assignments_workspace_id', 'agent_assignments')
    op.drop_index('ix_agent_assignments_user_id', 'agent_assignments')
    op.drop_index('ix_agent_assignments_agent_id', 'agent_assignments')
    op.drop_table('agent_assignments')
    
    # Drop workspace_invitations table
    op.drop_index('ix_workspace_invitations_status', 'workspace_invitations')
    op.drop_index('ix_workspace_invitations_token', 'workspace_invitations')
    op.drop_index('ix_workspace_invitations_email', 'workspace_invitations')
    op.drop_index('ix_workspace_invitations_workspace_id', 'workspace_invitations')
    op.drop_table('workspace_invitations')
    
    # Drop workspace_members table
    op.drop_index('ix_workspace_members_user_id', 'workspace_members')
    op.drop_index('ix_workspace_members_workspace_id', 'workspace_members')
    op.drop_table('workspace_members')
    
    # Drop user_profiles table
    op.drop_index('ix_user_profiles_organization_id', 'user_profiles')
    op.drop_index('ix_user_profiles_user_id', 'user_profiles')
    op.drop_table('user_profiles')
    
    # Remove organization_id from workspaces
    op.drop_constraint('fk_workspaces_organization_id', 'workspaces', type_='foreignkey')
    op.drop_index('ix_workspaces_organization_id', 'workspaces')
    op.drop_column('workspaces', 'organization_id')
    
    # Remove new columns from users
    op.drop_constraint('fk_users_organization_id', 'users', type_='foreignkey')
    op.drop_index('ix_users_email_verification_token', 'users')
    op.drop_index('ix_users_organization_id', 'users')
    op.drop_index('ix_users_provider_id', 'users')
    
    op.alter_column('users', 'hashed_password', nullable=False)
    
    op.drop_column('users', 'last_login_at')
    op.drop_column('users', 'locked_until')
    op.drop_column('users', 'failed_login_attempts')
    op.drop_column('users', 'last_otp_sent_at')
    op.drop_column('users', 'otp_expires_at')
    op.drop_column('users', 'otp_secret')
    op.drop_column('users', 'email_verification_sent_at')
    op.drop_column('users', 'email_verification_token')
    op.drop_column('users', 'email_verified')
    op.drop_column('users', 'role')
    op.drop_column('users', 'organization_id')
    op.drop_column('users', 'provider_id')
    op.drop_column('users', 'provider')
    
    # Drop organizations table
    op.drop_index('ix_organizations_plan_type', 'organizations')
    op.drop_index('ix_organizations_owner_id', 'organizations')
    op.drop_index('ix_organizations_slug', 'organizations')
    op.drop_table('organizations')

