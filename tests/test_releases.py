import json

import pytest
from pydantic import ValidationError

from tools.releases import MARKER, release_state


@pytest.mark.parametrize("label", ["v5.048", "nightly-generation"])
@pytest.mark.parametrize("source_version", [None, "v5.048"])
def test_current_and_legacy_build_metadata(state, label, source_version):
    state["label"] = label
    if source_version is not None:
        state["source_version"] = source_version
    parsed = release_state(f"<!-- {MARKER} {json.dumps(state)} -->")
    assert parsed.model_dump(exclude_none=True) == state


@pytest.mark.parametrize("body", [None, "", "release notes", f"<!-- {MARKER} not json -->"])
def test_missing_or_invalid_metadata_is_rejected(body):
    with pytest.raises(ValueError):
        release_state(body)


@pytest.mark.parametrize("state", [None, [], {"sha": "a"}])
def test_metadata_requires_an_object_with_required_fields(state):
    with pytest.raises(ValidationError):
        release_state(f"<!-- {MARKER} {json.dumps(state)} -->")


@pytest.mark.parametrize("label", ["v5.048", "nightly-generation"])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("label", "../unsafe"),
        ("label", ""),
        ("sha", 123),
        ("sha", "a" * 39),
        ("sha", "a" * 40 + "\n"),
        ("recipe", []),
        ("recipe", ""),
        ("source_version", []),
        ("source_version", "bad"),
    ],
)
def test_invalid_field_types_and_formats_are_rejected(state, label, field, value):
    state.update(label=label)
    state[field] = value
    with pytest.raises(ValidationError):
        release_state(f"<!-- {MARKER} {json.dumps(state)} -->")


def test_stable_source_version_must_match_release_label(state):
    state["source_version"] = "v5.050"
    with pytest.raises(ValidationError, match="differs from the release label"):
        release_state(f"<!-- {MARKER} {json.dumps(state)} -->")
