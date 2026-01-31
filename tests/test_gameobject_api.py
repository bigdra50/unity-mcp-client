"""Tests for unity_cli/api/gameobject.py - GameObject API"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from unity_cli.api.gameobject import GameObjectAPI


@pytest.fixture
def mock_conn() -> MagicMock:
    return MagicMock()


@pytest.fixture
def sut(mock_conn: MagicMock) -> GameObjectAPI:
    return GameObjectAPI(mock_conn)


class TestGameObjectAPISetActive:
    """set_active() メソッドのテスト"""

    def test_set_active_true_by_name(self, sut: GameObjectAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"message": "active set to True"}

        sut.set_active(active=True, name="Main Camera")

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["action"] == "active"
        assert params["active"] is True
        assert params["name"] == "Main Camera"

    def test_set_active_false_by_name(self, sut: GameObjectAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"message": "active set to False"}

        sut.set_active(active=False, name="DebugUI")

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["active"] is False
        assert params["name"] == "DebugUI"

    def test_set_active_by_instance_id(self, sut: GameObjectAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}

        sut.set_active(active=True, instance_id=12345)

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["active"] is True
        assert params["id"] == 12345
        assert "name" not in params

    def test_set_active_sends_gameobject_command(self, sut: GameObjectAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}

        sut.set_active(active=True, name="Cube")

        assert mock_conn.send_request.call_args[0][0] == "gameobject"

    def test_set_active_without_target_sends_only_action_and_active(
        self, sut: GameObjectAPI, mock_conn: MagicMock
    ) -> None:
        mock_conn.send_request.return_value = {}

        sut.set_active(active=False)

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params == {"action": "active", "active": False}


class TestGameObjectAPIFind:
    """find() メソッドのテスト"""

    def test_find_by_name(self, sut: GameObjectAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"found": 1, "objects": []}

        sut.find(name="Player")

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["action"] == "find"
        assert params["name"] == "Player"

    def test_find_by_instance_id(self, sut: GameObjectAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"found": 1, "objects": []}

        sut.find(instance_id=42)

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["id"] == 42


class TestGameObjectAPICreate:
    """create() メソッドのテスト"""

    def test_create_with_name_only(self, sut: GameObjectAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}

        sut.create(name="Empty")

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params == {"action": "create", "name": "Empty"}

    def test_create_with_primitive_and_transform(self, sut: GameObjectAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}

        sut.create(name="Cube", primitive_type="Cube", position=[1, 2, 3])

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["primitive"] == "Cube"
        assert params["position"] == [1, 2, 3]
