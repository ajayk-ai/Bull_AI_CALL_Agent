"""Request paths relative to the app, whatever prefix (BASE_PATH) the app is mounted under."""

from starlette.types import Scope


def route_path(scope: Scope) -> str:
    """The path without the mount prefix: /api/v1/auth/me for /aicall/api/v1/auth/me."""
    path: str = scope["path"]
    root: str = scope.get("root_path", "")
    return path[len(root) :] if root and path.startswith(root) else path
