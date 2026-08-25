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
