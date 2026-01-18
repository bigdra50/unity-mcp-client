"""
Unity Bridge Protocol v1.0

Framing: 4-byte big-endian length prefix + JSON payload
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Constants
PROTOCOL_VERSION = "1.0"
MAX_PAYLOAD_BYTES = 16 * 1024 * 1024  # 16 MiB
HEADER_SIZE = 4


class MessageType(str, Enum):
    # Unity → Relay
    REGISTER = "REGISTER"
    REGISTERED = "REGISTERED"
    STATUS = "STATUS"
    COMMAND_RESULT = "COMMAND_RESULT"
    PONG = "PONG"

    # Relay → Unity
    PING = "PING"
    COMMAND = "COMMAND"

    # CLI → Relay
    REQUEST = "REQUEST"
    LIST_INSTANCES = "LIST_INSTANCES"
    SET_DEFAULT = "SET_DEFAULT"

    # Relay → CLI
    RESPONSE = "RESPONSE"
    ERROR = "ERROR"
    INSTANCES = "INSTANCES"


class ErrorCode(str, Enum):
    INSTANCE_NOT_FOUND = "INSTANCE_NOT_FOUND"
    INSTANCE_RELOADING = "INSTANCE_RELOADING"
    INSTANCE_BUSY = "INSTANCE_BUSY"
    INSTANCE_DISCONNECTED = "INSTANCE_DISCONNECTED"
    COMMAND_NOT_FOUND = "COMMAND_NOT_FOUND"
    INVALID_PARAMS = "INVALID_PARAMS"
    TIMEOUT = "TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    MALFORMED_JSON = "MALFORMED_JSON"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    PROTOCOL_VERSION_MISMATCH = "PROTOCOL_VERSION_MISMATCH"
    CAPABILITY_NOT_SUPPORTED = "CAPABILITY_NOT_SUPPORTED"
    QUEUE_FULL = "QUEUE_FULL"


class InstanceStatus(str, Enum):
    READY = "ready"
    BUSY = "busy"
    RELOADING = "reloading"
    DISCONNECTED = "disconnected"


@dataclass(frozen=True)
class Message:
    """Base message class"""

    type: MessageType
    ts: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "ts": self.ts}


# Unity → Relay Messages


@dataclass(frozen=True)
class RegisterMessage(Message):
    """Unity registration message"""

    type: MessageType = field(default=MessageType.REGISTER, init=False)
    protocol_version: str = PROTOCOL_VERSION
    instance_id: str = ""
    project_name: str = ""
    unity_version: str = ""
    capabilities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(
            {
                "protocol_version": self.protocol_version,
                "instance_id": self.instance_id,
                "project_name": self.project_name,
                "unity_version": self.unity_version,
                "capabilities": self.capabilities,
            }
        )
        return d


@dataclass(frozen=True)
class RegisteredMessage(Message):
    """Registration response"""

    type: MessageType = field(default=MessageType.REGISTERED, init=False)
    success: bool = True
    heartbeat_interval_ms: int = 5000
    error: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(
            {
                "success": self.success,
                "heartbeat_interval_ms": self.heartbeat_interval_ms,
            }
        )
        if self.error:
            d["error"] = self.error
        return d


@dataclass(frozen=True)
class StatusMessage(Message):
    """Status update from Unity"""

    type: MessageType = field(default=MessageType.STATUS, init=False)
    instance_id: str = ""
    status: str = ""
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({"instance_id": self.instance_id, "status": self.status})
        if self.detail:
            d["detail"] = self.detail
        return d


@dataclass(frozen=True)
class CommandResultMessage(Message):
    """Command result from Unity"""

    type: MessageType = field(default=MessageType.COMMAND_RESULT, init=False)
    id: str = ""
    success: bool = True
    data: dict[str, Any] | None = None
    error: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({"id": self.id, "success": self.success})
        if self.data:
            d["data"] = self.data
        if self.error:
            d["error"] = self.error
        return d


@dataclass(frozen=True)
class PongMessage(Message):
    """Heartbeat response"""

    type: MessageType = field(default=MessageType.PONG, init=False)
    echo_ts: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["echo_ts"] = self.echo_ts
        return d


# Relay → Unity Messages


@dataclass(frozen=True)
class PingMessage(Message):
    """Heartbeat request"""

    type: MessageType = field(default=MessageType.PING, init=False)


@dataclass(frozen=True)
class CommandMessage(Message):
    """Command to Unity"""

    type: MessageType = field(default=MessageType.COMMAND, init=False)
    id: str = ""
    command: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 30000

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(
            {
                "id": self.id,
                "command": self.command,
                "params": self.params,
                "timeout_ms": self.timeout_ms,
            }
        )
        return d


# CLI → Relay Messages


@dataclass(frozen=True)
class RequestMessage(Message):
    """Request from CLI"""

    type: MessageType = field(default=MessageType.REQUEST, init=False)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    instance: str | None = None
    command: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 30000

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(
            {
                "id": self.id,
                "command": self.command,
                "params": self.params,
                "timeout_ms": self.timeout_ms,
            }
        )
        if self.instance:
            d["instance"] = self.instance
        return d


@dataclass(frozen=True)
class ListInstancesMessage(Message):
    """List instances request"""

    type: MessageType = field(default=MessageType.LIST_INSTANCES, init=False)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["id"] = self.id
        return d


@dataclass(frozen=True)
class SetDefaultMessage(Message):
    """Set default instance"""

    type: MessageType = field(default=MessageType.SET_DEFAULT, init=False)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    instance: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({"id": self.id, "instance": self.instance})
        return d


# Relay → CLI Messages


@dataclass(frozen=True)
class ResponseMessage(Message):
    """Success response to CLI"""

    type: MessageType = field(default=MessageType.RESPONSE, init=False)
    id: str = ""
    success: bool = True
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({"id": self.id, "success": self.success})
        if self.data:
            d["data"] = self.data
        return d


@dataclass(frozen=True)
class ErrorMessage(Message):
    """Error response to CLI"""

    type: MessageType = field(default=MessageType.ERROR, init=False)
    id: str = ""
    success: bool = False
    error: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({"id": self.id, "success": self.success, "error": self.error})
        return d

    @classmethod
    def from_code(
        cls, request_id: str, code: ErrorCode, message: str
    ) -> ErrorMessage:
        return cls(id=request_id, error={"code": code.value, "message": message})


@dataclass(frozen=True)
class InstancesMessage(Message):
    """Instance list response"""

    type: MessageType = field(default=MessageType.INSTANCES, init=False)
    id: str = ""
    success: bool = True
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({"id": self.id, "success": self.success, "data": self.data})
        return d


# Framing functions


async def write_frame(
    writer: asyncio.StreamWriter, payload: dict[str, Any]
) -> None:
    """Write a framed message: 4-byte big-endian length + JSON payload"""
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    length = len(payload_bytes)

    if length > MAX_PAYLOAD_BYTES:
        raise ValueError(f"Payload too large: {length} > {MAX_PAYLOAD_BYTES}")

    header = struct.pack(">I", length)  # 4-byte big-endian unsigned int
    writer.write(header + payload_bytes)
    await writer.drain()


async def read_frame(reader: asyncio.StreamReader) -> dict[str, Any]:
    """Read a framed message: 4-byte big-endian length + JSON payload"""
    header = await reader.readexactly(HEADER_SIZE)
    (length,) = struct.unpack(">I", header)

    if length > MAX_PAYLOAD_BYTES:
        raise ValueError(f"Payload too large: {length} > {MAX_PAYLOAD_BYTES}")

    payload_bytes = await reader.readexactly(length)
    payload_str = payload_bytes.decode("utf-8")

    return json.loads(payload_str)


def write_frame_sync(payload: dict[str, Any]) -> bytes:
    """Create a framed message (synchronous, for testing)"""
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    length = len(payload_bytes)

    if length > MAX_PAYLOAD_BYTES:
        raise ValueError(f"Payload too large: {length} > {MAX_PAYLOAD_BYTES}")

    header = struct.pack(">I", length)
    return header + payload_bytes


def parse_message(data: dict[str, Any]) -> dict[str, Any]:
    """Parse a raw message dict (for validation/logging)"""
    msg_type = data.get("type")
    if not msg_type:
        raise ValueError("Missing 'type' field")
    return data


def generate_request_id(client_id: str | None = None) -> str:
    """Generate a unique request ID"""
    if client_id:
        return f"{client_id}:{uuid.uuid4()}"
    return str(uuid.uuid4())
