using System;
using UnityEngine;

namespace SilksongGodhome.Rebuild
{
    /// <summary>
    /// Turns a request for a Godhome scene into a request for a real Silksong scene,
    /// remembering what was actually asked for.
    ///
    /// Silksong's Addressables catalog contains no GG_* entries, so
    /// Addressables.LoadSceneAsync("Scenes/GG_Atrium") fails and the transition hangs.
    /// But the whole engine around a scene load - the fade, the hero spawn, camera
    /// bounds, tilemap info, the SceneManager component GameManager.FindSceneManager
    /// expects - only works properly for a scene that genuinely loaded.
    ///
    /// So we load a real (small) gameplay room as a shell, then <see cref="SceneRebuilder"/>
    /// empties it and builds Godhome inside it. The game believes an ordinary room came
    /// up; we control its contents.
    /// </summary>
    internal static class SceneRedirect
    {
        /// <summary>Prefix identifying a Godhome scene. Matches Hollow Knight's naming.</summary>
        public const string GodhomePrefix = "GG_";

        /// <summary>
        /// The Godhome scene the game asked for, or null if we're in a normal scene.
        /// Read by <see cref="SceneRebuilder"/> once the donor is live.
        /// </summary>
        public static string PendingGodhomeScene { get; private set; }

        /// <summary>The most recent Godhome scene we actually built.</summary>
        public static string CurrentGodhomeScene { get; internal set; }

        public static bool IsGodhomeScene(string sceneName) =>
            !string.IsNullOrEmpty(sceneName) &&
            sceneName.StartsWith(GodhomePrefix, StringComparison.Ordinal);

        /// <summary>Where a Godhome scene should be entered, once we're already inside Godhome.</summary>
        public static string PendingEntryGate { get; private set; }

        /// <summary>
        /// Called from a prefix on GameManager.BeginSceneTransition.
        ///
        /// Returns false to cancel the transition entirely, which is what happens when
        /// we're already standing in Godhome: moving between two Godhome rooms would map
        /// both onto donor scenes and run the full transition pipeline for a scene whose
        /// contents we're going to replace anyway. That pipeline is where loads were
        /// hanging, and none of it buys us anything - so the room is swapped in place
        /// instead. See <see cref="SceneRebuilder.SwapInPlace"/>.
        ///
        /// The first entry into Godhome still needs a real transition, because we have to
        /// get into a gameplay scene at all.
        /// </summary>
        public static bool Intercept(GameManager.SceneLoadInfo info)
        {
            if (info == null) return true;

            string requested = info.SceneName;
            if (!IsGodhomeScene(requested))
            {
                // Leaving Godhome - stop claiming scenes we didn't build.
                PendingGodhomeScene = null;
                CurrentGodhomeScene = null;
                return true;
            }

            if (!string.IsNullOrEmpty(CurrentGodhomeScene) && GodhomeData.HasScene(requested))
            {
                PendingEntryGate = info.EntryGateName;
                Plugin.Log.LogInfo(
                    $"Godhome: '{CurrentGodhomeScene}' -> '{requested}' in place (gate '{PendingEntryGate}').");
                SceneRebuilder.RequestSwap(requested, info.EntryGateName);
                return false;
            }

            if (!GodhomeData.HasScene(requested))
            {
                Plugin.Log.LogWarning(
                    $"Godhome: '{requested}' was requested but isn't in the baked data. " +
                    "Run tools/extract_godhome.py to bake it. Falling through to the donor room as-is.");
            }

            PendingGodhomeScene = requested;
            PendingEntryGate = info.EntryGateName;
            info.SceneName = NextDonor();

            // A stale resource location would win over SceneName and load the original
            // scene anyway.
            info.SceneResourceLocation = null;

            Plugin.Log.LogInfo($"Godhome: '{requested}' -> donor scene '{info.SceneName}'.");
            return true;
        }

        private static string _lastDonor;

        /// <summary>
        /// Picks a donor room that isn't the one we're currently standing in.
        ///
        /// Every Godhome scene maps onto a donor, so walking from the Atrium into an
        /// arena would ask the game to load the scene it's already in. Unity will do
        /// that, but the transition then waits forever for the old copy to unload - which
        /// presents as an infinite loading screen. Alternating between two real rooms
        /// avoids it entirely.
        /// </summary>
        private static string NextDonor()
        {
            string[] donors = GodhomeConfig.DonorScene.Value
                .Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries);

            for (int i = 0; i < donors.Length; i++) donors[i] = donors[i].Trim();

            if (donors.Length == 0) return "Bone_05";

            string current = UnityEngine.SceneManagement.SceneManager.GetActiveScene().name;

            foreach (string d in donors)
            {
                if (!string.Equals(d, current, StringComparison.Ordinal) &&
                    !string.Equals(d, _lastDonor, StringComparison.Ordinal))
                {
                    _lastDonor = d;
                    return d;
                }
            }

            // Only one usable donor: still avoid the active scene if we can.
            foreach (string d in donors)
            {
                if (!string.Equals(d, current, StringComparison.Ordinal))
                {
                    _lastDonor = d;
                    return d;
                }
            }

            Plugin.Log.LogWarning(
                $"Godhome: only donor '{donors[0]}' is configured and we're already in it; " +
                "the transition may hang. Add a second room to DonorScene.");
            _lastDonor = donors[0];
            return donors[0];
        }

        /// <summary>Consumes the pending name; returns null if there's nothing to build.</summary>
        public static string TakePending()
        {
            string s = PendingGodhomeScene;
            PendingGodhomeScene = null;
            return s;
        }
    }
}
