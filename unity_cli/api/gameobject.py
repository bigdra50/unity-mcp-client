"""GameObject API for Unity CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from unity_cli.client import RelayConnection


class GameObjectAPI:
    """GameObject operations via 'gameobject' tool."""

    def __init__(self, conn: RelayConnection) -> None:
        self._conn = conn

    def find(
        self,
        name: str | None = None,
        instance_id: int | None = None,
    ) -> dict[str, Any]:
        """Find GameObject(s) by name or instance ID.

        Args:
            name: GameObject name to search for
            instance_id: Instance ID to search for

        Returns:
            Dictionary with found GameObjects
        """
        params: dict[str, Any] = {"action": "find"}
        if name:
            params["name"] = name
        if instance_id is not None:
            params["id"] = instance_id
        return self._conn.send_request("gameobject", params)

    def create(
        self,
        name: str,
        primitive_type: str | None = None,
        position: list[float] | None = None,
        rotation: list[float] | None = None,
        scale: list[float] | None = None,
    ) -> dict[str, Any]:
        """Create GameObject.

        Args:
            name: Name for the new GameObject
            primitive_type: Primitive type (e.g., "Cube", "Sphere")
            position: Initial position [x, y, z]
            rotation: Initial rotation [x, y, z]
            scale: Initial scale [x, y, z]

        Returns:
            Dictionary with created GameObject info
        """
        params: dict[str, Any] = {"action": "create", "name": name}
        if primitive_type:
            params["primitive"] = primitive_type
        if position:
            params["position"] = position
        if rotation:
            params["rotation"] = rotation
        if scale:
            params["scale"] = scale
        return self._conn.send_request("gameobject", params)

    def modify(
        self,
        name: str | None = None,
        instance_id: int | None = None,
        position: list[float] | None = None,
        rotation: list[float] | None = None,
        scale: list[float] | None = None,
    ) -> dict[str, Any]:
        """Modify GameObject transform.

        Args:
            name: GameObject name to modify
            instance_id: Instance ID to modify
            position: New position [x, y, z]
            rotation: New rotation [x, y, z]
            scale: New scale [x, y, z]

        Returns:
            Dictionary with modified GameObject info
        """
        params: dict[str, Any] = {"action": "modify"}
        if name:
            params["name"] = name
        if instance_id is not None:
            params["id"] = instance_id
        if position:
            params["position"] = position
        if rotation:
            params["rotation"] = rotation
        if scale:
            params["scale"] = scale
        return self._conn.send_request("gameobject", params)

    def set_active(
        self,
        active: bool,
        name: str | None = None,
        instance_id: int | None = None,
    ) -> dict[str, Any]:
        """Set GameObject active state.

        Args:
            active: Whether to activate or deactivate
            name: GameObject name
            instance_id: Instance ID

        Returns:
            Dictionary with operation result
        """
        params: dict[str, Any] = {"action": "active", "active": active}
        if name:
            params["name"] = name
        if instance_id is not None:
            params["id"] = instance_id
        return self._conn.send_request("gameobject", params)

    def delete(
        self,
        name: str | None = None,
        instance_id: int | None = None,
    ) -> dict[str, Any]:
        """Delete GameObject.

        Args:
            name: GameObject name to delete
            instance_id: Instance ID to delete

        Returns:
            Dictionary with operation result
        """
        params: dict[str, Any] = {"action": "delete"}
        if name:
            params["name"] = name
        if instance_id is not None:
            params["id"] = instance_id
        return self._conn.send_request("gameobject", params)
