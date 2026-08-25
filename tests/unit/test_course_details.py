import json
import math
import sys
from collections.abc import Mapping

import pytest

from garmin_mcp.course_details import (
    MAX_COURSE_METRIC,
    _parse_course_id,
    get_course_details_service,
)


class RecordingClient:
    def __init__(self, response=None, failure=None):
        self.response = response
        self.failure = failure
        self.calls = []

    def connectapi(self, path):
        self.calls.append(path)
        if self.failure is not None:
            raise self.failure
        return self.response

    def __getattr__(self, name):
        raise AssertionError(f"forbidden Garmin access: {name}")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, 1),
        (9007199254740991, 9007199254740991),
        ("1", 1),
        ("  123  ", 123),
        (" " + ("0" * 61) + "1" + " ", 1),
    ],
)
def test_course_id_accepts_positive_int_and_trimmed_ascii_decimal(value, expected):
    assert _parse_course_id(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        1.0,
        0,
        -1,
        "",
        "   ",
        "+1",
        "-1",
        "1e2",
        "١",
        "12.0",
        "9" * 65,
        9007199254740992,
        "9" * 64,
        "1 2",
    ],
)
def test_course_id_rejects_nonconservative_values_without_io(value):
    client = RecordingClient()
    result = get_course_details_service(client, value)
    assert result == {
        "status": "error",
        "error": {
            "code": "invalid_course_id",
            "message": "course_id must be a positive integer or decimal string.",
        },
        "course": None,
        "warnings": [],
    }
    assert client.calls == []


def test_unavailable_client_returns_fixed_error_without_io():
    result = get_course_details_service(None, 123)
    assert result == {
        "status": "error",
        "error": {
            "code": "client_unavailable",
            "message": "Garmin client is unavailable. Authenticate with garmin-mcp-auth and restart the server.",
        },
        "course": None,
        "warnings": [],
    }


def test_provider_calls_exact_detail_endpoint_once():
    client = RecordingClient({"courseId": 123})

    get_course_details_service(client, 123)

    assert client.calls == ["/course-service/course/123"]


def test_provider_failure_returns_fixed_course_unavailable():
    client = RecordingClient(failure=RuntimeError("https://private/?token=sentinel request-id=secret"))

    result = get_course_details_service(client, 123)

    assert result == {
        "status": "error",
        "error": {
            "code": "course_unavailable",
            "message": "Course data is unavailable. Check the course ID, re-run garmin-mcp-auth if the session expired, or retry later.",
        },
        "course": None,
        "warnings": [],
    }
    assert "private" not in json.dumps(result)
    assert "sentinel" not in json.dumps(result)
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("response", [None, {}])
def test_none_and_empty_mapping_are_course_not_found(response):
    client = RecordingClient(response=response)

    result = get_course_details_service(client, 123)

    assert result == {
        "status": "error",
        "error": {
            "code": "course_not_found",
            "message": "No course data was found for the requested course ID.",
        },
        "course": None,
        "warnings": [],
    }
    assert client.calls == ["/course-service/course/123"]


@pytest.mark.parametrize("response", [[], (), "raw-provider-value", 42])
def test_non_mapping_root_is_invalid_course_response(response):
    client = RecordingClient(response=response)

    result = get_course_details_service(client, 123)

    assert result == {
        "status": "error",
        "error": {
            "code": "invalid_course_response",
            "message": "Course data had an unexpected shape.",
        },
        "course": None,
        "warnings": [],
    }
    assert "raw-provider-value" not in json.dumps(result)


class GuardedMapping(Mapping):
    def __init__(self, values):
        self._values = values

    def __getitem__(self, key):
        if key not in {"courseId", "courseName", "activityTypePk", "distanceMeter", "elevationGainMeter", "elevationLossMeter"}:
            raise AssertionError(f"forbidden provider key: {key}")
        return self._values[key]

    def __iter__(self):
        raise AssertionError("provider mapping must not be recursively iterated")

    def __len__(self):
        return len(self._values)


def test_mapping_subclass_is_accepted_without_recursive_inspection():
    client = RecordingClient(
        GuardedMapping(
            {
                "courseId": 123,
                "courseName": "Canal Loop",
                "activityTypePk": 1,
                "distanceMeter": 10000.0,
                "elevationGainMeter": 120.0,
                "elevationLossMeter": 115.0,
            }
        )
    )

    result = get_course_details_service(client, 123)

    assert result["status"] == "success"
    assert result["course"]["course_id"] == 123


@pytest.mark.parametrize(
    "provider_id",
    [None, True, 0, -1, 9007199254740992, 123.0, "123", 124],
)
def test_missing_invalid_and_mismatched_provider_course_id_are_invalid(provider_id):
    response = {"courseName": "Course without an ID"} if provider_id is None else {"courseId": provider_id}
    client = RecordingClient(response=response)

    result = get_course_details_service(client, 123)

    assert result == {
        "status": "error",
        "error": {
            "code": "invalid_course_response",
            "message": "Course data had an unexpected shape.",
        },
        "course": None,
        "warnings": [],
    }


class FailingLengthMapping(Mapping):
    def __len__(self):
        raise RuntimeError("https://private.example/course?token=length-secret sentinel=length")

    def __iter__(self):
        raise AssertionError("provider mapping must not be recursively iterated")

    def __getitem__(self, key):
        raise AssertionError(f"unexpected provider key: {key}")


def test_mapping_length_failure_returns_fixed_invalid_response_without_leakage():
    client = RecordingClient(FailingLengthMapping())

    result = get_course_details_service(client, 123)

    assert result == {
        "status": "error",
        "error": {
            "code": "invalid_course_response",
            "message": "Course data had an unexpected shape.",
        },
        "course": None,
        "warnings": [],
    }
    serialized = json.dumps(result)
    assert "length-secret" not in serialized
    assert "sentinel=length" not in serialized


class FailingAccessMapping(Mapping):
    _values = {
        "courseId": 123,
        "courseName": "Course",
        "activityTypePk": 1,
        "distanceMeter": 10.0,
        "elevationGainMeter": 20.0,
        "elevationLossMeter": 30.0,
    }

    def __init__(self, failing_key):
        self.failing_key = failing_key

    def __len__(self):
        return len(self._values)

    def __iter__(self):
        raise AssertionError("provider mapping must not be recursively iterated")

    def __getitem__(self, key):
        if key == self.failing_key:
            raise RuntimeError(
                f"https://private.example/course?token={key}-secret sentinel={key}-sentinel"
            )
        return self._values[key]


@pytest.mark.parametrize(
    "failing_key",
    ["courseId", "courseName", "activityTypePk", "distanceMeter", "elevationGainMeter", "elevationLossMeter"],
)
def test_mapping_allowlisted_key_failure_returns_fixed_invalid_response_without_leakage(failing_key):
    client = RecordingClient(FailingAccessMapping(failing_key))

    result = get_course_details_service(client, 123)

    assert result == {
        "status": "error",
        "error": {
            "code": "invalid_course_response",
            "message": "Course data had an unexpected shape.",
        },
        "course": None,
        "warnings": [],
    }
    serialized = json.dumps(result)
    assert f"{failing_key}-secret" not in serialized
    assert f"{failing_key}-sentinel" not in serialized


@pytest.mark.parametrize(
    ("activity_id", "activity"),
    [
        (1, "running"),
        (2, "cycling"),
        (3, "hiking"),
        (4, "gravel_cycling"),
        (5, "mountain_biking"),
        (6, "trail_running"),
        (9, "walking"),
        (10, "road_biking"),
    ],
)
def test_activity_type_maps_every_existing_upload_id(activity_id, activity):
    client = RecordingClient(
        {
            "courseId": 123,
            "courseName": "Course",
            "activityTypePk": activity_id,
            "distanceMeter": 1.0,
            "elevationGainMeter": 1.0,
            "elevationLossMeter": 1.0,
        }
    )

    result = get_course_details_service(client, 123)

    assert result["status"] == "success"
    assert result["course"]["activity"] == activity
    assert set(result["course"]) == {
        "course_id",
        "name",
        "activity",
        "distance_m",
        "elevation_gain_m",
        "elevation_loss_m",
    }


@pytest.mark.parametrize("activity_id", [True, 1.0, "1", 0, 999, None])
def test_activity_type_requires_exact_int_and_known_id(activity_id):
    client = RecordingClient(
        {
            "courseId": 123,
            "courseName": "Course",
            "activityTypePk": activity_id,
            "distanceMeter": 1.0,
            "elevationGainMeter": 1.0,
            "elevationLossMeter": 1.0,
        }
    )

    result = get_course_details_service(client, 123)

    assert result["status"] == "partial_success"
    assert result["course"]["activity"] is None
    assert result["warnings"] == [
        {
            "code": "activity_type_unavailable",
            "message": "Course activity type is unavailable.",
        }
    ]


@pytest.mark.parametrize(
    ("course_name", "expected_name"),
    [
        ("A", "A"),
        ("N" * 256, "N" * 256),
        ("  Canal Loop  ", "Canal Loop"),
    ],
)
def test_course_name_is_trimmed_and_limited(course_name, expected_name):
    client = RecordingClient(
        {
            "courseId": 123,
            "courseName": course_name,
            "activityTypePk": 1,
            "distanceMeter": 1.0,
            "elevationGainMeter": 1.0,
            "elevationLossMeter": 1.0,
        }
    )

    result = get_course_details_service(client, 123)

    assert result["status"] == "success"
    assert result["course"]["name"] == expected_name
    assert result["warnings"] == []


@pytest.mark.parametrize("course_name", ["", "   ", "X" * 257, None, 123, True])
def test_invalid_course_names_are_partial_with_one_warning(course_name):
    client = RecordingClient(
        {
            "courseId": 123,
            "courseName": course_name,
            "activityTypePk": 1,
            "distanceMeter": 1.0,
            "elevationGainMeter": 1.0,
            "elevationLossMeter": 1.0,
        }
    )

    result = get_course_details_service(client, 123)

    assert result["status"] == "partial_success"
    assert result["course"]["name"] is None
    assert result["warnings"] == [
        {
            "code": "course_name_unavailable",
            "message": "Course name is unavailable.",
        }
    ]


@pytest.mark.parametrize(
    "metric_value",
    [0, 12, 12.5, sys.float_info.max, math.nextafter(sys.float_info.max, 0.0)],
)
@pytest.mark.parametrize("metric_key", ["distanceMeter", "elevationGainMeter", "elevationLossMeter"])
def test_metrics_accept_finite_nonnegative_int_or_float(metric_key, metric_value):
    client = RecordingClient(
        {
            "courseId": 123,
            "courseName": "Course",
            "activityTypePk": 1,
            "distanceMeter": 1.0,
            "elevationGainMeter": 1.0,
            "elevationLossMeter": 1.0,
            metric_key: metric_value,
        }
    )

    result = get_course_details_service(client, 123)

    output_key = {
        "distanceMeter": "distance_m",
        "elevationGainMeter": "elevation_gain_m",
        "elevationLossMeter": "elevation_loss_m",
    }[metric_key]
    assert result["status"] == "success"
    assert result["course"][output_key] == metric_value
    assert result["warnings"] == []


def test_metric_bound_is_ieee754_binary64_finite_maximum():
    assert MAX_COURSE_METRIC == sys.float_info.max


@pytest.mark.parametrize("bad_metric", [True, float("nan"), float("inf"), -1, "12", None, object()])
def test_metrics_reject_bool_nan_infinity_negative_and_other_types(bad_metric):
    client = RecordingClient(
        {
            "courseId": 123,
            "courseName": "Course",
            "activityTypePk": 1,
            "distanceMeter": bad_metric,
            "elevationGainMeter": bad_metric,
            "elevationLossMeter": bad_metric,
        }
    )

    result = get_course_details_service(client, 123)

    assert result["status"] == "partial_success"
    assert result["course"]["distance_m"] is None
    assert result["course"]["elevation_gain_m"] is None
    assert result["course"]["elevation_loss_m"] is None
    assert result["warnings"] == [
        {
            "code": "invalid_course_metric",
            "message": "One or more course distance or elevation metrics are unavailable.",
        }
    ]


@pytest.mark.parametrize(
    ("metric_key", "output_key", "retained_values"),
    [
        ("distanceMeter", "distance_m", {"elevation_gain_m": 20.0, "elevation_loss_m": 30.0}),
        ("elevationGainMeter", "elevation_gain_m", {"distance_m": 10.0, "elevation_loss_m": 30.0}),
        ("elevationLossMeter", "elevation_loss_m", {"distance_m": 10.0, "elevation_gain_m": 20.0}),
    ],
)
@pytest.mark.parametrize(
    "bad_metric",
    [True, float("nan"), float("inf"), float("-inf"), -1, "12", None, object(), 10**309],
)
def test_one_malformed_metric_preserves_other_metrics_and_one_warning(
    metric_key, output_key, retained_values, bad_metric
):
    response = {
        "courseId": 123,
        "courseName": "Course",
        "activityTypePk": 1,
        "distanceMeter": 10.0,
        "elevationGainMeter": 20.0,
        "elevationLossMeter": 30.0,
        metric_key: bad_metric,
    }
    client = RecordingClient(response)

    result = get_course_details_service(client, 123)

    assert result["status"] == "partial_success"
    assert result["course"][output_key] is None
    for retained_key, retained_value in retained_values.items():
        assert result["course"][retained_key] == retained_value
    assert result["warnings"] == [
        {
            "code": "invalid_course_metric",
            "message": "One or more course distance or elevation metrics are unavailable.",
        }
    ]


def test_warning_order_is_name_activity_metric():
    client = RecordingClient(
        {
            "courseId": 123,
            "courseName": " ",
            "activityTypePk": 999,
            "distanceMeter": -1,
            "elevationGainMeter": float("nan"),
            "elevationLossMeter": True,
        }
    )

    result = get_course_details_service(client, 123)

    assert result["status"] == "partial_success"
    assert [warning["code"] for warning in result["warnings"]] == [
        "course_name_unavailable",
        "activity_type_unavailable",
        "invalid_course_metric",
    ]


class HostileGeometry:
    def __iter__(self):
        raise AssertionError("geometry must not be iterated")

    def __len__(self):
        raise AssertionError("geometry must not be sized")

    def __str__(self):
        raise AssertionError("geometry must not be stringified")

    def __repr__(self):
        raise AssertionError("geometry must not be represented")


def test_projection_excludes_all_private_and_geometry_fields():
    sentinel = "private-course-details-sentinel"
    response = {
        "courseId": 123,
        "courseName": "Canal Loop",
        "activityTypePk": 1,
        "distanceMeter": 10000.0,
        "elevationGainMeter": 120.0,
        "elevationLossMeter": 115.0,
        "geoPoints": HostileGeometry(),
        "courseLines": HostileGeometry(),
        "coursePoints": HostileGeometry(),
        "boundingBox": {"latitude": sentinel, "longitude": sentinel},
        "startPoint": {"latitude": sentinel, "longitude": sentinel},
        "userProfilePk": sentinel,
        "userGroupPk": sentinel,
        "ownerName": sentinel,
        "profileName": sentinel,
        "groupName": sentinel,
        "firstName": sentinel,
        "lastName": sentinel,
        "description": sentinel,
        "notes": sentinel,
        "url": sentinel,
    }
    client = RecordingClient(response)

    result = get_course_details_service(client, 123)
    serialized = json.dumps(result)

    assert result["status"] == "success"
    assert result["course"] == {
        "course_id": 123,
        "name": "Canal Loop",
        "activity": "running",
        "distance_m": 10000.0,
        "elevation_gain_m": 120.0,
        "elevation_loss_m": 115.0,
    }
    for forbidden in (
        "geoPoints",
        "courseLines",
        "coursePoints",
        "boundingBox",
        "startPoint",
        "userProfilePk",
        "userGroupPk",
        "ownerName",
        "profileName",
        "groupName",
        "firstName",
        "lastName",
        "description",
        "notes",
        "url",
        sentinel,
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "course_points",
    [None, object(), [], [HostileGeometry()]],
)
def test_geometry_shape_and_size_do_not_change_status_or_warnings(course_points):
    client = RecordingClient(
        {
            "courseId": 123,
            "courseName": "Canal Loop",
            "activityTypePk": 1,
            "distanceMeter": 10000.0,
            "elevationGainMeter": 120.0,
            "elevationLossMeter": 115.0,
            "coursePoints": course_points,
            "geoPoints": HostileGeometry(),
            "courseLines": HostileGeometry(),
        }
    )

    result = get_course_details_service(client, 123)

    assert result == {
        "status": "success",
        "error": None,
        "course": {
            "course_id": 123,
            "name": "Canal Loop",
            "activity": "running",
            "distance_m": 10000.0,
            "elevation_gain_m": 120.0,
            "elevation_loss_m": 115.0,
        },
        "warnings": [],
    }
