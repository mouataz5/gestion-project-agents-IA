from pathlib import Path

import pytest
import yaml

from app.core.config import REPO_ROOT
from app.schemas.candidate import CandidateProfile
from app.services.candidate_profile import (
    ProfileNotFoundError,
    ProfileValidationError,
    deep_merge,
    load_profile,
    needs_user_input,
    parse_profile,
    profile_to_yaml,
)

pytestmark = pytest.mark.feature("candidate-profile")


def _repo_profile_data() -> dict[str, object]:
    data = yaml.safe_load((REPO_ROOT / "candidate" / "profile.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_repository_profile_is_valid() -> None:
    profile = load_profile(REPO_ROOT / "candidate")

    assert profile.identity.full_name == "Mouataz Bouazizi"
    assert profile.identity.location.country_code == "TN"
    assert profile.work_authorization.visa_sponsorship_required is True
    assert profile.relocation.willing_to_relocate is True
    assert "AI Engineer" in profile.targets.roles
    assert [c.code for c in profile.targets.countries.primary][:3] == ["FR", "DE", "NL"]
    assert "NO" in [c.code for c in profile.targets.countries.secondary]
    assert "LangGraph" in profile.core_skills
    assert profile.cv_policy.allow_title_changes is False


def test_unknown_fields_are_rejected_with_their_path() -> None:
    data = _repo_profile_data()
    data["identity"]["fullname"] = "typo"  # type: ignore[index]

    with pytest.raises(ProfileValidationError) as excinfo:
        parse_profile(data)

    assert any(error["loc"] == "identity.fullname" for error in excinfo.value.details)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("targets", "roles"), "AI Engineer"),  # must be a list
        (("identity", "location", "country_code"), "Tunisia"),  # must be ISO alpha-2
        (("relocation", "willing_to_relocate"), "maybe"),
        (("schema_version",), 2),
    ],
)
def test_wrong_types_are_rejected(path: tuple[str, ...], value: object) -> None:
    data = _repo_profile_data()
    target: dict[str, object] = data
    for key in path[:-1]:
        nested = target[key]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value

    with pytest.raises(ProfileValidationError) as excinfo:
        parse_profile(data)

    assert any(error["loc"].startswith(".".join(path)) for error in excinfo.value.details)


def test_missing_values_are_reported_as_needing_user_input() -> None:
    fields = needs_user_input(load_profile(REPO_ROOT / "candidate"))

    for expected in (
        "contact.email",
        "contact.phone",
        "application_defaults.notice_period",
        "application_defaults.salary_expectations",
        "application_defaults.languages",
    ):
        assert expected in fields
    assert "identity.full_name" not in fields
    assert "work_authorization.visa_sponsorship_required" not in fields


def test_local_override_is_deep_merged(candidate_dir: Path) -> None:
    (candidate_dir / "profile.local.yaml").write_text(
        "contact:\n  email: alex@example.com\n"
        "application_defaults:\n  notice_period: 1 month\n"
        "targets:\n  roles: [LLM Engineer]\n",
        encoding="utf-8",
    )

    profile = load_profile(candidate_dir)

    assert profile.contact.email == "alex@example.com"
    assert profile.application_defaults.notice_period == "1 month"
    assert profile.targets.roles == ["LLM Engineer"]  # lists are replaced, not concatenated
    assert profile.identity.full_name == "Mouataz Bouazizi"  # untouched values are kept


def test_deep_merge_does_not_mutate_inputs() -> None:
    base = {"a": {"b": 1, "c": [1]}, "d": 1}
    override = {"a": {"b": 2}}

    assert deep_merge(base, override) == {"a": {"b": 2, "c": [1]}, "d": 1}
    assert base == {"a": {"b": 1, "c": [1]}, "d": 1}


def test_missing_profile_file_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ProfileNotFoundError):
        load_profile(tmp_path)


def test_yaml_export_round_trips_and_hides_private_fields_by_default() -> None:
    profile = load_profile(REPO_ROOT / "candidate").model_copy(deep=True)
    profile.contact.email = "private@example.com"

    public = profile_to_yaml(profile, include_private=False)
    private = profile_to_yaml(profile, include_private=True)

    assert "private@example.com" not in public
    assert "private@example.com" in private
    assert CandidateProfile.model_validate(yaml.safe_load(private)) == profile
    reparsed_public = CandidateProfile.model_validate(yaml.safe_load(public))
    assert reparsed_public.contact.email is None
    assert reparsed_public.targets == profile.targets
