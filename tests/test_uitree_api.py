"""Tests for unity_cli/api/uitree.py - UITree API"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from unity_cli.api.uitree import UITreeAPI


@pytest.fixture
def mock_conn() -> MagicMock:
    return MagicMock()


@pytest.fixture
def sut(mock_conn: MagicMock) -> UITreeAPI:
    return UITreeAPI(mock_conn)


class TestUITreeAPIDump:
    """dump() メソッドのテスト"""

    def test_dump_without_panel_lists_panels(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"panels": [{"name": "GameView", "contextType": "Editor"}]}

        result = sut.dump()

        mock_conn.send_request.assert_called_once_with("uitree", {"action": "dump", "format": "text"})
        assert "panels" in result

    def test_dump_with_panel_sends_panel_param(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {
            "panel": "GameView",
            "tree": "VisualElement ...",
        }

        sut.dump(panel="GameView")

        call_args = mock_conn.send_request.call_args
        assert call_args[0][1]["panel"] == "GameView"

    def test_dump_with_depth_sends_depth_param(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}

        sut.dump(panel="GameView", depth=3)

        call_args = mock_conn.send_request.call_args
        assert call_args[0][1]["depth"] == 3

    def test_dump_default_depth_not_sent(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}

        sut.dump(panel="GameView")

        call_args = mock_conn.send_request.call_args
        assert "depth" not in call_args[0][1]

    def test_dump_json_format(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}

        sut.dump(panel="GameView", format="json")

        call_args = mock_conn.send_request.call_args
        assert call_args[0][1]["format"] == "json"


class TestUITreeAPIQuery:
    """query() メソッドのテスト"""

    def test_query_with_type_filter(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"matches": [], "count": 0}

        sut.query(panel="GameView", type="Button")

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["action"] == "query"
        assert params["panel"] == "GameView"
        assert params["type"] == "Button"

    def test_query_with_name_filter(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"matches": [], "count": 0}

        sut.query(panel="GameView", name="StartBtn")

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["name"] == "StartBtn"

    def test_query_with_class_name_filter(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"matches": [], "count": 0}

        sut.query(panel="GameView", class_name="primary-button")

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["class_name"] == "primary-button"

    def test_query_multiple_filters_combined(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"matches": [], "count": 0}

        sut.query(
            panel="GameView",
            type="Button",
            name="Start",
            class_name="primary",
        )

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["type"] == "Button"
        assert params["name"] == "Start"
        assert params["class_name"] == "primary"

    def test_query_no_filters_sends_only_panel(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"matches": [], "count": 0}

        sut.query(panel="GameView")

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params == {"action": "query", "panel": "GameView"}

    def test_query_none_filters_not_included(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"matches": [], "count": 0}

        sut.query(panel="GameView", type=None, name=None, class_name=None)

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert "type" not in params
        assert "name" not in params
        assert "class_name" not in params


class TestUITreeAPIInspect:
    """inspect() メソッドのテスト"""

    def test_inspect_with_ref(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {
            "ref": "ref_3",
            "type": "Button",
        }

        sut.inspect(ref="ref_3")

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["action"] == "inspect"
        assert params["ref"] == "ref_3"
        assert params["include_style"] is False
        assert params["include_children"] is False

    def test_inspect_with_panel_and_name(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {
            "type": "Button",
            "name": "StartBtn",
        }

        sut.inspect(panel="GameView", name="StartBtn")

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["panel"] == "GameView"
        assert params["name"] == "StartBtn"
        assert "ref" not in params

    def test_inspect_with_style(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {
            "ref": "ref_3",
            "resolvedStyle": {"color": "rgba(255,255,255,1)"},
        }

        sut.inspect(ref="ref_3", include_style=True)

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["include_style"] is True

    def test_inspect_with_children(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {
            "ref": "ref_3",
            "children": [{"ref": "ref_4", "type": "Label"}],
        }

        sut.inspect(ref="ref_3", include_children=True)

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["include_children"] is True

    def test_inspect_with_both_style_and_children(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}

        sut.inspect(ref="ref_3", include_style=True, include_children=True)

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["include_style"] is True
        assert params["include_children"] is True

    def test_inspect_without_ref_or_panel_still_sends_request(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        """API層はバリデーションしない（CLI層で行う）"""
        mock_conn.send_request.return_value = {}

        sut.inspect()

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params == {
            "action": "inspect",
            "include_style": False,
            "include_children": False,
        }


class TestUITreeAPIParameterIntegrity:
    """パラメータの整合性テスト"""

    def test_all_methods_use_uitree_command(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}

        sut.dump()
        assert mock_conn.send_request.call_args_list[0][0][0] == "uitree"

        sut.query(panel="GameView")
        assert mock_conn.send_request.call_args_list[1][0][0] == "uitree"

        sut.inspect(ref="ref_0")
        assert mock_conn.send_request.call_args_list[2][0][0] == "uitree"

    def test_dump_action_value(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}
        sut.dump()
        assert mock_conn.send_request.call_args[0][1]["action"] == "dump"

    def test_query_action_value(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}
        sut.query(panel="GameView")
        assert mock_conn.send_request.call_args[0][1]["action"] == "query"

    def test_inspect_action_value(self, sut: UITreeAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {}
        sut.inspect(ref="ref_0")
        assert mock_conn.send_request.call_args[0][1]["action"] == "inspect"
