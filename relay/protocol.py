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
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Constants
PROTOCOL_VERSION = "1.0"
MAX_PAYLOAD_BYTES = 16 * 1024 * 1024  # 16 MiB
HEADER_SIZE = 4


class MessageType(str, Enum):
    # Unity -> Relay
    REGISTER = "REGISTER"
    REGISTERED = "REGISTERED"
    STATUS = "STATUS"
    COMMAND_RESULT = "COMMAND_RESULT"
    PONG = "PONG"

    # Relay -> Unity
    PING = "PING"
    COMMAND = "COMMAND"

    # CLI -> Relay
    REQUEST = "REQUEST"
    LIST_INSTANCES = "LIST_INSTANCES"
    SET_DEFAULT = "SET_DEFAULT"

    # Relay -> CLI
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
    AMBIGUOUS_INSTANCE = "AMBIGUOUS_INSTANCE"


class InstanceStatus(str, Enum):
    READY = "ready"
    BUSY = "busy"
    RELOADING = "reloading"
    DISCONNECTED = "disconnected"


def _timestamp_ms() -> int:
    """Generate current timestamp in milliseconds."""
    return int(time.time() * 1000)


def _generate_uuid() -> str:
    """Generate a UUID string."""
    return str(uuid.uuid4())


class Message(BaseModel):
    """Base message class"""

    model_config = ConfigDict(frozen=True)

    type: str
    ts: int = Field(default_factory=_timestamp_ms)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True, by_alias=True)


# Unity -> Relay Messages


class RegisterMessage(Message):
    """Unity registration message"""

    model_config = ConfigDict(frozen=True)

    type: Literal["REGISTER"] = "REGISTER"
    protocol_version: str = PROTOCOL_VERSION
    instance_id: str = ""
    project_name: str = ""
    unity_version: str = ""
    capabilities: list[str] = Field(default_factory=list)

    @field_validator("instance_id")
    @classmethod
    def validate_instance_id(cls, v: str) -> str:
        # Allow empty string for backwards compatibility, but validate format if provided
        return v


class RegisteredMessage(Message):
    """Registration response"""

    model_config = ConfigDict(frozen=True)

    type: Literal["REGISTERED"] = "REGISTERED"
    success: bool = True
    heartbeat_interval_ms: int = Field(default=5000, gt=0)
    error: dict[str, str] | None = None


class StatusMessage(Message):
    """Status update from Unity"""

    model_config = ConfigDict(frozen=True)

    type: Literal["STATUS"] = "STATUS"
    instance_id: str = ""
    status: str = ""
    detail: str | None = None


class CommandResultMessage(Message):
    """Command result from Unity"""

    model_config = ConfigDict(frozen=True)

    type: Literal["COMMAND_RESULT"] = "COMMAND_RESULT"
    id: str = ""
    success: bool = True
    data: dict[str, Any] | None = None
    error: dict[str, str] | None = None


class PongMessage(Message):
    """Heartbeat response"""

    model_config = ConfigDict(frozen=True)

    type: Literal["PONG"] = "PONG"
    echo_ts: int = 0


# Relay -> Unity Messages


class PingMessage(Message):
    """Heartbeat request"""

    model_config = ConfigDict(frozen=True)

    type: Literal["PING"] = "PING"


class CommandMessage(Message):
    """Command to Unity"""

    model_config = ConfigDict(frozen=True)

    type: Literal["COMMAND"] = "COMMAND"
    id: str = ""
    command: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    timeout_ms: int = Field(default=30000, gt=0)

    @field_validator("command")
    @classmethod
    def validate_command(cls, v: str) -> str:
        if not v:
            raise ValueError("command must not be empty")
        return v


# CLI -> Relay Messages


class RequestMessage(Message):
    """Request from CLI"""

    model_config = ConfigDict(frozen=True)

    type: Literal["REQUEST"] = "REQUEST"
    id: str = Field(default_factory=_generate_uuid)
    instance: str | None = None
    command: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    timeout_ms: int = Field(default=30000, gt=0)

    @field_validator("command")
    @classmethod
    def validate_command(cls, v: str) -> str:
        if not v:
            raise ValueError("command must not be empty")
        return v


class ListInstancesMessage(Message):
    """List instances request"""

    model_config = ConfigDict(frozen=True)

    type: Literal["LIST_INSTANCES"] = "LIST_INSTANCES"
    id: str = Field(default_factory=_generate_uuid)


class SetDefaultMessage(Message):
    """Set default instance"""

    model_config = ConfigDict(frozen=True)

    type: Literal["SET_DEFAULT"] = "SET_DEFAULT"
    id: str = Field(default_factory=_generate_uuid)
    instance: str = ""

    @field_validator("instance")
    @classmethod
    def validate_instance(cls, v: str) -> str:
        if not v:
            raise ValueError("instance must not be empty")
        return v


# Relay -> CLI Messages


class ResponseMessage(Message):
    """Success response to CLI"""

    model_config = ConfigDict(frozen=True)

    type: Literal["RESPONSE"] = "RESPONSE"
    id: str = ""
    success: bool = True
    data: dict[str, Any] | None = None
    error: dict[str, str] | None = None


class ErrorMessage(Message):
    """Error response to CLI"""

    model_config = ConfigDict(frozen=True)

    type: Literal["ERROR"] = "ERROR"
    id: str = ""
    success: bool = False
    error: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_code(cls, request_id: str, code: ErrorCode, message: str) -> ErrorMessage:
        return cls(id=request_id, error={"code": code.value, "message": message})


class InstancesMessage(Message):
    """Instance list response"""

    model_config = ConfigDict(frozen=True)

    type: Literal["INSTANCES"] = "INSTANCES"
    id: str = ""
    success: bool = True
    data: dict[str, Any] = Field(default_factory=dict)


# Framing functions


async def write_frame(writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
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
