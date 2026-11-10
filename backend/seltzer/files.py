"""Where attachment bytes live.

Databricks Apps don't mount /Volumes, so in Databricks the bytes go through
the SDK's Files API to a Unity Catalog volume. Locally they go to a folder.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, Protocol

from seltzer.config import Settings

CHUNK = 1024 * 1024


class FileStore(Protocol):
    def upload(self, path: str, fileobj: BinaryIO) -> None: ...
    def stream(self, path: str) -> Iterator[bytes]: ...
    def delete(self, path: str) -> None: ...


class VolumeFileStore:
    def __init__(self, volume_root: str) -> None:
        from databricks.sdk import WorkspaceClient

        self.root = volume_root.rstrip("/")
        self._client = WorkspaceClient()

    def _full(self, path: str) -> str:
        return f"{self.root}/{path}"

    def upload(self, path: str, fileobj: BinaryIO) -> None:
        self._client.files.upload(self._full(path), fileobj, overwrite=False)

    def stream(self, path: str) -> Iterator[bytes]:
        response = self._client.files.download(self._full(path))
        contents = response.contents
        assert contents is not None
        try:
            while chunk := contents.read(CHUNK):
                yield chunk
        finally:
            contents.close()

    def delete(self, path: str) -> None:
        self._client.files.delete(self._full(path))


class LocalFileStore:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()

    def _full(self, path: str) -> Path:
        full = (self.root / path).resolve()
        if self.root not in full.parents:
            raise ValueError("path escapes the attachment store")
        return full

    def upload(self, path: str, fileobj: BinaryIO) -> None:
        full = self._full(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        with full.open("xb") as out:
            shutil.copyfileobj(fileobj, out, CHUNK)

    def stream(self, path: str) -> Iterator[bytes]:
        with self._full(path).open("rb") as f:
            while chunk := f.read(CHUNK):
                yield chunk

    def delete(self, path: str) -> None:
        self._full(path).unlink(missing_ok=True)


def make_store(settings: Settings) -> FileStore:
    if settings.volume_root:
        return VolumeFileStore(settings.volume_root)
    if not settings.is_local:
        raise RuntimeError("SELTZER_VOLUME must be set outside local development")
    return LocalFileStore(settings.seltzer_local_files_dir)
