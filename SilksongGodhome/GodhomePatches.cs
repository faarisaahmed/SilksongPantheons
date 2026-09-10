using System;
using System.Reflection;
using HarmonyLib;
using SilksongGodhome.Rebuild;

namespace SilksongGodhome
{
    /// <summary>
    /// Every hook into the base game lives here, so there's one place to look when a
    /// Silksong patch renames something.
    /// </summary>
    [HarmonyPatch]
    internal static class GodhomePatches
    {
        /// <summary>
        /// StartGameEventTrigger.bossRush is private and we build against the stock
        /// assembly, so identifying the Godhome menu entry goes through reflection.
        /// </summary>
        private static readonly FieldInfo BossRushField =
            AccessTools.Field(typeof(StartGameEventTrigger), "bossRush");

        public static bool IsBossRushTrigger(StartGameEventTrigger t)
        {
            if (t == null || BossRushField == null) return false;
            try { return (bool)BossRushField.GetValue(t); }
            catch { return false; }
        }

        // ------------------------------------------------------------------
        // 1. Reveal the menu entry.
        // ------------------------------------------------------------------

        /// <summary>
        /// SetupStatusModifiers is where the game applies its own unlock flags during
        /// boot (it's the method that would set RecBossRushMode if the shipped
        /// gameConfig.unlockBossRushMode were true). Hooking it means the record is in
        /// place before any menu screen evaluates its button conditions.
        /// </summary>
        [HarmonyPostfix]
        [HarmonyPatch(typeof(GameManager), "SetupStatusModifiers")]
        private static void GameManager_SetupStatusModifiers_Postfix(GameManager __instance)
        {
            ModeUnlock.Unlock(__instance);

            // Idempotent (AddRespawnPoint checks Contains first). Doing it here as well
            // as in the loadout covers continuing an existing Godseeker save and the
            // debug warp, not just starting a new one.
            GodhomeLoadout.RegisterHubWithTeleportMap();
        }

        // ------------------------------------------------------------------
        // 2. Give the mode a save state.
        // ------------------------------------------------------------------

        /// <summary>
        /// The shipped AddGGPlayerDataOverrides has an empty body. A postfix is enough:
        /// there's nothing there to run first, and running after leaves the door open
        /// should a future patch restore some of it.
        /// </summary>
        [HarmonyPostfix]
        [HarmonyPatch(typeof(PlayerData), nameof(PlayerData.AddGGPlayerDataOverrides))]
        private static void PlayerData_AddGGPlayerDataOverrides_Postfix(PlayerData __instance)
        {
            GodhomeLoadout.Apply(__instance);
        }

        // ------------------------------------------------------------------
        // 3. Let a Godhome save load back into Godhome.
        // ------------------------------------------------------------------

        /// <summary>
        /// GetRespawnInfo doesn't trust playerData.respawnScene - it validates the scene
        /// and marker against SceneTeleportMap and, on a miss, silently rewrites them to
        /// Tut_01. We register the hub at boot, but a save made at Godhome's bench points
        /// at that bench's own marker, which only exists once the scene has been rebuilt.
        /// On a cold launch that lookup fails and the player lands in the tutorial.
        ///
        /// So: if the save points at a Godhome scene we actually have baked, put the
        /// saved values back. Everything else is left to the game.
        /// </summary>
        [HarmonyPostfix]
        [HarmonyPatch(typeof(GameManager), "GetRespawnInfo")]
        private static void GameManager_GetRespawnInfo_Postfix(
            GameManager __instance, ref string scene, ref string marker)
        {
            try
            {
                PlayerData pd = __instance.playerData;
                if (pd == null) return;

                string saved = !string.IsNullOrEmpty(pd.tempRespawnScene)
                    ? pd.tempRespawnScene
                    : pd.respawnScene;
                if (!SceneRedirect.IsGodhomeScene(saved)) return;
                if (!GodhomeData.HasScene(saved)) return;
                if (scene == saved) return;   // the map already accepted it

                string savedMarker = !string.IsNullOrEmpty(pd.tempRespawnScene)
                    ? pd.tempRespawnMarker
                    : pd.respawnMarkerName;

                Plugin.Log.LogInfo(
                    $"Godhome: restoring respawn to '{saved}' / '{savedMarker}' " +
                    $"(the teleport map had sent us to '{scene}').");

                scene = saved;
                if (!string.IsNullOrEmpty(savedMarker)) marker = savedMarker;
            }
            catch (Exception e)
            {
                Plugin.Log.LogError("Godhome: couldn't restore the Godhome respawn point: " + e);
            }
        }

        // ------------------------------------------------------------------
        // 4. Show Godhome saves as Godhome on the save-select screen.
        // ------------------------------------------------------------------

        /// <summary>
        /// PresentSaveSlot is where a slot's art and label are decided. Running after it
        /// means we don't have to reproduce any of that logic - only override the two
        /// pieces that should differ for a Godseeker save.
        /// </summary>
        [HarmonyPostfix]
        [HarmonyPatch(typeof(UnityEngine.UI.SaveSlotButton), "PresentSaveSlot")]
        private static void SaveSlotButton_PresentSaveSlot_Postfix(
            UnityEngine.UI.SaveSlotButton __instance, SaveStats currentSaveStats)
        {
            Godhome.GodhomeSaveSlot.Apply(__instance, currentSaveStats);
        }

        // ------------------------------------------------------------------
        // 5. Serve the GG_* scenes, which Silksong doesn't ship.
        // ------------------------------------------------------------------

        /// <summary>
        /// Godhome's scene names are still hard-coded all through the game
        /// (Constants.GG_ENTRANCE_SCENE, GG_RETURN_SCENE, every BossStatue's target),
        /// but none of them exist in Silksong's Addressables catalog, so the load would
        /// fail outright.
        ///
        /// Rather than register a custom Addressables provider - scene providers are
        /// awkward to fake, and SceneLoad wants a real AsyncOperationHandle it can
        /// activate and later unload - we let the load run against a real, cheap donor
        /// scene and then replace its contents once it's live. The engine's transition,
        /// camera and hero-placement machinery all behave normally because from its
        /// point of view an ordinary scene loaded; we just own what's inside it.
        ///
        /// <see cref="SceneRedirect"/> records the logical Godhome name so the rebuilder
        /// knows what to construct when the donor comes up.
        ///
        /// BeginSceneTransition is the single funnel every scene change goes through -
        /// a better hook than SceneLoad's constructors, of which there are two.
        /// </summary>
        [HarmonyPrefix]
        [HarmonyPatch(typeof(GameManager), nameof(GameManager.BeginSceneTransition))]
        private static bool GameManager_BeginSceneTransition_Prefix(GameManager.SceneLoadInfo info)
        {
            // Returning false cancels the transition - used when we're already in Godhome
            // and can swap the room in place instead.
            return SceneRedirect.Intercept(info);
        }
    }
}
