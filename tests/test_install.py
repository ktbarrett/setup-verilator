import io
import json
import tarfile
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from github import GithubException
from responses.matchers import query_param_matcher

from tools.config import RELEASE_REPOSITORY
from tools.github import GitHub
from tools.install import build_source, install, main, requested_version, runner_platform
from tools.releases import MARKER

API = f"https://api.github.com/repos/{RELEASE_REPOSITORY}"
# PyGithub makes Requests calls with an explicit port; response URLs use GitHub's canonical form.
SDK_API = f"https://api.github.com:443/repos/{RELEASE_REPOSITORY}"


@pytest.fixture
def publish(http):
    def create(
        package,
        requested="v5.048",
        missing_archive=False,
        archive_status=200,
        draft=False,
        body=None,
        paginate=False,
    ):
        release_url = f"{API}/releases/42"
        assets = [
            {
                "id": i,
                "url": f"{API}/releases/assets/{i}",
                "name": path.name,
                "size": path.stat().st_size,
            }
            for i, path in enumerate((package.archive, package.checksums), 1)
        ]
        http.get(
            f"{SDK_API}/releases/tags/{requested}",
            json={
                "id": 42,
                "url": release_url,
                "draft": draft,
                "body": body
                if body is not None
                else f"<!-- {MARKER} {json.dumps(package.state)} -->",
            },
        )
        available = assets[1:] if missing_archive else assets
        assets_endpoint = f"{SDK_API}/releases/42/assets"
        if paginate:
            page_two = f"{release_url}/assets?per_page=100&page=2"
            http.get(
                f"{assets_endpoint}?per_page=100",
                json=[{"name": "pending-generation.tar.gz", "size": 1}],
                headers={"Link": f'<{page_two}>; rel="next"'},
                match=[query_param_matcher({"per_page": "100"})],
            )
            http.get(
                f"{assets_endpoint}?per_page=100&page=2",
                json=available,
                match=[query_param_matcher({"per_page": "100", "page": "2"})],
            )
        else:
            http.get(assets_endpoint, json=available)
        http.get(assets[0]["url"], body=package.archive.read_bytes(), status=archive_status)
        http.get(assets[1]["url"], body=package.checksums.read_bytes())
        return assets

    return create


@pytest.fixture
def installer(tmp_path, monkeypatch, launcher, state, build_environment):
    root = tmp_path / "destination"
    root.mkdir()

    def build(api, requested, work, prefix, platform, jobs, install_dependencies):
        actual = "v5.049" if requested == "nightly" else requested
        launcher(prefix, actual, state["sha"])
        return actual, state["sha"]

    build_mock = Mock(side_effect=build)
    monkeypatch.setattr("tools.install.build_source", build_mock)

    def run(requested="v5.048", **kwargs):
        return install(requested, RELEASE_REPOSITORY, "action-token", root, **kwargs)

    return run, build_mock, root


@pytest.mark.parametrize("value", ["5.048", "v5.048", " v5.048 "])
def test_normalize_versions(value):
    assert requested_version(value) == "v5.048"


def test_nightly_version():
    assert requested_version("nightly") == "nightly"


@pytest.mark.parametrize(
    "value", ["", "latest", "master", "v5", "5.48", "../../etc", "$(id)", "5.048\nx"]
)
def test_reject_refs_and_shell_text(value):
    with pytest.raises(ValueError):
        requested_version(value)


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("Linux", "x86_64", "linux-x86_64"),
        ("Linux", "aarch64", "linux-aarch64"),
        ("Linux", "arm64", "linux-aarch64"),
        ("Darwin", "x86_64", "macos-x86_64"),
        ("Darwin", "arm64", "macos-arm64"),
    ],
)
def test_runner_architectures(monkeypatch, system, machine, expected):
    monkeypatch.setattr("tools.install.host_platform.system", lambda: system)
    monkeypatch.setattr("tools.install.host_platform.machine", lambda: machine)
    assert runner_platform() == expected


def test_unsupported_system(monkeypatch):
    monkeypatch.setattr("tools.install.host_platform.system", lambda: "Windows")
    with pytest.raises(ValueError, match="Supported runners"):
        runner_platform()


def test_install_stable_archive_without_compilation(make_package, publish, installer, state):
    publish(make_package())
    run, build, root = installer
    result = run("5.048")
    assert result["built-from-source"] == "false"
    assert result["source-sha"] == state["sha"]
    assert (Path(result["path"]) / "bin/verilator").is_file()
    assert list(root.iterdir()) == [Path(result["path"])]
    build.assert_not_called()


def test_nightly_uses_published_generation_and_paginates_assets(make_package, publish, installer):
    publish(make_package(label="nightly-successful"), requested="nightly", paginate=True)
    run, build, _ = installer
    result = run("nightly")
    assert result["version"] == "v5.048"
    assert result["built-from-source"] == "false"
    build.assert_not_called()


@pytest.mark.parametrize("requested", ["v4.228", "nightly"])
def test_missing_release_builds_requested_source(http, installer, requested):
    http.get(f"{SDK_API}/releases/tags/{requested}", status=404, json={"message": "Not Found"})
    run, build, _ = installer
    result = run(requested)
    assert result["built-from-source"] == "true"
    assert build.call_args.args[1] == requested


@pytest.mark.parametrize("reason", ["missing_archive", "draft", "deleted_asset"])
def test_unavailable_package_falls_back_to_source(make_package, publish, installer, reason):
    publish(
        make_package(),
        missing_archive=reason == "missing_archive",
        draft=reason == "draft",
        archive_status=404 if reason == "deleted_asset" else 200,
    )
    run, build, _ = installer
    assert run()["built-from-source"] == "true"
    build.assert_called_once()


@pytest.mark.parametrize("requested", ["v5.048", "nightly"])
def test_force_source_bypasses_all_release_requests(installer, http, requested):
    run, build, _ = installer
    assert run(requested, force_source=True)["built-from-source"] == "true"
    build.assert_called_once()
    assert len(http.calls) == 0


@pytest.mark.parametrize("status", [401, 403, 500])
def test_release_errors_do_not_trigger_source_fallback(http, installer, status):
    http.get(f"{SDK_API}/releases/tags/v5.048", status=status, json={"message": "Request failed"})
    run, build, root = installer
    with pytest.raises(GithubException):
        run()
    build.assert_not_called()
    assert not list(root.iterdir())


def test_download_error_does_not_trigger_source_fallback(make_package, publish, installer):
    publish(make_package(), archive_status=500)
    run, build, root = installer
    with pytest.raises(requests.HTTPError):
        run()
    build.assert_not_called()
    assert not list(root.iterdir())


@pytest.mark.parametrize("problem", ["checksum", "metadata", "platform", "schema", "audit"])
def test_invalid_package_fails_without_source_fallback(make_package, publish, installer, problem):
    updates = {
        "platform": {"platform": "linux-aarch64"},
        "schema": {"schema": True},
        "audit": {"abi_audited": 1},
    }.get(problem)
    package = make_package(manifest_updates=updates)
    if problem == "checksum":
        package.archive.write_bytes(b"corrupt")
    publish(package, body="missing state" if problem == "metadata" else None)
    run, build, root = installer
    with pytest.raises(ValueError):
        run()
    build.assert_not_called()
    assert not list(root.iterdir())


def test_older_source_build_need_not_embed_commit(installer, monkeypatch, state):
    run, _, _ = installer
    monkeypatch.setattr(
        "tools.install.subprocess.check_output", lambda *args, **kwargs: "Verilator 4.228\n"
    )
    assert run("v4.228", force_source=True)["source-sha"] == state["sha"]


def test_wrong_installed_version_removes_installation(installer, monkeypatch):
    run, _, root = installer
    monkeypatch.setattr(
        "tools.install.subprocess.check_output", lambda *args, **kwargs: "Verilator 5.050\n"
    )
    with pytest.raises(ValueError, match="expected version"):
        run(force_source=True)
    assert not list(root.iterdir())


def test_action_exports_outputs_and_keeps_repeated_installations(
    make_package, publish, installer, monkeypatch, tmp_path, state
):
    publish(make_package())
    _, _, root = installer
    env = {
        "RUNNER_TEMP": str(root),
        "INSTALL_VERSION": "5.048",
        "INSTALL_TOKEN": "action-token",
        "GITHUB_ACTION_REPOSITORY": "example/action",
        "GITHUB_REPOSITORY": "example/consumer",
        "INSTALL_JOBS": "2",
        "INSTALL_DEPENDENCIES": "false",
        "INSTALL_FORCE_SOURCE": "false",
        "GITHUB_PATH": str(tmp_path / "path"),
        "GITHUB_ENV": str(tmp_path / "env"),
        "GITHUB_OUTPUT": str(tmp_path / "output"),
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    main()
    outputs = dict(line.split("=", 1) for line in (tmp_path / "output").read_text().splitlines())
    assert outputs["version"] == "v5.048"
    assert outputs["source-sha"] == state["sha"]
    assert outputs["built-from-source"] == "false"
    assert (tmp_path / "path").read_text() == outputs["path"] + "/bin\n"
    assert (tmp_path / "env").read_text() == f"VERILATOR_ROOT={outputs['path']}/share/verilator\n"
    main()
    assert len(list(root.iterdir())) == 2
    assert (Path(outputs["path"]) / "bin/verilator").is_file()


@pytest.mark.parametrize(
    "requested,ref", [("v5.046", "refs%2Ftags%2Fv5.046"), ("nightly", "master")]
)
def test_source_fetch_pins_tag_or_branch_to_a_commit(
    http, tmp_path, monkeypatch, state, requested, ref, build_environment
):
    upstream = "https://api.github.com:443/repos/verilator/verilator"
    sha = state["sha"]
    http.get(f"{upstream}/commits/{ref}", json={"sha": sha})
    archive_url = f"https://codeload.github.com/verilator/verilator/legacy.tar.gz/{sha}"
    http.get(f"{upstream}/tarball/{sha}", status=302, headers={"Location": archive_url})
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        data = b"AC_INIT([Verilator],[5.046], [])\n"
        entry = tarfile.TarInfo("verilator-source/configure.ac")
        entry.size = len(data)
        archive.addfile(entry, io.BytesIO(data))
    http.get(archive_url, body=buffer.getvalue())
    build = Mock(return_value="v5.046")
    monkeypatch.setattr("tools.install.build_native", build)
    with GitHub(RELEASE_REPOSITORY, token="action-token") as api:
        result = build_source(
            api, requested, tmp_path, tmp_path / "install", "linux-x86_64", 2, False
        )
    assert result == ("v5.046", sha)
    assert build.call_args.args[2:5] == (requested, sha, 2)
    assert not build.call_args.args[0].exists()
