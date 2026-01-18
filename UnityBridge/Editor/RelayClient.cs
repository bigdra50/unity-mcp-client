using System;
using System.Net.Sockets;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace UnityBridge
{
    /// <summary>
    /// Connection status for the relay client
    /// </summary>
    public enum ConnectionStatus
    {
        Disconnected,
        Connecting,
        Connected,
        Reloading
    }

    /// <summary>
    /// Event args for connection status changes
    /// </summary>
    public class ConnectionStatusChangedEventArgs : EventArgs
    {
        public ConnectionStatus OldStatus { get; }
        public ConnectionStatus NewStatus { get; }

        public ConnectionStatusChangedEventArgs(ConnectionStatus oldStatus, ConnectionStatus newStatus)
        {
            OldStatus = oldStatus;
            NewStatus = newStatus;
        }
    }

    /// <summary>
    /// Event args for received commands
    /// </summary>
    public class CommandReceivedEventArgs : EventArgs
    {
        public string Id { get; }
        public string Command { get; }
        public JObject Parameters { get; }
        public int TimeoutMs { get; }

        public CommandReceivedEventArgs(string id, string command, JObject parameters, int timeoutMs)
        {
            Id = id;
            Command = command;
            Parameters = parameters;
            TimeoutMs = timeoutMs;
        }
    }

    /// <summary>
    /// TCP client for connecting to the Relay Server.
    /// Handles registration, heartbeat, and command message routing.
    /// </summary>
    public class RelayClient : IDisposable
    {
        private TcpClient _client;
        private NetworkStream _stream;
        private CancellationTokenSource _cts;
        private Task _receiveTask;
        private Task _heartbeatTask;

        private readonly string _host;
        private readonly int _port;
        private int _heartbeatIntervalMs = ProtocolConstants.HeartbeatIntervalMs;
        private long _lastPingTs;

        private ConnectionStatus _status = ConnectionStatus.Disconnected;
        private readonly object _statusLock = new object();

        /// <summary>
        /// Instance ID (project path)
        /// </summary>
        public string InstanceId { get; }

        /// <summary>
        /// Project name
        /// </summary>
        public string ProjectName { get; }

        /// <summary>
        /// Unity version
        /// </summary>
        public string UnityVersion { get; }

        /// <summary>
        /// Supported capabilities
        /// </summary>
        public string[] Capabilities { get; set; } = Array.Empty<string>();

        /// <summary>
        /// Current connection status
        /// </summary>
        public ConnectionStatus Status
        {
            get
            {
                lock (_statusLock)
                {
                    return _status;
                }
            }
            private set
            {
                ConnectionStatus oldStatus;
                lock (_statusLock)
                {
                    if (_status == value)
                        return;
                    oldStatus = _status;
                    _status = value;
                }

                Debug.Log($"[UnityBridge] Status: {oldStatus} -> {value}");
                StatusChanged?.Invoke(this, new ConnectionStatusChangedEventArgs(oldStatus, value));
            }
        }

        /// <summary>
        /// Whether the client is currently connected
        /// </summary>
        public bool IsConnected => Status == ConnectionStatus.Connected;

        /// <summary>
        /// Event fired when connection status changes
        /// </summary>
        public event EventHandler<ConnectionStatusChangedEventArgs> StatusChanged;

        /// <summary>
        /// Event fired when a command is received from the relay server
        /// </summary>
        public event EventHandler<CommandReceivedEventArgs> CommandReceived;

        /// <summary>
        /// Create a new relay client
        /// </summary>
        public RelayClient(string host = "127.0.0.1", int port = ProtocolConstants.DefaultPort)
        {
            _host = host;
            _port = port;

            InstanceId = InstanceIdHelper.GetInstanceId();
            ProjectName = InstanceIdHelper.GetProjectName(InstanceId);
            UnityVersion = Application.unityVersion;
        }

        /// <summary>
        /// Connect to the relay server and register this instance
        /// </summary>
        public async Task ConnectAsync(CancellationToken cancellationToken = default)
        {
            if (Status == ConnectionStatus.Connected || Status == ConnectionStatus.Connecting)
            {
                Debug.LogWarning("[UnityBridge] Already connected or connecting");
                return;
            }

            Status = ConnectionStatus.Connecting;
            _cts = new CancellationTokenSource();

            try
            {
                Debug.Log($"[UnityBridge] Connecting to {_host}:{_port}...");

                _client = new TcpClient();
                await _client.ConnectAsync(_host, _port);
                _stream = _client.GetStream();

                // Send REGISTER
                var registerMsg = Messages.CreateRegister(
                    InstanceId,
                    ProjectName,
                    UnityVersion,
                    Capabilities);

                await Framing.WriteFrameAsync(_stream, registerMsg, cancellationToken);
                Debug.Log($"[UnityBridge] Sent REGISTER: {InstanceId}");

                // Wait for REGISTERED response
                var response = await Framing.ReadFrameAsync(_stream, cancellationToken);
                var msgType = response["type"]?.Value<string>();

                if (msgType != MessageType.Registered)
                {
                    throw new ProtocolException(
                        ErrorCode.ProtocolError,
                        $"Expected REGISTERED, got: {msgType}");
                }

                var (success, heartbeatIntervalMs, errorCode, errorMessage) =
                    Messages.ParseRegistered(response);

                if (!success)
                {
                    throw new ProtocolException(
                        errorCode ?? ErrorCode.InternalError,
                        errorMessage ?? "Registration failed");
                }

                _heartbeatIntervalMs = heartbeatIntervalMs;
                Status = ConnectionStatus.Connected;
                Debug.Log($"[UnityBridge] Connected! Heartbeat interval: {_heartbeatIntervalMs}ms");

                // Start receive and heartbeat tasks
                _receiveTask = Task.Run(() => ReceiveLoopAsync(_cts.Token), _cts.Token);
                _heartbeatTask = Task.Run(() => HeartbeatLoopAsync(_cts.Token), _cts.Token);
            }
            catch (Exception ex)
            {
                Debug.LogError($"[UnityBridge] Connection failed: {ex.Message}");
                await DisconnectInternalAsync();
                throw;
            }
        }

        /// <summary>
        /// Disconnect from the relay server
        /// </summary>
        public async Task DisconnectAsync()
        {
            Debug.Log("[UnityBridge] Disconnecting...");
            await DisconnectInternalAsync();
        }

        /// <summary>
        /// Send a STATUS message to indicate reloading state
        /// </summary>
        public async Task SendReloadingStatusAsync()
        {
            if (_stream == null || !_client?.Connected == true)
                return;

            try
            {
                Status = ConnectionStatus.Reloading;
                var statusMsg = Messages.CreateStatus(InstanceId, InstanceStatus.Reloading, "Domain reload started");
                await Framing.WriteFrameAsync(_stream, statusMsg);
                Debug.Log("[UnityBridge] Sent STATUS: reloading");
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[UnityBridge] Failed to send reloading status: {ex.Message}");
            }
        }

        /// <summary>
        /// Send a STATUS message to indicate ready state
        /// </summary>
        public async Task SendReadyStatusAsync()
        {
            if (_stream == null || !_client?.Connected == true)
                return;

            try
            {
                var statusMsg = Messages.CreateStatus(InstanceId, InstanceStatus.Ready);
                await Framing.WriteFrameAsync(_stream, statusMsg);
                Debug.Log("[UnityBridge] Sent STATUS: ready");
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[UnityBridge] Failed to send ready status: {ex.Message}");
            }
        }

        /// <summary>
        /// Send a command result back to the relay server
        /// </summary>
        public async Task SendCommandResultAsync(string id, JObject data)
        {
            if (_stream == null || !_client?.Connected == true)
            {
                Debug.LogWarning("[UnityBridge] Cannot send result: not connected");
                return;
            }

            try
            {
                var resultMsg = Messages.CreateCommandResult(id, data);
                await Framing.WriteFrameAsync(_stream, resultMsg);
                Debug.Log($"[UnityBridge] Sent COMMAND_RESULT: {id} at {DateTime.Now:HH:mm:ss.fff}");
            }
            catch (Exception ex)
            {
                Debug.LogError($"[UnityBridge] Failed to send command result: {ex.Message}");
            }
        }

        /// <summary>
        /// Send a command error result back to the relay server
        /// </summary>
        public async Task SendCommandErrorAsync(string id, string code, string message)
        {
            if (_stream == null || !_client?.Connected == true)
            {
                Debug.LogWarning("[UnityBridge] Cannot send error: not connected");
                return;
            }

            try
            {
                var errorMsg = Messages.CreateCommandResultError(id, code, message);
                await Framing.WriteFrameAsync(_stream, errorMsg);
                Debug.Log($"[UnityBridge] Sent COMMAND_RESULT (error): {id} - {code}");
            }
            catch (Exception ex)
            {
                Debug.LogError($"[UnityBridge] Failed to send command error: {ex.Message}");
            }
        }

        private async Task ReceiveLoopAsync(CancellationToken cancellationToken)
        {
            Debug.Log("[UnityBridge] Receive loop started");

            try
            {
                while (!cancellationToken.IsCancellationRequested && _client?.Connected == true)
                {
                    var msg = await Framing.ReadFrameAsync(_stream, cancellationToken);
                    await HandleMessageAsync(msg, cancellationToken);
                }
            }
            catch (OperationCanceledException)
            {
                // Normal cancellation
            }
            catch (Exception ex)
            {
                if (!cancellationToken.IsCancellationRequested)
                {
                    Debug.LogError($"[UnityBridge] Receive loop error: {ex.Message}");
                    await DisconnectInternalAsync();
                }
            }

            Debug.Log("[UnityBridge] Receive loop ended");
        }

        private async Task HandleMessageAsync(JObject msg, CancellationToken cancellationToken)
        {
            var msgType = msg["type"]?.Value<string>();

            switch (msgType)
            {
                case MessageType.Ping:
                    await HandlePingAsync(msg, cancellationToken);
                    break;

                case MessageType.Command:
                    HandleCommand(msg);
                    break;

                default:
                    Debug.LogWarning($"[UnityBridge] Unknown message type: {msgType}");
                    break;
            }
        }

        private async Task HandlePingAsync(JObject msg, CancellationToken cancellationToken)
        {
            var pingTs = Messages.ParsePing(msg);
            _lastPingTs = pingTs;

            var pongMsg = Messages.CreatePong(pingTs);
            await Framing.WriteFrameAsync(_stream, pongMsg, cancellationToken);
        }

        private void HandleCommand(JObject msg)
        {
            var (id, command, parameters, timeoutMs) = Messages.ParseCommand(msg);
            Debug.Log($"[UnityBridge] Received COMMAND: {command} (id: {id}) at {DateTime.Now:HH:mm:ss.fff}");

            // Fire event on main thread
            var args = new CommandReceivedEventArgs(id, command, parameters, timeoutMs);

            // Since Unity isn't thread-safe, we need to dispatch to main thread
            // This will be handled by the subscriber (e.g., CommandDispatcher)
            CommandReceived?.Invoke(this, args);
        }

        private async Task HeartbeatLoopAsync(CancellationToken cancellationToken)
        {
            Debug.Log("[UnityBridge] Heartbeat monitor started");

            try
            {
                while (!cancellationToken.IsCancellationRequested && _client?.Connected == true)
                {
                    await Task.Delay(_heartbeatIntervalMs, cancellationToken);

                    // The server sends PING, we respond with PONG
                    // This loop is just for monitoring/cleanup if needed
                }
            }
            catch (OperationCanceledException)
            {
                // Normal cancellation
            }
            catch (Exception ex)
            {
                if (!cancellationToken.IsCancellationRequested)
                {
                    Debug.LogError($"[UnityBridge] Heartbeat error: {ex.Message}");
                }
            }

            Debug.Log("[UnityBridge] Heartbeat monitor ended");
        }

        private async Task DisconnectInternalAsync()
        {
            // Guard against re-entrant calls
            lock (_statusLock)
            {
                if (_status == ConnectionStatus.Disconnected)
                    return;
            }

            // Set status first to prevent race conditions
            // Use direct field assignment to avoid event firing during cleanup
            ConnectionStatus oldStatus;
            lock (_statusLock)
            {
                oldStatus = _status;
                _status = ConnectionStatus.Disconnected;
            }

            try
            {
                // Cancel token first to signal all async operations to stop
                try
                {
                    _cts?.Cancel();
                }
                catch (ObjectDisposedException)
                {
                    // Already disposed
                }

                // Capture references before nulling to avoid race conditions
                var stream = _stream;
                var client = _client;
                var receiveTask = _receiveTask;
                var heartbeatTask = _heartbeatTask;
                var cts = _cts;

                _stream = null;
                _client = null;
                _receiveTask = null;
                _heartbeatTask = null;
                _cts = null;

                // Close stream/client first to unblock any pending reads
                try
                {
                    stream?.Close();
                }
                catch
                {
                    // Ignore - stream may already be closed
                }

                try
                {
                    client?.Close();
                }
                catch
                {
                    // Ignore - client may already be closed
                }

                // Wait briefly for tasks to complete (non-blocking)
                // Use ConfigureAwait(false) to avoid deadlock on UI thread
                var tasksToWait = new System.Collections.Generic.List<Task>();
                if (receiveTask != null && !receiveTask.IsCompleted)
                    tasksToWait.Add(receiveTask);
                if (heartbeatTask != null && !heartbeatTask.IsCompleted)
                    tasksToWait.Add(heartbeatTask);

                if (tasksToWait.Count > 0)
                {
                    try
                    {
                        // Wait with timeout - don't block forever
                        await Task.WhenAny(
                            Task.WhenAll(tasksToWait),
                            Task.Delay(500)
                        ).ConfigureAwait(false);
                    }
                    catch
                    {
                        // Ignore - tasks may have faulted
                    }
                }

                // Dispose resources
                try
                {
                    stream?.Dispose();
                }
                catch
                {
                    // Ignore
                }

                try
                {
                    client?.Dispose();
                }
                catch
                {
                    // Ignore
                }

                try
                {
                    cts?.Dispose();
                }
                catch
                {
                    // Ignore
                }
            }
            finally
            {
                // Fire status changed event after all cleanup is done
                // Only fire if status actually changed
                if (oldStatus != ConnectionStatus.Disconnected)
                {
                    Debug.Log($"[UnityBridge] Status: {oldStatus} -> Disconnected");
                    try
                    {
                        StatusChanged?.Invoke(this, new ConnectionStatusChangedEventArgs(oldStatus, ConnectionStatus.Disconnected));
                    }
                    catch (Exception ex)
                    {
                        Debug.LogWarning($"[UnityBridge] StatusChanged event handler error: {ex.Message}");
                    }
                }
            }
        }

        public void Dispose()
        {
            // Fire and forget to avoid blocking Unity main thread
            _ = DisconnectInternalAsync();
        }
    }
}
