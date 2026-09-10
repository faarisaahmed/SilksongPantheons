using BepInEx.Configuration;
using UnityEngine;

namespace SilksongGodhome
{
    /// <summary>
    /// Config lives in BepInEx/config/com.faaris.silksonggodhome.cfg.
    /// </summary>
    internal static class GodhomeConfig
    {
        public static ConfigEntry<string> ModeName;
        public static ConfigEntry<string> ModeDescription;
        public static ConfigEntry<bool> RelabelMenuEntry;
        public static ConfigEntry<KeyCode> WarpKey;
        public static ConfigEntry<KeyCode> SkipBossKey;
        public static ConfigEntry<KeyCode> SpawnBossKey;
        public static ConfigEntry<string> SpawnBossName;
        public static ConfigEntry<bool> VerboseRebuildLogging;
        public static ConfigEntry<bool> TraceBossStates;
        public static ConfigEntry<string> DonorScene;

        public static void Bind(ConfigFile cfg)
        {
            ModeName = cfg.Bind(
                "Menu", "ModeName", "GODSEEKER",
                "Title shown on the Godhome entry in the play-mode menu.");

            ModeDescription = cfg.Bind(
                "Menu", "ModeDescription", "Enter the Pantheons.",
                "Subtitle shown under the mode name.");

            RelabelMenuEntry = cfg.Bind(
                "Menu", "RelabelMenuEntry", true,
                "Silksong's own boss-rush button ships with no localised label, so it " +
                "would otherwise appear blank. Turn this off to see it untouched.");

            WarpKey = cfg.Bind(
                "Debug", "WarpKey", KeyCode.F10,
                "Rebuilds and warps straight to GG_Atrium from wherever you are, " +
                "without going through the menu.");

            DonorScene = cfg.Bind(
                "Rebuild", "DonorScene", "Bone_05,Bone_03",
                "Silksong ships no GG_* scenes, so Godhome is built inside a real room " +
                "that acts as a shell (see SceneRedirect). This must be a *standalone " +
                "gameplay room*, not one of the additive sub-scenes: GameManager needs " +
                "the _SceneManager and TileMap objects that only a full room contains. " +
                "Bone_05 is one of the smallest that qualifies. Names like " +
                "'Bone_05_bellway' are additive chunks and will black-screen.\n" +
                "Give at least two, comma-separated: moving between two Godhome rooms " +
                "would otherwise ask the game to load the scene it is already standing " +
                "in, which deadlocks the transition.");

            TraceBossStates = cfg.Bind(
                "Debug", "TraceBossStates", true,
                "Logs every state change in a spawned boss's FSMs. This is the fastest " +
                "way to tell a boss that is misbehaving from one that is simply sitting " +
                "in a state waiting for an event the arena never sends.");

            SkipBossKey = cfg.Bind(
                "Debug", "SkipBossKey", KeyCode.F8,
                "During a Pantheon run, skips the current arena and moves to the next. " +
                "A run now advances by itself when the room's own BossSceneController " +
                "reports the fight won, so this is for reaching a specific arena.");

            SpawnBossKey = cfg.Bind(
                "Debug", "SpawnBossKey", KeyCode.F6,
                "Spawns the baked boss named below in front of Hornet. Stage one: the " +
                "boss appears and animates. Its FSM behaviour isn't wired up yet, so it " +
                "won't fight back.");

            SpawnBossName = cfg.Bind(
                "Debug", "SpawnBossName", "Giant Fly",
                "Which baked boss SpawnBossKey spawns. 'Giant Fly' is Gruz Mother - the " +
                "name is Hollow Knight's internal one. Bake more with tools/bossbake.py.");

            VerboseRebuildLogging = cfg.Bind(
                "Debug", "VerboseRebuildLogging", false,
                "Logs every GameObject the scene rebuilder creates. Very noisy.");
        }
    }
}
