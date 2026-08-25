"""Safe, selective reads for one saved Garmin course."""

import json
from collections.abc import Mapping
from math import isfinite
from typing import Any

from pydantic import StrictInt, StrictStr

from .courses import _ACTIVITY_TYPE_IDS


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

_ACTIVITY_BY_ID = {value: key for key, value in _ACTIVITY_TYPE_IDS.items()}


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


def _text(value: Any) -> str | None:
    if type(value) is not str:
        return None
    value = value.strip()
    return value if 1 <= len(value) <= 256 else None


def _metric(value: Any) -> int | float | None:
    if type(value) not in (int, float):
        return None
    return value if isfinite(value) and value >= 0 else None


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


class _ProviderResult:
    def __init__(self, data: Any = None, failed: bool = False):
        self.data = data
        self.failed = failed


def _fetch_course(client: Any, course_id: int) -> _ProviderResult:
    try:
        return _ProviderResult(client.connectapi(f"/course-service/course/{course_id}"))
    except Exception:
        return _ProviderResult(failed=True)


def _read_mapping_value(data: Mapping[str, Any], key: str) -> tuple[bool, Any]:
    """Read one allowlisted provider key without exposing provider failures."""
    try:
        return True, data.get(key)
    except Exception:
        return False, None


def get_course_details_service(client: Any, course_id: Any) -> dict[str, Any]:
    """Return a bounded course summary for a validated request identifier."""
    validated_id = _parse_course_id(course_id)
    if validated_id is None:
        return _error("invalid_course_id")
    if client is None:
        return _error("client_unavailable")

    provider_result = _fetch_course(client, validated_id)
    if provider_result.failed:
        return _error("course_unavailable")

    data = provider_result.data
    if data is None:
        return _error("course_not_found")
    if not isinstance(data, Mapping):
        return _error("invalid_course_response")
    try:
        is_empty = len(data) == 0
    except Exception:
        return _error("invalid_course_response")
    if is_empty:
        return _error("course_not_found")

    provider_id_read, provider_id = _read_mapping_value(data, "courseId")
    if (
        not provider_id_read
        or
        type(provider_id) is not int
        or provider_id <= 0
        or provider_id > MAX_SAFE_COURSE_ID
        or provider_id != validated_id
    ):
        return _error("invalid_course_response")

    course = _course_template(validated_id)
    warnings: list[dict[str, str]] = []

    name_read, raw_name = _read_mapping_value(data, "courseName")
    if not name_read:
        return _error("invalid_course_response")
    name = _text(raw_name)
    if name is None:
        warnings.append(_warning("course_name_unavailable"))
    else:
        course["name"] = name

    activity_read, activity_id = _read_mapping_value(data, "activityTypePk")
    if not activity_read:
        return _error("invalid_course_response")
    if type(activity_id) is not int or activity_id not in _ACTIVITY_BY_ID:
        warnings.append(_warning("activity_type_unavailable"))
    else:
        course["activity"] = _ACTIVITY_BY_ID[activity_id]

    metric_fields = (
        ("distanceMeter", "distance_m"),
        ("elevationGainMeter", "elevation_gain_m"),
        ("elevationLossMeter", "elevation_loss_m"),
    )
    invalid_metric = False
    for source_key, output_key in metric_fields:
        metric_read, raw_metric = _read_mapping_value(data, source_key)
        if not metric_read:
            return _error("invalid_course_response")
        metric = _metric(raw_metric)
        if metric is None:
            invalid_metric = True
        else:
            course[output_key] = metric
    if invalid_metric:
        warnings.append(_warning("invalid_course_metric"))

    return {
        "status": "partial_success" if warnings else "success",
        "error": None,
        "course": course,
        "warnings": warnings,
    }
