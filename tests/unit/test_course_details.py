import json
from collections.abc import Mapping

import pytest

from garmin_mcp.course_details import _parse_course_id, get_course_details_service


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
    [None, True, 0, -1, 9007199254740992, "123", 124],
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
