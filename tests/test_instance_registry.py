"""Tests for relay/instance_registry.py - Unity instance management"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from relay.instance_registry import InstanceRegistry, UnityInstance
from relay.protocol import InstanceStatus


class TestUnityInstance:
    """Test UnityInstance dataclass"""

    def test_default_values(self) -> None:
        instance = UnityInstance(
            instance_id="/Users/dev/MyGame",
            project_name="MyGame",
            unity_version="2022.3.20f1",
        )

        assert instance.instance_id == "/Users/dev/MyGame"
        assert instance.project_name == "MyGame"
        assert instance.unity_version == "2022.3.20f1"
        assert instance.capabilities == []
        assert instance.status == InstanceStatus.DISCONNECTED
        assert instance.reader is None
        assert instance.writer is None

    def test_is_connected_without_writer(self) -> None:
        instance = UnityInstance(
            instance_id="/test",
            project_name="Test",
            unity_version="2022.3",
        )
        assert instance.is_connected is False

    def test_is_connected_with_closing_writer(self) -> None:
        writer = MagicMock()
        writer.is_closing.return_value = True

        instance = UnityInstance(
            instance_id="/test",
            project_name="Test",
            unity_version="2022.3",
            writer=writer,
            status=InstanceStatus.READY,
        )
        assert instance.is_connected is False

    def test_is_connected_when_ready(self) -> None:
        writer = MagicMock()
        writer.is_closing.return_value = False

        instance = UnityInstance(
            instance_id="/test",
            project_name="Test",
            unity_version="2022.3",
            writer=writer,
            status=InstanceStatus.READY,
        )
        assert instance.is_connected is True

    def test_is_available_when_ready(self) -> None:
        writer = MagicMock()
        writer.is_closing.return_value = False

        instance = UnityInstance(
            instance_id="/test",
            project_name="Test",
            unity_version="2022.3",
            writer=writer,
            status=InstanceStatus.READY,
        )
        assert instance.is_available is True

    def test_is_available_when_busy(self) -> None:
        writer = MagicMock()
        writer.is_closing.return_value = False

        instance = UnityInstance(
            instance_id="/test",
            project_name="Test",
            unity_version="2022.3",
            writer=writer,
            status=InstanceStatus.BUSY,
        )
        assert instance.is_available is False

    def test_to_dict(self) -> None:
        instance = UnityInstance(
            instance_id="/Users/dev/MyGame",
            project_name="MyGame",
            unity_version="2022.3.20f1",
            capabilities=["manage_editor"],
            status=InstanceStatus.READY,
        )

        d = instance.to_dict(is_default=True)

        assert d["instance_id"] == "/Users/dev/MyGame"
        assert d["project_name"] == "MyGame"
        assert d["unity_version"] == "2022.3.20f1"
        assert d["status"] == "ready"
        assert d["is_default"] is True
        assert d["capabilities"] == ["manage_editor"]

    def test_update_heartbeat(self) -> None:
        instance = UnityInstance(
            instance_id="/test",
            project_name="Test",
            unity_version="2022.3",
        )
        old_heartbeat = instance.last_heartbeat

        # Small delay to ensure time difference
        import time

        time.sleep(0.01)

        instance.update_heartbeat()
        assert instance.last_heartbeat > old_heartbeat

    def test_set_status_to_reloading(self) -> None:
        instance = UnityInstance(
            instance_id="/test",
            project_name="Test",
            unity_version="2022.3",
            status=InstanceStatus.READY,
        )
        assert instance.reloading_since is None

        instance.set_status(InstanceStatus.RELOADING)

        assert instance.status == InstanceStatus.RELOADING
        assert instance.reloading_since is not None

    def test_set_status_from_reloading_to_ready(self) -> None:
        instance = UnityInstance(
            instance_id="/test",
            project_name="Test",
            unity_version="2022.3",
            status=InstanceStatus.RELOADING,
        )
        instance.reloading_since = 12345.0

        instance.set_status(InstanceStatus.READY)

        assert instance.status == InstanceStatus.READY
        assert instance.reloading_since is None


class TestInstanceRegistry:
    """Test InstanceRegistry"""

    @pytest.fixture
    def registry(self) -> InstanceRegistry:
        return InstanceRegistry()

    @pytest.fixture
    def mock_reader(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture
    def mock_writer(self) -> MagicMock:
        writer = MagicMock()
        writer.is_closing.return_value = False
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()
        return writer

    @pytest.mark.asyncio
    async def test_register_first_instance_becomes_default(
        self, registry: InstanceRegistry, mock_reader: MagicMock, mock_writer: MagicMock
    ) -> None:
        instance = await registry.register(
            instance_id="/Users/dev/MyGame",
            project_name="MyGame",
            unity_version="2022.3.20f1",
            capabilities=["manage_editor"],
            reader=mock_reader,
            writer=mock_writer,
        )

        assert instance.instance_id == "/Users/dev/MyGame"
        assert instance.status == InstanceStatus.READY
        assert registry.get_default() == instance
        assert registry.count == 1

    @pytest.mark.asyncio
    async def test_register_second_instance_not_default(
        self, registry: InstanceRegistry, mock_reader: MagicMock, mock_writer: MagicMock
    ) -> None:
        await registry.register(
            instance_id="/Users/dev/First",
            project_name="First",
            unity_version="2022.3",
            capabilities=[],
            reader=mock_reader,
            writer=mock_writer,
        )

        # Create new mocks for second instance
        mock_writer2 = MagicMock()
        mock_writer2.is_closing.return_value = False

        await registry.register(
            instance_id="/Users/dev/Second",
            project_name="Second",
            unity_version="2022.3",
            capabilities=[],
            reader=mock_reader,
            writer=mock_writer2,
        )

        default = registry.get_default()
        assert default is not None
        assert default.instance_id == "/Users/dev/First"
        assert registry.count == 2

    @pytest.mark.asyncio
    async def test_register_takeover_replaces_existing(
        self, registry: InstanceRegistry, mock_reader: MagicMock, mock_writer: MagicMock
    ) -> None:
        # Register first time
        await registry.register(
            instance_id="/Users/dev/MyGame",
            project_name="MyGame",
            unity_version="2022.3.20f1",
            capabilities=[],
            reader=mock_reader,
            writer=mock_writer,
        )

        # Create new mocks for takeover
        new_writer = MagicMock()
        new_writer.is_closing.return_value = False

        # Register again (takeover)
        instance = await registry.register(
            instance_id="/Users/dev/MyGame",
            project_name="MyGame",
            unity_version="2022.3.21f1",  # Different version
            capabilities=["new_capability"],
            reader=mock_reader,
            writer=new_writer,
        )

        assert instance.unity_version == "2022.3.21f1"
        assert registry.count == 1  # Still only 1 instance
        mock_writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_unregister_existing(
        self, registry: InstanceRegistry, mock_reader: MagicMock, mock_writer: MagicMock
    ) -> None:
        await registry.register(
            instance_id="/Users/dev/MyGame",
            project_name="MyGame",
            unity_version="2022.3",
            capabilities=[],
            reader=mock_reader,
            writer=mock_writer,
        )

        result = await registry.unregister("/Users/dev/MyGame")

        assert result is True
        assert registry.count == 0
        assert registry.get("/Users/dev/MyGame") is None

    @pytest.mark.asyncio
    async def test_unregister_nonexistent(self, registry: InstanceRegistry) -> None:
        result = await registry.unregister("/nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_unregister_updates_default(
        self, registry: InstanceRegistry, mock_reader: MagicMock, mock_writer: MagicMock
    ) -> None:
        # Register two instances
        await registry.register(
            instance_id="/first",
            project_name="First",
            unity_version="2022.3",
            capabilities=[],
            reader=mock_reader,
            writer=mock_writer,
        )

        mock_writer2 = MagicMock()
        mock_writer2.is_closing.return_value = False
        mock_writer2.close = MagicMock()
        mock_writer2.wait_closed = AsyncMock()

        await registry.register(
            instance_id="/second",
            project_name="Second",
            unity_version="2022.3",
            capabilities=[],
            reader=mock_reader,
            writer=mock_writer2,
        )

        # Unregister the default (first)
        await registry.unregister("/first")

        default = registry.get_default()
        assert default is not None
        assert default.instance_id == "/second"

    def test_get_existing(self, registry: InstanceRegistry) -> None:
        instance = UnityInstance(
            instance_id="/test",
            project_name="Test",
            unity_version="2022.3",
        )
        registry._instances["/test"] = instance

        result = registry.get("/test")
        assert result == instance

    def test_get_nonexistent(self, registry: InstanceRegistry) -> None:
        result = registry.get("/nonexistent")
        assert result is None

    def test_set_default_existing(self, registry: InstanceRegistry) -> None:
        instance = UnityInstance(
            instance_id="/test",
            project_name="Test",
            unity_version="2022.3",
        )
        registry._instances["/test"] = instance

        result = registry.set_default("/test")

        assert result is True
        assert registry._default_instance_id == "/test"

    def test_set_default_nonexistent(self, registry: InstanceRegistry) -> None:
        result = registry.set_default("/nonexistent")
        assert result is False

    def test_update_status(self, registry: InstanceRegistry) -> None:
        instance = UnityInstance(
            instance_id="/test",
            project_name="Test",
            unity_version="2022.3",
            status=InstanceStatus.READY,
        )
        registry._instances["/test"] = instance

        result = registry.update_status("/test", InstanceStatus.BUSY)

        assert result is True
        assert instance.status == InstanceStatus.BUSY

    def test_list_all(self, registry: InstanceRegistry) -> None:
        instance1 = UnityInstance(
            instance_id="/first",
            project_name="First",
            unity_version="2022.3",
            status=InstanceStatus.READY,
        )
        instance2 = UnityInstance(
            instance_id="/second",
            project_name="Second",
            unity_version="2022.3",
            status=InstanceStatus.BUSY,
        )
        registry._instances["/first"] = instance1
        registry._instances["/second"] = instance2
        registry._default_instance_id = "/first"

        result = registry.list_all()

        assert len(result) == 2
        # Find the default instance
        default_instance = next(d for d in result if d["instance_id"] == "/first")
        assert default_instance["is_default"] is True

    def test_get_instance_for_request_with_id(self, registry: InstanceRegistry) -> None:
        instance = UnityInstance(
            instance_id="/test",
            project_name="Test",
            unity_version="2022.3",
        )
        registry._instances["/test"] = instance

        result = registry.get_instance_for_request("/test")
        assert result == instance

    def test_get_instance_for_request_without_id(self, registry: InstanceRegistry) -> None:
        instance = UnityInstance(
            instance_id="/test",
            project_name="Test",
            unity_version="2022.3",
        )
        registry._instances["/test"] = instance
        registry._default_instance_id = "/test"

        result = registry.get_instance_for_request(None)
        assert result == instance

    def test_connected_count(self, registry: InstanceRegistry) -> None:
        writer = MagicMock()
        writer.is_closing.return_value = False

        instance1 = UnityInstance(
            instance_id="/connected",
            project_name="Connected",
            unity_version="2022.3",
            status=InstanceStatus.READY,
            writer=writer,
        )
        instance2 = UnityInstance(
            instance_id="/disconnected",
            project_name="Disconnected",
            unity_version="2022.3",
            status=InstanceStatus.DISCONNECTED,
        )
        registry._instances["/connected"] = instance1
        registry._instances["/disconnected"] = instance2

        assert registry.connected_count == 1

    def test_get_instances_by_status(self, registry: InstanceRegistry) -> None:
        instance1 = UnityInstance(
            instance_id="/ready",
            project_name="Ready",
            unity_version="2022.3",
            status=InstanceStatus.READY,
        )
        instance2 = UnityInstance(
            instance_id="/busy",
            project_name="Busy",
            unity_version="2022.3",
            status=InstanceStatus.BUSY,
        )
        registry._instances["/ready"] = instance1
        registry._instances["/busy"] = instance2

        ready_instances = registry.get_instances_by_status(InstanceStatus.READY)

        assert len(ready_instances) == 1
        assert ready_instances[0].instance_id == "/ready"

    @pytest.mark.asyncio
    async def test_close_all(
        self, registry: InstanceRegistry, mock_reader: MagicMock, mock_writer: MagicMock
    ) -> None:
        await registry.register(
            instance_id="/test",
            project_name="Test",
            unity_version="2022.3",
            capabilities=[],
            reader=mock_reader,
            writer=mock_writer,
        )

        await registry.close_all()

        assert registry.count == 0
        assert registry._default_instance_id is None
        mock_writer.close.assert_called()

    @pytest.mark.asyncio
    async def test_handle_heartbeat_timeout_not_expired(
        self, registry: InstanceRegistry, mock_reader: MagicMock, mock_writer: MagicMock
    ) -> None:
        await registry.register(
            instance_id="/test",
            project_name="Test",
            unity_version="2022.3",
            capabilities=[],
            reader=mock_reader,
            writer=mock_writer,
        )

        # Just registered, heartbeat should be fresh
        result = await registry.handle_heartbeat_timeout("/test", timeout_ms=15000)

        assert result is False

    @pytest.mark.asyncio
    async def test_handle_heartbeat_timeout_expired(
        self, registry: InstanceRegistry, mock_reader: MagicMock, mock_writer: MagicMock
    ) -> None:
        await registry.register(
            instance_id="/test",
            project_name="Test",
            unity_version="2022.3",
            capabilities=[],
            reader=mock_reader,
            writer=mock_writer,
        )

        # Manually set old heartbeat
        import time

        registry._instances["/test"].last_heartbeat = time.time() - 20  # 20 seconds ago

        result = await registry.handle_heartbeat_timeout("/test", timeout_ms=15000)

        assert result is True
        assert registry._instances["/test"].status == InstanceStatus.DISCONNECTED
