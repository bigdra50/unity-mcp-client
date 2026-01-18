"""Component API for Unity CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from unity_cli.client import RelayConnection


class ComponentAPI:
    """Component operations via 'component' tool."""

    def __init__(self, conn: RelayConnection) -> None:
        self._conn = conn

    def list(
        self,
        target: str | None = None,
        target_id: int | None = None,
    ) -> dict[str, Any]:
        """List components on a GameObject.

        Args:
            target: Target GameObject name
            target_id: Target GameObject instance ID

        Returns:
            Dictionary with component list
        """
        params: dict[str, Any] = {"action": "list"}
        if target:
            params["target"] = target
        if target_id is not None:
            params["targetId"] = target_id
        return self._conn.send_request("component", params)

    def inspect(
        self,
        component_type: str,
        target: str | None = None,
        target_id: int | None = None,
    ) -> dict[str, Any]:
        """Inspect component properties.

        Args:
            component_type: Component type name to inspect
            target: Target GameObject name
            target_id: Target GameObject instance ID

        Returns:
            Dictionary with component properties
        """
        params: dict[str, Any] = {"action": "inspect", "type": component_type}
        if target:
            params["target"] = target
        if target_id is not None:
            params["targetId"] = target_id
        return self._conn.send_request("component", params)

    def add(
        self,
        component_type: str,
        target: str | None = None,
        target_id: int | None = None,
    ) -> dict[str, Any]:
        """Add a component to a GameObject.

        Args:
            component_type: Component type name to add
            target: Target GameObject name
            target_id: Target GameObject instance ID

        Returns:
            Dictionary with added component info
        """
        params: dict[str, Any] = {"action": "add", "type": component_type}
        if target:
            params["target"] = target
        if target_id is not None:
            params["targetId"] = target_id
        return self._conn.send_request("component", params)

    def remove(
        self,
        component_type: str,
        target: str | None = None,
        target_id: int | None = None,
    ) -> dict[str, Any]:
        """Remove a component from a GameObject.

        Args:
            component_type: Component type name to remove
            target: Target GameObject name
            target_id: Target GameObject instance ID

        Returns:
            Dictionary with removal result
        """
        params: dict[str, Any] = {"action": "remove", "type": component_type}
        if target:
            params["target"] = target
        if target_id is not None:
            params["targetId"] = target_id
        return self._conn.send_request("component", params)
