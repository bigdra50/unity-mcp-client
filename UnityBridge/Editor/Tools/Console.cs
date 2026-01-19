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
    /// Based on Coplay/unity-mcp (now CoplayDev/unity-mcp) implementation.
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
                BridgeLog.Verbose($"Console: Total entries={totalCount}, requested types={string.Join(",", types)}, count={count}");

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
            // Unity 6000.x observed mode values:
            //   Debug.Log:       0x00804400
            //   Debug.LogWarning: 0x00804200
            //   Compiler Warning: 0x00041000
            //   Error/Exception: typically has bit 0 (kModeLog) not set
            //
            // The lower 8 bits often appear to be 0x00, so we cannot rely on LogType mask.
            // Instead, use bit pattern analysis and message content.

            // 1. First check message content (most reliable)
            if (message != null)
            {
                // Check for error indicators
                if (message.Contains("error CS") ||        // Compiler error
                    message.Contains("Exception:") ||       // Exception with colon
                    message.Contains("NullReferenceException") ||
                    message.Contains("IndexOutOfRangeException") ||
                    message.Contains("ArgumentException") ||
                    message.StartsWith("[Error]") ||
                    (message.Contains("Error") && !message.Contains("[UnityBridge]")))  // Exclude our own logs
                    return "error";

                // Check for warning indicators
                if (message.Contains("warning CS") ||      // Compiler warning
                    message.StartsWith("[Warning]") ||
                    message.StartsWith("Warning:"))
                    return "warning";
            }

            // 2. Check known mode bit patterns for Unity 6000.x
            // Compiler warning: 0x00041000 (bits 12, 16 set)
            // Debug.LogWarning: 0x00804200 (bit 9 set instead of bit 10)
            // Debug.Log:        0x00804400 (bit 10 set)
            // Note: bits 9 vs 10 distinguish Warning vs Log in Unity's internal encoding

            const int kBit9 = 1 << 9;   // 0x200 - Warning indicator
            const int kBit10 = 1 << 10; // 0x400 - Log indicator
            const int kBit12 = 1 << 12; // 0x1000 - Compiler message
            const int kBit16 = 1 << 16; // 0x10000 - Warning class

            // Compiler warnings: bits 12 and 16 set (0x00041000)
            if ((mode & kBit12) != 0 && (mode & kBit16) != 0)
                return "warning";

            // Debug.LogWarning: bit 9 set but not bit 10
            if ((mode & kBit9) != 0 && (mode & kBit10) == 0)
                return "warning";

            // Debug.Log: bit 10 set (0x00804400)
            if ((mode & kBit10) != 0)
                return "log";

            // Default: treat as log
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
