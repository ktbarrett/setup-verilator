import os
from types import SimpleNamespace

import pytest
import requests
from github import GithubException

from tools.github import GitHub, GitHubNotFound

API = "https://api.github.com:443/repos/example/repo"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_only_404_counts_as_a_missing_release(http, status):
    http.get(f"{API}/releases/tags/v5.048", status=status, json={"message": "Request failed"})
    with GitHub("example/repo") as api:
        if status == 404:
            assert api.release("v5.048") is None
        else:
            with pytest.raises(GithubException) as error:
                api.release("v5.048")
            assert error.value.status == status


def test_action_token_is_used_without_changing_the_environment(http, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "caller-token")
    monkeypatch.setenv("GH_HOST", "example.com")
    http.get(f"{API}/releases/tags/v5.048", json={"id": 42, "url": f"{API}/releases/42"})
    with GitHub("example/repo", token="action-token") as api:
        assert api.release("v5.048").id == 42
    assert http.calls[0].request.headers["Authorization"] == "token action-token"
    assert os.environ["GH_TOKEN"] == "caller-token"
    assert os.environ["GH_HOST"] == "example.com"


def test_source_archive_uses_sdk_redirect_without_forwarding_token(http, tmp_path):
    data = b"\x1f\x8b\xff\x00\r\n"
    archive_url = "https://codeload.github.com/example/repo/legacy.tar.gz/commit"
    http.get(f"{API}/tarball/commit", status=302, headers={"Location": archive_url})
    http.get(archive_url, body=data)
    with GitHub("example/repo", token="action-token") as api:
        api.download_source("example/repo", "commit", tmp_path / "source.tar.gz")
    assert (tmp_path / "source.tar.gz").read_bytes() == data
    assert http.calls[0].request.headers["Authorization"] == "token action-token"
    assert http.calls[0].request.headers.get("Accept") != "application/octet-stream"
    assert "Authorization" not in http.calls[-1].request.headers


def test_asset_download_follows_redirect_and_preserves_bytes(http, tmp_path):
    asset_url = f"{API}/releases/assets/1"
    storage_url = "https://release-assets.githubusercontent.com/asset"
    data = b"\x1f\x8b\xff\x00\r\n"
    http.get(asset_url, status=302, headers={"Location": storage_url})
    http.get(storage_url, body=data)
    with GitHub("example/repo", token="action-token") as api:
        api.download_asset(SimpleNamespace(url=asset_url), tmp_path / "archive.tar.gz")
    assert (tmp_path / "archive.tar.gz").read_bytes() == data
    assert http.calls[0].request.headers["Authorization"] == "Bearer action-token"
    assert http.calls[0].request.headers["Accept"] == "application/octet-stream"
    assert "Authorization" not in http.calls[1].request.headers


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_download_errors_distinguish_missing_assets(http, tmp_path, status):
    url = f"{API}/releases/assets/1"
    http.get(url, status=status)
    expected = GitHubNotFound if status == 404 else requests.HTTPError
    with GitHub("example/repo") as api, pytest.raises(expected):
        api.download_asset(SimpleNamespace(url=url), tmp_path / "archive.tar.gz")
    assert not (tmp_path / "archive.tar.gz").exists()


def test_download_timeout_propagates(http, tmp_path):
    url = f"{API}/releases/assets/1"
    http.get(url, body=requests.Timeout("timed out"))
    with GitHub("example/repo") as api, pytest.raises(requests.Timeout):
        api.download_asset(SimpleNamespace(url=url), tmp_path / "archive.tar.gz")
