"""LiveKit agent worker entrypoint. Run: python main.py start"""

import structlog
from livekit.agents import WorkerOptions, cli

from config import settings
from gemini_agent import run_gemini_agent

import logging
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
)

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=run_gemini_agent,
            ws_url=settings.LIVEKIT_URL,
            api_key=settings.LIVEKIT_API_KEY,
            api_secret=settings.LIVEKIT_API_SECRET,
        )
    )
