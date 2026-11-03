"""Object storage behind a small interface.

Only a local-directory backend exists today (a Docker volume in production). An S3-compatible backend can be
added later without changing callers: they only use put/get/delete with string keys.
"""

import asyncio
import re
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")


class Storage(Protocol):
    name: str

    async def put(self, key: str, data: bytes) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


def check_key(key: str) -> str:
    """Keys are relative paths of safe characters; '..' and absolute paths are rejected."""
    if not _KEY.match(key) or ".." in key.split("/"):
        raise ValueError(f"Invalid storage key: {key!r}")
    return key


class LocalStorage:
    name = "local"

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        return self.root / check_key(key)

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(path)

        await asyncio.to_thread(_write)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, True)


@lru_cache
def get_storage() -> Storage:
    return LocalStorage(get_settings().storage_root)
