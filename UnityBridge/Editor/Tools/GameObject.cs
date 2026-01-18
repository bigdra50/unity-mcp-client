using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace UnityBridge.Tools
{
    /// <summary>
    /// Handler for GameObject commands.
    /// Provides find, create, modify, and delete operations.
    /// </summary>
    [BridgeTool("gameobject")]
    public static class GameObjectHandler
    {
        public static JObject HandleCommand(JObject parameters)
        {
            var action = parameters["action"]?.Value<string>() ?? "";

            return action.ToLowerInvariant() switch
            {
                "find" => Find(parameters),
                "create" => Create(parameters),
                "modify" => Modify(parameters),
                "delete" => Delete(parameters),
                _ => throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Unknown action: {action}. Valid actions: find, create, modify, delete")
            };
        }

        #region Actions

        private static JObject Find(JObject parameters)
        {
            var name = parameters["name"]?.Value<string>();
            var id = parameters["id"]?.Value<int>();

            if (string.IsNullOrEmpty(name) && !id.HasValue)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "Either 'name' or 'id' parameter is required for find action");
            }

            var results = new JArray();

            if (id.HasValue)
            {
                // Search by instanceID
                var obj = FindByInstanceId(id.Value);
                if (obj != null)
                {
                    results.Add(CreateGameObjectData(obj));
                }
            }
            else
            {
                // Search by name
                var allObjects = GetAllSceneObjects(includeInactive: true);
                foreach (var obj in allObjects.Where(go => go.name == name))
                {
                    results.Add(CreateGameObjectData(obj));
                }
            }

            return new JObject
            {
                ["found"] = results.Count,
                ["objects"] = results,
                ["message"] = results.Count > 0
                    ? $"Found {results.Count} GameObject(s)"
                    : "No matching GameObjects found"
            };
        }

        private static JObject Create(JObject parameters)
        {
            var name = parameters["name"]?.Value<string>();
            if (string.IsNullOrEmpty(name))
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "'name' parameter is required for create action");
            }

            var primitiveStr = parameters["primitive"]?.Value<string>();
            UnityEngine.GameObject newGo;

            if (!string.IsNullOrEmpty(primitiveStr))
            {
                if (!Enum.TryParse<PrimitiveType>(primitiveStr, true, out var primitiveType))
                {
                    var validTypes = string.Join(", ", Enum.GetNames(typeof(PrimitiveType)));
                    throw new ProtocolException(
                        ErrorCode.InvalidParams,
                        $"Invalid primitive type: '{primitiveStr}'. Valid types: {validTypes}");
                }

                newGo = UnityEngine.GameObject.CreatePrimitive(primitiveType);
                newGo.name = name;
            }
            else
            {
                newGo = new UnityEngine.GameObject(name);
            }

            Undo.RegisterCreatedObjectUndo(newGo, $"Create GameObject '{name}'");

            // Apply transform
            ApplyTransform(newGo.transform, parameters);

            EditorUtility.SetDirty(newGo);
            EditorSceneManager.MarkSceneDirty(EditorSceneManager.GetActiveScene());
            Selection.activeGameObject = newGo;

            return new JObject
            {
                ["message"] = $"GameObject '{name}' created successfully",
                ["gameObject"] = CreateGameObjectData(newGo)
            };
        }

        private static JObject Modify(JObject parameters)
        {
            var targetGo = ResolveTarget(parameters);
            if (targetGo == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "Target GameObject not found. Specify 'name' or 'id' parameter");
            }

            Undo.RecordObject(targetGo.transform, "Modify GameObject Transform");

            var modified = ApplyTransform(targetGo.transform, parameters);

            if (!modified)
            {
                return new JObject
                {
                    ["message"] = $"No changes applied to '{targetGo.name}'",
                    ["gameObject"] = CreateGameObjectData(targetGo)
                };
            }

            EditorUtility.SetDirty(targetGo);
            EditorSceneManager.MarkSceneDirty(EditorSceneManager.GetActiveScene());

            return new JObject
            {
                ["message"] = $"GameObject '{targetGo.name}' modified successfully",
                ["gameObject"] = CreateGameObjectData(targetGo)
            };
        }

        private static JObject Delete(JObject parameters)
        {
            var targetGo = ResolveTarget(parameters);
            if (targetGo == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "Target GameObject not found. Specify 'name' or 'id' parameter");
            }

            var goName = targetGo.name;
            var goId = targetGo.GetInstanceID();

            Undo.DestroyObjectImmediate(targetGo);
            EditorSceneManager.MarkSceneDirty(EditorSceneManager.GetActiveScene());

            return new JObject
            {
                ["message"] = $"GameObject '{goName}' deleted successfully",
                ["deleted"] = new JObject
                {
                    ["name"] = goName,
                    ["instanceID"] = goId
                }
            };
        }

        #endregion

        #region Helpers

        private static UnityEngine.GameObject ResolveTarget(JObject parameters)
        {
            var id = parameters["id"]?.Value<int>();
            var name = parameters["name"]?.Value<string>();

            if (id.HasValue)
            {
                return FindByInstanceId(id.Value);
            }

            if (!string.IsNullOrEmpty(name))
            {
                return FindByName(name);
            }

            return null;
        }

        private static UnityEngine.GameObject FindByInstanceId(int instanceId)
        {
            var allObjects = GetAllSceneObjects(includeInactive: true);
            return allObjects.FirstOrDefault(go => go.GetInstanceID() == instanceId);
        }

        private static UnityEngine.GameObject FindByName(string name)
        {
            var allObjects = GetAllSceneObjects(includeInactive: true);
            return allObjects.FirstOrDefault(go => go.name == name);
        }

        private static IEnumerable<UnityEngine.GameObject> GetAllSceneObjects(bool includeInactive)
        {
            var rootObjects = new List<UnityEngine.GameObject>();
            var sceneCount = SceneManager.sceneCount;

            for (var i = 0; i < sceneCount; i++)
            {
                var scene = SceneManager.GetSceneAt(i);
                if (scene.isLoaded)
                {
                    rootObjects.AddRange(scene.GetRootGameObjects());
                }
            }

            foreach (var root in rootObjects)
            {
                yield return root;

                foreach (var child in GetAllChildren(root.transform, includeInactive))
                {
                    yield return child.gameObject;
                }
            }
        }

        private static IEnumerable<Transform> GetAllChildren(Transform parent, bool includeInactive)
        {
            foreach (Transform child in parent)
            {
                if (includeInactive || child.gameObject.activeInHierarchy)
                {
                    yield return child;

                    foreach (var grandChild in GetAllChildren(child, includeInactive))
                    {
                        yield return grandChild;
                    }
                }
            }
        }

        private static bool ApplyTransform(Transform transform, JObject parameters)
        {
            var modified = false;

            var position = ParseVector3(parameters["position"] as JArray);
            if (position.HasValue)
            {
                transform.localPosition = position.Value;
                modified = true;
            }

            var rotation = ParseVector3(parameters["rotation"] as JArray);
            if (rotation.HasValue)
            {
                transform.localEulerAngles = rotation.Value;
                modified = true;
            }

            var scale = ParseVector3(parameters["scale"] as JArray);
            if (scale.HasValue)
            {
                transform.localScale = scale.Value;
                modified = true;
            }

            return modified;
        }

        private static Vector3? ParseVector3(JArray array)
        {
            if (array == null || array.Count < 3)
                return null;

            try
            {
                return new Vector3(
                    array[0].Value<float>(),
                    array[1].Value<float>(),
                    array[2].Value<float>()
                );
            }
            catch
            {
                return null;
            }
        }

        private static JObject CreateGameObjectData(UnityEngine.GameObject go)
        {
            var transform = go.transform;

            return new JObject
            {
                ["name"] = go.name,
                ["instanceID"] = go.GetInstanceID(),
                ["active"] = go.activeSelf,
                ["tag"] = go.tag,
                ["layer"] = go.layer,
                ["layerName"] = LayerMask.LayerToName(go.layer),
                ["position"] = new JArray(
                    transform.localPosition.x,
                    transform.localPosition.y,
                    transform.localPosition.z),
                ["rotation"] = new JArray(
                    transform.localEulerAngles.x,
                    transform.localEulerAngles.y,
                    transform.localEulerAngles.z),
                ["scale"] = new JArray(
                    transform.localScale.x,
                    transform.localScale.y,
                    transform.localScale.z),
                ["parent"] = transform.parent != null
                    ? new JObject
                    {
                        ["name"] = transform.parent.name,
                        ["instanceID"] = transform.parent.gameObject.GetInstanceID()
                    }
                    : null,
                ["childCount"] = transform.childCount
            };
        }

        #endregion
    }
}
