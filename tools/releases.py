"""Validate release metadata and select a published package generation."""

import re
from dataclasses import dataclass

from github.GitReleaseAsset import GitReleaseAsset
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import archive_name, validate_label, version

MARKER = "verilator-builds-state:"


class ReleaseState(BaseModel):
    model_config = ConfigDict(strict=True)

    label: str
    sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    recipe: str = Field(min_length=1)
    source_version: str | None = None

    @field_validator("label")
    @classmethod
    def valid_label(cls, value):
        return validate_label(value)

    @field_validator("source_version")
    @classmethod
    def valid_version(cls, value):
        if value is not None and version(value) is None:
            raise ValueError("Invalid source version")
        return value

    @model_validator(mode="after")
    def matching_version(self):
        if version(self.label) and self.source_version is not None:
            if self.source_version != self.label:
                raise ValueError("Source version differs from the release label")
        return self


def release_state(body):
    match = re.search(r"<!-- " + MARKER + r" (.*?) -->", body or "")
    if not match:
        raise ValueError("Published release has no Verilator build metadata")
    return ReleaseState.model_validate_json(match[1])


@dataclass(frozen=True)
class PublishedPackage:
    state: ReleaseState
    archive: GitReleaseAsset
    checksums: GitReleaseAsset


def published_package(api, requested, platform):
    """Select only the committed generation, ignoring partially uploaded nightlies."""
    release = api.release(requested)
    if release is None or release.draft:
        return None
    state = release_state(release.body)
    if requested != "nightly" and state.label != requested:
        raise ValueError("Published release label differs from the requested version")
    name = archive_name(state.label, platform)
    checksums = f"SHA256SUMS-{state.label}.txt"
    assets = {asset.name: asset for asset in release.get_assets() if asset.size > 0}
    if not {name, checksums} <= assets.keys():
        return None
    return PublishedPackage(state, assets[name], assets[checksums])
