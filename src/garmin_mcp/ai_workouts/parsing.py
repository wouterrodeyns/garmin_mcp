"""Primitive parsers for the friendly workout DSL.

The parser registries are intentionally ordinary dictionaries: downstream
compiler code can add a new normalized end condition or target without
changing the validation entry point.
"""

from __future__ import annotations

from datetime import date
import re
from collections.abc import Callable
from typing import Any


_POSITIVE_NUMBER = r"(?:\d+(?:\.\d+)?|\.\d+)"
_DURATION_RE = re.compile(rf"\A({_POSITIVE_NUMBER})([smh])\Z")
_DISTANCE_RE = re.compile(rf"\A({_POSITIVE_NUMBER})(m|km)\Z")
_PACE_RE = re.compile(r"\A(\d+):(\d{2})-(\d+):(\d{2})/km\Z")
_HEART_RATE_RE = re.compile(rf"\A({_POSITIVE_NUMBER})-({_POSITIVE_NUMBER})bpm\Z")
_POWER_RE = re.compile(rf"\A({_POSITIVE_NUMBER})-({_POSITIVE_NUMBER})W\Z")
_ZONE_RE = re.compile(r"\AZ([0-9]+)\Z", re.IGNORECASE)


def _positive_string_number(value: Any, pattern: re.Pattern[str], field: str) -> re.Match[str]:
    if not isinstance(value, str):
        raise ValueError(f"invalid {field}: expected a string")
    match = pattern.fullmatch(value)
    if match is None:
        raise ValueError(f"invalid {field}: expected a positive value")
    if float(match.group(1)) <= 0:
        raise ValueError(f"invalid {field}: value must be positive")
    return match


def parse_duration(value: Any) -> float:
    """Parse a positive seconds, minutes, or hours duration into seconds."""

    match = _positive_string_number(value, _DURATION_RE, "duration")
    multiplier = {"s": 1.0, "m": 60.0, "h": 3600.0}[match.group(2)]
    return float(match.group(1)) * multiplier


def parse_distance(value: Any) -> float:
    """Parse a positive metre or kilometre distance into metres."""

    match = _positive_string_number(value, _DISTANCE_RE, "distance")
    multiplier = 1000.0 if match.group(2) == "km" else 1.0
    return float(match.group(1)) * multiplier


def parse_pace(value: Any) -> tuple[float, float]:
    """Parse a minutes-per-kilometre range into faster/slower metres per second."""

    if not isinstance(value, str):
        raise ValueError("invalid pace: expected M:SS-M:SS/km")
    match = _PACE_RE.fullmatch(value)
    if match is None:
        raise ValueError("invalid pace: expected M:SS-M:SS/km")
    first_minutes, first_seconds = int(match.group(1)), int(match.group(2))
    second_minutes, second_seconds = int(match.group(3)), int(match.group(4))
    if first_seconds > 59 or second_seconds > 59:
        raise ValueError("invalid pace: seconds must be between 00 and 59")
    first_total = first_minutes * 60 + first_seconds
    second_total = second_minutes * 60 + second_seconds
    if first_total <= 0 or second_total <= 0:
        raise ValueError("invalid pace: pace must be positive")
    if first_total > second_total:
        raise ValueError("invalid pace: first pace must be faster or equal to second pace")
    return (1000.0 / first_total, 1000.0 / second_total)


def _parse_range(value: Any, pattern: re.Pattern[str], field: str, unit: str) -> tuple[float, float]:
    if not isinstance(value, str):
        raise ValueError(f"invalid {field}: expected low-high{unit}")
    match = pattern.fullmatch(value)
    if match is None:
        raise ValueError(f"invalid {field}: expected low-high{unit}")
    low, high = float(match.group(1)), float(match.group(2))
    if low <= 0 or high <= 0:
        raise ValueError(f"invalid {field}: values must be positive")
    if low >= high:
        raise ValueError(f"invalid {field}: low must be less than high")
    return low, high


def parse_heart_rate(value: Any) -> tuple[float, float]:
    """Parse a positive, increasing beats-per-minute range."""

    return _parse_range(value, _HEART_RATE_RE, "heart rate", "bpm")


def parse_power(value: Any) -> tuple[float, float]:
    """Parse a positive, increasing watt range."""

    return _parse_range(value, _POWER_RE, "power", "W")


def parse_zone(value: Any, maximum: int, field: str) -> int:
    """Parse an integer zone written as ``Z3`` or as an integer."""

    if isinstance(value, bool):
        raise ValueError(f"invalid {field}: expected an integer zone")
    if isinstance(value, int):
        zone = value
    elif isinstance(value, str):
        match = _ZONE_RE.fullmatch(value)
        if match is None:
            raise ValueError(f"invalid {field}: expected Z1-Z{maximum} or an integer")
        zone = int(match.group(1))
    else:
        raise ValueError(f"invalid {field}: expected Z1-Z{maximum} or an integer")
    if not 1 <= zone <= maximum:
        raise ValueError(f"invalid {field}: zone must be between 1 and {maximum}")
    return zone


def parse_reps(value: Any) -> int:
    """Parse a positive repetition count, excluding booleans."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("invalid reps: expected a positive integer")
    return value


def parse_lap_button(value: Any) -> None:
    """Parse the open-ended lap-button marker and normalize it to no value."""

    if value is not True:
        raise ValueError("invalid lap_button: only true is supported")
    return None


def parse_date(value: Any) -> date:
    """Parse a canonical, valid ISO calendar date."""

    if not isinstance(value, str):
        raise ValueError("invalid schedule_date: expected YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid schedule_date: expected a valid YYYY-MM-DD date") from exc
    if parsed.isoformat() != value:
        raise ValueError("invalid schedule_date: expected canonical YYYY-MM-DD")
    return parsed


END_CONDITION_PARSERS: dict[str, Callable[[Any], Any]] = {
    "duration": parse_duration,
    "distance": parse_distance,
    "reps": parse_reps,
    "lap_button": parse_lap_button,
}

TARGET_PARSERS: dict[str, Callable[[Any], Any]] = {
    "pace": parse_pace,
    "heart_rate_zone": lambda value: parse_zone(value, 5, "heart_rate_zone"),
    "heart_rate": parse_heart_rate,
    "power_zone": lambda value: parse_zone(value, 7, "power_zone"),
    "power": parse_power,
}
