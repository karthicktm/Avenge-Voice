"""CLI commands for Avenge Voice management."""

import asyncio
import getpass
import re
import sys
from typing import NoReturn

import structlog
from passlib.context import CryptContext
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.user import User, UserRole

logger = structlog.get_logger()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def validate_email(email: str) -> bool:
    """Validate email format.

    Args:
        email: Email address to validate

    Returns:
        True if valid, False otherwise
    """
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(pattern, email) is not None


def validate_password(password: str) -> tuple[bool, str]:
    """Validate password strength.

    Args:
        password: Password to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(password) < 12:
        return False, "Password must be at least 12 characters long"

    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"

    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"

    if not re.search(r"\d", password):
        return False, "Password must contain at least one number"

    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character"

    return True, ""


async def create_superuser() -> None:
    """Create a super admin user interactively."""
    print("\n" + "=" * 50)
    print("Creating Super Admin Account")
    print("=" * 50 + "\n")

    # Get email
    while True:
        email = input("Email: ").strip()
        if not email:
            print("❌ Email is required")
            continue
        if not validate_email(email):
            print("❌ Invalid email format")
            continue
        break

    # Check if user already exists
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        existing_user = result.scalar_one_or_none()

        if existing_user:
            print(f"\n❌ User with email {email} already exists")
            if existing_user.role == UserRole.SUPER_ADMIN:
                print("   This user is already a super admin")
            else:
                promote = input("\nPromote this user to super admin? (y/n): ").strip().lower()
                if promote == "y":
                    existing_user.role = UserRole.SUPER_ADMIN
                    existing_user.organization_id = None
                    existing_user.email_verified = True
                    await db.commit()
                    print(f"\n✓ User {email} promoted to super admin!")
                    return
            return

    # Get password
    while True:
        password = getpass.getpass("Password: ")
        if not password:
            print("❌ Password is required")
            continue

        is_valid, error_msg = validate_password(password)
        if not is_valid:
            print(f"❌ {error_msg}")
            continue

        confirm_password = getpass.getpass("Confirm Password: ")
        if password != confirm_password:
            print("❌ Passwords do not match")
            continue

        break

    # Get full name
    full_name = input("Full Name: ").strip()
    if not full_name:
        full_name = "Super Admin"

    # Create super admin
    async with AsyncSessionLocal() as db:
        hashed_password = pwd_context.hash(password)

        super_admin = User(
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            role=UserRole.SUPER_ADMIN,
            email_verified=True,  # Auto-verify super admin
            is_active=True,
            organization_id=None,  # Super admin has no organization
        )

        db.add(super_admin)
        await db.commit()
        await db.refresh(super_admin)

        print("\n" + "=" * 50)
        print("✓ Super admin created successfully!")
        print("=" * 50)
        print(f"\nEmail: {email}")
        print(f"Role: {UserRole.SUPER_ADMIN}")
        print("Email verified: Yes")
        print(
            f"\nYou can now login at: {getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')}/login"
        )
        print()


async def list_superusers() -> None:
    """List all super admin users."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.role == UserRole.SUPER_ADMIN).order_by(User.created_at)
        )
        superusers = result.scalars().all()

        if not superusers:
            print("\nNo super admin users found.")
            return

        print("\n" + "=" * 80)
        print("Super Admin Users")
        print("=" * 80)
        print(f"\n{'ID':<6} {'Email':<35} {'Name':<25} {'Created':<20}")
        print("-" * 80)

        for user in superusers:
            created = user.created_at.strftime("%Y-%m-%d %H:%M:%S")
            print(f"{user.id:<6} {user.email:<35} {user.full_name or 'N/A':<25} {created:<20}")

        print()


async def delete_superuser() -> None:
    """Delete a super admin user."""
    print("\n" + "=" * 50)
    print("Delete Super Admin Account")
    print("=" * 50 + "\n")

    email = input("Email of super admin to delete: ").strip()
    if not email:
        print("❌ Email is required")
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.email == email, User.role == UserRole.SUPER_ADMIN)
        )
        user = result.scalar_one_or_none()

        if not user:
            print(f"\n❌ Super admin with email {email} not found")
            return

        # Confirm deletion
        print("\nFound super admin:")
        print(f"  Email: {user.email}")
        print(f"  Name: {user.full_name or 'N/A'}")
        print(f"  Created: {user.created_at.strftime('%Y-%m-%d %H:%M:%S')}")

        confirm = (
            input("\n⚠️  Are you sure you want to delete this super admin? (yes/no): ")
            .strip()
            .lower()
        )
        if confirm != "yes":
            print("\n❌ Deletion cancelled")
            return

        await db.delete(user)
        await db.commit()

        print(f"\n✓ Super admin {email} deleted successfully")


async def verify_user_email() -> None:
    """Verify a user's email address manually."""
    print("\n" + "=" * 50)
    print("Verify User Email")
    print("=" * 50 + "\n")

    email = input("Email to verify: ").strip()
    if not email:
        print("❌ Email is required")
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            print(f"\n❌ User with email {email} not found")
            return

        if user.email_verified:
            print(f"\n✓ User {email} is already verified")
            return

        user.email_verified = True
        await db.commit()

        print(f"\n✓ Email verified for user: {email}")
        print(f"  Role: {user.role}")
        print(f"  Name: {user.full_name or 'N/A'}")


async def verify_all_superadmins() -> None:
    """Verify email for all super admin users."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.role == UserRole.SUPER_ADMIN)
        )
        superusers = result.scalars().all()

        if not superusers:
            print("\nNo super admin users found.")
            return

        verified_count = 0
        for user in superusers:
            if not user.email_verified:
                user.email_verified = True
                verified_count += 1
                print(f"✓ Verified: {user.email}")

        await db.commit()

        if verified_count == 0:
            print("\nAll super admins are already verified.")
        else:
            print(f"\n✓ Verified {verified_count} super admin(s)")


async def create_superuser_from_env() -> None:
    """Create super admin from environment variables (for production deployment).

    Environment variables:
        SUPER_ADMIN_EMAIL: Email address
        SUPER_ADMIN_PASSWORD: Password
        SUPER_ADMIN_NAME: Full name (optional)
    """
    email = getattr(settings, "SUPER_ADMIN_EMAIL", None)
    password = getattr(settings, "SUPER_ADMIN_PASSWORD", None)
    name = getattr(settings, "SUPER_ADMIN_NAME", "Super Admin")

    if not email or not password:
        logger.info(
            "super_admin_env_not_configured",
            message="SUPER_ADMIN_EMAIL or SUPER_ADMIN_PASSWORD not set",
        )
        return

    # Check if super admin already exists
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        existing_user = result.scalar_one_or_none()

        if existing_user:
            logger.info("super_admin_exists", email=email)
            return

        # Create super admin
        hashed_password = pwd_context.hash(password)

        super_admin = User(
            email=email,
            hashed_password=hashed_password,
            full_name=name,
            role=UserRole.SUPER_ADMIN,
            email_verified=True,
            is_active=True,
            organization_id=None,
        )

        db.add(super_admin)
        await db.commit()

        logger.info("super_admin_created_from_env", email=email)


def main() -> NoReturn:
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print("\nAvenge Voice CLI")
        print("=" * 50)
        print("\nAvailable commands:")
        print("  create-superuser       Create a new super admin user")
        print("  list-superusers        List all super admin users")
        print("  delete-superuser       Delete a super admin user")
        print("  verify-email           Verify a user's email manually")
        print("  verify-all-superadmins Verify email for all super admins")
        print("\nUsage: python -m app.cli <command>")
        print()
        sys.exit(1)

    command = sys.argv[1]

    if command == "create-superuser":
        asyncio.run(create_superuser())
    elif command == "list-superusers":
        asyncio.run(list_superusers())
    elif command == "delete-superuser":
        asyncio.run(delete_superuser())
    elif command == "verify-email":
        asyncio.run(verify_user_email())
    elif command == "verify-all-superadmins":
        asyncio.run(verify_all_superadmins())
    else:
        print(f"\n❌ Unknown command: {command}")
        print("\nRun 'python -m app.cli' to see available commands")
        print()
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
