"""Unit tests for email verification service."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.email_verification_service import (
    can_request_verification_code,
    generate_verification_code,
    is_code_expired,
    verify_code_timing_safe,
)


class TestGenerateVerificationCode:
    """Tests for generate_verification_code function."""

    def test_generates_6_digit_code(self) -> None:
        """Test that generated code is exactly 6 digits."""
        code = generate_verification_code()
        assert len(code) == 6
        assert code.isdigit()

    def test_generates_different_codes(self) -> None:
        """Test that multiple calls generate different codes."""
        codes = {generate_verification_code() for _ in range(100)}
        # Should have many unique codes (statistically unlikely to have duplicates)
        assert len(codes) > 90

    def test_code_is_zero_padded(self) -> None:
        """Test that codes with leading zeros are properly padded."""
        # Generate many codes and check all are 6 digits
        for _ in range(100):
            code = generate_verification_code()
            assert len(code) == 6


class TestVerifyCodeTimingSafe:
    """Tests for verify_code_timing_safe function."""

    def test_matching_codes_return_true(self) -> None:
        """Test that matching codes return True."""
        assert verify_code_timing_safe("123456", "123456") is True

    def test_non_matching_codes_return_false(self) -> None:
        """Test that non-matching codes return False."""
        assert verify_code_timing_safe("123456", "654321") is False

    def test_empty_codes(self) -> None:
        """Test empty code comparison."""
        assert verify_code_timing_safe("", "") is True
        assert verify_code_timing_safe("123456", "") is False

    def test_partial_match_returns_false(self) -> None:
        """Test that partial matches return False."""
        assert verify_code_timing_safe("123456", "123457") is False
        assert verify_code_timing_safe("123456", "12345") is False


class TestCanRequestVerificationCode:
    """Tests for can_request_verification_code function."""

    @pytest.mark.asyncio
    async def test_first_request_allowed(self) -> None:
        """Test that first request (no previous timestamp) is allowed."""
        can_request, seconds = await can_request_verification_code(None, 1, None)  # type: ignore[arg-type]
        assert can_request is True
        assert seconds == 0

    @pytest.mark.asyncio
    async def test_request_after_cooldown_allowed(self) -> None:
        """Test that request after 60 seconds cooldown is allowed."""
        last_sent = datetime.now(UTC) - timedelta(seconds=61)
        can_request, seconds = await can_request_verification_code(None, 1, last_sent)  # type: ignore[arg-type]
        assert can_request is True
        assert seconds == 0

    @pytest.mark.asyncio
    async def test_request_during_cooldown_blocked(self) -> None:
        """Test that request during cooldown is blocked."""
        last_sent = datetime.now(UTC) - timedelta(seconds=30)
        can_request, seconds = await can_request_verification_code(None, 1, last_sent)  # type: ignore[arg-type]
        assert can_request is False
        assert 29 <= seconds <= 31  # Allow some tolerance for timing

    @pytest.mark.asyncio
    async def test_request_just_sent_blocked(self) -> None:
        """Test that request sent just now is blocked with ~60 seconds remaining."""
        last_sent = datetime.now(UTC)
        can_request, seconds = await can_request_verification_code(None, 1, last_sent)  # type: ignore[arg-type]
        assert can_request is False
        assert 58 <= seconds <= 60


class TestIsCodeExpired:
    """Tests for is_code_expired function."""

    def test_recent_code_not_expired(self) -> None:
        """Test that code created just now is not expired."""
        created_at = datetime.now(UTC)
        assert is_code_expired(created_at) is False

    def test_code_expired_after_10_minutes(self) -> None:
        """Test that code is expired after 10 minutes."""
        created_at = datetime.now(UTC) - timedelta(minutes=11)
        assert is_code_expired(created_at) is True

    def test_code_not_expired_at_9_minutes(self) -> None:
        """Test that code is not expired at 9 minutes."""
        created_at = datetime.now(UTC) - timedelta(minutes=9)
        assert is_code_expired(created_at) is False

    def test_custom_expiry_time(self) -> None:
        """Test custom expiry time."""
        created_at = datetime.now(UTC) - timedelta(minutes=6)
        # Not expired with 10 minute default
        assert is_code_expired(created_at) is False
        # Expired with 5 minute custom expiry
        assert is_code_expired(created_at, expiry_minutes=5) is True
