# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Unity CLI + Relay Server for controlling Unity Editor via TCP. Supports multiple Unity instances with domain reload resilience.

```
CLI ←──TCP:6500──→ Relay Server (Python) ←──TCP:6500──→ Unity Editor(s)
```

## Commands

```bash
# Install globally (provides: unity-cli, u, unity commands)
uv tool install .

# Run CLI (u and unity are aliases for unity-cli)
u state                                   # Get editor state
u play                                    # Enter play mode
u stop                                    # Exit play mode
u pause                                   # Toggle pause
u refresh                                 # Refresh AssetDatabase
u instances                               # List connected instances

# Editor Selection & Screenshot
u selection                               # Get current editor selection
u screenshot -s game -p ./out.png

# Console commands (adb logcat style levels)
u console get                             # All logs (plain text)
u console get -o json                     # All logs (JSON format)
u console get -v                          # All logs with stack traces
u console get -l W                        # Warning and above
u console get -l E                        # Error and above
u console get -l +W                       # Warning only
u console get -l +E+X                     # Error and exception only
u console get -l E -c 10                  # Last 10 error+ logs
u console clear                           # Clear console

# Scene commands
u scene active                            # Get active scene info
u scene hierarchy                         # Get scene hierarchy
u scene load <path>                       # Load a scene
u scene save                              # Save current scene

# Test commands
u tests run edit                          # Run EditMode tests
u tests run play                          # Run PlayMode tests
u tests list edit                         # List EditMode tests
u tests status                            # Check test status

# GameObject commands
u gameobject find <name>                  # Find GameObjects
u gameobject create <name>                # Create GameObject
u gameobject modify -n <name> --position 0 1 0  # Modify transform
u gameobject delete <name>                # Delete GameObject

# Component commands
u component list <gameobject>             # List components
u component inspect <gameobject> <type>   # Inspect properties
u component add <gameobject> <type>       # Add component
u component remove <gameobject> <type>    # Remove component

# Menu commands
u menu exec "Window/General/Console"      # Execute menu item

# Asset commands
u asset prefab <gameobject> <path>        # Create prefab
u asset scriptable-object <type> <path>   # Create ScriptableObject
u asset info <path>                       # Get asset info

# UI Toolkit tree commands (Playwright MCP-like ref ID system)
u uitree dump                            # List all panels
u uitree dump -p "GameView"              # Dump tree as text
u uitree dump -p "GameView" -o json      # Dump tree as JSON
u uitree dump -p "GameView" -d 3         # Limit depth
u uitree query -p "GameView" -t Button   # Query by type
u uitree query -p "GameView" -n "StartBtn"  # Query by name
u uitree query -p "GameView" -c "primary-button"  # Query by class
u uitree inspect ref_3                   # Inspect by ref ID
u uitree inspect ref_3 --style           # Include resolvedStyle
u uitree inspect ref_3 --children        # Include children

# Standalone tools (no Relay required)
u config show                             # Show configuration
u project info                            # Project info
u editor list                             # List installed editors
u editor install <version>                # Install via Hub
u open                                    # Open project

# Run Relay Server standalone
unity-relay --port 6500

# Run directly without install
python -m unity_cli state
python -m relay.server --port 6500

# Test with uvx (after pushing to GitHub)
uvx --from git+https://github.com/bigdra50/unity-cli u state
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

unity_cli/
├── __init__.py         # Package init
├── cli/
│   └── app.py          # CLI entry point (Typer + Rich)
├── client.py           # Relay client with retry logic
├── config.py           # Configuration management
├── models.py           # Data models
└── exceptions.py       # Custom exceptions

UnityBridge/
├── Editor/
│   ├── RelayClient.cs        # TCP connection to Relay
│   ├── Protocol.cs           # Framing, message serialization
│   ├── CommandDispatcher.cs  # [BridgeTool] attribute handler
│   ├── BridgeReloadHandler.cs # Domain reload recovery
│   ├── BridgeManager.cs      # Singleton manager
│   ├── BridgeEditorWindow.cs # UI
│   ├── RelayServerLauncher.cs # uvx server launch
│   ├── Helpers/
│   │   ├── BridgeJobStateStore.cs # Job state persistence
│   │   ├── BridgeLog.cs      # Logging utility
│   │   ├── PortManager.cs    # Port management
│   │   └── Response.cs       # Response builder
│   └── Tools/                # Command handlers
│       ├── Asset.cs          # Prefab, ScriptableObject
│       ├── Component.cs      # Component operations
│       ├── Console.cs        # Console log retrieval
│       ├── EditorSelection.cs # Selection state
│       ├── GameObject.cs     # GameObject operations
│       ├── MenuItem.cs       # Menu item execution
│       ├── Playmode.cs       # Play/Stop/Pause
│       ├── Refresh.cs        # Asset database refresh
│       ├── Scene.cs          # Scene management
│       ├── Screenshot.cs     # Screenshot capture
│       ├── Tests.cs          # Test runner
│       └── UITree.cs         # UI Toolkit tree inspection
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
unity-cli console get -l E
```
