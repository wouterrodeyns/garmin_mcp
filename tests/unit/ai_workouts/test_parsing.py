from dataclasses import FrozenInstanceError

import pytest

from garmin_mcp.ai_workouts.parsing import (
    END_CONDITION_PARSERS,
    TARGET_PARSERS,
    parse_date,
    parse_distance,
    parse_duration,
    parse_heart_rate,
    parse_lap_button,
    parse_pace,
    parse_power,
    parse_reps,
    parse_zone,
)
from garmin_mcp.ai_workouts.schema import (
    ActionStep,
    EndCondition,
    RepeatStep,
    Target,
    WorkoutDefinition,
    validate_workout,
)


THRESHOLD_STEPS = [
    {"warmup": {"duration": "15m"}},
    {
        "repeat": 4,
        "steps": [
            {"run": {"duration": "6m", "pace": "4:20-4:30/km"}},
            {"recovery": {"duration": "2m"}},
        ],
    },
    {"cooldown": {"duration": "10m"}},
]


def test_parse_duration_supports_seconds_minutes_and_hours():
    assert parse_duration("90s") == 90.0
    assert parse_duration("15m") == 900.0
    assert parse_duration("1.5h") == 5400.0
    assert parse_duration("24h") == 86400.0


def test_parse_distance_supports_metres_and_kilometres():
    assert parse_distance("800m") == 800.0
    assert parse_distance("5km") == 5000.0
    assert parse_distance("500km") == 500000.0


@pytest.mark.parametrize(
    ("parser", "value", "field"),
    [
        (parse_duration, "24.1h", "duration"),
        (parse_distance, "500.1km", "distance"),
    ],
)
def test_parse_end_conditions_reject_values_above_v1_safety_maxima(parser, value, field):
    with pytest.raises(ValueError, match=field):
        parser(value)


@pytest.mark.parametrize(
    ("parser", "value", "field"),
    [
        (parse_duration, "9" * 400 + "s", "duration"),
        (parse_distance, "9" * 400 + "m", "distance"),
        (parse_heart_rate, "1-" + "9" * 400 + "bpm", "heart rate"),
        (parse_power, "1-" + "9" * 400 + "W", "power"),
    ],
)
def test_parse_numeric_boundaries_reject_non_finite_values(parser, value, field):
    with pytest.raises(ValueError, match=field):
        parser(value)


def test_parse_pace_rejects_extreme_values_with_value_error():
    extreme = "9" * 400
    with pytest.raises(ValueError, match="pace"):
        parse_pace(f"{extreme}:00-{extreme}:01/km")


def test_parse_pace_returns_faster_then_slower_mps():
    assert parse_pace("4:20-4:30/km") == pytest.approx((1000 / 260, 1000 / 270))


def test_parse_pace_allows_equal_bounds():
    assert parse_pace("4:20-4:20/km") == pytest.approx((1000 / 260, 1000 / 260))


def test_parse_ranges_zones_and_date():
    assert parse_heart_rate("150-165bpm") == (150.0, 165.0)
    assert parse_power("220-250W") == (220.0, 250.0)
    assert parse_zone("Z3", maximum=5, field="heart_rate_zone") == 3
    assert parse_zone(7, maximum=7, field="power_zone") == 7
    assert parse_date("2026-08-10").isoformat() == "2026-08-10"


@pytest.mark.parametrize("value", ["15", "m15", "0m", "-2m", "1 minute", True])
def test_parse_duration_rejects_malformed_values(value):
    with pytest.raises(ValueError, match="duration"):
        parse_duration(value)


@pytest.mark.parametrize("value", ["800", "0m", "-1km", "1 kilometre", True])
def test_parse_distance_rejects_malformed_values(value):
    with pytest.raises(ValueError, match="distance"):
        parse_distance(value)


@pytest.mark.parametrize("value", ["4:20/km", "4:70-5:00/km", "4:30-4:20/km", "4:20-5:00/m"])
def test_parse_pace_rejects_malformed_or_inverted_values(value):
    with pytest.raises(ValueError, match="pace"):
        parse_pace(value)


@pytest.mark.parametrize("parser, value, field", [
    (parse_heart_rate, "0-165bpm", "heart rate"),
    (parse_heart_rate, "150-150bpm", "heart rate"),
    (parse_heart_rate, "165-150bpm", "heart rate"),
    (parse_heart_rate, "2-5bpm", "heart rate"),
    (parse_power, "0-250W", "power"),
    (parse_power, "220-220W", "power"),
    (parse_power, "250-220W", "power"),
])
def test_parse_ranges_reject_non_positive_or_inverted_values(parser, value, field):
    with pytest.raises(ValueError, match=field):
        parser(value)


@pytest.mark.parametrize("value", [True, False, "Z0", "Z6", 0, 8, 1.5, "3"])
def test_parse_zone_rejects_bool_non_integer_and_out_of_range_values(value):
    with pytest.raises(ValueError, match="heart_rate_zone"):
        parse_zone(value, maximum=5, field="heart_rate_zone")


@pytest.mark.parametrize("value", [0, -1, 1.5, True, "10"])
def test_parse_reps_requires_positive_integer(value):
    with pytest.raises(ValueError, match="reps"):
        parse_reps(value)


def test_parse_reps_and_lap_button_normalize_values():
    assert parse_reps(10) == 10
    assert parse_lap_button(True) is None
    with pytest.raises(ValueError, match="lap_button"):
        parse_lap_button(False)


@pytest.mark.parametrize("value", ["2026-2-03", "2026-02-30", "2026-08-10T00:00:00"])
def test_parse_date_rejects_noncanonical_or_impossible_values(value):
    with pytest.raises(ValueError, match="schedule_date"):
        parse_date(value)


def test_parser_registries_expose_stable_extension_seams():
    assert set(END_CONDITION_PARSERS) == {"duration", "distance", "reps", "lap_button"}
    assert set(TARGET_PARSERS) == {"pace", "heart_rate_zone", "heart_rate", "power_zone", "power"}


def test_validate_threshold_workout_builds_normalized_steps():
    workout = validate_workout("Threshold 4x6", "running", THRESHOLD_STEPS, "2026-08-10")
    assert workout == WorkoutDefinition(
        name="Threshold 4x6",
        sport="running",
        steps=(
            ActionStep("warmup", EndCondition("duration", 900.0)),
            RepeatStep(
                4,
                (
                    ActionStep(
                        "run",
                        EndCondition("duration", 360.0),
                        Target("pace", values=(1000 / 260, 1000 / 270)),
                    ),
                    ActionStep("recovery", EndCondition("duration", 120.0)),
                ),
            ),
            ActionStep("cooldown", EndCondition("duration", 600.0)),
        ),
        schedule_date="2026-08-10",
    )
    assert isinstance(workout.steps[0], ActionStep)
    assert isinstance(workout.steps[1], RepeatStep)
    assert workout.steps[1].iterations == 4
    assert workout.steps[1].steps[0].target.kind == "pace"


@pytest.mark.parametrize("count", [0, -1, 1.5, True])
def test_validate_rejects_invalid_repeat_count(count):
    with pytest.raises(ValueError, match="repeat"):
        validate_workout(
            "Bad",
            "running",
            [{"repeat": count, "steps": [{"run": {"duration": "1m"}}]}],
        )


def test_validate_allows_repeat_count_at_v1_safety_limit():
    workout = validate_workout(
        "Fifty Repeats",
        "running",
        [{"repeat": 50, "steps": [{"run": {"duration": "1m"}}]}],
    )

    assert workout.steps[0] == RepeatStep(
        50,
        (ActionStep("run", EndCondition("duration", 60.0)),),
    )


def test_validate_rejects_repeat_count_above_v1_safety_limit():
    with pytest.raises(ValueError, match="repeat must not exceed 50"):
        validate_workout(
            "Too Many Repeats",
            "running",
            [{"repeat": 51, "steps": [{"run": {"duration": "1m"}}]}],
        )


def test_validate_rejects_repeat_nested_inside_repeat_group():
    with pytest.raises(ValueError, match="repeat nesting must not exceed 1"):
        validate_workout(
            "Nested Repeats",
            "running",
            [
                {
                    "repeat": 2,
                    "steps": [
                        {
                            "repeat": 2,
                            "steps": [{"run": {"duration": "1m"}}],
                        }
                    ],
                }
            ],
        )


def test_validate_rejects_ambiguous_end_conditions_and_targets():
    with pytest.raises(ValueError, match="exactly one end condition"):
        validate_workout("Bad", "running", [{"run": {"duration": "5m", "distance": "1km"}}])
    with pytest.raises(ValueError, match="at most one target"):
        validate_workout(
            "Bad",
            "running",
            [{"run": {"duration": "5m", "pace": "5:00-5:10/km", "heart_rate_zone": "Z3"}}],
        )


def test_validate_rejects_incompatible_targets_and_metadata():
    with pytest.raises(ValueError, match="power"):
        validate_workout("Bad", "running", [{"run": {"duration": "5m", "power": "220-250W"}}])
    with pytest.raises(ValueError, match="pace"):
        validate_workout("Bad", "walking", [{"work": {"duration": "5m", "pace": "8:00-8:30/km"}}])
    with pytest.raises(ValueError, match="exercise"):
        validate_workout("Bad", "running", [{"run": {"duration": "1m", "exercise": "SQUAT"}}])
    with pytest.raises(ValueError, match="reps"):
        validate_workout("Bad", "running", [{"run": {"reps": 10}}])


def test_validate_strength_keeps_conservative_metadata():
    workout = validate_workout(
        "Strength A",
        "strength",
        [{"work": {"reps": 10, "exercise": "BARBELL_SQUAT", "category": "SQUAT"}}],
    )
    assert workout.sport == "strength"
    assert workout.steps[0].exercise == "BARBELL_SQUAT"
    assert workout.steps[0].category == "SQUAT"


def test_validate_strength_training_alias_and_trimmed_metadata():
    workout = validate_workout(
        "  Strength A  ",
        "strength_training",
        [{"work": {"reps": 10, "exercise": "  BARBELL_SQUAT  ", "category": " SQUAT "}}],
    )
    assert workout.name == "Strength A"
    assert workout.sport == "strength"
    assert workout.steps[0].exercise == "BARBELL_SQUAT"
    assert workout.steps[0].category == "SQUAT"


@pytest.mark.parametrize("value", [None, "", "  "])
def test_validate_requires_nonempty_name(value):
    with pytest.raises(ValueError, match="name"):
        validate_workout(value, "running", [{"run": {"duration": "1m"}}])


@pytest.mark.parametrize("steps", [[], (), None, "not steps"])
def test_validate_requires_nonempty_steps_list(steps):
    with pytest.raises(ValueError, match="steps"):
        validate_workout("Workout", "running", steps)


def test_validate_rejects_unknown_and_conflicting_structural_keys():
    with pytest.raises(ValueError, match="exactly one action key"):
        validate_workout("Bad", "running", [{"run": {"duration": "1m"}, "rest": {"duration": "1m"}}])
    with pytest.raises(ValueError, match="repeat"):
        validate_workout("Bad", "running", [{"repeat": 2, "run": {"duration": "1m"}, "steps": []}])
    with pytest.raises(ValueError, match="unknown"):
        validate_workout("Bad", "running", [{"sprint": {"duration": "1m"}}])


def test_validate_rejects_unknown_action_fields_and_empty_repeat():
    with pytest.raises(ValueError, match="unknown"):
        validate_workout("Bad", "running", [{"run": {"duration": "1m", "cadence": 90}}])
    with pytest.raises(ValueError, match="steps"):
        validate_workout("Bad", "running", [{"repeat": 2, "steps": []}])


def test_validate_rejects_non_strength_metadata_and_empty_metadata():
    with pytest.raises(ValueError, match="category"):
        validate_workout("Bad", "running", [{"run": {"duration": "1m", "category": "SQUAT"}}])
    with pytest.raises(ValueError, match="exercise"):
        validate_workout("Bad", "strength", [{"work": {"reps": 10, "exercise": "  "}}])


def test_validate_allows_supported_heart_rate_targets_on_walking():
    workout = validate_workout("Walk", "walking", [{"work": {"duration": "20m", "heart_rate": "100-120bpm"}}])
    assert workout.steps[0].target == Target("heart_rate", values=(100.0, 120.0))


def test_normalized_model_is_immutable_and_recursive():
    assert WorkoutDefinition.__dataclass_params__.frozen
    assert ActionStep.__dataclass_params__.frozen
    assert RepeatStep.__dataclass_params__.frozen
    with pytest.raises(FrozenInstanceError):
        validate_workout("Workout", "running", [{"run": {"duration": "1m"}}]).name = "changed"
