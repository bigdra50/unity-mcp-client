using System;
using System.Collections.Generic;
using System.Reflection;
using Newtonsoft.Json.Linq;
using UnityBridge.Helpers;

namespace UnityBridge.Tools
{
    /// <summary>
    /// Handler for console commands.
    /// Reads and clears Unity console log entries.
    /// Based on Coplay/unity-mcp implementation.
    /// </summary>
    [BridgeTool("console")]
    public static class Console
    {
        public static JObject HandleCommand(JObject parameters)
        {
            var action = parameters["action"]?.Value<string>() ?? "read";

            return action switch
            {
                "read" => HandleRead(parameters),
                "clear" => HandleClear(),
                _ => new JObject
                {
                    ["success"] = false,
                    ["error"] = $"Unknown action: {action}. Valid actions: read, clear"
                }
            };
        }

        private static JObject HandleRead(JObject parameters)
        {
            var types = parameters["types"]?.ToObject<string[]>() ?? new[] { "log", "warning", "error" };
            var count = parameters["count"]?.Value<int>() ?? 100;
            var search = parameters["search"]?.Value<string>();

            var entries = GetConsoleEntries(types, count, search);

            return new JObject
            {
                ["entries"] = JArray.FromObject(entries),
                ["count"] = entries.Count
            };
        }

        private static JObject HandleClear()
        {
            ClearConsole();

            return new JObject
            {
                ["success"] = true,
                ["message"] = "Console cleared"
            };
        }

        private static List<object> GetConsoleEntries(string[] types, int count, string search)
        {
            var entries = new List<object>();

            // Use reflection to access internal LogEntries class
            var logEntriesType = Type.GetType("UnityEditor.LogEntries, UnityEditor");
            if (logEntriesType == null)
            {
                BridgeLog.Error("Could not find LogEntries type");
                return entries;
            }

            BridgeLog.Verbose($"LogEntries type found: {logEntriesType.FullName}");

            var logEntryType = Type.GetType("UnityEditor.LogEntry, UnityEditor");
            if (logEntryType == null)
            {
                BridgeLog.Error("Could not find LogEntry type");
                return entries;
            }

            BridgeLog.Verbose($"LogEntry type found: {logEntryType.FullName}");

            // Get methods - include NonPublic binding flag
            var bindingFlags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;

            var getCountMethod = logEntriesType.GetMethod("GetCount", bindingFlags);
            var startGettingEntriesMethod = logEntriesType.GetMethod("StartGettingEntries", bindingFlags);
            var getEntryInternalMethod = logEntriesType.GetMethod("GetEntryInternal", bindingFlags);
            var endGettingEntriesMethod = logEntriesType.GetMethod("EndGettingEntries", bindingFlags);

            if (getCountMethod == null || startGettingEntriesMethod == null ||
                getEntryInternalMethod == null || endGettingEntriesMethod == null)
            {
                BridgeLog.Error($"Could not find required LogEntries methods: GetCount={getCountMethod != null}, StartGettingEntries={startGettingEntriesMethod != null}, GetEntryInternal={getEntryInternalMethod != null}, EndGettingEntries={endGettingEntriesMethod != null}");
                // List all methods for debugging
                foreach (var method in logEntriesType.GetMethods(bindingFlags))
                {
                    BridgeLog.Verbose($"LogEntries method: {method.Name}");
                }
                return entries;
            }

            BridgeLog.Verbose("All LogEntries methods found");

            // Get LogEntry fields - include NonPublic binding flag
            var instanceBindingFlags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
            var messageField = logEntryType.GetField("message", instanceBindingFlags);
            var modeField = logEntryType.GetField("mode", instanceBindingFlags);

            // Also try "condition" field which some Unity versions use
            if (messageField == null)
            {
                messageField = logEntryType.GetField("condition", instanceBindingFlags);
            }

            if (messageField == null || modeField == null)
            {
                BridgeLog.Error($"Could not find required LogEntry fields: message={messageField != null}, mode={modeField != null}");
                // List all fields for debugging
                foreach (var field in logEntryType.GetFields(instanceBindingFlags))
                {
                    BridgeLog.Error($"LogEntry field: {field.Name} ({field.FieldType})");
                }
                return entries;
            }

            BridgeLog.Verbose($"LogEntry fields found: message={messageField.Name}, mode={modeField.Name}");

            // Convert type filters
            var typeSet = new HashSet<string>(types, StringComparer.OrdinalIgnoreCase);

            try
            {
                startGettingEntriesMethod.Invoke(null, null);

                var totalCount = (int)getCountMethod.Invoke(null, null);
                BridgeLog.Info($"Console: Total entries={totalCount}, requested types={string.Join(",", types)}, count={count}");

                var logEntry = Activator.CreateInstance(logEntryType);

                // Read from the end (most recent first)
                var startIndex = Math.Max(0, totalCount - count);

                for (var i = totalCount - 1; i >= startIndex && entries.Count < count; i--)
                {
                    getEntryInternalMethod.Invoke(null, new[] { i, logEntry });

                    var message = (string)messageField.GetValue(logEntry);
                    var mode = (int)modeField.GetValue(logEntry);
                    var entryType = GetEntryType(mode, message);

                    // Filter by type
                    if (!typeSet.Contains(entryType))
                        continue;

                    // Filter by search
                    if (!string.IsNullOrEmpty(search) &&
                        !message.Contains(search, StringComparison.OrdinalIgnoreCase))
                        continue;

                    entries.Add(new
                    {
                        message = message,
                        type = entryType,
                        timestamp = DateTime.Now.ToString("HH:mm:ss") // LogEntry doesn't have timestamp
                    });
                }
            }
            finally
            {
                endGettingEntriesMethod.Invoke(null, null);
            }

            return entries;
        }

        private static string GetEntryType(int mode, string message)
        {
            // Unity's mode field contains multiple flags. The lower bits vary by Unity version.
            // Observed: 0x804400 for Debug.Log
            //
            // Common bit patterns (may vary by Unity version):
            // Error/Exception bits tend to be in lower positions
            // Warning bits in middle positions
            // Log bits can be in various positions
            //
            // Unity 6000.x observed values:
            //   Log:     0x804400 (bit 10, 14, 23 set)
            //   Warning: TBD
            //   Error:   TBD

            // Use message content inference as primary method (most reliable across Unity versions)
            if (message != null)
            {
                // Check for error indicators in the message
                if (message.StartsWith("[Error]") ||
                    message.Contains("Exception") ||
                    message.Contains("NullReferenceException") ||
                    message.Contains("error CS") ||  // Compiler error
                    message.Contains("Error:"))
                    return "error";

                // Check for warning indicators
                if (message.StartsWith("[Warning]") ||
                    message.Contains("warning CS") ||  // Compiler warning
                    message.Contains("Warning:"))
                    return "warning";
            }

            // Fallback: check known mode bit patterns
            // These values are from Unity's internal ConsoleWindow
            const int kModeError = 1 << 0;      // 1
            const int kModeAssert = 1 << 1;     // 2
            const int kModeException = 1 << 8;  // 256

            if ((mode & kModeError) != 0 || (mode & kModeException) != 0 || (mode & kModeAssert) != 0)
                return "error";

            // Default to log (most common case)
            return "log";
        }

        private static void ClearConsole()
        {
            var logEntriesType = Type.GetType("UnityEditor.LogEntries, UnityEditor");
            var clearMethod = logEntriesType?.GetMethod("Clear", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
            clearMethod?.Invoke(null, null);
        }
    }
}
