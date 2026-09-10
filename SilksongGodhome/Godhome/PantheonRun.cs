using System;
using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// Tracks progress through a Pantheon.
    ///
    /// Hollow Knight advances a run from <c>BossSequenceController.FinishBossScene</c>,
    /// which fires when a <c>BossSceneController</c> reports its boss dead and then hands
    /// off to a "Dream Enter Next Scene" FSM. Godhome's arenas here have neither - no
    /// BossSceneController, and no bosses to kill - so the run index is kept here instead.
    ///
    /// Silksong's own <c>BossSequenceController</c> is still set up for the run
    /// (<c>SetupNewSequence</c>), so bindings, bound nail damage and bound max health all
    /// behave as they do in Hollow Knight; only the "which boss are we on" bookkeeping is
    /// ours, because the thing that normally drives it doesn't exist yet.
    /// </summary>
    internal static class PantheonRun
    {
        public static BossSequence Sequence { get; private set; }
        public static string Title { get; private set; }
        public static int Index { get; private set; }

        public static bool IsActive => Sequence != null;

        public static int Count => Sequence != null ? Sequence.Count : 0;

        /// <summary>Scene name of the arena we're currently in, or null.</summary>
        public static string CurrentScene =>
            (Sequence != null && Index >= 0 && Index < Sequence.Count)
                ? Sequence.GetSceneAt(Index)
                : null;

        private const string ArenaEntryGate = "door_dreamEnter";

        public static void Begin(BossSequence sequence, string title)
        {
            Sequence = sequence;
            Title = title;
            Index = 0;
            Plugin.Log.LogInfo($"Godhome: run '{title}' begun ({sequence.Count} bosses).");
            GoTo(0);
        }

        public static void Clear()
        {
            Sequence = null;
            Title = null;
            Index = 0;
        }

        /// <summary>Moves to the next arena, or ends the run after the last one.</summary>
        public static void Advance()
        {
            if (!IsActive) return;

            Index++;
            if (Index >= Sequence.Count)
            {
                Finish();
                return;
            }
            GoTo(Index);
        }

        /// <summary>
        /// Skips the current arena. Without bosses this is the only way through a
        /// Pantheon; with them it's still useful for getting to a specific fight.
        /// </summary>
        public static void Skip()
        {
            if (!IsActive)
            {
                Plugin.Log.LogInfo("Godhome: no Pantheon run in progress; nothing to skip.");
                return;
            }

            string from = CurrentScene;
            Plugin.Log.LogInfo($"Godhome: skipping '{from}' ({Index + 1}/{Count}).");
            Advance();
        }

        private static void GoTo(int index)
        {
            string scene = Sequence.GetSceneAt(index);

            // Arenas we never baked would drop the player into an unbuilt room, so step
            // over them rather than stranding the run.
            int guard = 0;
            while (!Rebuild.GodhomeData.HasScene(scene) && guard++ < Sequence.Count)
            {
                Plugin.Log.LogWarning($"Godhome: '{scene}' isn't baked; skipping past it.");
                Index++;
                if (Index >= Sequence.Count)
                {
                    Finish();
                    return;
                }
                scene = Sequence.GetSceneAt(Index);
            }

            Plugin.Log.LogInfo($"Godhome: run -> {scene} ({Index + 1}/{Count})");
            Travel(scene, ArenaEntryGate);
        }

        private static void Finish()
        {
            string title = Title;
            Clear();

            try { BossSequenceController.Reset(); }
            catch (Exception) { }

            Plugin.Log.LogInfo($"Godhome: run '{title}' complete; returning to the Atrium.");
            Travel(GodhomeLoadout.HubScene, null);
        }

        private static void Travel(string scene, string gate)
        {
            try
            {
                GameManager.instance.BeginSceneTransition(new GameManager.SceneLoadInfo
                {
                    SceneName = scene,
                    EntryGateName = gate,
                    Visualization = GameManager.SceneLoadVisualizations.Default,
                    AlwaysUnloadUnusedAssets = true,
                    WaitForSceneTransitionCameraFade = true,
                });
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Godhome: couldn't travel to '{scene}': {e}");
            }
        }
    }
}
