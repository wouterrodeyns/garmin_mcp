"""Compatibility contract for the pinned GarminConnect client."""

from importlib.metadata import version
from inspect import Parameter, signature

from garminconnect import Garmin


REQUIRED_METHODS = {
    "connectapi",
    "delete_workout",
    "download_activity",
    "get_activities",
    "get_activities_by_date",
    "get_activity",
    "get_activity_exercise_sets",
    "get_activity_hr_in_timezones",
    "get_activity_power_in_timezones",
    "get_activity_splits",
    "get_hrv_data",
    "get_sleep_data",
    "get_training_readiness",
    "get_user_summary",
    "get_workouts",
    "login",
    "query_garmin_graphql",
    "schedule_workout",
    "unschedule_workout",
    "upload_workout",
}


def test_installed_garminconnect_version_is_pinned() -> None:
    assert version("garminconnect") == "0.3.10"


def test_high_value_garmin_methods_remain_available() -> None:
    missing = sorted(
        name for name in REQUIRED_METHODS if not callable(getattr(Garmin, name, None))
    )
    assert missing == []


def test_connectapi_accepts_separate_request_parameters() -> None:
    parameters = signature(Garmin.connectapi).parameters.values()

    assert any(parameter.kind is Parameter.VAR_KEYWORD for parameter in parameters)
