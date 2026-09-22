"""Install a published Verilator package or build the requested version on this runner."""

import os
import platform as host_platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import (
    NIGHTLY_BRANCH,
    PLATFORMS,
    RELEASE_REPOSITORY,
    UPSTREAM_REPOSITORY,
    version,
)
from .github import GitHub, GitHubNotFound
from .native import build_native, dependencies
from .package import extract_archive, unpack_package
from .releases import published_package


def requested_version(value):
    value = value.strip()
    if value == "nightly":
        return value
    tag = value if value.startswith("v") else "v" + value
    if version(tag) is None:
        raise ValueError("version must be an upstream release such as v5.048 or 5.048, or nightly")
    return tag


def runner_platform():
    system = {"Linux": "linux", "Darwin": "macos"}.get(host_platform.system())
    machine = host_platform.machine().lower()
    arch = {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    if system == "macos" and arch == "aarch64":
        arch = "arm64"
    result = f"{system}-{arch}"
    if result not in PLATFORMS:
        raise ValueError("Supported runners are Linux and macOS on x86-64 or ARM64")
    return result


def install_package(api, platform, package, work, prefix):
    archive = work / package.archive.name
    checksums = work / package.checksums.name
    api.download_asset(package.checksums, checksums)
    api.download_asset(package.archive, archive)
    extracted, manifest = unpack_package(
        archive, checksums, work / "package", package.state, platform
    )
    shutil.move(extracted, prefix)
    return manifest.source_version, manifest.sha


def build_source(api, requested, work, prefix, platform, jobs, install_dependencies):
    ref = NIGHTLY_BRANCH if requested == "nightly" else f"refs/tags/{requested}"
    sha = api.commit(UPSTREAM_REPOSITORY, ref)
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Upstream returned an invalid commit")
    archive = work / "source.tar.gz"
    api.download_source(UPSTREAM_REPOSITORY, sha, archive)
    source = extract_archive(archive, work / "source")
    env = dependencies(platform, build=True, install=install_dependencies)
    actual = build_native(source, prefix, requested, sha, jobs, env)
    # Prove that the installed launcher does not depend on its build directory.
    shutil.rmtree(source)
    return actual, sha


def install(
    requested, repository, token, root, jobs=2, install_dependencies=True, force_source=False
):
    requested = requested_version(requested)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid release repository")
    if jobs < 1:
        raise ValueError("jobs must be positive")
    platform = runner_platform()
    prefix = root / "verilator"
    try:
        with (
            GitHub(repository, token=token) as api,
            tempfile.TemporaryDirectory(prefix="build-", dir=root) as temp,
        ):
            work = Path(temp)
            package = None if force_source else published_package(api, requested, platform)
            result = None
            if package is not None:
                print(f"Installing {package.state.label} for {platform}", flush=True)
                try:
                    result = install_package(api, platform, package, work, prefix)
                except GitHubNotFound:
                    # A nightly can switch generations between lookup and download.
                    print(
                        "Published assets are no longer available; building from source", flush=True
                    )
            built = result is None
            if built:
                print(f"Building {requested} from source for {platform}", flush=True)
                result = build_source(
                    api, requested, work, prefix, platform, jobs, install_dependencies
                )
        actual, sha = result
        env = dependencies(platform, build=False, install=install_dependencies)
        output = subprocess.check_output(
            [str(prefix / "bin/verilator"), "--version"], env=env, text=True
        )
        print(output, end="", flush=True)
        if not re.search(rf"\bVerilator v?{re.escape(actual[1:])}\b", output):
            raise ValueError("Installed Verilator does not report the expected version")
        # Older upstream releases predate VERILATOR_SRC_VERSION support. Their
        # source commit is pinned at download time, but is absent from --version.
        if not built and sha not in output:
            raise ValueError("Installed Verilator does not identify the expected source commit")
        return {
            "version": actual,
            "path": str(prefix),
            "source-sha": sha,
            "built-from-source": str(built).lower(),
        }
    except BaseException:
        if prefix.exists():
            shutil.rmtree(prefix)
        raise


def boolean_input(name, default):
    value = os.environ.get(name, default).lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"


def main():
    # Each invocation gets its own prefix so repeated setup steps cannot replace
    # an installation still referenced by an earlier step's outputs.
    root = Path(tempfile.mkdtemp(prefix="setup-verilator-", dir=os.environ["RUNNER_TEMP"]))
    try:
        outputs = install(
            os.environ["INSTALL_VERSION"],
            RELEASE_REPOSITORY,
            os.environ.get("INSTALL_TOKEN", ""),
            root,
            jobs=int(os.environ.get("INSTALL_JOBS", "2")),
            install_dependencies=boolean_input("INSTALL_DEPENDENCIES", "true"),
            force_source=boolean_input("INSTALL_FORCE_SOURCE", "false"),
        )
        with open(os.environ["GITHUB_PATH"], "a") as stream:
            stream.write(outputs["path"] + "/bin\n")
        with open(os.environ["GITHUB_ENV"], "a") as stream:
            # A runner may already have another installation selected through this variable.
            stream.write(f"VERILATOR_ROOT={outputs['path']}/share/verilator\n")
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.writelines(f"{name}={value}\n" for name, value in outputs.items())
    except BaseException:
        shutil.rmtree(root)
        raise


if __name__ == "__main__":
    main()
