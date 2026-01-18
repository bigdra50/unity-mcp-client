using UnityEngine;
using UnityEditor;

namespace UnityBridge.Helpers
{
    internal static class BridgeLog
    {
        private const string Prefix = "[UnityBridge]";
        private const string EditorPrefsKey = "UnityBridge.DebugLogs";

        private const string InfoColor = "#2EA3FF";
        private const string DebugColor = "#6AA84F";
        private const string WarnColor = "#cc7a00";
        private const string ErrorColor = "#cc3333";

        private static volatile bool _debugEnabled;

        static BridgeLog()
        {
            _debugEnabled = EditorPrefs.GetBool(EditorPrefsKey, false);
        }

        public static void SetDebugLoggingEnabled(bool enabled)
        {
            _debugEnabled = enabled;
            EditorPrefs.SetBool(EditorPrefsKey, enabled);
        }

        public static bool IsDebugLoggingEnabled() => _debugEnabled;

        public static void Info(string message)
        {
            UnityEngine.Debug.Log(Format(message, InfoColor));
        }

        public static void Debug(string message)
        {
            if (!_debugEnabled) return;
            UnityEngine.Debug.Log(Format(message, DebugColor));
        }

        public static void Warn(string message)
        {
            UnityEngine.Debug.LogWarning(Format(message, WarnColor));
        }

        public static void Error(string message)
        {
            UnityEngine.Debug.LogError(Format(message, ErrorColor));
        }

        private static string Format(string message, string color)
        {
            return $"<color={color}>{Prefix}</color> {message}";
        }
    }
}
