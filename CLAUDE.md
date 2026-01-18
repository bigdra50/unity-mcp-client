# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Unity CLI + Relay Server for controlling Unity Editor via TCP. Supports multiple Unity instances with domain reload resilience.

```
CLI ←──TCP:6500──→ Relay Server (Python) ←──TCP:6500──→ Unity Editor(s)
```

## Commands

```bash
# Install globally
uv tool install .

# Run CLI
unity-cli state
unity-cli play
unity-cli console --types error --count 10
unity-cli instances

# Run Relay Server standalone
unity-relay --port 6500

# Run directly without install
python -m unity_cli state
python -m relay.server --port 6500

# Test with uvx (after pushing to GitHub)
uvx --from git+https://github.com/bigdra50/unity-cli unity-cli state
```

## Architecture

### Protocol (4-byte framing)

```
┌────────────────────────────────────┐
│ 4-byte Length (big-endian, uint32) │
├────────────────────────────────────┤
│ JSON Payload (UTF-8)               │
└────────────────────────────────────┘
```

Max payload: 16 MiB

### Message Flow

**CLI → Relay:**
```json
{"type": "REQUEST", "id": "cli-xxx:uuid", "command": "manage_editor", "params": {"action": "play"}}
```

**Relay → Unity:**
```json
{"type": "COMMAND", "id": "cli-xxx:uuid", "command": "manage_editor", "params": {"action": "play"}}
```

**Unity → Relay → CLI:**
```json
{"type": "RESPONSE", "id": "cli-xxx:uuid", "success": true, "data": {...}}
```

### State Machine

```
DISCONNECTED → (REGISTER) → READY → (COMMAND) → BUSY → (COMMAND_RESULT) → READY
                              ↓                                              ↑
                        (beforeReload)                              (afterReload)
                              ↓                                              ↑
                          RELOADING ─────────────────────────────────────────┘
```

### Code Structure

```
relay/
├── server.py           # Main Relay Server
├── protocol.py         # Message types, framing, error codes
├── instance_registry.py # Unity instance management, queue
└── request_cache.py    # Idempotency cache (success only)

unity_cli/              # CLI package (Typer + Rich)

UnityBridge/
├── Editor/
│   ├── RelayClient.cs      # TCP connection to Relay
│   ├── Protocol.cs         # Framing, message serialization
│   ├── CommandDispatcher.cs # [BridgeTool] attribute handler
│   ├── BridgeReloadHandler.cs # Domain reload recovery
│   ├── BridgeManager.cs    # Singleton manager
│   ├── BridgeEditorWindow.cs # UI
│   ├── RelayServerLauncher.cs # uvx server launch
│   └── Tools/              # Command handlers
└── package.json
```

## Key Implementation Details

### Relay Server

- Port: 6500 (default)
- Heartbeat: 5s interval, 15s timeout, 3 retries
- RELOADING timeout: 30s (extended)
- Single Outstanding PING rule
- Queue: FIFO, max 10, disabled by default
- Idempotency: cache success responses for 60s

### CLI

- Exponential backoff: 500ms → 1s → 2s → 4s → 8s (max 30s total)
- Retryable errors: INSTANCE_RELOADING, INSTANCE_BUSY, TIMEOUT
- request_id format: `{client_id}:{uuid}`

### Unity Bridge

- Instance ID: `Path.GetFullPath(Application.dataPath + "/..")`
- Domain reload: STATUS "reloading" → reconnect → REGISTER
- [BridgeTool("command_name")] attribute for auto-discovery

## Protocol Spec

See `docs/protocol-spec.md` for full specification.

## Testing

```bash
# Run relay tests
python -m pytest tests/

# Verify Unity compilation
unity-cli refresh
unity-cli console --types error
```
