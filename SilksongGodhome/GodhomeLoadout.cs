using System;
using UnityEngine;

namespace SilksongGodhome
{
    /// <summary>
    /// Fills in PlayerData.AddGGPlayerDataOverrides(), which Team Cherry left as an
    /// empty method body.
    ///
    /// GameManager.StartNewGame is what calls it, and the surrounding code still works:
    ///
    ///     playerData = PlayerData.CreateNewSingleton(addEditorOverrides: false);
    ///     playerData.permadeathMode = ...;
    ///     if (bossRushMode) { playerData.AddGGPlayerDataOverrides(); StartCoroutine(RunContinueGame()); }
    ///     else              { StartCoroutine(RunStartNewGame()); }
    ///
    /// Note the asymmetry: boss-rush runs RunContinueGame, not RunStartNewGame. It
    /// deliberately skips the opening sequence and loads straight from the save's
    /// respawn point instead - which is precisely why this method has to set both the
    /// loadout and the respawn scene. On a fresh PlayerData with an empty override,
    /// you'd currently be dumped at the game's normal start with nothing.
    ///
    /// The field names below are taken from the decompiled PlayerData, not guessed.
    /// </summary>
    internal static class GodhomeLoadout
    {
        /// <summary>Where a Godseeker-mode save wakes up.</summary>
        public const string HubScene = "GG_Atrium";

        /// <summary>
        /// Spawn point inside the hub.
        ///
        /// This is Hollow Knight's own marker name, not one we invented: GG_Atrium
        /// contains a RespawnMarker on a GameObject called "Death Respawn Marker" at
        /// (14.69, 35.11), and the rebuild preserves object names - so
        /// HeroController.LocateSpawnPoint(), which matches on the GameObject name,
        /// finds it with nothing extra to do.
        /// </summary>
        public const string HubSpawnMarker = "Death Respawn Marker";

        public static void Apply(PlayerData pd)
        {
            if (pd == null)
            {
                Plugin.Log.LogWarning("Godhome: AddGGPlayerDataOverrides called with no PlayerData.");
                return;
            }

            try
            {
                ApplyModeFlags(pd);
                ApplyLoadout(pd);
                ApplyRespawn(pd);
                RegisterHubWithTeleportMap();
                Godhome.GodhomeSave.EnsureUnlocks();
                Plugin.Log.LogInfo("Godhome: Godseeker overrides applied to a new save.");
            }
            catch (Exception e)
            {
                // Better to drop the player into an under-equipped Godhome than to throw
                // inside GameManager.StartNewGame and hang the load.
                Plugin.Log.LogError("Godhome: failed to apply Godseeker overrides: " + e);
            }
        }

        private static void ApplyModeFlags(PlayerData pd)
        {
            // bossRushMode is what every GGCheckIsBossRushMode PlayMaker action reads
            // ("GameManager.instance.playerData.bossRushMode") to decide it's in Godhome
            // rather than in the normal game.
            pd.SetBool(nameof(PlayerData.bossRushMode), true);

            // Godhome is not the opening of the game; leaving this on makes the intro
            // machinery (tutorial prompts, first-game camera work) fire in the hub.
            pd.SetBool(nameof(PlayerData.isFirstGame), false);
        }

        /// <summary>
        /// The Godseeker kit: Hornet fully equipped, because Godhome is a combat mode
        /// and nothing in it hands out abilities.
        /// </summary>
        private static void ApplyLoadout(PlayerData pd)
        {
            // --- Health and silk ---
            // maxHealthBase is the real stat; maxHealth is derived from it and gets
            // recomputed by HeroController.CharmUpdate, so writing maxHealth directly
            // would just be overwritten.
            pd.SetInt(nameof(PlayerData.maxHealthBase), 11);
            pd.SetInt(nameof(PlayerData.health), 11);
            pd.SetInt(nameof(PlayerData.silkMax), 9);
            pd.SetInt(nameof(PlayerData.silk), 9);

            // --- Needle ---
            pd.SetInt(nameof(PlayerData.nailUpgrades), 4);
            pd.SetInt(nameof(PlayerData.silkSpecialLevel), 3);

            // --- Tool capacity ---
            // Pouch is how many tools you can carry, Kit is tool damage tier. Without
            // these, unlocking every tool leaves you nowhere to put them.
            pd.SetInt(nameof(PlayerData.ToolPouchUpgrades), 4);
            pd.SetInt(nameof(PlayerData.ToolKitUpgrades), 4);
            pd.SetBool(nameof(PlayerData.UnlockedExtraBlueSlot), true);
            pd.SetBool(nameof(PlayerData.UnlockedExtraYellowSlot), true);

            // --- Traversal ---
            pd.SetBool(nameof(PlayerData.hasDash), true);
            pd.SetBool(nameof(PlayerData.hasBrolly), true);
            pd.SetBool(nameof(PlayerData.hasWalljump), true);
            pd.SetBool(nameof(PlayerData.hasDoubleJump), true);
            pd.SetBool(nameof(PlayerData.hasSuperJump), true);
            pd.SetBool(nameof(PlayerData.hasHarpoonDash), true);

            // --- Combat ---
            pd.SetBool(nameof(PlayerData.hasNeedleThrow), true);
            pd.SetBool(nameof(PlayerData.hasThreadSphere), true);
            pd.SetBool(nameof(PlayerData.hasParry), true);
            pd.SetBool(nameof(PlayerData.hasSilkCharge), true);
            pd.SetBool(nameof(PlayerData.hasSilkBomb), true);
            pd.SetBool(nameof(PlayerData.hasSilkBossNeedle), true);
            pd.SetBool(nameof(PlayerData.hasSilkSpecial), true);
            pd.SetBool(nameof(PlayerData.hasChargeSlash), true);
            pd.SetBool(nameof(PlayerData.hasQuill), true);
            pd.SetBool(nameof(PlayerData.hasNeedolin), true);
        }

        /// <summary>
        /// RunContinueGame loads whatever respawnScene says, so this is what actually
        /// puts you in Godhome instead of at the start of the game.
        /// </summary>
        private static void ApplyRespawn(PlayerData pd)
        {
            pd.respawnScene = HubScene;
            pd.respawnMarkerName = HubSpawnMarker;
            pd.respawnType = 0;

            // Cleared so the "died somewhere else" recovery path can't drag the player
            // back out of Godhome on the first load.
            pd.tempRespawnScene = null;
            pd.nonLethalRespawnScene = null;
        }

        /// <summary>
        /// Without this the mode silently does nothing.
        ///
        /// GameManager.GetRespawnInfo doesn't trust playerData.respawnScene - it
        /// validates it against SceneTeleportMap, and on a miss falls back to:
        ///
        ///     scene = "Tut_01"; marker = "Death Respawn Marker Init";
        ///
        /// GG_Atrium isn't in Silksong's teleport map, so a fresh Godseeker save would
        /// be quietly redirected to the tutorial. SceneTeleportMap exposes a public
        /// AddRespawnPoint, and its internal GetSceneInfo creates missing entries, so
        /// registering the hub is enough to make the lookup succeed.
        /// </summary>
        public static void RegisterHubWithTeleportMap()
        {
            try
            {
                SceneTeleportMap.AddRespawnPoint(HubScene, HubSpawnMarker);
                Plugin.Log.LogInfo($"Godhome: registered '{HubSpawnMarker}' in {HubScene} with the teleport map.");
            }
            catch (Exception e)
            {
                Plugin.Log.LogError(
                    "Godhome: couldn't register the hub with SceneTeleportMap - a new " +
                    "Godseeker save will fall back to Tut_01. " + e);
            }
        }
    }
}
