using System;
using System.Collections.Concurrent;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using UnityBridge.Helpers;
using UnityEditor;

namespace UnityBridge
{
    /// <summary>
    /// Singleton manager for the Unity Bridge connection.
    /// Handles connection lifecycle, command dispatch, and main thread synchronization.
    /// </summary>
    public class BridgeManager
    {
        private static BridgeManager _instance;
        private static readonly object _lock = new object();

        private RelayClient _client;
        private CommandDispatcher _dispatcher;

        // Command queue for main thread execution
        private readonly ConcurrentQueue<CommandReceivedEventArgs> _commandQueue = new();
        private bool _updateRegistered;

        /// <summary>
        /// Singleton instance
        /// </summary>
        public static BridgeManager Instance
        {
            get
            {
                if (_instance == null)
                {
                    lock (_lock)
                    {
                        if (_instance == null)
                        {
                            _instance = new BridgeManager();
                        }
                    }
                }

                return _instance;
            }
        }

        /// <summary>
        /// The relay client instance
        /// </summary>
        public RelayClient Client => _client;

        /// <summary>
        /// The command dispatcher instance
        /// </summary>
        public CommandDispatcher Dispatcher => _dispatcher;

        /// <summary>
        /// Current connection host
        /// </summary>
        public string Host { get; private set; } = "127.0.0.1";

        /// <summary>
        /// Current connection port
        /// </summary>
        public int Port { get; private set; } = ProtocolConstants.DefaultPort;

        /// <summary>
        /// Whether the client is connected
        /// </summary>
        public bool IsConnected => _client?.IsConnected ?? false;

        /// <summary>
        /// Event fired when connection status changes
        /// </summary>
        public event EventHandler<ConnectionStatusChangedEventArgs> StatusChanged;

        private BridgeManager()
        {
            _dispatcher = new CommandDispatcher();
        }

        /// <summary>
        /// Connect to the relay server
        /// </summary>
        public async Task ConnectAsync(string host = "127.0.0.1", int port = ProtocolConstants.DefaultPort)
        {
            if (_client != null)
            {
                await DisconnectAsync();
            }

            Host = host;
            Port = port;

            _client = new RelayClient(host, port);
            _client.StatusChanged += OnClientStatusChanged;
            _client.CommandReceived += OnCommandReceived;

            await _client.ConnectAsync();

            // Register for reload handling
            BridgeReloadHandler.RegisterClient(_client, host, port);
        }

        /// <summary>
        /// Disconnect from the relay server
        /// </summary>
        public async Task DisconnectAsync()
        {
            BridgeReloadHandler.UnregisterClient();

            // Unregister update handler
            UnregisterUpdate();

            // Capture reference to avoid race conditions
            var client = _client;
            _client = null;

            if (client != null)
            {
                // Unsubscribe from events first to prevent callbacks during disconnect
                client.StatusChanged -= OnClientStatusChanged;
                client.CommandReceived -= OnCommandReceived;

                try
                {
                    await client.DisconnectAsync().ConfigureAwait(false);
                }
                catch (Exception ex)
                {
                    BridgeLog.Warn($"Disconnect error (ignored): {ex.Message}");
                }

                try
                {
                    client.Dispose();
                }
                catch (Exception ex)
                {
                    BridgeLog.Warn($"Dispose error (ignored): {ex.Message}");
                }
            }
        }

        private void OnClientStatusChanged(object sender, ConnectionStatusChangedEventArgs e)
        {
            // Forward to subscribers
            StatusChanged?.Invoke(this, e);
        }

        private void OnCommandReceived(object sender, CommandReceivedEventArgs e)
        {
            BridgeLog.Verbose($"Queuing command for main thread: {e.Command} (id: {e.Id})");

            // Queue command for main thread execution
            _commandQueue.Enqueue(e);

            // Ensure update handler is registered
            EnsureUpdateRegistered();
        }

        private void EnsureUpdateRegistered()
        {
            if (_updateRegistered)
                return;

            EditorApplication.update += ProcessCommandQueue;
            _updateRegistered = true;
            BridgeLog.Verbose("Registered EditorApplication.update handler");
        }

        private void UnregisterUpdate()
        {
            if (!_updateRegistered)
                return;

            EditorApplication.update -= ProcessCommandQueue;
            _updateRegistered = false;
        }

        private void ProcessCommandQueue()
        {
            // Process all queued commands
            while (_commandQueue.TryDequeue(out var e))
            {
                BridgeLog.Verbose($"Processing command from queue: {e.Command} (id: {e.Id})");
                ExecuteCommandOnMainThread(e);
            }
        }

        private async void ExecuteCommandOnMainThread(CommandReceivedEventArgs e)
        {
            BridgeLog.Verbose($"Executing command on main thread: {e.Command} (id: {e.Id})");

            if (_client == null || !_client.IsConnected)
            {
                BridgeLog.Warn($"Cannot execute command, not connected: {e.Command}");
                return;
            }

            try
            {
                // Execute command asynchronously - await allows EditorApplication.update to continue
                var result = await _dispatcher.ExecuteAsync(e.Command, e.Parameters);

                // Send result
                await _client.SendCommandResultAsync(e.Id, result).ConfigureAwait(false);
            }
            catch (ProtocolException pex)
            {
                BridgeLog.Warn($"Protocol error: {pex.Code} - {pex.Message}");
                try
                {
                    await _client.SendCommandErrorAsync(e.Id, pex.Code, pex.Message).ConfigureAwait(false);
                }
                catch (Exception sendEx)
                {
                    BridgeLog.Error($"Failed to send error response: {sendEx.Message}");
                }
            }
            catch (Exception ex)
            {
                BridgeLog.Error($"Command execution failed: {ex.GetType().Name} - {ex.Message}\n{ex.StackTrace}");
                try
                {
                    await _client.SendCommandErrorAsync(e.Id, ErrorCode.InternalError, ex.Message).ConfigureAwait(false);
                }
                catch (Exception sendEx)
                {
                    BridgeLog.Error($"Failed to send error response: {sendEx.Message}");
                }
            }
        }

        /// <summary>
        /// Set the capabilities to advertise during registration
        /// </summary>
        public void SetCapabilities(params string[] capabilities)
        {
            if (_client != null)
            {
                _client.Capabilities = capabilities;
            }
        }
    }
}
