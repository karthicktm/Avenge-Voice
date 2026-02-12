"""Campaign tools for voice agents during outbound campaign calls."""

from typing import Any


class CampaignTools:
    """Tools for managing campaign call outcomes during a voice call."""

    @staticmethod
    def get_tool_definitions() -> list[dict[str, Any]]:
        """Get tool definitions for campaign tools."""
        return [
            {
                "type": "function",
                "name": "set_call_disposition",
                "description": (
                    "Record the outcome/disposition of this campaign call. "
                    "Call this before ending the call to capture the result."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "disposition": {
                            "type": "string",
                            "enum": [
                                "interested",
                                "appointment_booked",
                                "sale_made",
                                "callback_requested",
                                "info_sent",
                                "voicemail_left",
                                "wrong_number",
                                "not_available",
                                "transferred",
                                "not_interested",
                                "do_not_call",
                                "hung_up",
                            ],
                            "description": "The call outcome disposition code",
                        },
                        "notes": {
                            "type": "string",
                            "description": "Brief notes about the call outcome",
                        },
                    },
                    "required": ["disposition"],
                },
            }
        ]

    @staticmethod
    async def execute_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a campaign tool.

        Args:
            tool_name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result with action field for the stream handler
        """
        if tool_name == "set_call_disposition":
            disposition = arguments.get("disposition", "")
            notes = arguments.get("notes")
            return {
                "success": True,
                "action": "set_disposition",
                "disposition": disposition,
                "notes": notes,
                "message": f"Disposition set to: {disposition}",
            }

        return {"success": False, "error": f"Unknown campaign tool: {tool_name}"}
