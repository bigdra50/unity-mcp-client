using System;
using System.Threading.Tasks;
using UnityEditor;
using UnityEngine;

namespace UnityBridge
{
    /// <summary>
    /// Handles domain reload events to maintain relay connection stability.
    /// Sends STATUS "reloading" before assembly reload and reconnects after.
    /// </summary>
    [InitializeOnLoad]
    public static class BridgeReloadHandler
    {
        // Use SessionState to persist connection info across domain reloads
        private const string SessionStateKeyWasConnected = "UnityBridge.ReloadHandler.WasConnected";
        private const string SessionStateKeyLastHost = "UnityBridge.ReloadHandler.LastHost";
        private const string SessionStateKeyLastPort = "UnityBridge.ReloadHandler.LastPort";

        private static bool WasConnected
        {
            get => SessionState.GetBool(SessionStateKeyWasConnected, false);
            set => SessionState.SetBool(SessionStateKeyWasConnected, value);
        }

        private static string LastHost
        {
            get => SessionState.GetString(SessionStateKeyLastHost, "127.0.0.1");
            set => SessionState.SetString(SessionStateKeyLastHost, value);
        }

        private static int LastPort
        {
            get => SessionState.GetInt(SessionStateKeyLastPort, ProtocolConstants.DefaultPort);
            set => SessionState.SetInt(SessionStateKeyLastPort, value);
        }

        static BridgeReloadHandler()
        {
            AssemblyReloadEvents.beforeAssemblyReload += OnBeforeAssemblyReload;
            AssemblyReloadEvents.afterAssemblyReload += OnAfterAssemblyReload;
            EditorApplication.quitting += OnEditorQuitting;

            Debug.Log("[UnityBridge] Reload handler initialized");
        }

        /// <summary>
        /// Register the relay client to be managed during domain reloads
        /// </summary>
        public static void RegisterClient(RelayClient client, string host, int port)
        {
            if (client != null && client.IsConnected)
            {
                WasConnected = true;
                LastHost = host;
                LastPort = port;
            }
        }

        /// <summary>
        /// Unregister the relay client
        /// </summary>
        public static void UnregisterClient()
        {
            WasConnected = false;
        }

        private static void OnBeforeAssemblyReload()
        {
            Debug.Log("[UnityBridge] Before assembly reload");

            var manager = BridgeManager.Instance;
            if (manager != null && manager.Client != null && manager.Client.IsConnected)
            {
                WasConnected = true;
                LastHost = manager.Host;
                LastPort = manager.Port;

                // Fire-and-forget: send reloading status without waiting
                // Waiting would freeze Unity during domain reload
                _ = Task.Run(async () =>
                {
                    try
                    {
                        await manager.Client.SendReloadingStatusAsync().ConfigureAwait(false);
                    }
                    catch
                    {
                        // Ignore - connection may be lost during reload anyway
                    }
                });
            }
        }

        private static void OnAfterAssemblyReload()
        {
            Debug.Log("[UnityBridge] After assembly reload");

            if (WasConnected)
            {
                WasConnected = false;

                // Use update callback instead of delayCall
                // delayCall doesn't fire until editor receives focus
                var host = LastHost;
                var port = LastPort;

                void ReconnectOnUpdate()
                {
                    EditorApplication.update -= ReconnectOnUpdate;
                    ReconnectAsync(host, port);
                }

                EditorApplication.update += ReconnectOnUpdate;
            }
        }

        private static async void ReconnectAsync(string host, int port)
        {
            if (string.IsNullOrEmpty(host) || port <= 0)
            {
                Debug.LogError($"[UnityBridge] Reconnection failed: invalid parameters (host={host}, port={port})");
                return;
            }

            try
            {
                var manager = BridgeManager.Instance;
                if (manager == null)
                {
                    Debug.LogError("[UnityBridge] Reconnection failed: BridgeManager.Instance is null");
                    return;
                }

                await manager.ConnectAsync(host, port);
                Debug.Log("[UnityBridge] Reconnected after reload");

                if (manager.Client != null && manager.Client.IsConnected)
                {
                    await manager.Client.SendReadyStatusAsync();
                }
            }
            catch (Exception ex)
            {
                Debug.LogError($"[UnityBridge] Reconnection failed: {ex.Message}");
            }
        }

        private static void OnEditorQuitting()
        {
            Debug.Log("[UnityBridge] Editor quitting");

            var manager = BridgeManager.Instance;
            if (manager != null)
            {
                // Fire-and-forget disconnect - don't block editor quit
                _ = Task.Run(async () =>
                {
                    try
                    {
                        await manager.DisconnectAsync().ConfigureAwait(false);
                    }
                    catch
                    {
                        // Ignore - editor is quitting anyway
                    }
                });
            }

            WasConnected = false;
        }
    }
}
