"""Safe, selective reads for one saved Garmin course."""

import json
from typing import Any

from pydantic import StrictInt, StrictStr


garmin_client: Any = None
MAX_SAFE_COURSE_ID = 9007199254740991

ERROR_MESSAGES = {
    "invalid_course_id": "course_id must be a positive integer or decimal string.",
    "client_unavailable": "Garmin client is unavailable. Authenticate with garmin-mcp-auth and restart the server.",
    "course_unavailable": "Course data is unavailable. Check the course ID, re-run garmin-mcp-auth if the session expired, or retry later.",
    "course_not_found": "No course data was found for the requested course ID.",
    "invalid_course_response": "Course data had an unexpected shape.",
}

WARNING_MESSAGES = {
    "course_name_unavailable": "Course name is unavailable.",
    "activity_type_unavailable": "Course activity type is unavailable.",
    "invalid_course_metric": "One or more course distance or elevation metrics are unavailable.",
}


def _parse_course_id(value: Any) -> int | None:
    if type(value) is int:
        return value if 0 < value <= MAX_SAFE_COURSE_ID else None
    if type(value) is not str or len(value) > 64:
        return None
    text = value.strip()
    if not text or not all("0" <= char <= "9" for char in text):
        return None
    parsed = int(text)
    return parsed if 0 < parsed <= MAX_SAFE_COURSE_ID else None


def _error(code: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": {"code": code, "message": ERROR_MESSAGES[code]},
        "course": None,
        "warnings": [],
    }


def _warning(code: str) -> dict[str, str]:
    return {"code": code, "message": WARNING_MESSAGES[code]}


def _course_template(course_id: int) -> dict[str, Any]:
    return {
        "course_id": course_id,
        "name": None,
        "activity": None,
        "distance_m": None,
        "elevation_gain_m": None,
        "elevation_loss_m": None,
    }


def configure(client: Any) -> None:
    """Configure the Garmin client used by the MCP adapter."""
    global garmin_client
    garmin_client = client


def get_course_details_service(client: Any, course_id: Any) -> dict[str, Any]:
    """Return a bounded course summary for a validated request identifier."""
    validated_id = _parse_course_id(course_id)
    if validated_id is None:
        return _error("invalid_course_id")
    if client is None:
        return _error("client_unavailable")
    return _error("course_unavailable")
