"""Bounded, read-only Garmin data providers for training context assembly."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from math import ceil
from typing import Any


RUNNING_TYPE_KEYS = frozenset({"running", "trail_running", "treadmill_running"})
PAGE_SIZE = 200
MAX_ACTIVITY_RECORDS = 1000


@dataclass(frozen=True)
class ProviderResult:
    """A provider response plus safe, user-facing failure metadata."""

    data: Any
    failed: bool = False
    truncated: bool = False
    warnings: tuple[dict[str, str], ...] = ()


def activity_cap(days: int) -> int:
    """Return the bounded number of activity records for a date period."""
    return min(MAX_ACTIVITY_RECORDS, PAGE_SIZE * ceil(max(PAGE_SIZE, days * 10) / PAGE_SIZE))


def _warning(provider: str, code: str, message: str) -> tuple[dict[str, str], ...]:
    return ({"provider": provider, "code": code, "message": message},)


def _invalid_activities_result(data: tuple[Any, ...] = ()) -> ProviderResult:
    return ProviderResult(
        data=data,
        failed=True,
        truncated=bool(data),
        warnings=_warning(
            "activities",
            "invalid_provider_response",
            "Activity history response had an unexpected shape.",
        ),
    )


def _unavailable_activities_result(data: tuple[Any, ...] = ()) -> ProviderResult:
    if data:
        return ProviderResult(
            data=data,
            failed=True,
            truncated=True,
            warnings=_warning(
                "activities",
                "provider_unavailable",
                "Activity history is incomplete because a later page was unavailable.",
            ),
        )
    return ProviderResult(
        data=(),
        failed=True,
        warnings=_warning(
            "activities",
            "provider_unavailable",
            "Activity history is currently unavailable.",
        ),
    )


def _truncated_activities_result(data: tuple[Any, ...]) -> ProviderResult:
    cap = len(data)
    return ProviderResult(
        data=data,
        truncated=True,
        warnings=_warning(
            "activities",
            "activities_truncated",
            f"Activity history was limited to {cap} records; period totals are lower bounds.",
        ),
    )


def _activity_items(raw: Any) -> tuple[Any, ...]:
    """Normalize the documented activity response roots without coercion."""
    if raw is None:
        return ()
    if raw == {}:
        return ()
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict) and isinstance(raw.get("activityList"), list):
        items = raw["activityList"]
    else:
        raise ValueError("unexpected activity response")
    if not all(isinstance(item, dict) for item in items):
        raise ValueError("activity list contains a non-object item")
    return tuple(items)


def _activity_page(client: Any, params: dict[str, str]) -> tuple[Any, ...]:
    raw = client.connectapi(client.garmin_connect_activities, params=params)
    return _activity_items(raw)


def _period_page_params(start_date: str, end_date: str, start: int) -> dict[str, str]:
    return {
        "startDate": start_date,
        "endDate": end_date,
        "start": str(start),
        "limit": str(PAGE_SIZE),
        "sortOrder": "desc",
    }


def _last_run_page_params(start: int) -> dict[str, str]:
    return {"start": str(start), "limit": str(PAGE_SIZE), "sortOrder": "desc"}


def get_period_activities(
    client: Any, start_date: str, end_date: str, days: int
) -> ProviderResult:
    """Fetch a capped activity history for a specific period."""
    cap = activity_cap(days)
    activities: list[Any] = []
    for start in range(0, cap, PAGE_SIZE):
        try:
            page = _activity_page(client, _period_page_params(start_date, end_date, start))
        except ValueError:
            return _invalid_activities_result(tuple(activities))
        except Exception:
            return _unavailable_activities_result(tuple(activities))

        remaining = cap - len(activities)
        activities.extend(page[:remaining])
        if len(page) < PAGE_SIZE:
            return ProviderResult(data=tuple(activities))

    return _truncated_activities_result(tuple(activities))


def _is_running_activity(activity: Any) -> bool:
    if not isinstance(activity, dict):
        return False
    activity_type = activity.get("activityType")
    return isinstance(activity_type, dict) and activity_type.get("typeKey") in RUNNING_TYPE_KEYS


def _local_start_timestamp(activity: dict[str, Any]) -> float | None:
    """Return a sortable local start timestamp when Garmin supplied one."""
    value = activity.get("startTimeLocal")
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def _newest_running_activity(page: tuple[Any, ...]) -> dict[str, Any] | None:
    """Pick the newest parseable running item, with stable page-order fallback."""
    matches = [item for item in page if _is_running_activity(item)]
    if not matches:
        return None

    def sort_key(indexed: tuple[int, dict[str, Any]]) -> tuple[bool, float, int]:
        position, activity = indexed
        timestamp = _local_start_timestamp(activity)
        return (
            timestamp is not None,
            timestamp if timestamp is not None else float("-inf"),
            -position,
        )

    return max(
        enumerate(matches),
        key=sort_key,
    )[1]


def get_last_run(client: Any) -> ProviderResult:
    """Find the most recent running activity without server-side type filtering."""
    for start in range(0, MAX_ACTIVITY_RECORDS, PAGE_SIZE):
        try:
            page = _activity_page(client, _last_run_page_params(start))
        except ValueError:
            return ProviderResult(
                data=None,
                failed=True,
                truncated=start > 0,
                warnings=_warning(
                    "last_run",
                    "invalid_provider_response",
                    "Activity history response had an unexpected shape.",
                ),
            )
        except Exception:
            return ProviderResult(
                data=None,
                failed=True,
                truncated=start > 0,
                warnings=_warning(
                    "last_run",
                    "provider_unavailable",
                    "Activity history is currently unavailable.",
                ),
            )

        newest_running = _newest_running_activity(page)
        if newest_running is not None:
            return ProviderResult(data=newest_running)
        if len(page) < PAGE_SIZE:
            return ProviderResult(data=None)

    return ProviderResult(
        data=None,
        truncated=True,
        warnings=_warning(
            "last_run",
            "activities_truncated",
            "Latest-run search reached the 1000-record limit and was inconclusive.",
        ),
    )


def _invalid_scheduled_workouts() -> ProviderResult:
    return ProviderResult(
        data=(),
        failed=True,
        warnings=_warning(
            "scheduled_workouts",
            "invalid_provider_response",
            "Scheduled workouts response had an unexpected shape.",
        ),
    )


def _unavailable_scheduled_workouts() -> ProviderResult:
    return ProviderResult(
        data=(),
        failed=True,
        warnings=_warning(
            "scheduled_workouts",
            "provider_unavailable",
            "Scheduled workouts are currently unavailable.",
        ),
    )


def get_scheduled_workouts(client: Any, start_date: str, end_date: str) -> ProviderResult:
    """Fetch scheduled-workout summaries through the read-only GraphQL query."""
    query = {
        "query": (
            f'query{{workoutScheduleSummariesScalar(startDate:"{start_date}", '
            f'endDate:"{end_date}")}}'
        )
    }
    try:
        response = client.query_garmin_graphql(query)
    except json.JSONDecodeError:
        return _invalid_scheduled_workouts()
    except Exception:
        return _unavailable_scheduled_workouts()

    if not isinstance(response, dict) or response.get("errors"):
        return _invalid_scheduled_workouts()
    data = response.get("data")
    if not isinstance(data, dict) or "workoutScheduleSummariesScalar" not in data:
        return _invalid_scheduled_workouts()
    workouts = data["workoutScheduleSummariesScalar"]
    if workouts is None:
        return ProviderResult(data=())
    if not isinstance(workouts, list):
        return _invalid_scheduled_workouts()
    return ProviderResult(data=tuple(workouts))


def get_daily_stats(client: Any, date: str) -> Any:
    return client.get_stats(date)


def get_sleep(client: Any, date: str) -> Any:
    return client.get_sleep_data(date)


def get_hrv(client: Any, date: str) -> Any:
    return client.get_hrv_data(date)


def get_training_readiness(client: Any, date: str) -> Any:
    return client.get_morning_training_readiness(date)


def get_training_status(client: Any, date: str) -> Any:
    return client.get_training_status(date)


def get_wellness_heart_rate_day(client: Any, date: str) -> ProviderResult:
    """Fetch one daily wellness-HR DTO through the pinned read-only client."""
    try:
        data = client.get_heart_rates(date)
    except Exception:
        return ProviderResult(
            data=None,
            failed=True,
            warnings=_warning(
                "wellness_heart_rate",
                "provider_unavailable",
                "Wellness heart-rate data is unavailable for this date.",
            ),
        )
    return ProviderResult(data=data)
