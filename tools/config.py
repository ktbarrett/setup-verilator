"""Installation sources, supported runners, and published package naming."""

import re

RELEASE_REPOSITORY = "ktbarrett/verilator-builds"
UPSTREAM_REPOSITORY = "verilator/verilator"
NIGHTLY_BRANCH = "master"
PLATFORMS = (
    "linux-x86_64",
    "linux-aarch64",
    "macos-x86_64",
    "macos-arm64",
)


def version(tag):
    match = re.fullmatch(r"v(\d+)\.(\d{3})", tag)
    return tuple(map(int, match.groups())) if match else None


def validate_label(label):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}", label):
        raise ValueError(f"Unsafe package label: {label!r}")
    return label


def archive_name(label, platform):
    validate_label(label)
    return f"verilator-{label}-{platform}.tar.gz"
