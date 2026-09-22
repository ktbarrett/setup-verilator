"""GitHub metadata lookup and streaming archive downloads."""

from contextlib import AbstractContextManager

import requests
from github import Auth, Github, GithubException


class GitHubNotFound(RuntimeError):
    """A download disappeared after its release was selected."""


class GitHub(AbstractContextManager):
    def __init__(self, repository, token=None):
        self.client = Github(
            auth=Auth.Token(token) if token else None, per_page=100, timeout=30, lazy=True
        )
        self.repository = self.client.get_repo(repository)
        self.downloads = requests.Session()
        self.auth_headers = {"Authorization": f"Bearer {token}"} if token else {}

    def __exit__(self, *exc):
        self.downloads.close()
        self.client.close()

    def release(self, tag):
        try:
            return self.repository.get_release(tag)
        except GithubException as error:
            if error.status == 404:
                return None
            raise

    def download(self, url, destination, headers=None):
        with self.downloads.get(url, headers=headers, stream=True, timeout=(10, 120)) as response:
            if response.status_code == 404:
                raise GitHubNotFound(f"Download is no longer available: {url}")
            response.raise_for_status()
            with destination.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    stream.write(chunk)

    def download_asset(self, asset, destination):
        self.download(
            asset.url,
            destination,
            headers={**self.auth_headers, "Accept": "application/octet-stream"},
        )

    def download_source(self, repository, ref, destination):
        url = self.client.get_repo(repository).get_archive_link("tarball", ref)
        # The SDK resolves the authenticated archive URL. Do not send the API
        # token to the archive host on this separate request.
        self.download(url, destination)

    def commit(self, repository, ref):
        return self.client.get_repo(repository).get_commit(ref).complete().sha
