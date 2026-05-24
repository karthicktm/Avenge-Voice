"""Calendly integration tools for voice agents."""

from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

ToolHandler = Callable[..., Awaitable[dict[str, Any]]]


class CalendlyTools:
    """Calendly API integration tools.

    Provides tools for:
    - Getting user info and organization
    - Listing event types
    - Getting available time slots
    - Scheduling events
    - Listing scheduled events
    - Canceling events
    """

    BASE_URL = "https://api.calendly.com"

    def __init__(self, access_token: str) -> None:
        """Initialize Calendly tools.

        Args:
            access_token: Calendly Personal Access Token
        """
        self.access_token = access_token
        self._client: httpx.AsyncClient | None = None
        self._user_uri: str | None = None
        self._organization_uri: str | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
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
                "name": "calendly_get_event_types",
                "description": "Get available event types (meeting types) that can be scheduled",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "active": {
                            "type": "boolean",
                            "description": "Filter by active status (default: true)",
                        },
                    },
                    "required": [],
                },
            },
            {
                "type": "function",
                "name": "calendly_get_availability",
                "description": "Get available time slots for a specific event type",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "event_type_uri": {
                            "type": "string",
                            "description": "The event type URI (from calendly_get_event_types)",
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Start of availability window (ISO 8601 format)",
                        },
                        "end_time": {
                            "type": "string",
                            "description": "End of availability window (ISO 8601 format)",
                        },
                    },
                    "required": ["event_type_uri", "start_time", "end_time"],
                },
            },
            {
                "type": "function",
                "name": "calendly_create_scheduling_link",
                "description": "Generate a one-time booking link to send to a customer. The link allows them to choose an available time slot. Note: Calendly API does not support direct booking - customers must use the link to self-schedule.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "invitee_email": {
                            "type": "string",
                            "description": "Email of the person being invited (pre-fills the booking form)",
                        },
                        "invitee_name": {
                            "type": "string",
                            "description": "Name of the person being invited (pre-fills the booking form)",
                        },
                    },
                    "required": ["invitee_email"],
                },
            },
            {
                "type": "function",
                "name": "calendly_list_events",
                "description": "List scheduled events/appointments",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["active", "canceled"],
                            "description": "Filter by event status",
                        },
                        "min_start_time": {
                            "type": "string",
                            "description": "Filter events starting after this time (ISO 8601)",
                        },
                        "max_start_time": {
                            "type": "string",
                            "description": "Filter events starting before this time (ISO 8601)",
                        },
                        "invitee_email": {
                            "type": "string",
                            "description": "Filter by invitee email",
                        },
                        "count": {
                            "type": "integer",
                            "description": "Number of results (max 100, default 20)",
                        },
                    },
                    "required": [],
                },
            },
            {
                "type": "function",
                "name": "calendly_get_event",
                "description": "Get details of a specific scheduled event",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "event_uuid": {
                            "type": "string",
                            "description": "The event UUID",
                        },
                    },
                    "required": ["event_uuid"],
                },
            },
            {
                "type": "function",
                "name": "calendly_cancel_event",
                "description": "Cancel a scheduled event",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "event_uuid": {
                            "type": "string",
                            "description": "The event UUID to cancel",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Reason for cancellation",
                        },
                    },
                    "required": ["event_uuid"],
                },
            },
        ]

    async def _ensure_user_info(self) -> None:
        """Fetch and cache user/organization URIs."""
        if self._user_uri and self._organization_uri:
            return

        response = await self.client.get("/users/me")
        if response.status_code == HTTPStatus.OK:
            data = response.json()
            self._user_uri = data["resource"]["uri"]
            self._organization_uri = data["resource"]["current_organization"]

    async def get_event_types(self, active: bool = True) -> dict[str, Any]:
        """Get available event types."""
        try:
            await self._ensure_user_info()

            params: dict[str, Any] = {"user": self._user_uri}
            if active:
                params["active"] = "true"

            response = await self.client.get("/event_types", params=params)

            if response.status_code != HTTPStatus.OK:
                return {
                    "success": False,
                    "error": f"Failed to get event types: {response.text}",
                }

            data = response.json()
            event_types = []
            for et in data.get("collection", []):
                event_types.append(
                    {
                        "uri": et["uri"],
                        "name": et["name"],
                        "slug": et["slug"],
                        "duration": et["duration"],
                        "description": et.get("description_plain"),
                        "active": et["active"],
                        "scheduling_url": et["scheduling_url"],
                    }
                )

            return {"success": True, "event_types": event_types}

        except Exception as e:
            logger.exception("calendly_get_event_types_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def get_availability(
        self, event_type_uri: str, start_time: str, end_time: str
    ) -> dict[str, Any]:
        """Get available time slots for an event type."""
        try:
            response = await self.client.get(
                "/event_type_available_times",
                params={
                    "event_type": event_type_uri,
                    "start_time": start_time,
                    "end_time": end_time,
                },
            )

            if response.status_code != HTTPStatus.OK:
                return {
                    "success": False,
                    "error": f"Failed to get availability: {response.text}",
                }

            data = response.json()
            slots = []
            for slot in data.get("collection", []):
                slots.append(
                    {
                        "start_time": slot["start_time"],
                        "status": slot["status"],
                        "invitees_remaining": slot.get("invitees_remaining"),
                    }
                )

            return {"success": True, "available_slots": slots}

        except Exception as e:
            logger.exception("calendly_get_availability_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def create_scheduling_link(
        self,
        invitee_email: str,
        invitee_name: str | None = None,
    ) -> dict[str, Any]:
        """Create a single-use scheduling link for an invitee.

        Note: Calendly API does not support direct booking - this creates a link
        the customer can use to self-schedule.
        """
        try:
            await self._ensure_user_info()

            # Create a single-use scheduling link
            payload: dict[str, Any] = {
                "max_event_count": 1,
                "owner": self._user_uri,
                "owner_type": "User",
            }

            response = await self.client.post("/scheduling_links", json=payload)

            if response.status_code != HTTPStatus.CREATED:
                return {
                    "success": False,
                    "error": f"Failed to create scheduling link: {response.text}",
                }

            data = response.json()
            booking_url = data["resource"]["booking_url"]

            # Add prefill parameters for invitee
            prefill_params = f"?email={invitee_email}"
            if invitee_name:
                prefill_params += f"&name={invitee_name}"

            return {
                "success": True,
                "message": f"Scheduling link created for {invitee_email}",
                "booking_url": booking_url + prefill_params,
                "invitee_email": invitee_email,
                "invitee_name": invitee_name,
            }

        except Exception as e:
            logger.exception("calendly_schedule_event_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def list_events(
        self,
        status: str | None = None,
        min_start_time: str | None = None,
        max_start_time: str | None = None,
        invitee_email: str | None = None,
        count: int = 20,
    ) -> dict[str, Any]:
        """List scheduled events."""
        try:
            await self._ensure_user_info()

            params: dict[str, Any] = {
                "user": self._user_uri,
                "count": min(count, 100),
            }

            if status:
                params["status"] = status
            if min_start_time:
                params["min_start_time"] = min_start_time
            if max_start_time:
                params["max_start_time"] = max_start_time
            if invitee_email:
                params["invitee_email"] = invitee_email

            response = await self.client.get("/scheduled_events", params=params)

            if response.status_code != HTTPStatus.OK:
                return {
                    "success": False,
                    "error": f"Failed to list events: {response.text}",
                }

            data = response.json()
            events = []
            for event in data.get("collection", []):
                events.append(
                    {
                        "uri": event["uri"],
                        "uuid": event["uri"].split("/")[-1],
                        "name": event["name"],
                        "status": event["status"],
                        "start_time": event["start_time"],
                        "end_time": event["end_time"],
                        "event_type": event.get("event_type"),
                        "location": event.get("location", {}).get("location"),
                        "created_at": event["created_at"],
                    }
                )

            return {"success": True, "events": events, "total": len(events)}

        except Exception as e:
            logger.exception("calendly_list_events_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def get_event(self, event_uuid: str) -> dict[str, Any]:
        """Get details of a specific event."""
        try:
            response = await self.client.get(f"/scheduled_events/{event_uuid}")

            if response.status_code != HTTPStatus.OK:
                return {
                    "success": False,
                    "error": f"Failed to get event: {response.text}",
                }

            event = response.json()["resource"]

            # Get invitees
            invitees_response = await self.client.get(f"/scheduled_events/{event_uuid}/invitees")
            invitees = []
            if invitees_response.status_code == HTTPStatus.OK:
                for inv in invitees_response.json().get("collection", []):
                    invitees.append(
                        {
                            "email": inv["email"],
                            "name": inv["name"],
                            "status": inv["status"],
                        }
                    )

            return {
                "success": True,
                "event": {
                    "uri": event["uri"],
                    "uuid": event_uuid,
                    "name": event["name"],
                    "status": event["status"],
                    "start_time": event["start_time"],
                    "end_time": event["end_time"],
                    "event_type": event.get("event_type"),
                    "location": event.get("location"),
                    "invitees": invitees,
                    "created_at": event["created_at"],
                },
            }

        except Exception as e:
            logger.exception("calendly_get_event_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def cancel_event(self, event_uuid: str, reason: str | None = None) -> dict[str, Any]:
        """Cancel a scheduled event."""
        try:
            payload: dict[str, Any] = {}
            if reason:
                payload["reason"] = reason

            response = await self.client.post(
                f"/scheduled_events/{event_uuid}/cancellation", json=payload
            )

            if response.status_code not in (HTTPStatus.OK, HTTPStatus.CREATED):
                return {
                    "success": False,
                    "error": f"Failed to cancel event: {response.text}",
                }

            return {
                "success": True,
                "message": f"Event {event_uuid} has been canceled",
                "reason": reason,
            }

        except Exception as e:
            logger.exception("calendly_cancel_event_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a Calendly tool by name."""
        tool_map: dict[str, ToolHandler] = {
            "calendly_get_event_types": self.get_event_types,
            "calendly_get_availability": self.get_availability,
            "calendly_create_scheduling_link": self.create_scheduling_link,
            "calendly_list_events": self.list_events,
            "calendly_get_event": self.get_event,
            "calendly_cancel_event": self.cancel_event,
        }

        handler = tool_map.get(tool_name)
        if not handler:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        result: dict[str, Any] = await handler(**arguments)
        return result
