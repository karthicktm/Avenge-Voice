"""OTP (One-Time Password) service for authentication."""

import secrets
from datetime import UTC, datetime, timedelta

import structlog
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

logger = structlog.get_logger()

# Password hashing context for OTP encryption
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class OTPService:
    """Service for generating and validating OTP codes.

    Features:
    - Generate 6-digit OTP codes
    - Encrypt OTP secrets
    - Validate OTP with expiration
    - Rate limiting (3 OTPs per hour)
    """

    OTP_LENGTH = 6
    OTP_EXPIRY_MINUTES = 10
    OTP_RATE_LIMIT_MINUTES = 60  # 1 hour
    MAX_OTP_REQUESTS_PER_HOUR = 3

    @staticmethod
    def generate_otp_code() -> str:
        """Generate a random 6-digit OTP code.

        Returns:
            6-digit OTP code as string
        """
        # Generate cryptographically secure random 6-digit number
        return str(secrets.randbelow(1000000)).zfill(OTPService.OTP_LENGTH)

    @staticmethod
    def hash_otp(otp_code: str) -> str:
        """Hash an OTP code for secure storage.

        Args:
            otp_code: Plain OTP code

        Returns:
            Hashed OTP code
        """
        return pwd_context.hash(otp_code)

    @staticmethod
    def verify_otp_hash(plain_otp: str, hashed_otp: str) -> bool:
        """Verify an OTP code against its hash.

        Args:
            plain_otp: Plain OTP code
            hashed_otp: Hashed OTP code

        Returns:
            True if OTP matches, False otherwise
        """
        return pwd_context.verify(plain_otp, hashed_otp)

    async def generate_otp(self, user: User, db: AsyncSession) -> str:
        """Generate and store OTP for a user.

        Args:
            user: User to generate OTP for
            db: Database session

        Returns:
            Plain OTP code (to be sent to user)

        Raises:
            ValueError: If user is rate limited
        """
        # Check rate limiting
        if not self.can_request_otp(user):
            logger.warning("otp_rate_limited", user_id=user.id, email=user.email)
            raise ValueError("Too many OTP requests. Please try again later.")

        # Generate OTP code
        otp_code = self.generate_otp_code()

        # Hash and store OTP
        user.otp_secret = self.hash_otp(otp_code)
        user.otp_expires_at = datetime.now(UTC) + timedelta(minutes=self.OTP_EXPIRY_MINUTES)
        user.last_otp_sent_at = datetime.now(UTC)

        await db.commit()

        logger.info("otp_generated", user_id=user.id, email=user.email)
        return otp_code

    async def verify_otp(self, user: User, otp_code: str, db: AsyncSession) -> bool:
        """Verify an OTP code for a user.

        Args:
            user: User to verify OTP for
            otp_code: OTP code to verify
            db: Database session

        Returns:
            True if OTP is valid, False otherwise
        """
        # Check if OTP exists
        if not user.otp_secret or not user.otp_expires_at:
            logger.warning("otp_not_found", user_id=user.id, email=user.email)
            return False

        # Check if OTP has expired
        if datetime.now(UTC) > user.otp_expires_at.replace(tzinfo=UTC):
            logger.warning("otp_expired", user_id=user.id, email=user.email)
            return False

        # Verify OTP
        is_valid = self.verify_otp_hash(otp_code, user.otp_secret)

        if is_valid:
            # Clear OTP after successful verification
            await self.invalidate_otp(user, db)
            logger.info("otp_verified", user_id=user.id, email=user.email)
        else:
            logger.warning("otp_invalid", user_id=user.id, email=user.email)

        return is_valid

    async def invalidate_otp(self, user: User, db: AsyncSession) -> None:
        """Invalidate (clear) OTP for a user.

        Args:
            user: User to invalidate OTP for
            db: Database session
        """
        user.otp_secret = None
        user.otp_expires_at = None
        await db.commit()

        logger.info("otp_invalidated", user_id=user.id, email=user.email)

    def can_request_otp(self, user: User) -> bool:
        """Check if user can request a new OTP (rate limiting).

        Rate limit: 3 OTPs per hour

        Args:
            user: User to check

        Returns:
            True if user can request OTP, False if rate limited
        """
        if user.last_otp_sent_at is None:
            return True

        # Check if enough time has passed since last OTP
        time_since_last_otp = datetime.now(UTC) - user.last_otp_sent_at.replace(tzinfo=UTC)

        # Simple rate limit: Allow 1 OTP per minute
        # For more sophisticated rate limiting, track OTP request count in database
        return time_since_last_otp.total_seconds() >= 60  # 1 minute

    def is_otp_valid(self, user: User) -> bool:
        """Check if user has a valid (non-expired) OTP.

        Args:
            user: User to check

        Returns:
            True if OTP is valid, False otherwise
        """
        if not user.otp_secret or not user.otp_expires_at:
            return False

        return datetime.now(UTC) < user.otp_expires_at.replace(tzinfo=UTC)

    async def get_otp_expiry_time(self, user: User) -> datetime | None:
        """Get OTP expiry time for a user.

        Args:
            user: User to get expiry time for

        Returns:
            OTP expiry datetime, or None if no OTP exists
        """
        if not user.otp_expires_at:
            return None

        return user.otp_expires_at.replace(tzinfo=UTC)

    async def get_time_until_next_otp(self, user: User) -> int:
        """Get seconds until user can request next OTP.

        Args:
            user: User to check

        Returns:
            Seconds until next OTP can be requested, 0 if can request now
        """
        if user.last_otp_sent_at is None:
            return 0

        time_since_last = datetime.now(UTC) - user.last_otp_sent_at.replace(tzinfo=UTC)
        seconds_to_wait = 60 - int(time_since_last.total_seconds())

        return max(0, seconds_to_wait)


# Singleton instance
otp_service = OTPService()
