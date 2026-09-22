import io
import json
import tarfile

import pytest
from pydantic import ValidationError

from tools.package import Manifest, extract_archive, unpack_package
from tools.releases import ReleaseState


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", True),
        ("schema", "1"),
        ("schema", 2),
        ("abi_audited", 1),
        ("abi_audited", "true"),
        ("source_version", None),
        ("source_version", "5.048"),
        ("source_version", "v5.048\n"),
        ("source_version", "v5.050"),
    ],
)
def test_manifest_uses_strict_field_types_and_versions(manifest, field, value):
    manifest[field] = value
    with pytest.raises(ValidationError):
        Manifest.model_validate_json(json.dumps(manifest))


@pytest.mark.parametrize("field", ["schema", "source_version", "sha", "abi_audited"])
def test_missing_manifest_fields_have_validation_errors(manifest, field):
    del manifest[field]
    with pytest.raises(ValidationError, match=field):
        Manifest.model_validate_json(json.dumps(manifest))


@pytest.mark.parametrize("field", ["upstream", "platform", "recipe", "sha", "abi_audited"])
def test_manifest_must_match_release_and_platform(make_package, tmp_path, field):
    values = {
        "upstream": "other/repo",
        "platform": "linux-aarch64",
        "recipe": "c" * 40,
        "sha": "c" * 40,
        "abi_audited": False,
    }
    package = make_package(manifest_updates={field: values[field]})
    with pytest.raises(ValueError, match=field):
        unpack_package(
            package.archive,
            package.checksums,
            tmp_path / "extracted",
            ReleaseState(**package.state),
            "linux-x86_64",
        )


def test_nightly_manifest_must_match_declared_source_version(make_package, tmp_path):
    package = make_package(label="nightly-generation")
    state = ReleaseState(**package.state, source_version="v5.050")
    with pytest.raises(ValueError, match="source_version"):
        unpack_package(
            package.archive, package.checksums, tmp_path / "extracted", state, "linux-x86_64"
        )


def test_archive_traversal_is_rejected(tmp_path):
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as package:
        entry = tarfile.TarInfo("../escaped")
        entry.size = 1
        package.addfile(entry, io.BytesIO(b"x"))
    with pytest.raises(tarfile.OutsideDestinationError):
        extract_archive(archive, tmp_path / "destination")
    assert not (tmp_path / "escaped").exists()
