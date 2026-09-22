"""Extract archives and validate downloaded Verilator packages."""

import hashlib
import re
import tarfile
from pathlib import Path

from pydantic import Field

from .config import UPSTREAM_REPOSITORY
from .releases import ReleaseState


class Manifest(ReleaseState):
    schema_version: int = Field(alias="schema", ge=1, le=1)
    upstream: str
    platform: str
    abi_audited: bool
    source_version: str


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def extract_archive(archive, destination):
    with tarfile.open(archive) as package:
        package.extractall(destination, filter="data")
    entries = list(destination.iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        raise ValueError("Expected a single directory in the archive")
    return entries[0]


def unpack_package(archive, checksums, destination, state, platform):
    matches = re.findall(
        rf"^([0-9a-f]{{64}})  {re.escape(archive.name)}$", checksums.read_text(), re.MULTILINE
    )
    if len(matches) != 1 or sha256(archive) != matches[0]:
        raise ValueError(f"SHA-256 checksum mismatch for {archive.name}")
    extracted = extract_archive(archive, destination)
    manifest = Manifest.model_validate_json((extracted / "manifest.json").read_bytes())
    expected = {
        "upstream": UPSTREAM_REPOSITORY,
        "label": state.label,
        "sha": state.sha,
        "recipe": state.recipe,
        "platform": platform,
        "abi_audited": True,
    }
    if state.source_version is not None:
        expected["source_version"] = state.source_version
    for field, value in expected.items():
        if getattr(manifest, field) != value:
            raise ValueError(f"Package {field} differs from release metadata")
    return extracted, manifest
