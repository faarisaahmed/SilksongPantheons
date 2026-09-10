using System;
using UnityEngine;

namespace SilksongGodhome
{
    /// <summary>
    /// Forwards Unity's own errors into the BepInEx log while Godhome is loading.
    ///
    /// A black screen almost always means an exception fired somewhere in GameManager's
    /// enter-scene sequence and killed it partway - but that exception surfaces through
    /// Unity's log, not ours, so it's easy to miss when reading a plugin log. Mirroring
    /// them with a Godhome prefix makes the actual failure obvious.
    /// </summary>
    internal static class CrashWatch
    {
        private static bool _hooked;
        private static int _errors;

        public static int ErrorCount => _errors;

        public static void Arm()
        {
            if (_hooked) return;
            Application.logMessageReceived += OnLog;
            _hooked = true;
            _errors = 0;
        }

        public static void Disarm()
        {
            if (!_hooked) return;
            Application.logMessageReceived -= OnLog;
            _hooked = false;
        }

        private static void OnLog(string condition, string stackTrace, LogType type)
        {
            if (type != LogType.Exception && type != LogType.Error) return;

            _errors++;
            // Only the first few matter; a broken frame can repeat forever.
            if (_errors > 8) return;

            Plugin.Log.LogError($"Godhome: [game] {type}: {condition}\n{stackTrace}");
        }
    }
}
