"""Tests for unity_cli/api/package.py - Package API"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from unity_cli.api.package import PackageAPI


@pytest.fixture
def mock_conn() -> MagicMock:
    return MagicMock()


@pytest.fixture
def sut(mock_conn: MagicMock) -> PackageAPI:
    return PackageAPI(mock_conn)


class TestPackageAPIList:
    def test_list_sends_package_command(self, sut: PackageAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"count": 0, "packages": []}

        sut.list()

        call_args = mock_conn.send_request.call_args
        assert call_args[0][0] == "package"
        assert call_args[0][1]["action"] == "list"

    def test_list_returns_result(self, sut: PackageAPI, mock_conn: MagicMock) -> None:
        expected = {"count": 2, "packages": [{"name": "com.unity.core"}, {"name": "com.unity.ugui"}]}
        mock_conn.send_request.return_value = expected

        result = sut.list()

        assert result == expected


class TestPackageAPIAdd:
    def test_add_sends_name_param(self, sut: PackageAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"message": "added"}

        sut.add("com.unity.textmeshpro@3.0.6")

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["action"] == "add"
        assert params["name"] == "com.unity.textmeshpro@3.0.6"

    def test_add_sends_package_command(self, sut: PackageAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"message": "added"}

        sut.add("com.unity.ugui")

        assert mock_conn.send_request.call_args[0][0] == "package"


class TestPackageAPIRemove:
    def test_remove_sends_name_param(self, sut: PackageAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"message": "removed"}

        sut.remove("com.unity.textmeshpro")

        call_args = mock_conn.send_request.call_args
        params = call_args[0][1]
        assert params["action"] == "remove"
        assert params["name"] == "com.unity.textmeshpro"

    def test_remove_sends_package_command(self, sut: PackageAPI, mock_conn: MagicMock) -> None:
        mock_conn.send_request.return_value = {"message": "removed"}

        sut.remove("com.unity.ugui")

        assert mock_conn.send_request.call_args[0][0] == "package"
