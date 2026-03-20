"""Resend email integration tools for voice agents."""

from typing import Any

import structlog

logger = structlog.get_logger()


class ResendEmailTools:
    """Resend email API integration tools.

    Provides tools for:
    - Sending transactional emails during a voice call
    """

    RESEND_API_URL = "https://api.resend.com/emails"

    def __init__(self, api_key: str, from_email: str) -> None:
        self.api_key = api_key
        self.from_email = from_email
        self._client: Any = None

    @property
    def client(self) -> Any:
        import httpx

        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=15.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def get_tool_definitions() -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "resend_send_email",
                "description": (
                    "Send a transactional email to the caller or any address. "
                    "Use this to send confirmations, summaries, follow-ups, or any "
                    "information the caller asks to receive by email."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": "Recipient email address",
                        },
                        "subject": {
                            "type": "string",
                            "description": "Email subject line",
                        },
                        "body": {
                            "type": "string",
                            "description": ("Plain-text email body. Keep it concise and friendly."),
                        },
                    },
                    "required": ["to", "subject", "body"],
                },
            }
        ]

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "resend_send_email":
            return await self._send_email(arguments)
        return {"success": False, "error": f"Unknown email tool: {tool_name}"}

    async def _send_email(self, arguments: dict[str, Any]) -> dict[str, Any]:
        to: str = str(arguments.get("to", "")).strip()
        subject: str = str(arguments.get("subject", "")).strip()
        body: str = str(arguments.get("body", "")).strip()

        if not to or not subject or not body:
            return {"success": False, "error": "to, subject, and body are required"}

        log = logger.bind(component="resend_email_tools", to=to, subject=subject)

        try:
            response = await self.client.post(
                self.RESEND_API_URL,
                json={
                    "from": self.from_email,
                    "to": [to],
                    "subject": subject,
                    "text": body,
                },
            )
            data: dict[str, Any] = response.json()

            if response.status_code in {200, 201}:
                log.info("resend_email_sent", email_id=data.get("id"))
                return {"success": True, "email_id": data.get("id"), "to": to}

            log.warning("resend_email_failed", status=response.status_code, detail=data)
            return {
                "success": False,
                "error": data.get("message") or f"Resend API error {response.status_code}",
            }

        except Exception as exc:
            log.exception("resend_email_error")
            return {"success": False, "error": str(exc)}
