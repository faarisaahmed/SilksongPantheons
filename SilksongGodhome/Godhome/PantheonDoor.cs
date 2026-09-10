using System;
using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// A Pantheon entrance.
    ///
    /// Hollow Knight's <see cref="BossSequenceDoor"/> exists in Silksong, but it needs a
    /// dozen wired prefab references (lockSet, unlockedSet, challengeFSM, the binding
    /// displays) that we have no way to reconstruct, and its <c>Start()</c> reads a
    /// per-tier PlayerData field that Silksong's save doesn't have. So the *presentation*
    /// is ours.
    ///
    /// The part that matters is not: starting a run goes through Silksong's own
    /// <c>BossSequenceController.SetupNewSequence</c>, which is exactly what Hollow
    /// Knight's challenge FSM does. From there the game tracks bindings, boss index and
    /// completion itself.
    ///
    /// Hollow Knight's FSM then sets the door's "To Scene" to <c>bossSequence.GetSceneAt(0)</c>
    /// and transitions with entry gate "door_dreamEnter"; this does the same.
    /// </summary>
    internal class PantheonDoor : GodhomeInteractable
    {
        /// <summary>The Pantheon's title, e.g. "Pantheon of the Judge".</summary>
        public string SequenceName;

        /// <summary>
        /// Which Pantheon a Hollow Knight door leads to now.
        ///
        /// Godhome's Atrium has five doors. Four of them carry a tier name; the fifth is
        /// Hollow Knight's Pantheon of Hallownest, which it only revealed once the rest
        /// were done and which has no counterpart here. Tiers one to three are the
        /// authored Pantheons and tier four is Pantheon of Pharloom - the three back to
        /// back, and deliberately open from the start rather than gated behind them.
        /// </summary>
        public static string TitleForTier(string doorSequence)
        {
            switch (doorSequence)
            {
                case "Boss Sequence Tier 1": return PantheonRegistry.Titles[0];
                case "Boss Sequence Tier 2": return PantheonRegistry.Titles[1];
                case "Boss Sequence Tier 3": return PantheonRegistry.Titles[2];
                case "Boss Sequence Tier 4": return PantheonRegistry.Titles[3];
                default: return null;
            }
        }

        /// <summary>Hollow Knight's per-tier PlayerData field, e.g. "bossDoorStateTier1".</summary>
        public string PlayerDataName;

        private const string ArenaEntryGate = "door_dreamEnter";

        private string Title => SequenceName;

        protected override bool CanInteract() =>
            !string.IsNullOrEmpty(SequenceName) && !PantheonChallengeUI.IsOpen;

        protected override string Prompt
        {
            get
            {
                BossSequence seq = PantheonRegistry.Get(SequenceName);
                if (seq == null) return $"{Title} (unavailable)";

                return $"{Title} - {seq.Count} bosses\nPress Up to inspect";
            }
        }

        /// <summary>
        /// Inspecting a door opens the binding screen, as it does in Hollow Knight -
        /// it doesn't start the run outright.
        /// </summary>
        protected override void Interact()
        {
            BossSequence seq = PantheonRegistry.Get(SequenceName);
            if (seq == null || seq.Count == 0)
            {
                Plugin.Log.LogWarning($"Godhome: '{SequenceName}' has no bosses; not starting.");
                return;
            }

            string first = seq.GetSceneAt(0);
            if (!Rebuild.GodhomeData.HasScene(first))
            {
                // Starting anyway would strand the player in an empty donor room, which
                // reads as a crash. Refuse loudly instead.
                Plugin.Log.LogWarning(
                    $"Godhome: not starting '{SequenceName}' - its first arena '{first}' " +
                    "hasn't been baked. Add it with tools/extract_godhome.py --scenes " + first);
                return;
            }

            PantheonChallengeUI.Open(this, seq, Title);
        }

        /// <summary>
        /// Called by the challenge screen once bindings are chosen. This is the point
        /// Hollow Knight's challenge FSM reaches: set up the sequence, then walk into the
        /// first arena through "door_dreamEnter".
        /// </summary>
        public void BeginRun(BossSequence seq, BossSequenceController.ChallengeBindings bindings)
        {
            try
            {
                // Silksong's own controller still runs the bindings; PantheonRun only
                // tracks which boss we're on, because the BossSceneController that
                // normally does that doesn't exist in a rebuilt arena.
                BossSequenceController.SetupNewSequence(
                    seq, bindings, PlayerDataName ?? string.Empty);

                Plugin.Log.LogInfo($"Godhome: starting {Title} (bindings: {bindings})");
                PantheonRun.Begin(seq, Title);
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Godhome: couldn't start '{SequenceName}': {e}");
            }
        }
    }
}
