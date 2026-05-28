# backend/tests/unit/test_workflow_test_voice.py
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.api.workflow_test import _resolve_voice_config, VoiceConfigOut


@pytest.fixture
def mock_db():
    db = AsyncMock()
    # Provide a MagicMock as execute.return_value so that .scalar_one_or_none()
    # is called synchronously (matching SQLAlchemy's CursorResult behaviour).
    db.execute.return_value = MagicMock()
    return db


@pytest.fixture
def mock_user():
    u = MagicMock()
    u.id = 1
    return u


@pytest.mark.asyncio
async def test_resolve_voice_config_no_agent_with_openai_key(mock_db, mock_user):
    """No agent attached → OpenAI shimmer if key available."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = None  # no agent
    mock_db.get.return_value = MagicMock(workspace_id=uuid.uuid4())

    fake_settings = MagicMock(openai_api_key="sk-test", elevenlabs_api_key=None)
    with patch("app.api.workflow_test.get_user_api_keys", return_value=fake_settings), \
         patch("app.api.workflow_test.settings") as mock_cfg:
        mock_cfg.OPENAI_API_KEY = None
        mock_cfg.ELEVENLABS_API_KEY = None
        result = await _resolve_voice_config(uuid.uuid4(), mock_user, mock_db)

    assert result.provider == "openai"
    assert result.voice == "shimmer"
    assert result.available is True


@pytest.mark.asyncio
async def test_resolve_voice_config_budget_agent_elevenlabs(mock_db, mock_user):
    """Budget tier → ElevenLabs if key present."""
    agent = MagicMock(pricing_tier="budget", voice="voice_abc123")
    mock_db.execute.return_value.scalar_one_or_none.return_value = agent
    mock_db.get.return_value = MagicMock(workspace_id=uuid.uuid4())

    fake_settings = MagicMock(openai_api_key=None, elevenlabs_api_key="el-test")
    with patch("app.api.workflow_test.get_user_api_keys", return_value=fake_settings), \
         patch("app.api.workflow_test.settings") as mock_cfg:
        mock_cfg.OPENAI_API_KEY = None
        mock_cfg.ELEVENLABS_API_KEY = None
        result = await _resolve_voice_config(uuid.uuid4(), mock_user, mock_db)

    assert result.provider == "elevenlabs"
    assert result.voice == "voice_abc123"
    assert result.tts_model == "eleven_flash_v2_5"


@pytest.mark.asyncio
async def test_resolve_voice_config_premium_agent_openai(mock_db, mock_user):
    """Premium tier → OpenAI tts-1 with agent voice."""
    agent = MagicMock(pricing_tier="premium", voice="nova")
    mock_db.execute.return_value.scalar_one_or_none.return_value = agent
    mock_db.get.return_value = MagicMock(workspace_id=uuid.uuid4())

    fake_settings = MagicMock(openai_api_key="sk-test", elevenlabs_api_key=None)
    with patch("app.api.workflow_test.get_user_api_keys", return_value=fake_settings), \
         patch("app.api.workflow_test.settings") as mock_cfg:
        mock_cfg.OPENAI_API_KEY = None
        result = await _resolve_voice_config(uuid.uuid4(), mock_user, mock_db)

    assert result.provider == "openai"
    assert result.voice == "nova"


@pytest.mark.asyncio
async def test_resolve_voice_config_no_keys_returns_browser(mock_db, mock_user):
    """No keys at all → browser fallback."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    mock_db.get.return_value = MagicMock(workspace_id=uuid.uuid4())

    with patch("app.api.workflow_test.get_user_api_keys", return_value=None), \
         patch("app.api.workflow_test.settings") as mock_cfg:
        mock_cfg.OPENAI_API_KEY = None
        mock_cfg.ELEVENLABS_API_KEY = None
        result = await _resolve_voice_config(uuid.uuid4(), mock_user, mock_db)

    assert result.provider == "browser"
    assert result.available is False
