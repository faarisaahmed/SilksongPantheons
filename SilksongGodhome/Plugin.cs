using System;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;

namespace SilksongGodhome
{
    /// <summary>
    /// Godhome for Silksong.
    ///
    /// Silksong is built on Hollow Knight's codebase and Team Cherry never stripped the
    /// Godmaster systems out of it: BossSceneController, BossSequenceController,
    /// BossStatue, BossSequenceDoor and the whole GG_* PlayMaker action set are all
    /// still live code. Even the menu entry exists - Menu_Title ships a third
    /// StartGameEventTrigger with bossRush = 1, sitting next to Normal and Steel Soul.
    ///
    /// Two things are missing, and they're what this mod supplies:
    ///
    ///   1. The entry is hidden. StartGameEventTrigger.IsFulfilled() hides any bossRush
    ///      button while the "RecBossRushMode" status record is 0, and nothing in the
    ///      shipped game ever sets it. See <see cref="ModeUnlock"/>.
    ///
    ///   2. PlayerData.AddGGPlayerDataOverrides() - the method that gives you the
    ///      Godseeker loadout - has an empty body, and none of the GG_* scenes ship in
    ///      Silksong's Addressables catalog. See <see cref="GodhomeLoadout"/> and
    ///      <see cref="Rebuild.SceneRebuilder"/>.
    /// </summary>
    [BepInPlugin(Guid, "Silksong Godhome", "0.1.0")]
    public class Plugin : BaseUnityPlugin
    {
        public const string Guid = "com.faaris.silksonggodhome";

        internal static ManualLogSource Log;
        internal static Plugin Instance;

        private Harmony _harmony;

        private void Awake()
        {
            Instance = this;
            Log = Logger;

            GodhomeConfig.Bind(Config);

            try
            {
                _harmony = new Harmony(Guid);
                _harmony.PatchAll(typeof(GodhomePatches));
                Log.LogInfo("Godhome: Harmony patches applied.");
            }
            catch (Exception e)
            {
                // A failed patch means no menu entry, but the game itself stays up and
                // the debug key can still force a warp in.
                Log.LogError("Godhome: Harmony patching failed: " + e);
            }

            // Runs coroutines and the debug overlay independently of the plugin object.
            var go = new GameObject("GodhomeManager");
            go.transform.SetParent(transform);
            go.AddComponent<GodhomeManager>();

            Log.LogInfo("Silksong Godhome loaded.");
        }

        private void OnDestroy()
        {
            _harmony?.UnpatchSelf();
        }
    }
}
