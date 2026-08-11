"""Contract tests for the bounded, read-only activity provider seams."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from garmin_mcp.ai_activity.providers import (
    CYCLING_TYPE_KEYS,
    MAX_RETURNED_SPLITS,
    RUNNING_TYPE_KEYS,
    STRENGTH_TYPE_KEYS,
    WALKING_TYPE_KEYS,
    ProviderResult,
    get_activity,
    get_heart_rate_zones,
    get_power_zones,
    get_splits,
    get_strength,
)


class RecordingReadOnlyClient:
    """Client test double that rejects any method outside the pinned reads."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.activity = {"activityId": 42, "opaque": object()}
        self.splits = {"lapDTOs": [{"lapNumber": 1}]}
        self.heart_rate_zones = [{"zoneNumber": 1}]
        self.power_zones = [{"zoneNumber": 1}]
        self.strength = {"exercises": [{"sets": []}]}

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"unexpected client attribute: {name}")

    def get_activity(self, activity_id: int) -> object:
        self.calls.append(("activity", activity_id))
        return self.activity

    def get_activity_splits(self, activity_id: int) -> object:
        self.calls.append(("splits", activity_id))
        return self.splits

    def get_activity_hr_in_timezones(self, activity_id: int) -> object:
        self.calls.append(("heart_rate_zones", activity_id))
        return self.heart_rate_zones

    def get_activity_power_in_timezones(self, activity_id: int) -> object:
        self.calls.append(("power_zones", activity_id))
        return self.power_zones

    def get_activity_exercise_sets(self, activity_id: int) -> object:
        self.calls.append(("strength", activity_id))
        return self.strength


def test_provider_methods_call_only_pinned_client_methods_in_fixed_order_and_preserve_raw_data():
    client = RecordingReadOnlyClient()

    results = (
        get_activity(client, 42),
        get_splits(client, 42),
        get_heart_rate_zones(client, 42),
        get_power_zones(client, 42),
        get_strength(client, 42),
    )

    assert [result.data for result in results] == [
        client.activity,
        client.splits,
        client.heart_rate_zones,
        client.power_zones,
        client.strength,
    ]
    assert [result.data is raw for result, raw in zip(results, [
        client.activity,
        client.splits,
        client.heart_rate_zones,
        client.power_zones,
        client.strength,
    ])] == [True] * 5
    assert client.calls == [
        ("activity", 42),
        ("splits", 42),
        ("heart_rate_zones", 42),
        ("power_zones", 42),
        ("strength", 42),
    ]


@pytest.mark.parametrize(
    ("reader", "method_name"),
    [
        (get_activity, "get_activity"),
        (get_splits, "get_activity_splits"),
        (get_heart_rate_zones, "get_activity_hr_in_timezones"),
        (get_power_zones, "get_activity_power_in_timezones"),
        (get_strength, "get_activity_exercise_sets"),
    ],
)
def test_each_provider_exception_returns_empty_failed_result_without_exception_text(
    reader, method_name: str
):
    secret = "token=secret@example.com https://private.example/request/123"

    class FailingClient(RecordingReadOnlyClient):
        def __getattribute__(self, name: str) -> object:
            if name == method_name:
                def raise_secret(_activity_id: int) -> object:
                    raise RuntimeError(secret)

                return raise_secret
            return super().__getattribute__(name)

    result = reader(FailingClient(), 7)

    assert result == ProviderResult(data=None, failed=True)
    assert result.data is None
    assert result.failed is True
    assert secret not in repr(result)
    assert "secret@example.com" not in str(result)
    assert "private.example" not in repr(result)


def test_provider_result_is_frozen_and_has_no_exception_field():
    result = ProviderResult(data={"raw": True})

    assert result.failed is False
    assert set(result.__dataclass_fields__) == {"data", "failed"}
    with pytest.raises(FrozenInstanceError):
        result.failed = True


def test_public_activity_constants_match_the_exact_contract():
    assert RUNNING_TYPE_KEYS == frozenset({"running", "trail_running", "treadmill_running"})
    assert WALKING_TYPE_KEYS == frozenset({"walking", "treadmill_walking"})
    assert CYCLING_TYPE_KEYS == frozenset(
        {"cycling", "indoor_cycling", "road_biking", "mountain_biking", "gravel_cycling"}
    )
    assert STRENGTH_TYPE_KEYS == frozenset({"strength_training"})
    assert MAX_RETURNED_SPLITS == 100
