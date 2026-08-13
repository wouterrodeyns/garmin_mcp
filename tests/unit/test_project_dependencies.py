"""Project metadata and locked dependency regression tests."""

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())
LOCK = tomllib.loads((ROOT / "uv.lock").read_text())


def _locked_version(name: str) -> str:
    packages = [item for item in LOCK["package"] if item["name"] == name]
    assert len(packages) == 1
    return packages[0]["version"]


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def test_project_pins_secure_runtime_contract() -> None:
    project = PYPROJECT["project"]

    assert project["requires-python"] == ">=3.12"
    assert "garminconnect==0.3.10" in project["dependencies"]
    assert "mcp>=1.28.1,<2" in project["dependencies"]


def test_project_uses_standard_development_dependency_group() -> None:
    assert set(PYPROJECT["dependency-groups"]["dev"]) == {
        "pytest>=9.0.2",
        "pytest-asyncio>=0.25.2",
        "pytest-mock>=3.14.0",
        "pytest-timeout>=2.3.1",
    }
    assert "dev-dependencies" not in PYPROJECT.get("tool", {}).get("uv", {})


def test_lock_contains_fixed_dependency_versions() -> None:
    assert LOCK["requires-python"] == ">=3.12"
    assert _locked_version("garminconnect") == "0.3.10"
    assert _version_tuple(_locked_version("click")) >= (8, 3, 3)
    assert _version_tuple(_locked_version("h11")) >= (0, 16, 0)


def test_project_pins_fitdecode_without_replacing_fitparse() -> None:
    dependencies = PYPROJECT["project"]["dependencies"]
    assert "fitdecode==0.11.0" in dependencies
    assert "fitparse>=1.2.0" in dependencies
    assert _locked_version("fitdecode") == "0.11.0"
