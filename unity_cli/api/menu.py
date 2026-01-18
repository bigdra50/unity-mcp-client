"""Menu API for Unity CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from unity_cli.client import RelayConnection


class MenuAPI:
    """Menu operations for executing Unity MenuItems and ContextMenus."""

    def __init__(self, conn: RelayConnection) -> None:
        self._conn = conn

    def execute(self, path: str) -> dict[str, Any]:
        """Execute Unity menu item.

        Args:
            path: Menu item path (e.g., "Edit/Play", "Assets/Refresh")

        Returns:
            Dictionary with:
            - success: bool - Whether the menu item was executed
            - path: str - The menu path
            - message: str - Result message
        """
        return self._conn.send_request("menu", {"action": "execute", "path": path})

    def list(
        self,
        filter_text: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List available menu items.

        Args:
            filter_text: Text to filter menu items (case-insensitive)
            limit: Maximum number of items to return (default: 100)

        Returns:
            Dictionary with:
            - count: int - Number of items found
            - items: list - Menu items with path, priority, shortcut, type
        """
        params: dict[str, Any] = {"action": "list", "limit": limit}
        if filter_text:
            params["filter"] = filter_text
        return self._conn.send_request("menu", params)

    def context(
        self,
        method: str,
        target: str | None = None,
    ) -> dict[str, Any]:
        """Execute ContextMenu method on target object.

        Args:
            method: ContextMenu method name or menu item name
            target: Target object path (hierarchy or asset path).
                   If not specified, uses current Selection.

        Returns:
            Dictionary with execution result
        """
        params: dict[str, Any] = {"action": "context", "method": method}
        if target:
            params["target"] = target
        return self._conn.send_request("menu", params)
