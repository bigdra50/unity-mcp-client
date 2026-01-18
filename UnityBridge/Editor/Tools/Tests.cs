using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using UnityBridge.Helpers;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEditor.TestTools.TestRunner.Api;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace UnityBridge.Tools
{
    /// <summary>
    /// Handler for test runner commands.
    /// Executes Unity tests via TestRunnerApi.
    /// </summary>
    [BridgeTool("tests")]
    public static class Tests
    {
        private static TestRunnerApi _testRunnerApi;
        private static TestResultCollector _activeCollector;

        // SemaphoreSlim for exclusive access (prevents concurrent test runs)
        private static readonly SemaphoreSlim _operationLock = new(1, 1);

        private static TestRunnerApi Api
        {
            get
            {
                if (_testRunnerApi == null)
                {
                    _testRunnerApi = ScriptableObject.CreateInstance<TestRunnerApi>();
                }
                return _testRunnerApi;
            }
        }

        public static async Task<JObject> HandleCommand(JObject parameters)
        {
            var action = parameters["action"]?.Value<string>() ?? "run";

            // status doesn't need lock - read-only operation
            if (action.ToLowerInvariant() == "status")
            {
                return GetStatus();
            }

            // Acquire lock for run/list operations
            await _operationLock.WaitAsync().ConfigureAwait(true);
            try
            {
                return action.ToLowerInvariant() switch
                {
                    "run" => await RunTestsAsync(parameters),
                    "list" => await ListTestsAsync(parameters),
                    _ => throw new ProtocolException(
                        ErrorCode.InvalidParams,
                        $"Unknown action: {action}")
                };
            }
            finally
            {
                _operationLock.Release();
            }
        }

        private static async Task<JObject> RunTestsAsync(JObject parameters)
        {
            if (_activeCollector != null && !_activeCollector.IsComplete)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "Tests are already running. Use 'status' action to check progress.");
            }

            if (EditorApplication.isPlaying || EditorApplication.isPlayingOrWillChangePlaymode)
            {
                throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    "Cannot start tests while Editor is in Play Mode. Stop Play Mode first.");
            }

            var mode = parameters["mode"]?.Value<string>()?.ToLowerInvariant() ?? "edit";
            var testMode = mode switch
            {
                "edit" => TestMode.EditMode,
                "play" => TestMode.PlayMode,
                _ => throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Invalid test mode: {mode}. Use 'edit' or 'play'.")
            };

            var filter = new Filter { testMode = testMode };

            // Filter by test names (full names like "MyNamespace.MyClass.TestMethod")
            var testNames = parameters["testNames"]?.ToObject<string[]>();
            if (testNames != null && testNames.Length > 0)
            {
                filter.testNames = testNames;
            }

            // Filter by categories
            var categories = parameters["categories"]?.ToObject<string[]>();
            if (categories != null && categories.Length > 0)
            {
                filter.categoryNames = categories;
            }

            // Filter by assembly names
            var assemblies = parameters["assemblies"]?.ToObject<string[]>();
            if (assemblies != null && assemblies.Length > 0)
            {
                filter.assemblyNames = assemblies;
            }

            // Filter by group (regex pattern for namespaces)
            var groupPattern = parameters["groupPattern"]?.Value<string>();
            if (!string.IsNullOrEmpty(groupPattern))
            {
                filter.groupNames = new[] { groupPattern };
            }

            // PlayMode: Disable Domain Reload to keep connection alive
            // Use local variables to ensure proper restoration even on failure
            bool adjustedPlayModeOptions = false;
            bool originalEnterPlayModeOptionsEnabled = false;
            var originalEnterPlayModeOptions = EnterPlayModeOptions.None;

            if (testMode == TestMode.PlayMode)
            {
                adjustedPlayModeOptions = EnsurePlayModeRunsWithoutDomainReload(
                    out originalEnterPlayModeOptionsEnabled,
                    out originalEnterPlayModeOptions);
                SaveDirtyScenesIfNeeded();
            }

            try
            {
                // Create collector and register callback
                _activeCollector = new TestResultCollector(testMode)
                {
                    // Pass restoration info to collector so it can restore on completion
                    NeedsRestorePlayModeOptions = adjustedPlayModeOptions,
                    OriginalEnterPlayModeOptionsEnabled = originalEnterPlayModeOptionsEnabled,
                    OriginalEnterPlayModeOptions = originalEnterPlayModeOptions
                };
                Api.RegisterCallbacks(_activeCollector, 1);

                // Check for synchronous execution (EditMode only)
                var sync = parameters["synchronous"]?.Value<bool>() ?? false;
                var executionSettings = new ExecutionSettings(filter);

                if (sync && testMode == TestMode.EditMode)
                {
                    executionSettings.runSynchronously = true;
                    Api.Execute(executionSettings);

                    // Synchronous execution completes immediately
                    var result = BuildResultJson(_activeCollector);
                    Api.UnregisterCallbacks(_activeCollector);
                    _activeCollector = null;
                    return result;
                }

                // Async execution - wait for completion using TaskCompletionSource
                var tcs = new TaskCompletionSource<JObject>(TaskCreationOptions.RunContinuationsAsynchronously);
                _activeCollector.OnCompleted = () =>
                {
                    var result = BuildResultJson(_activeCollector);
                    Api.UnregisterCallbacks(_activeCollector);
                    _activeCollector = null;
                    tcs.TrySetResult(result);
                };

                Api.Execute(executionSettings);

                // Return immediately with async hint for non-blocking behavior
                // The caller can use 'status' action to poll for results
                return new JObject
                {
                    ["message"] = $"Test run started ({mode} mode)",
                    ["async"] = true,
                    ["hint"] = "Use 'status' action to check progress and get results"
                };
            }
            catch
            {
                // Ensure restoration on any exception during setup
                if (adjustedPlayModeOptions)
                {
                    RestoreEnterPlayModeOptions(originalEnterPlayModeOptionsEnabled, originalEnterPlayModeOptions);
                }
                throw;
            }
        }

        /// <summary>
        /// Temporarily disable Domain Reload for PlayMode tests to keep connection alive.
        /// Returns true if settings were changed and need to be restored.
        /// </summary>
        private static bool EnsurePlayModeRunsWithoutDomainReload(
            out bool originalEnterPlayModeOptionsEnabled,
            out EnterPlayModeOptions originalEnterPlayModeOptions)
        {
            originalEnterPlayModeOptionsEnabled = EditorSettings.enterPlayModeOptionsEnabled;
            originalEnterPlayModeOptions = EditorSettings.enterPlayModeOptions;

            bool domainReloadDisabled = (originalEnterPlayModeOptions & EnterPlayModeOptions.DisableDomainReload) != 0;
            bool needsChange = !originalEnterPlayModeOptionsEnabled || !domainReloadDisabled;

            if (!needsChange)
            {
                return false;
            }

            var desired = originalEnterPlayModeOptions | EnterPlayModeOptions.DisableDomainReload;
            EditorSettings.enterPlayModeOptionsEnabled = true;
            EditorSettings.enterPlayModeOptions = desired;

            BridgeLog.Info("[Tests] Temporarily disabled Domain Reload for PlayMode tests");
            return true;
        }

        /// <summary>
        /// Restore original Enter Play Mode settings
        /// </summary>
        private static void RestoreEnterPlayModeOptions(
            bool originalEnabled,
            EnterPlayModeOptions originalOptions)
        {
            EditorSettings.enterPlayModeOptions = originalOptions;
            EditorSettings.enterPlayModeOptionsEnabled = originalEnabled;

            BridgeLog.Info("[Tests] Restored Enter Play Mode settings");
        }

        /// <summary>
        /// Save dirty scenes before PlayMode tests to prevent save dialog
        /// </summary>
        private static void SaveDirtyScenesIfNeeded()
        {
            int sceneCount = SceneManager.sceneCount;
            for (int i = 0; i < sceneCount; i++)
            {
                var scene = SceneManager.GetSceneAt(i);
                if (scene.isDirty && !string.IsNullOrEmpty(scene.path))
                {
                    try
                    {
                        EditorSceneManager.SaveScene(scene);
                        BridgeLog.Info($"[Tests] Saved dirty scene: {scene.name}");
                    }
                    catch (Exception ex)
                    {
                        BridgeLog.Warn($"[Tests] Failed to save scene '{scene.name}': {ex.Message}");
                    }
                }
            }
        }

        private static Task<JObject> ListTestsAsync(JObject parameters)
        {
            var mode = parameters["mode"]?.Value<string>()?.ToLowerInvariant() ?? "edit";
            var testMode = mode switch
            {
                "edit" => TestMode.EditMode,
                "play" => TestMode.PlayMode,
                _ => throw new ProtocolException(
                    ErrorCode.InvalidParams,
                    $"Invalid test mode: {mode}. Use 'edit' or 'play'.")
            };

            var tests = new List<JObject>();
            // RunContinuationsAsynchronously prevents deadlocks
            var tcs = new TaskCompletionSource<JObject>(TaskCreationOptions.RunContinuationsAsynchronously);
            var startTime = DateTime.UtcNow;
            const int timeoutSeconds = 30;

            void OnUpdate()
            {
                // Check timeout
                if ((DateTime.UtcNow - startTime).TotalSeconds > timeoutSeconds)
                {
                    EditorApplication.update -= OnUpdate;
                    tcs.TrySetException(new ProtocolException(
                        ErrorCode.InternalError,
                        "Timeout retrieving test tree"));
                }
            }

            Api.RetrieveTestList(testMode, testRoot =>
            {
                EditorApplication.update -= OnUpdate;
                CollectTests(testRoot, tests);

                var result = new JObject
                {
                    ["mode"] = mode,
                    ["count"] = tests.Count,
                    ["tests"] = new JArray(tests)
                };
                tcs.TrySetResult(result);
            });

            EditorApplication.update += OnUpdate;

            // Force editor update even when not focused
            EditorApplication.QueuePlayerLoopUpdate();

            return tcs.Task;
        }

        private static void CollectTests(ITestAdaptor test, List<JObject> tests)
        {
            if (test == null) return;

            // Only include actual test methods (leaf nodes)
            if (!test.HasChildren && test.IsSuite == false)
            {
                tests.Add(new JObject
                {
                    ["fullName"] = test.FullName,
                    ["name"] = test.Name,
                    ["categories"] = new JArray(test.Categories ?? Array.Empty<string>()),
                    ["runState"] = test.RunState.ToString()
                });
            }

            if (test.Children != null)
            {
                foreach (var child in test.Children)
                {
                    CollectTests(child, tests);
                }
            }
        }

        private static JObject GetStatus()
        {
            if (_activeCollector == null)
            {
                return new JObject
                {
                    ["running"] = false,
                    ["message"] = "No test run in progress"
                };
            }

            if (_activeCollector.IsComplete)
            {
                var result = BuildResultJson(_activeCollector);
                Api.UnregisterCallbacks(_activeCollector);
                _activeCollector = null;
                return result;
            }

            return new JObject
            {
                ["running"] = true,
                ["testsStarted"] = _activeCollector.TestsStarted,
                ["testsFinished"] = _activeCollector.TestsFinished,
                ["passed"] = _activeCollector.Passed,
                ["failed"] = _activeCollector.Failed,
                ["skipped"] = _activeCollector.Skipped
            };
        }

        private static JObject BuildResultJson(TestResultCollector collector)
        {
            var failedTests = new JArray();
            foreach (var failure in collector.FailedTests)
            {
                failedTests.Add(new JObject
                {
                    ["name"] = failure.FullName,
                    ["message"] = failure.Message,
                    ["stackTrace"] = failure.StackTrace
                });
            }

            return new JObject
            {
                ["running"] = false,
                ["complete"] = true,
                ["passed"] = collector.Passed,
                ["failed"] = collector.Failed,
                ["skipped"] = collector.Skipped,
                ["duration"] = collector.Duration,
                ["failedTests"] = failedTests
            };
        }

        /// <summary>
        /// Collects test results from TestRunnerApi callbacks
        /// </summary>
        private class TestResultCollector : ICallbacks
        {
            private readonly TestMode _testMode;

            // Restoration state (set externally for PlayMode tests)
            public bool NeedsRestorePlayModeOptions { get; set; }
            public bool OriginalEnterPlayModeOptionsEnabled { get; set; }
            public EnterPlayModeOptions OriginalEnterPlayModeOptions { get; set; }

            // Callback for async completion notification
            public Action OnCompleted { get; set; }

            public bool IsComplete { get; private set; }
            public int TestsStarted { get; private set; }
            public int TestsFinished { get; private set; }
            public int Passed { get; private set; }
            public int Failed { get; private set; }
            public int Skipped { get; private set; }
            public double Duration { get; private set; }
            public List<FailedTestInfo> FailedTests { get; } = new();

            public TestResultCollector(TestMode testMode = TestMode.EditMode)
            {
                _testMode = testMode;
            }

            public void RunStarted(ITestAdaptor testsToRun)
            {
                BridgeLog.Info($"[Tests] Test run started: {testsToRun.TestCaseCount} tests ({_testMode})");
                IsComplete = false;
                TestsStarted = 0;
                TestsFinished = 0;
                Passed = 0;
                Failed = 0;
                Skipped = 0;
                FailedTests.Clear();
            }

            public void TestStarted(ITestAdaptor test)
            {
                TestsStarted++;
            }

            public void TestFinished(ITestResultAdaptor result)
            {
                TestsFinished++;

                // Only count leaf nodes (actual tests, not fixtures)
                if (result.HasChildren) return;

                switch (result.ResultState)
                {
                    case "Passed":
                        Passed++;
                        break;
                    case "Failed":
                        Failed++;
                        FailedTests.Add(new FailedTestInfo
                        {
                            FullName = result.FullName,
                            Message = result.Message,
                            StackTrace = result.StackTrace
                        });
                        BridgeLog.Error($"[Tests] Test failed: {result.FullName}\n{result.Message}");
                        break;
                    case "Skipped":
                    case "Ignored":
                        Skipped++;
                        break;
                }
            }

            public void RunFinished(ITestResultAdaptor testResults)
            {
                Duration = testResults.Duration;
                IsComplete = true;

                // Restore PlayMode settings if we changed them
                if (NeedsRestorePlayModeOptions)
                {
                    RestoreEnterPlayModeOptions(OriginalEnterPlayModeOptionsEnabled, OriginalEnterPlayModeOptions);
                }

                BridgeLog.Info($"[Tests] Test run finished ({_testMode}): " +
                         $"Pass={Passed}, Fail={Failed}, Skip={Skipped}, Duration={Duration:F2}s");

                // Notify completion for async callers
                OnCompleted?.Invoke();
            }

            public struct FailedTestInfo
            {
                public string FullName;
                public string Message;
                public string StackTrace;
            }
        }
    }
}
