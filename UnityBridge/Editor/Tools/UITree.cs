using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.UIElements;
using UnityBridge.Helpers;

namespace UnityBridge.Tools
{
    /// <summary>
    /// Handler for UIToolkit VisualElement tree inspection commands.
    /// Provides dump, query, and inspect operations for UI panels.
    /// </summary>
    [BridgeTool("uitree")]
    public static class UITree
    {
        private static Dictionary<string, WeakReference<VisualElement>> s_RefMap = new();
        private static int s_NextRefId = 1;

        public static JObject HandleCommand(JObject parameters)
        {
            var action = parameters["action"]?.Value<string>() ?? "";

            return action.ToLowerInvariant() switch
            {
                "dump" => HandleDump(parameters),
                "query" => HandleQuery(parameters),
                "inspect" => HandleInspect(parameters),
                _ => throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Unknown action: {action}. Valid actions: dump, query, inspect")
            };
        }

        #region Actions

        private static JObject HandleDump(JObject parameters)
        {
            var panelName = parameters["panel"]?.Value<string>();
            var depth = parameters["depth"]?.Value<int>() ?? -1;
            var format = parameters["format"]?.Value<string>() ?? "text";

            if (string.IsNullOrEmpty(panelName))
            {
                return ListPanels();
            }

            var (root, resolvedPanelName) = FindPanelRoot(panelName);
            if (root == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Panel not found: {panelName}");
            }

            ClearRefs();

            var elementCount = 0;

            if (format.Equals("json", StringComparison.OrdinalIgnoreCase))
            {
                var tree = BuildJsonTree(root, depth, 0, ref elementCount);
                return new JObject
                {
                    ["tree"] = tree,
                    ["elementCount"] = elementCount,
                    ["panel"] = resolvedPanelName
                };
            }
            else
            {
                var sb = new StringBuilder();
                BuildTextTree(root, depth, 0, sb, ref elementCount);
                return new JObject
                {
                    ["tree"] = sb.ToString().TrimEnd(),
                    ["elementCount"] = elementCount,
                    ["panel"] = resolvedPanelName
                };
            }
        }

        private static JObject HandleQuery(JObject parameters)
        {
            var panelName = parameters["panel"]?.Value<string>();
            if (string.IsNullOrEmpty(panelName))
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "'panel' parameter is required for query action");
            }

            var typeFilter = parameters["type"]?.Value<string>();
            var nameFilter = parameters["name"]?.Value<string>();
            var classFilter = parameters["class_name"]?.Value<string>();

            // Strip leading # from name and . from class_name
            if (nameFilter != null && nameFilter.StartsWith("#"))
                nameFilter = nameFilter.Substring(1);
            if (classFilter != null && classFilter.StartsWith("."))
                classFilter = classFilter.Substring(1);

            var (root, resolvedPanelName) = FindPanelRoot(panelName);
            if (root == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Panel not found: {panelName}");
            }

            ClearRefs();

            var matches = new JArray();
            CollectMatches(root, typeFilter, nameFilter, classFilter, matches, "");

            return new JObject
            {
                ["matches"] = matches,
                ["count"] = matches.Count,
                ["panel"] = resolvedPanelName
            };
        }

        private static JObject HandleInspect(JObject parameters)
        {
            var refId = parameters["ref"]?.Value<string>();
            var panelName = parameters["panel"]?.Value<string>();
            var nameFilter = parameters["name"]?.Value<string>();
            var includeStyle = parameters["include_style"]?.Value<bool>() ?? false;
            var includeChildren = parameters["include_children"]?.Value<bool>() ?? false;

            VisualElement target = null;

            if (!string.IsNullOrEmpty(refId))
            {
                target = ResolveRef(refId);
                if (target == null)
                {
                    throw new ProtocolException(
                        ErrorCode.InvalidParams,
                        $"ref not found or element has been garbage collected: {refId}");
                }
            }
            else if (!string.IsNullOrEmpty(panelName) && !string.IsNullOrEmpty(nameFilter))
            {
                if (nameFilter.StartsWith("#"))
                    nameFilter = nameFilter.Substring(1);

                var (root, _) = FindPanelRoot(panelName);
                if (root == null)
                {
                    throw new ProtocolException(
                        ErrorCode.InvalidParams,
                        $"Panel not found: {panelName}");
                }

                target = FindElementByName(root, nameFilter);
                if (target == null)
                {
                    throw new ProtocolException(
                        ErrorCode.InvalidParams,
                        $"Element with name '{nameFilter}' not found in panel '{panelName}'");
                }
            }
            else
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "Either 'ref' or 'panel' + 'name' parameters are required");
            }

            var elementRefId = FindOrAssignRef(target);
            var result = BuildInspectResult(target, elementRefId, includeStyle, includeChildren);
            return result;
        }

        #endregion

        #region Panel Discovery

        private static JObject ListPanels()
        {
            var panels = new JArray();

            // Editor panels via reflection
            foreach (var info in GetEditorPanels())
            {
                panels.Add(new JObject
                {
                    ["name"] = info.Name,
                    ["contextType"] = info.ContextType,
                    ["elementCount"] = info.ElementCount
                });
            }

            // Runtime panels via UIDocument
            foreach (var info in GetRuntimePanels())
            {
                panels.Add(new JObject
                {
                    ["name"] = info.Name,
                    ["contextType"] = info.ContextType,
                    ["elementCount"] = info.ElementCount
                });
            }

            return new JObject
            {
                ["panels"] = panels
            };
        }

        private static (VisualElement root, string panelName) FindPanelRoot(string panelName)
        {
            // Search editor panels
            foreach (var info in GetEditorPanels())
            {
                if (info.Name.Equals(panelName, StringComparison.OrdinalIgnoreCase))
                    return (info.Root, info.Name);
            }

            // Search runtime panels
            foreach (var info in GetRuntimePanels())
            {
                if (info.Name.Equals(panelName, StringComparison.OrdinalIgnoreCase))
                    return (info.Root, info.Name);
            }

            // Partial match fallback
            foreach (var info in GetEditorPanels())
            {
                if (info.Name.IndexOf(panelName, StringComparison.OrdinalIgnoreCase) >= 0)
                    return (info.Root, info.Name);
            }

            foreach (var info in GetRuntimePanels())
            {
                if (info.Name.IndexOf(panelName, StringComparison.OrdinalIgnoreCase) >= 0)
                    return (info.Root, info.Name);
            }

            return (null, null);
        }

        private struct PanelInfo
        {
            public string Name;
            public string ContextType;
            public int ElementCount;
            public VisualElement Root;
        }

        private static List<PanelInfo> GetEditorPanels()
        {
            var results = new List<PanelInfo>();

            // UIElementsUtility.GetPanelsIterator() is internal, use reflection
            var utilityType = Type.GetType(
                "UnityEngine.UIElements.UIElementsUtility, UnityEngine.UIElementsModule");
            if (utilityType == null)
            {
                BridgeLog.Verbose("UIElementsUtility type not found");
                return results;
            }

            var getIteratorMethod = utilityType.GetMethod(
                "GetPanelsIterator",
                BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
            if (getIteratorMethod == null)
            {
                BridgeLog.Verbose("GetPanelsIterator method not found");
                return results;
            }

            object iterator;
            try
            {
                iterator = getIteratorMethod.Invoke(null, null);
            }
            catch (Exception ex)
            {
                BridgeLog.Error($"Failed to get panels iterator: {ex.Message}");
                return results;
            }

            // The iterator is Dictionary<int, Panel>.Enumerator (a struct).
            // Wrap it in IEnumerator to avoid struct boxing issues with repeated MoveNext.
            var iteratorType = iterator.GetType();
            var moveNextMethod = iteratorType.GetMethod("MoveNext");
            var currentProp = iteratorType.GetProperty("Current");
            var disposeMethod = iteratorType.GetMethod("Dispose");

            if (moveNextMethod == null || currentProp == null)
                return results;

            try
            {
                // Use TypedReference / pointer trick not available, so collect all at once
                // by repeatedly calling MoveNext on the boxed struct via interface
                if (iterator is System.Collections.IEnumerator enumerator)
                {
                    while (enumerator.MoveNext())
                    {
                        ProcessPanelEntry(enumerator.Current, results);
                    }
                }
                else
                {
                    // Fallback: use a wrapper that handles the struct enumerator properly
                    // Box once and invoke via reflection on the same boxed reference
                    while ((bool)moveNextMethod.Invoke(iterator, null))
                    {
                        var kvp = currentProp.GetValue(iterator);
                        ProcessPanelEntry(kvp, results);
                    }
                }
            }
            finally
            {
                disposeMethod?.Invoke(iterator, null);
            }

            return results;
        }

        private static void ProcessPanelEntry(object kvp, List<PanelInfo> results)
        {
            if (kvp == null) return;

            var kvpType = kvp.GetType();
            var valueProp = kvpType.GetProperty("Value");
            var panel = valueProp?.GetValue(kvp);

            if (panel == null) return;

            var panelType = panel.GetType();

            // Get contextType
            var contextTypeProp = panelType.GetProperty("contextType",
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            var contextType = contextTypeProp?.GetValue(panel)?.ToString() ?? "Unknown";

            // Get visualTree
            var visualTreeProp = panelType.GetProperty("visualTree",
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            var visualTree = visualTreeProp?.GetValue(panel) as VisualElement;

            if (visualTree == null) return;

            // Derive panel name from ownerObject or type
            var ownerObjectProp = panelType.GetProperty("ownerObject",
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            var ownerObject = ownerObjectProp?.GetValue(panel) as ScriptableObject;

            var panelName = ownerObject != null
                ? ownerObject.GetType().Name
                : $"Panel_{contextType}";

            var elementCount = CountElements(visualTree);

            results.Add(new PanelInfo
            {
                Name = panelName,
                ContextType = contextType,
                ElementCount = elementCount,
                Root = visualTree
            });
        }

        private static List<PanelInfo> GetRuntimePanels()
        {
            var results = new List<PanelInfo>();

            var uiDocuments = UnityEngine.Object.FindObjectsOfType<UIDocument>();

            foreach (var doc in uiDocuments)
            {
                if (doc == null || doc.rootVisualElement == null)
                    continue;

                var panelSettingsName = doc.panelSettings != null
                    ? doc.panelSettings.name
                    : "Unknown";
                var panelName = $"UIDocument {panelSettingsName} ({doc.gameObject.name})";
                var elementCount = CountElements(doc.rootVisualElement);

                results.Add(new PanelInfo
                {
                    Name = panelName,
                    ContextType = "Player",
                    ElementCount = elementCount,
                    Root = doc.rootVisualElement
                });
            }

            return results;
        }

        #endregion

        #region Tree Building

        private static void BuildTextTree(
            VisualElement element, int maxDepth, int currentDepth,
            StringBuilder sb, ref int elementCount)
        {
            if (maxDepth >= 0 && currentDepth > maxDepth)
                return;

            var indent = new string(' ', currentDepth * 2);
            var refId = AssignRef(element);
            elementCount++;

            sb.Append(indent);
            sb.Append(element.GetType().Name);

            if (!string.IsNullOrEmpty(element.name))
            {
                sb.Append($" \"{element.name}\"");
            }

            foreach (var cls in element.GetClasses())
            {
                sb.Append($" .{cls}");
            }

            sb.AppendLine($" {refId}");

            foreach (var child in element.Children())
            {
                BuildTextTree(child, maxDepth, currentDepth + 1, sb, ref elementCount);
            }
        }

        private static JObject BuildJsonTree(
            VisualElement element, int maxDepth, int currentDepth,
            ref int elementCount)
        {
            var refId = AssignRef(element);
            elementCount++;

            var node = new JObject
            {
                ["ref"] = refId,
                ["type"] = element.GetType().Name,
                ["name"] = string.IsNullOrEmpty(element.name) ? null : element.name,
                ["classes"] = new JArray(element.GetClasses().ToArray()),
                ["childCount"] = element.childCount
            };

            if (maxDepth >= 0 && currentDepth >= maxDepth)
            {
                // Don't recurse further, but still report childCount
                return node;
            }

            if (element.childCount > 0)
            {
                var children = new JArray();
                foreach (var child in element.Children())
                {
                    children.Add(BuildJsonTree(child, maxDepth, currentDepth + 1, ref elementCount));
                }
                node["children"] = children;
            }

            return node;
        }

        #endregion

        #region Query

        private static void CollectMatches(
            VisualElement element, string typeFilter, string nameFilter,
            string classFilter, JArray matches, string parentPath)
        {
            var typeName = element.GetType().Name;
            var currentPath = string.IsNullOrEmpty(parentPath)
                ? typeName
                : $"{parentPath} > {typeName}";

            var matchesType = string.IsNullOrEmpty(typeFilter) ||
                              typeName.IndexOf(typeFilter, StringComparison.OrdinalIgnoreCase) >= 0;
            var matchesName = string.IsNullOrEmpty(nameFilter) ||
                              (!string.IsNullOrEmpty(element.name) &&
                               element.name.Equals(nameFilter, StringComparison.OrdinalIgnoreCase));
            var matchesClass = string.IsNullOrEmpty(classFilter) ||
                               element.GetClasses().Any(c =>
                                   c.Equals(classFilter, StringComparison.OrdinalIgnoreCase));

            if (matchesType && matchesName && matchesClass)
            {
                // At least one filter must be specified
                if (!string.IsNullOrEmpty(typeFilter) ||
                    !string.IsNullOrEmpty(nameFilter) ||
                    !string.IsNullOrEmpty(classFilter))
                {
                    var refId = AssignRef(element);
                    var layout = element.layout;
                    matches.Add(new JObject
                    {
                        ["ref"] = refId,
                        ["type"] = typeName,
                        ["name"] = string.IsNullOrEmpty(element.name) ? null : element.name,
                        ["classes"] = new JArray(element.GetClasses().ToArray()),
                        ["path"] = currentPath,
                        ["layout"] = new JObject
                        {
                            ["x"] = layout.x,
                            ["y"] = layout.y,
                            ["width"] = layout.width,
                            ["height"] = layout.height
                        }
                    });
                }
            }

            foreach (var child in element.Children())
            {
                CollectMatches(child, typeFilter, nameFilter, classFilter, matches, currentPath);
            }
        }

        #endregion

        #region Inspect

        private static JObject BuildInspectResult(
            VisualElement element, string refId,
            bool includeStyle, bool includeChildren)
        {
            var layout = element.layout;
            var worldBound = element.worldBound;

            var result = new JObject
            {
                ["ref"] = refId,
                ["type"] = element.GetType().Name,
                ["name"] = string.IsNullOrEmpty(element.name) ? null : element.name,
                ["classes"] = new JArray(element.GetClasses().ToArray()),
                ["visible"] = element.visible,
                ["enabledSelf"] = element.enabledSelf,
                ["enabledInHierarchy"] = element.enabledInHierarchy,
                ["focusable"] = element.focusable,
                ["tooltip"] = element.tooltip ?? "",
                ["path"] = BuildElementPath(element),
                ["layout"] = new JObject
                {
                    ["x"] = layout.x,
                    ["y"] = layout.y,
                    ["width"] = layout.width,
                    ["height"] = layout.height
                },
                ["worldBound"] = new JObject
                {
                    ["x"] = worldBound.x,
                    ["y"] = worldBound.y,
                    ["width"] = worldBound.width,
                    ["height"] = worldBound.height
                },
                ["childCount"] = element.childCount
            };

            if (includeChildren)
            {
                var children = new JArray();
                foreach (var child in element.Children())
                {
                    var childRefId = FindOrAssignRef(child);
                    children.Add(new JObject
                    {
                        ["ref"] = childRefId,
                        ["type"] = child.GetType().Name,
                        ["name"] = string.IsNullOrEmpty(child.name) ? null : child.name,
                        ["classes"] = new JArray(child.GetClasses().ToArray())
                    });
                }
                result["children"] = children;
            }

            if (includeStyle)
            {
                result["resolvedStyle"] = BuildResolvedStyle(element);
            }

            return result;
        }

        private static JObject BuildResolvedStyle(VisualElement element)
        {
            var style = element.resolvedStyle;
            return new JObject
            {
                ["width"] = style.width,
                ["height"] = style.height,
                ["backgroundColor"] = style.backgroundColor.ToString(),
                ["color"] = style.color.ToString(),
                ["fontSize"] = style.fontSize,
                ["display"] = style.display.ToString(),
                ["position"] = style.position.ToString(),
                ["flexDirection"] = style.flexDirection.ToString(),
                ["opacity"] = style.opacity,
                ["visibility"] = style.visibility.ToString(),
                ["overflow"] = style.overflow.ToString(),
                ["marginTop"] = style.marginTop,
                ["marginBottom"] = style.marginBottom,
                ["marginLeft"] = style.marginLeft,
                ["marginRight"] = style.marginRight,
                ["paddingTop"] = style.paddingTop,
                ["paddingBottom"] = style.paddingBottom,
                ["paddingLeft"] = style.paddingLeft,
                ["paddingRight"] = style.paddingRight,
                ["borderTopWidth"] = style.borderTopWidth,
                ["borderBottomWidth"] = style.borderBottomWidth,
                ["borderLeftWidth"] = style.borderLeftWidth,
                ["borderRightWidth"] = style.borderRightWidth
            };
        }

        private static string BuildElementPath(VisualElement element)
        {
            var parts = new List<string>();
            var current = element;

            while (current != null)
            {
                parts.Add(current.GetType().Name);
                current = current.parent;
            }

            parts.Reverse();
            return string.Join(" > ", parts);
        }

        #endregion

        #region Ref ID Management

        private static string AssignRef(VisualElement ve)
        {
            var refId = $"ref_{s_NextRefId++}";
            s_RefMap[refId] = new WeakReference<VisualElement>(ve);
            return refId;
        }

        private static string FindOrAssignRef(VisualElement ve)
        {
            // Check if this element already has a ref
            foreach (var kvp in s_RefMap)
            {
                if (kvp.Value.TryGetTarget(out var existing) && existing == ve)
                    return kvp.Key;
            }

            return AssignRef(ve);
        }

        private static VisualElement ResolveRef(string refId)
        {
            if (s_RefMap.TryGetValue(refId, out var weakRef) && weakRef.TryGetTarget(out var element))
                return element;

            return null;
        }

        private static void ClearRefs()
        {
            s_RefMap.Clear();
            s_NextRefId = 1;
        }

        #endregion

        #region Helpers

        private static VisualElement FindElementByName(VisualElement root, string name)
        {
            if (!string.IsNullOrEmpty(root.name) &&
                root.name.Equals(name, StringComparison.OrdinalIgnoreCase))
                return root;

            foreach (var child in root.Children())
            {
                var found = FindElementByName(child, name);
                if (found != null)
                    return found;
            }

            return null;
        }

        private static int CountElements(VisualElement root)
        {
            var count = 1;
            foreach (var child in root.Children())
            {
                count += CountElements(child);
            }
            return count;
        }

        #endregion
    }
}
