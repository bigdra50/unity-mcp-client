"""Tests for unity_cli/api/component.py - Component API"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from unity_cli.api.component import ComponentAPI


@pytest.fixture
def mock_conn() -> MagicMock:
    return MagicMock()


@pytest.fixture
def sut(mock_conn: MagicMock) -> ComponentAPI:
    return ComponentAPI(mock_conn)


class TestComponentAPIModify:
    """modify() メソッドのテスト"""

    def test_modify_int_value_by_name(self, sut: ComponentAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"message": "Modified"}

        sut.modify(
            target="Main Camera",
            component_type="Camera",
            prop="fieldOfView",
            value=90,
        )

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["action"] == "modify"
        assert params["type"] == "Camera"
        assert params["prop"] == "fieldOfView"
        assert params["value"] == 90
        assert params["target"] == "Main Camera"

    def test_modify_float_value(self, sut: ComponentAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}

        sut.modify(
            target="Cube",
            component_type="Rigidbody",
            prop="mass",
            value=2.5,
        )

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["value"] == 2.5

    def test_modify_bool_value(self, sut: ComponentAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}

        sut.modify(
            target="Cube",
            component_type="Rigidbody",
            prop="useGravity",
            value=False,
        )

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["value"] is False

    def test_modify_string_value(self, sut: ComponentAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}

        sut.modify(
            target="Player",
            component_type="PlayerController",
            prop="playerName",
            value="Hero",
        )

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["value"] == "Hero"

    def test_modify_vector3_value(self, sut: ComponentAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}

        sut.modify(
            target="Cube",
            component_type="Transform",
            prop="m_LocalPosition",
            value=[1.0, 2.0, 3.0],
        )

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["value"] == [1.0, 2.0, 3.0]

    def test_modify_color_value_as_dict(self, sut: ComponentAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}

        sut.modify(
            target="Light",
            component_type="Light",
            prop="m_Color",
            value={"r": 1.0, "g": 0.5, "b": 0.0, "a": 1.0},
        )

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["value"] == {"r": 1.0, "g": 0.5, "b": 0.0, "a": 1.0}

    def test_modify_by_target_id(self, sut: ComponentAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}

        sut.modify(
            target_id=12345,
            component_type="Camera",
            prop="fieldOfView",
            value=60,
        )

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["targetId"] == 12345
        assert "target" not in params

    def test_modify_sends_component_command(self, sut: ComponentAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}

        sut.modify(target="Cube", component_type="Camera", prop="fieldOfView", value=90)

        assert mock_conn.send_request.call_args[0][0] == "component"

    def test_modify_null_value(self, sut: ComponentAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}

        sut.modify(
            target="Cube",
            component_type="MeshRenderer",
            prop="m_Material",
            value=None,
        )

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["value"] is None


class TestComponentAPIList:
    """list() メソッドのテスト"""

    def test_list_by_target_name(self, sut: ComponentAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"components": []}

        sut.list(target="Player")

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["action"] == "list"
        assert params["target"] == "Player"


class TestComponentAPIInspect:
    """inspect() メソッドのテスト"""

    def test_inspect_by_target_name(self, sut: ComponentAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"properties": {}}

        sut.inspect(target="Player", component_type="Camera")

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["action"] == "inspect"
        assert params["type"] == "Camera"
        assert params["target"] == "Player"
