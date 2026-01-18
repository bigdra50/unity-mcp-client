using System;
using System.Diagnostics;
using System.IO;
using UnityEditor;
using UnityEngine;
using Debug = UnityEngine.Debug;

namespace UnityBridge
{
    /// <summary>
    /// Manages the Relay Server process lifecycle.
    /// Uses SessionState to persist server PID across domain reloads.
    /// </summary>
    public sealed class RelayServerLauncher : IDisposable
    {
        private const string PackageSource = "git+https://github.com/bigdra50/unity-mcp-client";
        private const string EditorPrefsKeyCommand = "UnityBridge.RelayServer.CustomCommand";
        private const string SessionStateKeyPid = "UnityBridge.RelayServer.Pid";
        private const string SessionStateKeyPort = "UnityBridge.RelayServer.Port";

        private static RelayServerLauncher _instance;
        public static RelayServerLauncher Instance => _instance ??= new RelayServerLauncher();

        private Process _serverProcess;
        private string _uvPath;
        private string _localDevPath;

        /// <summary>
        /// Check if server is running - either via Process object or via saved PID
        /// </summary>
        public bool IsRunning
        {
            get
            {
                // First check if we have a direct process reference
                if (_serverProcess is { HasExited: false })
                {
                    return true;
                }

                // Check if there's a saved PID from before domain reload
                var savedPid = SessionState.GetInt(SessionStateKeyPid, -1);
                if (savedPid > 0)
                {
                    try
                    {
                        var process = Process.GetProcessById(savedPid);
                        if (!process.HasExited)
                        {
                            return true;
                        }
                    }
                    catch
                    {
                        // Process doesn't exist anymore
                        SessionState.EraseInt(SessionStateKeyPid);
                    }
                }

                return false;
            }
        }

        /// <summary>
        /// Get the port the server is running on (from SessionState)
        /// </summary>
        public int CurrentPort => SessionState.GetInt(SessionStateKeyPort, ProtocolConstants.DefaultPort);

        public event EventHandler<string> OutputReceived;
        public event EventHandler<string> ErrorReceived;
        public event EventHandler ServerStarted;
        public event EventHandler ServerStopped;

        /// <summary>
        /// Custom command saved in EditorPrefs
        /// </summary>
        public string CustomCommand
        {
            get => EditorPrefs.GetString(EditorPrefsKeyCommand, "");
            set => EditorPrefs.SetString(EditorPrefsKeyCommand, value);
        }

        private RelayServerLauncher()
        {
            EditorApplication.quitting += OnEditorQuitting;
            DetectPaths();
        }

        private void DetectPaths()
        {
            _uvPath = FindExecutable("uv");

#if UNITY_BRIDGE_LOCAL_DEV
            // Force local development mode with define symbol
            var projectRoot = Path.GetDirectoryName(Application.dataPath);
            var relayPath = Path.Combine(projectRoot, "relay");
            if (Directory.Exists(relayPath))
            {
                _localDevPath = projectRoot;
                Debug.Log($"[UnityBridge] UNITY_BRIDGE_LOCAL_DEV enabled, using local path: {_localDevPath}");
            }
            else
            {
                Debug.LogWarning("[UnityBridge] UNITY_BRIDGE_LOCAL_DEV enabled but relay/ not found in project root");
            }
#endif
        }

        /// <summary>
        /// Build augmented PATH that includes common binary locations.
        /// Unity GUI app has limited PATH, so we need to add common paths explicitly.
        /// </summary>
        private static string BuildAugmentedPath()
        {
            var homeDir = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            var additionalPaths = new[]
            {
                "/opt/homebrew/bin", // Homebrew on Apple Silicon
                "/usr/local/bin", // Homebrew on Intel / common binaries
                "/usr/bin",
                "/bin",
                Path.Combine(homeDir, ".local", "bin"), // pip --user, uv
                Path.Combine(homeDir, ".cargo", "bin") // Rust/cargo installs
            };

            var currentPath = Environment.GetEnvironmentVariable("PATH") ?? "";

            return Application.platform == RuntimePlatform.WindowsEditor
                ? string.Join(";", additionalPaths) + ";" + currentPath
                : string.Join(":", additionalPaths) + ":" + currentPath;
        }

        /// <summary>
        /// Kill any process listening on the specified port
        /// </summary>
        private static void KillProcessOnPort(int port)
        {
            try
            {
                var pid = GetProcessIdForPort(port);
                if (pid > 0)
                {
                    Debug.Log($"[UnityBridge] Killing existing process on port {port} (PID: {pid})");
                    KillProcess(pid);
                    // Wait a bit for the port to be released
                    System.Threading.Thread.Sleep(500);
                }
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[UnityBridge] Error killing process on port {port}: {ex.Message}");
            }
        }

        private static int GetProcessIdForPort(int port)
        {
            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = "/usr/sbin/lsof",
                    Arguments = $"-i :{port} -t",
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true
                };

                using var process = Process.Start(psi);
                if (process == null) return -1;

                var output = process.StandardOutput.ReadToEnd().Trim();
                process.WaitForExit(5000);

                if (process.ExitCode == 0 && !string.IsNullOrEmpty(output))
                {
                    // lsof -t returns PID(s), take the first one
                    var firstLine = output.Split('\n')[0].Trim();
                    if (int.TryParse(firstLine, out var pid))
                    {
                        return pid;
                    }
                }
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[UnityBridge] Error checking port {port}: {ex.Message}");
            }

            return -1;
        }

        private static void KillProcess(int pid)
        {
            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = "/bin/kill",
                    Arguments = $"-9 {pid}",
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true
                };

                using var process = Process.Start(psi);
                process?.WaitForExit(3000);
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[UnityBridge] Error killing process {pid}: {ex.Message}");
            }
        }

        private static string FindExecutable(string name)
        {
            // First check augmented paths directly
            var homeDir = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            var searchPaths = new[]
            {
                "/opt/homebrew/bin",
                "/usr/local/bin",
                "/usr/bin",
                "/bin",
                Path.Combine(homeDir, ".local", "bin"),
                Path.Combine(homeDir, ".cargo", "bin")
            };

            foreach (var basePath in searchPaths)
            {
                var fullPath = Path.Combine(basePath, name);
                if (File.Exists(fullPath))
                {
                    return fullPath;
                }

                if (Application.platform == RuntimePlatform.WindowsEditor)
                {
                    var exePath = fullPath + ".exe";
                    if (File.Exists(exePath))
                    {
                        return exePath;
                    }
                }
            }

            // Also check current PATH
            var pathEnv = Environment.GetEnvironmentVariable("PATH") ?? "";
            var separator = Application.platform == RuntimePlatform.WindowsEditor ? ';' : ':';
            var paths = pathEnv.Split(separator);

            foreach (var basePath in paths)
            {
                if (string.IsNullOrEmpty(basePath)) continue;

                var fullPath = Path.Combine(basePath, name);
                if (File.Exists(fullPath))
                {
                    return fullPath;
                }

                if (Application.platform == RuntimePlatform.WindowsEditor)
                {
                    var exePath = fullPath + ".exe";
                    if (File.Exists(exePath))
                    {
                        return exePath;
                    }
                }
            }

            return null;
        }

        public void Start(int port = ProtocolConstants.DefaultPort)
        {
            if (IsRunning)
            {
                Debug.LogWarning("[UnityBridge] Relay Server is already running");
                return;
            }

            // Kill any existing process on the port
            KillProcessOnPort(port);

            try
            {
                var startInfo = BuildStartInfo(port);
                if (startInfo == null)
                {
                    return;
                }

                _serverProcess = new Process { StartInfo = startInfo, EnableRaisingEvents = true };

                _serverProcess.OutputDataReceived += (_, e) =>
                {
                    if (!string.IsNullOrEmpty(e.Data))
                    {
                        Debug.Log($"[Relay Server] {e.Data}");
                        OutputReceived?.Invoke(this, e.Data);
                    }
                };

                _serverProcess.ErrorDataReceived += (_, e) =>
                {
                    if (!string.IsNullOrEmpty(e.Data))
                    {
                        if (e.Data.Contains("ERROR") || e.Data.Contains("Exception"))
                        {
                            Debug.LogError($"[Relay Server] {e.Data}");
                        }
                        else
                        {
                            Debug.Log($"[Relay Server] {e.Data}");
                        }

                        ErrorReceived?.Invoke(this, e.Data);
                    }
                };

                _serverProcess.Exited += (_, _) =>
                {
                    Debug.Log("[UnityBridge] Relay Server stopped");
                    ServerStopped?.Invoke(this, EventArgs.Empty);
                };

                _serverProcess.Start();
                _serverProcess.BeginOutputReadLine();
                _serverProcess.BeginErrorReadLine();

                // Save PID and port to SessionState for domain reload persistence
                SessionState.SetInt(SessionStateKeyPid, _serverProcess.Id);
                SessionState.SetInt(SessionStateKeyPort, port);

                Debug.Log($"[UnityBridge] Relay Server started (PID: {_serverProcess.Id}, Port: {port})");
                Debug.Log($"[UnityBridge] Command: {startInfo.FileName} {startInfo.Arguments}");
                ServerStarted?.Invoke(this, EventArgs.Empty);
            }
            catch (Exception ex)
            {
                Debug.LogError($"[UnityBridge] Failed to start Relay Server: {ex.Message}");
                _serverProcess = null;
            }
        }

        private ProcessStartInfo BuildStartInfo(int port)
        {
            var startInfo = new ProcessStartInfo
            {
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };

            // Set augmented PATH for Unity GUI environment
            startInfo.Environment["PATH"] = BuildAugmentedPath();
            // Set PYTHONUNBUFFERED for real-time output
            startInfo.Environment["PYTHONUNBUFFERED"] = "1";

            // Priority 1: Custom command from EditorPrefs
            var customCmd = CustomCommand;
            if (!string.IsNullOrEmpty(customCmd))
            {
                var expanded = customCmd.Replace("{port}", port.ToString());
                return ParseShellCommand(expanded, startInfo);
            }

#if UNITY_BRIDGE_LOCAL_DEV
            // Priority 2: Local development (relay/ exists in project)
            if (!string.IsNullOrEmpty(_localDevPath))
            {
                if (_uvPath != null)
                {
                    startInfo.FileName = _uvPath;
                    startInfo.Arguments = $"run python -m relay.server --port {port}";
                    startInfo.WorkingDirectory = _localDevPath;
                    Debug.Log($"[UnityBridge] Using local development mode: {_localDevPath}");
                    return startInfo;
                }

                var python = FindExecutable("python3") ?? FindExecutable("python");
                if (python != null)
                {
                    startInfo.FileName = python;
                    startInfo.Arguments = $"-m relay.server --port {port}";
                    startInfo.WorkingDirectory = _localDevPath;
                    return startInfo;
                }
            }
#endif

            // Priority 3: uvx (production)
            if (_uvPath != null)
            {
                startInfo.FileName = _uvPath;
                startInfo.Arguments = $"run --from {PackageSource} unity-relay --port {port}";
                Debug.Log("[UnityBridge] Using uvx with remote package");
                return startInfo;
            }

            Debug.LogError(
                "[UnityBridge] Could not find uv. Please install uv (https://docs.astral.sh/uv/) or set a custom command.");
            return null;
        }

        private ProcessStartInfo ParseShellCommand(string command, ProcessStartInfo baseInfo)
        {
            // Simple parsing: first word is executable, rest is arguments
            var parts = command.Trim().Split(new[] { ' ' }, 2);
            var executable = parts[0];

            // Resolve common commands to their full paths
            executable = executable switch
            {
                "uv" => _uvPath ?? FindExecutable("uv") ?? executable,
                "python" => FindExecutable("python") ?? executable,
                "python3" => FindExecutable("python3") ?? executable,
                _ => executable
            };

            baseInfo.FileName = executable;
            baseInfo.Arguments = parts.Length > 1 ? parts[1] : "";
            return baseInfo;
        }

        public void Stop()
        {
            if (!IsRunning)
            {
                return;
            }

            try
            {
                Debug.Log("[UnityBridge] Stopping Relay Server...");

                // Try to stop via direct process reference first
                if (_serverProcess != null && !_serverProcess.HasExited)
                {
                    _serverProcess.Kill();
                }
                else
                {
                    // Fallback: use saved PID from SessionState (after domain reload)
                    var savedPid = SessionState.GetInt(SessionStateKeyPid, -1);
                    if (savedPid > 0)
                    {
                        Debug.Log($"[UnityBridge] Killing server by saved PID: {savedPid}");
                        KillProcess(savedPid);
                    }
                }
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[UnityBridge] Error stopping server: {ex.Message}");
            }
            finally
            {
                try
                {
                    _serverProcess?.Dispose();
                }
                catch
                {
                    // Ignore dispose errors
                }

                _serverProcess = null;

                // Clear SessionState
                SessionState.EraseInt(SessionStateKeyPid);
                SessionState.EraseInt(SessionStateKeyPort);

                Debug.Log("[UnityBridge] Relay Server stopped");

                // Fire ServerStopped event so listeners can clean up
                // Note: Process.Exited event may not fire when we call Kill() + Dispose()
                try
                {
                    ServerStopped?.Invoke(this, EventArgs.Empty);
                }
                catch (Exception ex)
                {
                    Debug.LogWarning($"[UnityBridge] ServerStopped event error: {ex.Message}");
                }
            }
        }

        private void OnEditorQuitting()
        {
            Stop();
        }

        public void Dispose()
        {
            EditorApplication.quitting -= OnEditorQuitting;
            Stop();
            _instance = null;
        }

        /// <summary>
        /// Get detected environment info for display
        /// </summary>
        public (string mode, string detail) GetDetectedMode()
        {
            if (!string.IsNullOrEmpty(CustomCommand))
            {
                return ("Custom", CustomCommand);
            }

#if UNITY_BRIDGE_LOCAL_DEV
            if (!string.IsNullOrEmpty(_localDevPath))
            {
                return ("Local Dev (UNITY_BRIDGE_LOCAL_DEV)", _localDevPath);
            }
#endif

            if (_uvPath != null)
            {
                return ("uvx", PackageSource);
            }

            return ("Not Available", "Install uv or set custom command");
        }

        /// <summary>
        /// Get the command that will be executed to start the server.
        /// Returns null if no valid command can be constructed.
        /// </summary>
        public string GetServerCommand(int port = ProtocolConstants.DefaultPort)
        {
            // Priority 1: Custom command
            var customCmd = CustomCommand;
            if (!string.IsNullOrEmpty(customCmd))
            {
                return customCmd.Replace("{port}", port.ToString());
            }

#if UNITY_BRIDGE_LOCAL_DEV
            // Priority 2: Local development
            if (!string.IsNullOrEmpty(_localDevPath))
            {
                if (_uvPath != null)
                {
                    return $"cd \"{_localDevPath}\" && uv run python -m relay.server --port {port}";
                }

                var python = FindExecutable("python3") ?? FindExecutable("python");
                if (python != null)
                {
                    return $"cd \"{_localDevPath}\" && python -m relay.server --port {port}";
                }
            }
#endif

            // Priority 3: uvx (production)
            if (_uvPath != null)
            {
                return $"uvx --from {PackageSource} unity-relay --port {port}";
            }

            return null;
        }
    }
}
