"""Console API for Unity CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from unity_cli.client import RelayConnection


class ConsoleAPI:
    """Console log operations."""

    def __init__(self, conn: RelayConnection) -> None:
        self._conn = conn

    def get(
        self,
        types: list[str] | None = None,
        count: int | None = None,
        format: str = "detailed",
        include_stacktrace: bool = True,
        filter_text: str | None = None,
    ) -> dict[str, Any]:
        """Get console logs.

        Args:
            types: Log types to retrieve (e.g., ["error", "warning"])
            count: Maximum number of logs to retrieve (None = all)
            format: Output format ("detailed" or "simple")
            include_stacktrace: Include stack traces in output
            filter_text: Text to filter logs by

        Returns:
            Dictionary containing console logs
        """
        params: dict[str, Any] = {
            "action": "read",
            "format": format,
            "include_stacktrace": include_stacktrace,
        }
        if types:
            params["types"] = types
        if count is not None:
            params["count"] = count
        if filter_text:
            params["search"] = filter_text

        return self._conn.send_request("console", params)

    def clear(self) -> dict[str, Any]:
        """Clear console logs.

        Returns:
            Dictionary with operation result
        """
        return self._conn.send_request("console", {"action": "clear"})
