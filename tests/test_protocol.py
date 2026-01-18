"""Tests for relay/protocol.py - Framing and message definitions"""

from __future__ import annotations

import json
import struct
import time

import pytest

from relay.protocol import (
    HEADER_SIZE,
    MAX_PAYLOAD_BYTES,
    PROTOCOL_VERSION,
    CommandMessage,
    CommandResultMessage,
    ErrorCode,
    ErrorMessage,
    InstancesMessage,
    InstanceStatus,
    ListInstancesMessage,
    MessageType,
    PingMessage,
    PongMessage,
    RegisteredMessage,
    RegisterMessage,
    RequestMessage,
    ResponseMessage,
    SetDefaultMessage,
    StatusMessage,
    generate_request_id,
    parse_message,
    write_frame_sync,
)


class TestProtocolConstants:
    """Test protocol constants"""

    def test_protocol_version(self) -> None:
        assert PROTOCOL_VERSION == "1.0"

    def test_header_size(self) -> None:
        assert HEADER_SIZE == 4

    def test_max_payload_bytes(self) -> None:
        assert MAX_PAYLOAD_BYTES == 16 * 1024 * 1024  # 16 MiB


class TestMessageTypes:
    """Test MessageType enum"""

    def test_unity_to_relay_types(self) -> None:
        assert MessageType.REGISTER.value == "REGISTER"
        assert MessageType.REGISTERED.value == "REGISTERED"
        assert MessageType.STATUS.value == "STATUS"
        assert MessageType.COMMAND_RESULT.value == "COMMAND_RESULT"
        assert MessageType.PONG.value == "PONG"

    def test_relay_to_unity_types(self) -> None:
        assert MessageType.PING.value == "PING"
        assert MessageType.COMMAND.value == "COMMAND"

    def test_cli_to_relay_types(self) -> None:
        assert MessageType.REQUEST.value == "REQUEST"
        assert MessageType.LIST_INSTANCES.value == "LIST_INSTANCES"
        assert MessageType.SET_DEFAULT.value == "SET_DEFAULT"

    def test_relay_to_cli_types(self) -> None:
        assert MessageType.RESPONSE.value == "RESPONSE"
        assert MessageType.ERROR.value == "ERROR"
        assert MessageType.INSTANCES.value == "INSTANCES"


class TestErrorCodes:
    """Test ErrorCode enum"""

    def test_instance_errors(self) -> None:
        assert ErrorCode.INSTANCE_NOT_FOUND.value == "INSTANCE_NOT_FOUND"
        assert ErrorCode.INSTANCE_RELOADING.value == "INSTANCE_RELOADING"
        assert ErrorCode.INSTANCE_BUSY.value == "INSTANCE_BUSY"
        assert ErrorCode.INSTANCE_DISCONNECTED.value == "INSTANCE_DISCONNECTED"

    def test_command_errors(self) -> None:
        assert ErrorCode.COMMAND_NOT_FOUND.value == "COMMAND_NOT_FOUND"
        assert ErrorCode.INVALID_PARAMS.value == "INVALID_PARAMS"

    def test_protocol_errors(self) -> None:
        assert ErrorCode.TIMEOUT.value == "TIMEOUT"
        assert ErrorCode.INTERNAL_ERROR.value == "INTERNAL_ERROR"
        assert ErrorCode.PROTOCOL_ERROR.value == "PROTOCOL_ERROR"
        assert ErrorCode.MALFORMED_JSON.value == "MALFORMED_JSON"
        assert ErrorCode.PAYLOAD_TOO_LARGE.value == "PAYLOAD_TOO_LARGE"
        assert ErrorCode.PROTOCOL_VERSION_MISMATCH.value == "PROTOCOL_VERSION_MISMATCH"


class TestInstanceStatus:
    """Test InstanceStatus enum"""

    def test_status_values(self) -> None:
        assert InstanceStatus.READY.value == "ready"
        assert InstanceStatus.BUSY.value == "busy"
        assert InstanceStatus.RELOADING.value == "reloading"
        assert InstanceStatus.DISCONNECTED.value == "disconnected"


class TestRegisterMessage:
    """Test RegisterMessage"""

    def test_default_values(self) -> None:
        msg = RegisterMessage()
        assert msg.type == MessageType.REGISTER
        assert msg.protocol_version == PROTOCOL_VERSION
        assert msg.instance_id == ""
        assert msg.project_name == ""
        assert msg.unity_version == ""
        assert msg.capabilities == []

    def test_to_dict(self) -> None:
        msg = RegisterMessage(
            instance_id="/Users/dev/MyGame",
            project_name="MyGame",
            unity_version="2022.3.20f1",
            capabilities=["manage_editor", "manage_gameobject"],
        )
        d = msg.to_dict()

        assert d["type"] == "REGISTER"
        assert d["protocol_version"] == "1.0"
        assert d["instance_id"] == "/Users/dev/MyGame"
        assert d["project_name"] == "MyGame"
        assert d["unity_version"] == "2022.3.20f1"
        assert d["capabilities"] == ["manage_editor", "manage_gameobject"]
        assert "ts" in d

    def test_immutable(self) -> None:
        msg = RegisterMessage()
        with pytest.raises(AttributeError):
            msg.instance_id = "new_id"  # type: ignore


class TestRegisteredMessage:
    """Test RegisteredMessage"""

    def test_success_response(self) -> None:
        msg = RegisteredMessage(success=True, heartbeat_interval_ms=5000)
        d = msg.to_dict()

        assert d["type"] == "REGISTERED"
        assert d["success"] is True
        assert d["heartbeat_interval_ms"] == 5000
        assert "error" not in d

    def test_error_response(self) -> None:
        msg = RegisteredMessage(
            success=False,
            error={"code": "PROTOCOL_VERSION_MISMATCH", "message": "Unsupported version"},
        )
        d = msg.to_dict()

        assert d["success"] is False
        assert d["error"]["code"] == "PROTOCOL_VERSION_MISMATCH"


class TestStatusMessage:
    """Test StatusMessage"""

    def test_to_dict_with_detail(self) -> None:
        msg = StatusMessage(
            instance_id="/Users/dev/MyGame",
            status="reloading",
            detail="Domain reload started",
        )
        d = msg.to_dict()

        assert d["type"] == "STATUS"
        assert d["instance_id"] == "/Users/dev/MyGame"
        assert d["status"] == "reloading"
        assert d["detail"] == "Domain reload started"

    def test_to_dict_without_detail(self) -> None:
        msg = StatusMessage(instance_id="/Users/dev/MyGame", status="ready")
        d = msg.to_dict()

        assert d["type"] == "STATUS"
        assert "detail" not in d


class TestCommandResultMessage:
    """Test CommandResultMessage"""

    def test_success_result(self) -> None:
        msg = CommandResultMessage(
            id="req-123",
            success=True,
            data={"isPlaying": True},
        )
        d = msg.to_dict()

        assert d["type"] == "COMMAND_RESULT"
        assert d["id"] == "req-123"
        assert d["success"] is True
        assert d["data"] == {"isPlaying": True}

    def test_error_result(self) -> None:
        msg = CommandResultMessage(
            id="req-123",
            success=False,
            error={"code": "INVALID_PARAMS", "message": "Unknown action"},
        )
        d = msg.to_dict()

        assert d["success"] is False
        assert d["error"]["code"] == "INVALID_PARAMS"


class TestPingPongMessages:
    """Test PING and PONG messages"""

    def test_ping_message(self) -> None:
        msg = PingMessage()
        d = msg.to_dict()

        assert d["type"] == "PING"
        assert "ts" in d

    def test_pong_message(self) -> None:
        ping_ts = int(time.time() * 1000)
        msg = PongMessage(echo_ts=ping_ts)
        d = msg.to_dict()

        assert d["type"] == "PONG"
        assert d["echo_ts"] == ping_ts


class TestCommandMessage:
    """Test CommandMessage"""

    def test_to_dict(self) -> None:
        msg = CommandMessage(
            id="req-456",
            command="manage_editor",
            params={"action": "play"},
            timeout_ms=30000,
        )
        d = msg.to_dict()

        assert d["type"] == "COMMAND"
        assert d["id"] == "req-456"
        assert d["command"] == "manage_editor"
        assert d["params"] == {"action": "play"}
        assert d["timeout_ms"] == 30000


class TestRequestMessage:
    """Test RequestMessage"""

    def test_auto_generates_id(self) -> None:
        msg = RequestMessage(command="manage_editor", params={"action": "play"})
        assert msg.id != ""
        assert len(msg.id) > 0

    def test_to_dict_with_instance(self) -> None:
        msg = RequestMessage(
            id="req-789",
            instance="/Users/dev/MyGame",
            command="get_editor_state",
            params={},
        )
        d = msg.to_dict()

        assert d["type"] == "REQUEST"
        assert d["id"] == "req-789"
        assert d["instance"] == "/Users/dev/MyGame"
        assert d["command"] == "get_editor_state"

    def test_to_dict_without_instance(self) -> None:
        msg = RequestMessage(id="req-789", command="get_editor_state", params={})
        d = msg.to_dict()

        assert "instance" not in d


class TestResponseMessage:
    """Test ResponseMessage"""

    def test_to_dict(self) -> None:
        msg = ResponseMessage(
            id="req-789",
            success=True,
            data={"isPlaying": False, "isCompiling": False},
        )
        d = msg.to_dict()

        assert d["type"] == "RESPONSE"
        assert d["id"] == "req-789"
        assert d["success"] is True
        assert d["data"]["isPlaying"] is False


class TestErrorMessage:
    """Test ErrorMessage"""

    def test_from_code(self) -> None:
        msg = ErrorMessage.from_code(
            "req-789",
            ErrorCode.INSTANCE_NOT_FOUND,
            "Instance not found: /path/to/project",
        )
        d = msg.to_dict()

        assert d["type"] == "ERROR"
        assert d["id"] == "req-789"
        assert d["success"] is False
        assert d["error"]["code"] == "INSTANCE_NOT_FOUND"
        assert d["error"]["message"] == "Instance not found: /path/to/project"


class TestInstancesMessage:
    """Test InstancesMessage"""

    def test_to_dict(self) -> None:
        msg = InstancesMessage(
            id="req-list",
            success=True,
            data={
                "instances": [
                    {
                        "instance_id": "/Users/dev/MyGame",
                        "project_name": "MyGame",
                        "status": "ready",
                        "is_default": True,
                    }
                ]
            },
        )
        d = msg.to_dict()

        assert d["type"] == "INSTANCES"
        assert d["success"] is True
        assert len(d["data"]["instances"]) == 1


class TestFraming:
    """Test framing functions"""

    def test_write_frame_sync_small_payload(self) -> None:
        payload = {"type": "PING", "ts": 1234567890}
        frame = write_frame_sync(payload)

        # Check header (4 bytes, big-endian)
        length = struct.unpack(">I", frame[:4])[0]
        payload_bytes = frame[4:]

        assert len(payload_bytes) == length
        assert json.loads(payload_bytes.decode("utf-8")) == payload

    def test_write_frame_sync_unicode(self) -> None:
        payload = {"type": "STATUS", "detail": "ドメインリロード開始"}
        frame = write_frame_sync(payload)

        length = struct.unpack(">I", frame[:4])[0]
        payload_bytes = frame[4:]

        assert len(payload_bytes) == length
        decoded = json.loads(payload_bytes.decode("utf-8"))
        assert decoded["detail"] == "ドメインリロード開始"

    def test_write_frame_sync_payload_too_large(self) -> None:
        # Create payload larger than MAX_PAYLOAD_BYTES
        large_data = "x" * (MAX_PAYLOAD_BYTES + 1)
        payload = {"data": large_data}

        with pytest.raises(ValueError, match="Payload too large"):
            write_frame_sync(payload)


class TestParseMessage:
    """Test parse_message function"""

    def test_valid_message(self) -> None:
        data = {"type": "REQUEST", "id": "123", "command": "test"}
        result = parse_message(data)
        assert result == data

    def test_missing_type(self) -> None:
        data = {"id": "123", "command": "test"}
        with pytest.raises(ValueError, match="Missing 'type' field"):
            parse_message(data)


class TestGenerateRequestId:
    """Test generate_request_id function"""

    def test_without_client_id(self) -> None:
        rid = generate_request_id()
        # Should be a valid UUID format
        assert len(rid) == 36  # UUID length with hyphens

    def test_with_client_id(self) -> None:
        rid = generate_request_id("client-abc")
        assert rid.startswith("client-abc:")
        # Rest should be UUID
        uuid_part = rid.split(":")[1]
        assert len(uuid_part) == 36

    def test_uniqueness(self) -> None:
        ids = [generate_request_id() for _ in range(100)]
        assert len(set(ids)) == 100  # All unique
