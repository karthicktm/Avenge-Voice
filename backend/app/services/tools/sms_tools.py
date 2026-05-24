"""SMS integration tools for voice agents (Twilio and Telnyx)."""

from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

ToolHandler = Callable[..., Awaitable[dict[str, Any]]]


class TwilioSMSTools:
    """Twilio SMS API integration tools.

    Provides tools for:
    - Sending SMS messages
    - Getting message status
    """

    BASE_URL = "https://api.twilio.com/2010-04-01"

    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        """Initialize Twilio SMS tools.

        Args:
            account_sid: Twilio Account SID
            auth_token: Twilio Auth Token
            from_number: Twilio phone number to send from (E.164 format)
        """
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=f"{self.BASE_URL}/Accounts/{self.account_sid}",
                auth=(self.account_sid, self.auth_token),
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def get_tool_definitions() -> list[dict[str, Any]]:
        """Get OpenAI function calling tool definitions."""
        return [
            {
                "type": "function",
                "name": "twilio_send_sms",
                "description": "Send an SMS message to a phone number",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": "Recipient phone number (E.164 format, e.g., +14155551234)",
                        },
                        "body": {
                            "type": "string",
                            "description": "Message content (max 1600 characters)",
                        },
                    },
                    "required": ["to", "body"],
                },
            },
            {
                "type": "function",
                "name": "twilio_get_message_status",
                "description": "Get the delivery status of a sent SMS message",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message_sid": {
                            "type": "string",
                            "description": "The Twilio message SID (starts with SM)",
                        },
                    },
                    "required": ["message_sid"],
                },
            },
        ]

    async def send_sms(self, to: str, body: str) -> dict[str, Any]:
        """Send an SMS message."""
        try:
            # Validate body length
            max_length = 1600
            if len(body) > max_length:
                return {
                    "success": False,
                    "error": f"Message too long. Max {max_length} characters, got {len(body)}",
                }

            response = await self.client.post(
                "/Messages.json",
                data={
                    "To": to,
                    "From": self.from_number,
                    "Body": body,
                },
            )

            if response.status_code != HTTPStatus.CREATED:
                error_data = response.json()
                return {
                    "success": False,
                    "error": error_data.get("message", response.text),
                }

            data = response.json()
            return {
                "success": True,
                "message_sid": data["sid"],
                "to": data["to"],
                "from": data["from"],
                "status": data["status"],
                "message": f"SMS sent successfully to {to}",
            }

        except Exception as e:
            logger.exception("twilio_send_sms_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def get_message_status(self, message_sid: str) -> dict[str, Any]:
        """Get the status of a sent message."""
        try:
            response = await self.client.get(f"/Messages/{message_sid}.json")

            if response.status_code != HTTPStatus.OK:
                return {
                    "success": False,
                    "error": f"Message not found: {response.text}",
                }

            data = response.json()
            return {
                "success": True,
                "message_sid": data["sid"],
                "to": data["to"],
                "from": data["from"],
                "status": data["status"],
                "date_sent": data.get("date_sent"),
                "error_code": data.get("error_code"),
                "error_message": data.get("error_message"),
            }

        except Exception as e:
            logger.exception("twilio_get_message_status_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a Twilio SMS tool by name."""
        tool_map: dict[str, ToolHandler] = {
            "twilio_send_sms": self.send_sms,
            "twilio_get_message_status": self.get_message_status,
        }

        handler = tool_map.get(tool_name)
        if not handler:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        result: dict[str, Any] = await handler(**arguments)
        return result


class TelnyxSMSTools:
    """Telnyx SMS API integration tools.

    Provides tools for:
    - Sending SMS messages
    - Getting message status
    """

    BASE_URL = "https://api.telnyx.com/v2"

    def __init__(
        self,
        api_key: str,
        from_number: str,
        messaging_profile_id: str | None = None,
    ) -> None:
        """Initialize Telnyx SMS tools.

        Args:
            api_key: Telnyx API Key
            from_number: Telnyx phone number to send from (E.164 format)
            messaging_profile_id: Optional messaging profile ID for routing
        """
        self.api_key = api_key
        self.from_number = from_number
        self.messaging_profile_id = messaging_profile_id
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def get_tool_definitions() -> list[dict[str, Any]]:
        """Get OpenAI function calling tool definitions."""
        return [
            {
                "type": "function",
                "name": "telnyx_send_sms",
                "description": "Send an SMS message to a phone number via Telnyx",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": "Recipient phone number (E.164 format, e.g., +14155551234)",
                        },
                        "body": {
                            "type": "string",
                            "description": "Message content",
                        },
                    },
                    "required": ["to", "body"],
                },
            },
            {
                "type": "function",
                "name": "telnyx_get_message_status",
                "description": "Get the delivery status of a sent SMS message via Telnyx",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message_id": {
                            "type": "string",
                            "description": "The Telnyx message ID (UUID)",
                        },
                    },
                    "required": ["message_id"],
                },
            },
        ]

    async def send_sms(self, to: str, body: str) -> dict[str, Any]:
        """Send an SMS message."""
        try:
            payload: dict[str, Any] = {
                "to": to,
                "from": self.from_number,
                "text": body,
                "type": "SMS",
            }

            if self.messaging_profile_id:
                payload["messaging_profile_id"] = self.messaging_profile_id

            response = await self.client.post("/messages", json=payload)

            if response.status_code != HTTPStatus.OK:
                error_data = response.json()
                errors = error_data.get("errors", [])
                error_msg = errors[0].get("detail") if errors else response.text
                return {
                    "success": False,
                    "error": error_msg,
                }

            data = response.json()["data"]
            return {
                "success": True,
                "message_id": data["id"],
                "to": data["to"][0]["phone_number"],
                "from": data["from"]["phone_number"],
                "status": data.get("to", [{}])[0].get("status"),
                "message": f"SMS sent successfully to {to}",
            }

        except Exception as e:
            logger.exception("telnyx_send_sms_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def get_message_status(self, message_id: str) -> dict[str, Any]:
        """Get the status of a sent message."""
        try:
            response = await self.client.get(f"/messages/{message_id}")

            if response.status_code != HTTPStatus.OK:
                return {
                    "success": False,
                    "error": f"Message not found: {response.text}",
                }

            data = response.json()["data"]
            to_info = data.get("to", [{}])[0] if data.get("to") else {}

            return {
                "success": True,
                "message_id": data["id"],
                "to": to_info.get("phone_number"),
                "from": data.get("from", {}).get("phone_number"),
                "status": to_info.get("status"),
                "completed_at": data.get("completed_at"),
                "errors": data.get("errors"),
            }

        except Exception as e:
            logger.exception("telnyx_get_message_status_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a Telnyx SMS tool by name."""
        tool_map: dict[str, ToolHandler] = {
            "telnyx_send_sms": self.send_sms,
            "telnyx_get_message_status": self.get_message_status,
        }

        handler = tool_map.get(tool_name)
        if not handler:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        result: dict[str, Any] = await handler(**arguments)
        return result
