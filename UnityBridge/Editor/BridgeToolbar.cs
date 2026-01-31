using System;
using System.Reflection;
using UnityBridge.Helpers;
using UnityEditor;
using UnityEngine;
using UnityEngine.UIElements;
#if UNITY_6000_3_OR_NEWER
using UnityEditor.Toolbars;
#endif

namespace UnityBridge
{
    internal static class BridgeToolbarHelper
    {
        static readonly Color DisconnectedColor = new(0.5f, 0.5f, 0.5f);
        static readonly Color ConnectingColor = new(0.9f, 0.7f, 0.2f);
        static readonly Color ConnectedColor = new(0.3f, 0.8f, 0.3f);

        static VisualElement s_button;
        static ConnectionStatus s_lastStatus = ConnectionStatus.Disconnected;

        internal static VisualElement CreateButton()
        {
            var button = new VisualElement();
            button.style.flexDirection = FlexDirection.Row;
            button.style.alignItems = Align.Center;
            button.style.paddingLeft = 4;
            button.style.paddingRight = 4;
            button.style.marginLeft = 2;
            button.style.marginRight = 2;
            button.AddToClassList("unity-toolbar-button");

            var indicator = new VisualElement { name = "bridge-indicator" };
            indicator.style.width = 8;
            indicator.style.height = 8;
            indicator.style.borderTopLeftRadius = 4;
            indicator.style.borderTopRightRadius = 4;
            indicator.style.borderBottomLeftRadius = 4;
            indicator.style.borderBottomRightRadius = 4;
            indicator.style.marginRight = 4;
            indicator.style.backgroundColor = DisconnectedColor;

            var label = new Label("Bridge") { name = "bridge-label" };
            label.style.unityTextAlign = TextAnchor.MiddleCenter;
            label.style.fontSize = 11;

            button.Add(indicator);
            button.Add(label);

            button.RegisterCallback<MouseEnterEvent>(_ =>
                button.style.backgroundColor = new Color(1f, 1f, 1f, 0.08f));
            button.RegisterCallback<MouseLeaveEvent>(_ =>
                button.style.backgroundColor = StyleKeyword.Null);

            return button;
        }

        internal static void Register(VisualElement button)
        {
            s_button = button;
            s_lastStatus = GetCurrentStatus();
            ApplyButtonState(s_button, s_lastStatus);
            EditorApplication.update += PollStatus;
        }

        static void PollStatus()
        {
            if (s_button?.panel == null)
            {
                EditorApplication.update -= PollStatus;
                s_button = null;
                return;
            }

            var current = GetCurrentStatus();
            if (current == s_lastStatus) return;

            s_lastStatus = current;
            ApplyButtonState(s_button, current);
        }

        static ConnectionStatus GetCurrentStatus()
        {
            return BridgeManager.Instance.Client?.Status ?? ConnectionStatus.Disconnected;
        }

        static void ApplyButtonState(VisualElement button, ConnectionStatus status)
        {
            if (button?.panel == null) return;

            var indicator = button.Q("bridge-indicator");
            if (indicator == null) return;

            var (color, tooltip, enabled) = status switch
            {
                ConnectionStatus.Disconnected => (
                    DisconnectedColor,
                    "Unity Bridge: Disconnected\nClick to connect",
                    true),
                ConnectionStatus.Connecting => (
                    ConnectingColor,
                    "Unity Bridge: Connecting...",
                    false),
                ConnectionStatus.Connected => (
                    ConnectedColor,
                    $"Unity Bridge: Connected ({BridgeManager.Instance.Host}:{BridgeManager.Instance.Port})\nClick to disconnect",
                    true),
                ConnectionStatus.Reloading => (
                    ConnectingColor,
                    "Unity Bridge: Reloading...",
                    false),
                _ => (DisconnectedColor, "Unity Bridge", true)
            };

            indicator.style.backgroundColor = color;
            button.tooltip = tooltip;
            button.SetEnabled(enabled);
        }

        internal static async void ToggleConnection()
        {
            var manager = BridgeManager.Instance;
            try
            {
                if (manager.IsConnected)
                {
                    await manager.DisconnectAsync();
                }
                else
                {
                    await manager.ConnectAsync(manager.Host, manager.Port);
                }
            }
            catch (ObjectDisposedException)
            {
                // Already disconnected
            }
            catch (Exception ex)
            {
                BridgeLog.Warn($"Toolbar toggle connection error: {ex.Message}");
            }
        }
    }

#if UNITY_6000_3_OR_NEWER
    [EditorToolbarElement("UnityBridge/Connection", typeof(EditorWindow))]
    sealed class BridgeToolbarElement : VisualElement
    {
        public BridgeToolbarElement()
        {
            var button = BridgeToolbarHelper.CreateButton();
            button.RegisterCallback<ClickEvent>(_ => BridgeToolbarHelper.ToggleConnection());
            Add(button);
            BridgeToolbarHelper.Register(button);
        }
    }
#else
    [InitializeOnLoad]
    static class BridgeToolbarInjector
    {
        static readonly Type s_toolbarType;
        static readonly FieldInfo s_getField;
        static readonly PropertyInfo s_visualTreeProp;

        static BridgeToolbarInjector()
        {
            var editorAssembly = typeof(Editor).Assembly;
            s_toolbarType = editorAssembly.GetType("UnityEditor.Toolbar");
            var guiViewType = editorAssembly.GetType("UnityEditor.GUIView");

            s_getField = s_toolbarType?.GetField("get",
                BindingFlags.Public | BindingFlags.Static);
            s_visualTreeProp = guiViewType?.GetProperty("visualTree",
                BindingFlags.NonPublic | BindingFlags.Instance);

            if (s_toolbarType == null || s_getField == null || s_visualTreeProp == null)
            {
                BridgeLog.Warn("Toolbar injection: required types/members not found");
                return;
            }

            EditorApplication.update += WaitForToolbar;
        }

        static void WaitForToolbar()
        {
            var toolbar = s_getField.GetValue(null);
            if (toolbar == null) return;

            EditorApplication.update -= WaitForToolbar;

            if (s_visualTreeProp.GetValue(toolbar) is not VisualElement root) return;

            var rightZone = root.Q("ToolbarZoneRightAlign");
            if (rightZone == null)
            {
                BridgeLog.Warn("Toolbar injection: ToolbarZoneRightAlign not found");
                return;
            }

            var button = BridgeToolbarHelper.CreateButton();
            button.RegisterCallback<ClickEvent>(_ => BridgeToolbarHelper.ToggleConnection());
            rightZone.Insert(0, button);
            BridgeToolbarHelper.Register(button);
        }
    }
#endif
}
