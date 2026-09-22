import json
import os
import tarfile
from functools import partial
from types import SimpleNamespace

import pytest
import responses
from github import Github

from tools.config import archive_name
from tools.package import sha256


@pytest.fixture(autouse=True)
def http(monkeypatch):
    # Exercise the real SDK without rate-limit delays or any live HTTP requests.
    monkeypatch.setattr("tools.github.Github", partial(Github, retry=0, seconds_between_requests=0))
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture
def state():
    return {"label": "v5.048", "sha": "a" * 40, "recipe": "b" * 40}


@pytest.fixture
def manifest(state):
    return {
        **state,
        "schema": 1,
        "upstream": "verilator/verilator",
        "platform": "linux-x86_64",
        "abi_audited": True,
        "source_version": "v5.048",
    }


@pytest.fixture
def launcher():
    def create(prefix, version, sha):
        (prefix / "bin").mkdir(parents=True)
        (prefix / "share/verilator").mkdir(parents=True)
        executable = prefix / "bin/verilator"
        executable.write_text(f"#!/bin/sh\necho 'Verilator {version} ({sha})'\n")
        executable.chmod(0o755)

    return create


@pytest.fixture
def make_package(tmp_path, state, manifest, launcher):
    def create(label="v5.048", manifest_updates=None):
        metadata = {**state, "label": label}
        contents = {**manifest, "label": label, **(manifest_updates or {})}
        staging = tmp_path / "staging"
        launcher(staging, "v5.048", state["sha"])
        (staging / "manifest.json").write_text(json.dumps(contents))
        archive = tmp_path / archive_name(label, "linux-x86_64")
        with tarfile.open(archive, "w:gz") as package:
            package.add(staging, arcname=archive.name.removesuffix(".tar.gz"))
        checksums = tmp_path / f"SHA256SUMS-{label}.txt"
        checksums.write_text(f"{sha256(archive)}  {archive.name}\n")
        return SimpleNamespace(archive=archive, checksums=checksums, state=metadata)

    return create


@pytest.fixture
def build_environment(monkeypatch):
    monkeypatch.setattr("tools.install.runner_platform", lambda: "linux-x86_64")
    monkeypatch.setattr("tools.install.dependencies", lambda *args, **kwargs: os.environ.copy())
