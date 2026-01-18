using System;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;

namespace UnityBridge.Tools
{
    /// <summary>
    /// Handler for asset commands.
    /// Creates and manages Unity assets (Prefabs, ScriptableObjects, etc.)
    /// </summary>
    [BridgeTool("asset")]
    public static class Asset
    {
        public static JObject HandleCommand(JObject parameters)
        {
            var action = parameters["action"]?.Value<string>() ?? "";

            return action.ToLowerInvariant() switch
            {
                "create_prefab" => CreatePrefab(parameters),
                "create_scriptable_object" => CreateScriptableObject(parameters),
                "info" => GetAssetInfo(parameters),
                _ => throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Unknown action: {action}. Valid: create_prefab, create_scriptable_object, info")
            };
        }

        private static JObject CreatePrefab(JObject parameters)
        {
            var sourceName = parameters["source"]?.Value<string>();
            var sourceId = parameters["sourceId"]?.Value<int>();
            var path = parameters["path"]?.Value<string>();

            if (string.IsNullOrEmpty(sourceName) && sourceId == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "Either 'source' (name) or 'sourceId' (instanceID) is required");
            }

            if (string.IsNullOrEmpty(path))
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "'path' is required (e.g., 'Assets/Prefabs/MyPrefab.prefab')");
            }

            if (!path.EndsWith(".prefab"))
            {
                path += ".prefab";
            }

            GameObject source = FindGameObject(sourceName, sourceId);
            if (source == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Source GameObject not found: {sourceName ?? sourceId?.ToString()}");
            }

            // Ensure directory exists
            var directory = System.IO.Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(directory) && !AssetDatabase.IsValidFolder(directory))
            {
                CreateFolderRecursively(directory);
            }

            var prefab = PrefabUtility.SaveAsPrefabAsset(source, path);
            if (prefab == null)
            {
                throw new ProtocolException(
                    ErrorCode.InternalError,
                    $"Failed to create prefab at: {path}");
            }

            return new JObject
            {
                ["message"] = $"Prefab created: {path}",
                ["path"] = path,
                ["assetGuid"] = AssetDatabase.AssetPathToGUID(path)
            };
        }

        private static JObject CreateScriptableObject(JObject parameters)
        {
            var typeName = parameters["type"]?.Value<string>();
            var path = parameters["path"]?.Value<string>();

            if (string.IsNullOrEmpty(typeName))
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "'type' is required (ScriptableObject type name)");
            }

            if (string.IsNullOrEmpty(path))
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "'path' is required (e.g., 'Assets/Data/MyData.asset')");
            }

            if (!path.EndsWith(".asset"))
            {
                path += ".asset";
            }

            var type = FindType(typeName);
            if (type == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Type not found: {typeName}");
            }

            if (!typeof(ScriptableObject).IsAssignableFrom(type))
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Type '{typeName}' is not a ScriptableObject");
            }

            // Ensure directory exists
            var directory = System.IO.Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(directory) && !AssetDatabase.IsValidFolder(directory))
            {
                CreateFolderRecursively(directory);
            }

            var asset = ScriptableObject.CreateInstance(type);
            AssetDatabase.CreateAsset(asset, path);
            AssetDatabase.SaveAssets();

            return new JObject
            {
                ["message"] = $"ScriptableObject created: {path}",
                ["path"] = path,
                ["type"] = type.FullName,
                ["assetGuid"] = AssetDatabase.AssetPathToGUID(path)
            };
        }

        private static JObject GetAssetInfo(JObject parameters)
        {
            var path = parameters["path"]?.Value<string>();

            if (string.IsNullOrEmpty(path))
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "'path' is required");
            }

            var asset = AssetDatabase.LoadMainAssetAtPath(path);
            if (asset == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Asset not found: {path}");
            }

            return new JObject
            {
                ["path"] = path,
                ["name"] = asset.name,
                ["type"] = asset.GetType().FullName,
                ["instanceID"] = asset.GetInstanceID(),
                ["guid"] = AssetDatabase.AssetPathToGUID(path)
            };
        }

        private static GameObject FindGameObject(string name, int? instanceId)
        {
            if (instanceId.HasValue)
            {
                var obj = EditorUtility.InstanceIDToObject(instanceId.Value);
                if (obj is GameObject go)
                    return go;
                return null;
            }

            if (!string.IsNullOrEmpty(name))
            {
                return GameObject.Find(name) ?? GameObject.Find("/" + name);
            }

            return null;
        }

        private static Type FindType(string typeName)
        {
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                try
                {
                    var type = assembly.GetType(typeName);
                    if (type != null) return type;

                    type = assembly.GetTypes().FirstOrDefault(t =>
                        t.Name == typeName || t.FullName == typeName);
                    if (type != null) return type;
                }
                catch
                {
                    // Skip assemblies that fail
                }
            }
            return null;
        }

        private static void CreateFolderRecursively(string path)
        {
            var parts = path.Split('/');
            var current = parts[0]; // "Assets"

            for (int i = 1; i < parts.Length; i++)
            {
                var next = current + "/" + parts[i];
                if (!AssetDatabase.IsValidFolder(next))
                {
                    AssetDatabase.CreateFolder(current, parts[i]);
                }
                current = next;
            }
        }
    }
}
