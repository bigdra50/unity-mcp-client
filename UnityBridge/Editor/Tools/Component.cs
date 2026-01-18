using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace UnityBridge.Tools
{
    /// <summary>
    /// Handler for component commands.
    /// Lists and inspects components on GameObjects.
    /// </summary>
    [BridgeTool("component")]
    public static class Component
    {
        // Types that require special handling to avoid circular references
        private static readonly HashSet<Type> SpecialTypes = new()
        {
            typeof(Transform),
            typeof(Camera),
            typeof(GameObject),
            typeof(UnityEngine.Component)
        };

        public static JObject HandleCommand(JObject parameters)
        {
            var action = parameters["action"]?.Value<string>() ?? "";

            return action.ToLowerInvariant() switch
            {
                "list" => ListComponents(parameters),
                "inspect" => InspectComponent(parameters),
                "add" => AddComponent(parameters),
                "remove" => RemoveComponent(parameters),
                _ => throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Unknown action: {action}. Valid: list, inspect, add, remove")
            };
        }

        /// <summary>
        /// Lists all components on the specified GameObject.
        /// </summary>
        private static JObject ListComponents(JObject parameters)
        {
            var target = parameters["target"]?.Value<string>();
            var targetId = parameters["targetId"]?.Value<int>();

            if (string.IsNullOrEmpty(target) && targetId == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "Either 'target' (name) or 'targetId' (instanceID) is required");
            }

            var gameObject = FindGameObject(target, targetId);
            if (gameObject == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"GameObject not found: {target ?? targetId?.ToString()}");
            }

            var components = gameObject.GetComponents<UnityEngine.Component>();
            var componentList = new JArray();

            foreach (var component in components)
            {
                if (component == null) continue;

                componentList.Add(new JObject
                {
                    ["typeName"] = component.GetType().FullName,
                    ["instanceID"] = component.GetInstanceID()
                });
            }

            return new JObject
            {
                ["gameObject"] = gameObject.name,
                ["gameObjectId"] = gameObject.GetInstanceID(),
                ["components"] = componentList
            };
        }

        /// <summary>
        /// Inspects a specific component on the specified GameObject.
        /// </summary>
        private static JObject InspectComponent(JObject parameters)
        {
            var target = parameters["target"]?.Value<string>();
            var targetId = parameters["targetId"]?.Value<int>();
            var typeName = parameters["type"]?.Value<string>();

            if (string.IsNullOrEmpty(target) && targetId == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "Either 'target' (name) or 'targetId' (instanceID) is required");
            }

            if (string.IsNullOrEmpty(typeName))
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "'type' parameter is required");
            }

            var gameObject = FindGameObject(target, targetId);
            if (gameObject == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"GameObject not found: {target ?? targetId?.ToString()}");
            }

            var componentType = FindType(typeName);
            if (componentType == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Component type not found: {typeName}");
            }

            var component = gameObject.GetComponent(componentType);
            if (component == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Component '{typeName}' not found on GameObject '{gameObject.name}'");
            }

            var properties = SerializeComponentProperties(component);

            return new JObject
            {
                ["typeName"] = component.GetType().FullName,
                ["instanceID"] = component.GetInstanceID(),
                ["properties"] = properties
            };
        }

        /// <summary>
        /// Adds a component to the specified GameObject.
        /// </summary>
        private static JObject AddComponent(JObject parameters)
        {
            var target = parameters["target"]?.Value<string>();
            var targetId = parameters["targetId"]?.Value<int>();
            var typeName = parameters["type"]?.Value<string>();

            if (string.IsNullOrEmpty(target) && targetId == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "Either 'target' (name) or 'targetId' (instanceID) is required");
            }

            if (string.IsNullOrEmpty(typeName))
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "'type' parameter is required");
            }

            var gameObject = FindGameObject(target, targetId);
            if (gameObject == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"GameObject not found: {target ?? targetId?.ToString()}");
            }

            var componentType = FindType(typeName);
            if (componentType == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Component type not found: {typeName}");
            }

            if (!typeof(UnityEngine.Component).IsAssignableFrom(componentType))
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Type '{typeName}' is not a Component");
            }

            var component = Undo.AddComponent(gameObject, componentType);
            if (component == null)
            {
                throw new ProtocolException(
                    ErrorCode.InternalError,
                    $"Failed to add component '{typeName}' to '{gameObject.name}'");
            }

            EditorUtility.SetDirty(gameObject);

            return new JObject
            {
                ["message"] = $"Added {componentType.Name} to {gameObject.name}",
                ["gameObject"] = gameObject.name,
                ["gameObjectId"] = gameObject.GetInstanceID(),
                ["component"] = new JObject
                {
                    ["typeName"] = componentType.FullName,
                    ["instanceID"] = component.GetInstanceID()
                }
            };
        }

        /// <summary>
        /// Removes a component from the specified GameObject.
        /// </summary>
        private static JObject RemoveComponent(JObject parameters)
        {
            var target = parameters["target"]?.Value<string>();
            var targetId = parameters["targetId"]?.Value<int>();
            var typeName = parameters["type"]?.Value<string>();

            if (string.IsNullOrEmpty(target) && targetId == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "Either 'target' (name) or 'targetId' (instanceID) is required");
            }

            if (string.IsNullOrEmpty(typeName))
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "'type' parameter is required");
            }

            var gameObject = FindGameObject(target, targetId);
            if (gameObject == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"GameObject not found: {target ?? targetId?.ToString()}");
            }

            var componentType = FindType(typeName);
            if (componentType == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Component type not found: {typeName}");
            }

            var component = gameObject.GetComponent(componentType);
            if (component == null)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Component '{typeName}' not found on '{gameObject.name}'");
            }

            // Prevent removing Transform
            if (componentType == typeof(Transform))
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "Cannot remove Transform component");
            }

            Undo.DestroyObjectImmediate(component);
            EditorUtility.SetDirty(gameObject);

            return new JObject
            {
                ["message"] = $"Removed {componentType.Name} from {gameObject.name}",
                ["gameObject"] = gameObject.name,
                ["gameObjectId"] = gameObject.GetInstanceID()
            };
        }

        /// <summary>
        /// Finds a GameObject by name or instanceID.
        /// </summary>
        private static GameObject FindGameObject(string name, int? instanceId)
        {
            if (instanceId.HasValue)
            {
                var obj = EditorUtility.InstanceIDToObject(instanceId.Value);
                if (obj is GameObject go)
                    return go;
                if (obj is UnityEngine.Component comp)
                    return comp.gameObject;
                return null;
            }

            if (!string.IsNullOrEmpty(name))
            {
                return FindGameObjectByName(name);
            }

            return null;
        }

        /// <summary>
        /// Finds a GameObject by name in the active scene (including inactive objects).
        /// </summary>
        private static GameObject FindGameObjectByName(string name)
        {
            // Check prefab stage first
            var prefabStage = PrefabStageUtility.GetCurrentPrefabStage();
            if (prefabStage?.prefabContentsRoot != null)
            {
                foreach (var transform in prefabStage.prefabContentsRoot.GetComponentsInChildren<Transform>(true))
                {
                    if (transform.name == name)
                        return transform.gameObject;
                }
            }

            // Search in active scene
            var activeScene = SceneManager.GetActiveScene();
            foreach (var root in activeScene.GetRootGameObjects())
            {
                foreach (var transform in root.GetComponentsInChildren<Transform>(true))
                {
                    if (transform.gameObject.name == name)
                        return transform.gameObject;
                }
            }

            return null;
        }

        /// <summary>
        /// Finds a Type by full name or short name.
        /// </summary>
        private static Type FindType(string typeName)
        {
            // Try full name first
            var type = Type.GetType(typeName);
            if (type != null) return type;

            // Search in all assemblies
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                try
                {
                    type = assembly.GetType(typeName);
                    if (type != null) return type;

                    // Try short name match
                    type = assembly.GetTypes().FirstOrDefault(t =>
                        t.Name == typeName || t.FullName == typeName);
                    if (type != null) return type;
                }
                catch (ReflectionTypeLoadException)
                {
                    // Skip assemblies that can't be loaded
                }
            }

            return null;
        }

        /// <summary>
        /// Serializes component properties using reflection.
        /// </summary>
        private static JObject SerializeComponentProperties(UnityEngine.Component component)
        {
            var result = new JObject();
            var componentType = component.GetType();

            // Handle Transform specially to avoid circular references
            if (componentType == typeof(Transform))
            {
                return SerializeTransform((Transform)component);
            }

            // Handle Camera specially
            if (componentType == typeof(Camera))
            {
                return SerializeCamera((Camera)component);
            }

            // Get public properties
            var properties = componentType.GetProperties(BindingFlags.Public | BindingFlags.Instance);
            foreach (var prop in properties)
            {
                if (!prop.CanRead) continue;
                if (prop.GetIndexParameters().Length > 0) continue;
                if (ShouldSkipProperty(prop.Name)) continue;

                try
                {
                    var value = prop.GetValue(component);
                    var serialized = SerializeValue(value, prop.PropertyType);
                    if (serialized != null)
                    {
                        result[prop.Name] = serialized;
                    }
                }
                catch
                {
                    // Skip properties that throw exceptions
                }
            }

            // Get public fields
            var fields = componentType.GetFields(BindingFlags.Public | BindingFlags.Instance);
            foreach (var field in fields)
            {
                if (ShouldSkipProperty(field.Name)) continue;

                try
                {
                    var value = field.GetValue(component);
                    var serialized = SerializeValue(value, field.FieldType);
                    if (serialized != null)
                    {
                        result[field.Name] = serialized;
                    }
                }
                catch
                {
                    // Skip fields that throw exceptions
                }
            }

            return result;
        }

        /// <summary>
        /// Properties to skip during serialization.
        /// </summary>
        private static bool ShouldSkipProperty(string name)
        {
            return name switch
            {
                // Generic Unity Component properties that cause issues
                "rigidbody" or "rigidbody2D" or "camera" or "light" or "animation" or
                "constantForce" or "renderer" or "audio" or "networkView" or
                "collider" or "collider2D" or "hingeJoint" or "particleSystem" => true,
                // Matrix properties that cause circular references
                "worldToLocalMatrix" or "localToWorldMatrix" or
                "cullingMatrix" or "worldToCameraMatrix" or "projectionMatrix" or
                "nonJitteredProjectionMatrix" or "previousViewProjectionMatrix" or
                "cameraToWorldMatrix" => true,
                // Transform properties on Camera/other components
                "transform" => true,
                _ => false
            };
        }

        /// <summary>
        /// Serializes a value to JToken, handling special Unity types.
        /// </summary>
        private static JToken SerializeValue(object value, Type type)
        {
            if (value == null) return JValue.CreateNull();

            // Handle primitive types
            if (type.IsPrimitive || type == typeof(string) || type == typeof(decimal))
            {
                return JToken.FromObject(value);
            }

            // Handle enums
            if (type.IsEnum)
            {
                return value.ToString();
            }

            // Handle Vector types
            if (type == typeof(Vector2))
            {
                var v = (Vector2)value;
                return new JObject { ["x"] = v.x, ["y"] = v.y };
            }
            if (type == typeof(Vector3))
            {
                var v = (Vector3)value;
                return new JObject { ["x"] = v.x, ["y"] = v.y, ["z"] = v.z };
            }
            if (type == typeof(Vector4))
            {
                var v = (Vector4)value;
                return new JObject { ["x"] = v.x, ["y"] = v.y, ["z"] = v.z, ["w"] = v.w };
            }

            // Handle Quaternion
            if (type == typeof(Quaternion))
            {
                var q = (Quaternion)value;
                var euler = q.eulerAngles;
                return new JObject { ["x"] = euler.x, ["y"] = euler.y, ["z"] = euler.z };
            }

            // Handle Color
            if (type == typeof(Color))
            {
                var c = (Color)value;
                return new JObject { ["r"] = c.r, ["g"] = c.g, ["b"] = c.b, ["a"] = c.a };
            }
            if (type == typeof(Color32))
            {
                var c = (Color32)value;
                return new JObject { ["r"] = c.r, ["g"] = c.g, ["b"] = c.b, ["a"] = c.a };
            }

            // Handle Rect
            if (type == typeof(Rect))
            {
                var r = (Rect)value;
                return new JObject { ["x"] = r.x, ["y"] = r.y, ["width"] = r.width, ["height"] = r.height };
            }

            // Handle Bounds
            if (type == typeof(Bounds))
            {
                var b = (Bounds)value;
                return new JObject
                {
                    ["center"] = new JObject { ["x"] = b.center.x, ["y"] = b.center.y, ["z"] = b.center.z },
                    ["size"] = new JObject { ["x"] = b.size.x, ["y"] = b.size.y, ["z"] = b.size.z }
                };
            }

            // Handle UnityEngine.Object references (avoid circular refs)
            if (typeof(UnityEngine.Object).IsAssignableFrom(type))
            {
                var unityObj = value as UnityEngine.Object;
                if (unityObj == null) return JValue.CreateNull();

                return new JObject
                {
                    ["name"] = unityObj.name,
                    ["instanceID"] = unityObj.GetInstanceID(),
                    ["type"] = unityObj.GetType().Name
                };
            }

            // Handle arrays and lists of primitives
            if (type.IsArray && type.GetElementType()?.IsPrimitive == true)
            {
                return JArray.FromObject(value);
            }

            // For other complex types, just return type info to avoid deep recursion
            return new JObject
            {
                ["_type"] = type.Name,
                ["_toString"] = value.ToString()
            };
        }

        /// <summary>
        /// Serializes Transform component with safe properties only.
        /// </summary>
        private static JObject SerializeTransform(Transform tr)
        {
            return new JObject
            {
                ["position"] = new JObject { ["x"] = tr.position.x, ["y"] = tr.position.y, ["z"] = tr.position.z },
                ["localPosition"] = new JObject { ["x"] = tr.localPosition.x, ["y"] = tr.localPosition.y, ["z"] = tr.localPosition.z },
                ["eulerAngles"] = new JObject { ["x"] = tr.eulerAngles.x, ["y"] = tr.eulerAngles.y, ["z"] = tr.eulerAngles.z },
                ["localEulerAngles"] = new JObject { ["x"] = tr.localEulerAngles.x, ["y"] = tr.localEulerAngles.y, ["z"] = tr.localEulerAngles.z },
                ["localScale"] = new JObject { ["x"] = tr.localScale.x, ["y"] = tr.localScale.y, ["z"] = tr.localScale.z },
                ["forward"] = new JObject { ["x"] = tr.forward.x, ["y"] = tr.forward.y, ["z"] = tr.forward.z },
                ["up"] = new JObject { ["x"] = tr.up.x, ["y"] = tr.up.y, ["z"] = tr.up.z },
                ["right"] = new JObject { ["x"] = tr.right.x, ["y"] = tr.right.y, ["z"] = tr.right.z },
                ["childCount"] = tr.childCount,
                ["parent"] = tr.parent != null ? new JObject
                {
                    ["name"] = tr.parent.name,
                    ["instanceID"] = tr.parent.gameObject.GetInstanceID()
                } : null
            };
        }

        /// <summary>
        /// Serializes Camera component with safe properties only.
        /// </summary>
        private static JObject SerializeCamera(Camera cam)
        {
            return new JObject
            {
                ["nearClipPlane"] = cam.nearClipPlane,
                ["farClipPlane"] = cam.farClipPlane,
                ["fieldOfView"] = cam.fieldOfView,
                ["orthographic"] = cam.orthographic,
                ["orthographicSize"] = cam.orthographicSize,
                ["depth"] = cam.depth,
                ["aspect"] = cam.aspect,
                ["cullingMask"] = cam.cullingMask,
                ["backgroundColor"] = new JObject
                {
                    ["r"] = cam.backgroundColor.r,
                    ["g"] = cam.backgroundColor.g,
                    ["b"] = cam.backgroundColor.b,
                    ["a"] = cam.backgroundColor.a
                },
                ["clearFlags"] = cam.clearFlags.ToString(),
                ["renderingPath"] = cam.renderingPath.ToString(),
                ["allowHDR"] = cam.allowHDR,
                ["allowMSAA"] = cam.allowMSAA,
                ["enabled"] = cam.enabled
            };
        }
    }
}
