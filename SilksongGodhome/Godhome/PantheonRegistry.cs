using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using HarmonyLib;
using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// Recreates Hollow Knight's Pantheon lists as live ScriptableObjects.
    ///
    /// A Pantheon is a <see cref="BossSequence"/> asset holding an ordered array of
    /// <see cref="BossScene"/> assets. Silksong still has both classes and, crucially,
    /// still has <c>BossSequenceController.SetupNewSequence</c> - so once the lists exist
    /// the game's own sequence machinery drives the run: bindings, boss index, completion.
    ///
    /// The lists themselves are baked from Hollow Knight's resources.assets by
    /// tools/sequences.py; see Baked/sequences.bin.
    /// </summary>
    internal static class PantheonRegistry
    {
        private const string Resource = "Godhome.sequences.bin";
        private const string Magic = "GGSQ";
        private const int Version = 1;

        private static Dictionary<string, BossSequence> _sequences;
        private static Dictionary<string, string[]> _raw;

        /// <summary>Sequence name -> ordered arena scene names.</summary>
        public static Dictionary<string, string[]> Raw
        {
            get { Load(); return _raw; }
        }

        public static bool IsLoaded => _raw != null && _raw.Count > 0;

        private static void Load()
        {
            if (_raw != null) return;

            _raw = new Dictionary<string, string[]>(StringComparer.Ordinal);
            _sequences = new Dictionary<string, BossSequence>(StringComparer.Ordinal);

            Stream s = Rebuild.GodhomeResources.Open(Resource.StartsWith("Godhome.")
                ? Resource.Substring("Godhome.".Length) : Resource);
            if (s == null)
            {
                Plugin.Log.LogWarning(
                    "Godhome: no sequences.bin embedded - the Pantheons will be unavailable. " +
                    "Run tools/extract_godhome.py and rebuild.");
                return;
            }

            try
            {
                using (s)
                using (var r = new BinaryReader(s))
                {
                    var magic = new string(r.ReadChars(4));
                    if (magic != Magic) throw new InvalidDataException($"bad magic '{magic}'");
                    int version = r.ReadInt32();
                    if (version != Version) throw new InvalidDataException($"version {version}, expected {Version}");

                    int count = r.ReadInt32();
                    for (int i = 0; i < count; i++)
                    {
                        string name = r.ReadString();
                        var scenes = new string[r.ReadInt32()];
                        for (int j = 0; j < scenes.Length; j++) scenes[j] = r.ReadString();
                        _raw[name] = scenes;
                    }
                }

                Plugin.Log.LogInfo($"Godhome: {_raw.Count} pantheons loaded.");
            }
            catch (Exception e)
            {
                Plugin.Log.LogError("Godhome: sequences.bin is unreadable: " + e);
            }
        }

        /// <summary>
        /// The live BossSequence for a Pantheon, built on first use.
        ///
        /// BossSequence.bossScenes is private [SerializeField], so it's set by reflection -
        /// the same thing Unity's deserialiser would do when loading the asset.
        /// </summary>
        public static BossSequence Get(string sequenceName)
        {
            Load();

            // BossScene.IsUnlockedSelf dereferences playerData.unlockedBossScenes without
            // a null check, and a fresh Godseeker save leaves it null.
            GodhomeSave.EnsureUnlocks();
            if (string.IsNullOrEmpty(sequenceName)) return null;
            if (_sequences.TryGetValue(sequenceName, out BossSequence cached) && cached != null) return cached;
            if (!_raw.TryGetValue(sequenceName, out string[] scenes)) return null;

            try
            {
                var seq = ScriptableObject.CreateInstance<BossSequence>();
                seq.name = sequenceName;

                // Hollow Knight gates each arena behind its own unlock flags, which don't
                // exist in a Silksong save. Turning scene unlocks off makes IsUnlocked()
                // true and lets every Pantheon be entered.
                seq.useSceneUnlocks = false;
                seq.tests = new BossScene.BossTest[0];

                var arenas = new BossScene[scenes.Length];
                for (int i = 0; i < scenes.Length; i++)
                {
                    var bs = ScriptableObject.CreateInstance<BossScene>();
                    bs.name = scenes[i];
                    bs.sceneName = scenes[i];
                    bs.isHidden = false;
                    bs.requireUnlock = false;
                    ComponentInitSafe(bs);
                    arenas[i] = bs;
                }

                FieldInfo f = AccessTools.Field(typeof(BossSequence), "bossScenes");
                if (f == null)
                {
                    Plugin.Log.LogError("Godhome: BossSequence.bossScenes not found; can't build a pantheon.");
                    return null;
                }
                f.SetValue(seq, arenas);

                _sequences[sequenceName] = seq;
                Plugin.Log.LogInfo($"Godhome: built '{sequenceName}' ({arenas.Length} bosses).");
                return seq;
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Godhome: couldn't build pantheon '{sequenceName}': {e}");
                return null;
            }
        }

        /// <summary>
        /// ScriptableObject.CreateInstance leaves [Serializable] arrays null exactly like
        /// AddComponent does, and BossScene.IsUnlocked walks bossTests without checking.
        /// </summary>
        private static void ComponentInitSafe(BossScene bs)
        {
            if (bs.bossTests == null) bs.bossTests = new BossScene.BossTest[0];
        }
    }
}
