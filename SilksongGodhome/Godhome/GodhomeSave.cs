using System;
using System.Collections.Generic;
using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// Godhome-shaped holes in a Silksong save.
    ///
    /// PlayerData.CreateNewSingleton deserialises from the literal string "{}", so any
    /// field without an initialiser stays null - and <c>unlockedBossScenes</c> is one of
    /// them. <see cref="BossScene.IsUnlockedSelf"/> then does:
    ///
    ///     if (GameManager.instance.playerData.unlockedBossScenes.Contains(base.name))
    ///
    /// with no null check, so the first thing that asks whether a boss is unlocked throws.
    /// That's every Pantheon door (via BossSequence.GetSceneAt) and every statue.
    ///
    /// Filling the list also *is* the unlock: with every Godhome arena listed,
    /// IsUnlockedSelf returns true and nothing is gated behind progress a Silksong save
    /// can't have.
    /// </summary>
    internal static class GodhomeSave
    {
        private static bool _done;

        /// <summary>Safe to call repeatedly; only rebuilds when the save changes underneath.</summary>
        public static void EnsureUnlocks()
        {
            PlayerData pd = PlayerData.instance;
            if (pd == null) return;

            if (_done && pd.unlockedBossScenes != null && pd.unlockedBossScenes.Count > 0) return;

            try
            {
                if (pd.unlockedBossScenes == null) pd.unlockedBossScenes = new List<string>();

                var seen = new HashSet<string>(pd.unlockedBossScenes, StringComparer.Ordinal);
                int added = 0;

                // Every arena named by a Pantheon...
                foreach (KeyValuePair<string, string[]> seq in PantheonRegistry.Raw)
                {
                    foreach (string scene in seq.Value)
                    {
                        if (!string.IsNullOrEmpty(scene) && seen.Add(scene))
                        {
                            pd.unlockedBossScenes.Add(scene);
                            added++;
                        }
                    }
                }

                // ...plus anything we baked, which covers statue-only bosses that appear
                // in no sequence.
                foreach (string scene in Rebuild.GodhomeData.Available)
                {
                    if (seen.Add(scene))
                    {
                        pd.unlockedBossScenes.Add(scene);
                        added++;
                    }
                }

                _done = true;
                Plugin.Log.LogInfo(
                    $"Godhome: unlockedBossScenes ready ({pd.unlockedBossScenes.Count} entries, {added} added).");
            }
            catch (Exception e)
            {
                Plugin.Log.LogError("Godhome: couldn't prepare unlockedBossScenes: " + e);
            }
        }

        public static void Forget() => _done = false;
    }
}
