from copy import deepcopy

import pytest

from garmin_mcp.ai_workouts import (
    END_CONDITION_COMPILERS,
    END_CONDITION_PARSERS,
    TARGET_COMPILERS,
    TARGET_PARSERS,
    ActionStep,
    EndCondition,
    WorkoutDefinition,
    compile_workout,
    validate_workout,
)
from garmin_mcp.workouts import prepare_workout_for_upload


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


def compile_friendly(name, sport, steps, schedule_date=None):
    return compile_workout(validate_workout(name, sport, steps, schedule_date))


def test_compile_easy_running_workout_has_complete_garmin_shape_and_no_target():
    result = compile_friendly("Easy 30m", "running", [{"run": {"duration": "30m"}}])

    assert result == {
        "workoutName": "Easy 30m",
        "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
                "workoutSteps": [
                    {
                        "type": "ExecutableStepDTO",
                        "stepOrder": 1,
                        "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
                        "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                        "endConditionValue": 1800.0,
                        "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"},
                    }
                ],
            }
        ],
    }


def test_compile_preserves_action_order_and_step_metadata():
    result = compile_friendly(
        "Phased Run",
        "running",
        [
            {"warmup": {"duration": "5m"}},
            {"work": {"distance": "1km"}},
            {"cooldown": {"lap_button": True}},
        ],
    )
    steps = result["workoutSegments"][0]["workoutSteps"]
    assert [step["stepOrder"] for step in steps] == [1, 2, 3]
    assert [step["stepType"] for step in steps] == [
        {"stepTypeId": 1, "stepTypeKey": "warmup"},
        {"stepTypeId": 3, "stepTypeKey": "interval"},
        {"stepTypeId": 2, "stepTypeKey": "cooldown"},
    ]
    assert steps[1]["endCondition"] == {"conditionTypeId": 3, "conditionTypeKey": "distance"}
    assert steps[1]["endConditionValue"] == 1000.0
    assert "endConditionValue" not in steps[2]


def test_compile_threshold_repeat_converts_pace_and_emits_repeat_metadata():
    result = compile_friendly("Threshold 4x6", "running", THRESHOLD_STEPS)
    outer = result["workoutSegments"][0]["workoutSteps"]
    repeat = outer[1]
    assert [step["stepOrder"] for step in outer] == [1, 2, 3]
    assert repeat["type"] == "RepeatGroupDTO"
    assert repeat["stepOrder"] == 2
    assert repeat["numberOfIterations"] == 4
    assert repeat["endCondition"] == {"conditionTypeId": 7, "conditionTypeKey": "iterations"}
    assert repeat["endConditionValue"] == 4.0
    nested = repeat["workoutSteps"]
    assert [step["stepOrder"] for step in nested] == [1, 2]
    assert nested[0]["targetType"] == {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone"}
    assert nested[0]["targetValueOne"] == pytest.approx(1000 / 260)
    assert nested[0]["targetValueTwo"] == pytest.approx(1000 / 270)


def test_compile_time_and_distance_repeats_use_canonical_end_conditions():
    result = compile_friendly(
        "Mixed Repeat",
        "running",
        [
            {"repeat": 2, "steps": [{"run": {"duration": "30s"}}, {"run": {"distance": "400m"}}]},
        ],
    )
    nested = result["workoutSegments"][0]["workoutSteps"][0]["workoutSteps"]
    assert nested[0]["endCondition"] == {"conditionTypeId": 2, "conditionTypeKey": "time"}
    assert nested[0]["endConditionValue"] == 30.0
    assert nested[1]["endCondition"] == {"conditionTypeId": 3, "conditionTypeKey": "distance"}
    assert nested[1]["endConditionValue"] == 400.0


def test_compile_heart_rate_named_zone_and_custom_range_never_mix_fields():
    named = compile_friendly("Named HR", "running", [{"run": {"duration": "5m", "heart_rate_zone": "Z3"}}])
    custom = compile_friendly("Custom HR", "walking", [{"work": {"duration": "5m", "heart_rate": "105-143bpm"}}])
    named_target = named["workoutSegments"][0]["workoutSteps"][0]
    custom_target = custom["workoutSegments"][0]["workoutSteps"][0]
    assert named_target["targetType"] == {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"}
    assert named_target["zoneNumber"] == 3
    assert "targetValueOne" not in named_target and "targetValueTwo" not in named_target
    assert custom_target["targetType"] == {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"}
    assert custom_target["targetValueOne"] == 105.0 and custom_target["targetValueTwo"] == 143.0
    assert "zoneNumber" not in custom_target


def test_prepare_preserves_plausible_custom_heart_rate_range():
    compiled = compile_friendly(
        "Custom HR",
        "running",
        [{"run": {"duration": "5m", "heart_rate": "30-143bpm"}}],
    )

    prepared = prepare_workout_for_upload(compiled)
    target = prepared["workoutSegments"][0]["workoutSteps"][0]

    assert target["targetValueOne"] == 30.0
    assert target["targetValueTwo"] == 143.0
    assert "zoneNumber" not in target


def test_compile_cycling_power_zone_and_watts_use_distinct_canonical_ids():
    result = compile_friendly(
        "Power",
        "cycling",
        [
            {"work": {"duration": "10m", "power_zone": "Z4"}},
            {"work": {"duration": "10m", "power": "200-250W"}},
        ],
    )
    steps = result["workoutSegments"][0]["workoutSteps"]
    assert steps[0]["targetType"] == {"workoutTargetTypeId": 2, "workoutTargetTypeKey": "power.zone"}
    assert steps[0]["zoneNumber"] == 4
    assert steps[1]["targetType"] == {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "power.between"}
    assert steps[1]["targetValueOne"] == 200.0 and steps[1]["targetValueTwo"] == 250.0


def test_compile_walking_uses_garmin_sport_id_12():
    result = compile_friendly("Walk", "walking", [{"work": {"duration": "20m"}}])
    assert result["sportType"] == {"sportTypeId": 12, "sportTypeKey": "walking"}


def test_compile_strength_preserves_reps_exercise_and_category():
    result = compile_friendly(
        "Strength A",
        "strength",
        [{"work": {"reps": 10, "exercise": "BARBELL_SQUAT", "category": "SQUAT"}}],
    )
    step = result["workoutSegments"][0]["workoutSteps"][0]
    assert result["sportType"] == {"sportTypeId": 5, "sportTypeKey": "strength_training"}
    assert step["stepType"] == {"stepTypeId": 3, "stepTypeKey": "interval"}
    assert step["endCondition"] == {"conditionTypeId": 10, "conditionTypeKey": "reps"}
    assert step["endConditionValue"] == 10.0
    assert step["exerciseName"] == "BARBELL_SQUAT"
    assert step["category"] == "SQUAT"


def test_compile_lap_button_has_no_end_condition_value():
    result = compile_friendly("Open End", "running", [{"run": {"lap_button": True}}])
    step = result["workoutSegments"][0]["workoutSteps"][0]
    assert step["endCondition"] == {"conditionTypeId": 1, "conditionTypeKey": "lap.button"}
    assert "endConditionValue" not in step


def test_compile_does_not_mutate_normalized_input():
    definition = validate_workout("Immutable", "running", THRESHOLD_STEPS)
    before = deepcopy(definition)
    result = compile_workout(definition)
    result["workoutSegments"][0]["workoutSteps"][0]["stepOrder"] = 99
    assert definition == before


def test_compile_uses_extensible_end_condition_parser_and_compiler_registries():
    original_parser = END_CONDITION_PARSERS.get("calories")
    original_compiler = END_CONDITION_COMPILERS.get("calories")
    END_CONDITION_PARSERS["calories"] = lambda value: float(value)
    END_CONDITION_COMPILERS["calories"] = lambda condition: {
        "conditionTypeId": 4,
        "conditionTypeKey": "calories",
    }
    try:
        result = compile_friendly("Calorie Run", "running", [{"run": {"calories": 250}}])
    finally:
        if original_parser is None:
            END_CONDITION_PARSERS.pop("calories", None)
        else:
            END_CONDITION_PARSERS["calories"] = original_parser
        if original_compiler is None:
            END_CONDITION_COMPILERS.pop("calories", None)
        else:
            END_CONDITION_COMPILERS["calories"] = original_compiler

    step = result["workoutSegments"][0]["workoutSteps"][0]
    assert step["endCondition"] == {"conditionTypeId": 4, "conditionTypeKey": "calories"}
    assert step["endConditionValue"] == 250.0


def test_compile_reports_unknown_end_condition_kind_contextually():
    definition = WorkoutDefinition(
        "Unsupported",
        "running",
        (ActionStep("run", EndCondition("unknown", 60.0)),),
    )
    with pytest.raises(ValueError, match="unknown end condition kind 'unknown'"):
        compile_workout(definition)


def test_compile_sport_type_dicts_are_independent_between_locations_and_calls():
    definition = validate_workout("Alias Safety", "running", [{"run": {"duration": "1m"}}])
    first = compile_workout(definition)
    second = compile_workout(definition)

    assert first["sportType"] is not first["workoutSegments"][0]["sportType"]
    assert first["sportType"] is not second["sportType"]
    first["sportType"]["sportTypeId"] = 99
    first["workoutSegments"][0]["sportType"]["sportTypeKey"] = "changed"
    assert second["sportType"] == {"sportTypeId": 1, "sportTypeKey": "running"}
    assert second["workoutSegments"][0]["sportType"] == {"sportTypeId": 1, "sportTypeKey": "running"}


def test_compile_reports_parser_only_target_extension_contextually():
    original_parser = TARGET_PARSERS.get("cadence")
    original_compiler = TARGET_COMPILERS.get("cadence")
    TARGET_PARSERS["cadence"] = lambda value: (float(value), float(value) + 1)
    TARGET_COMPILERS.pop("cadence", None)
    try:
        definition = validate_workout("Unsupported Target", "running", [{"run": {"duration": "1m", "cadence": 90}}])
        with pytest.raises(ValueError, match="unknown target kind 'cadence'.*action 'run'"):
            compile_workout(definition)
    finally:
        if original_parser is None:
            TARGET_PARSERS.pop("cadence", None)
        else:
            TARGET_PARSERS["cadence"] = original_parser
        if original_compiler is None:
            TARGET_COMPILERS.pop("cadence", None)
        else:
            TARGET_COMPILERS["cadence"] = original_compiler
