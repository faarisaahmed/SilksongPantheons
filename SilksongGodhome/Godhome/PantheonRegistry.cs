using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using HarmonyLib;
using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// The four Pantheons, as live ScriptableObjects.
    ///
    /// A Pantheon is a <see cref="BossSequence"/> holding an ordered array of
    /// <see cref="BossScene"/>. Silksong still has both classes and still has
    /// <c>BossSequenceController.SetupNewSequence</c>, so once the lists exist the game's
    /// own machinery drives the run: bindings, boss index, completion.
    ///
    /// The lists are plain text - `pantheons/pantheon1.txt` and friends, beside the DLL
    /// or embedded in it - in the format the Silksong boss-rush mods have settled on:
    ///
    ///     Bell Beast = Bone_05_boss : Bone Beast
    ///     Bench
    ///     # anything after a hash is a comment
    ///
    /// with a scene and an object name added to each line, because a Pantheon here loads
    /// Silksong's own room rather than rebuilding one. They are editable in place; no
    /// rebuild, no re-bake. tools/pantheons.py generates them.
    /// </summary>
    internal static class PantheonRegistry
    {
        /// <summary>Titles, in door order. Index 3 is the combined one.</summary>
        public static readonly string[] Titles =
        {
            "Pantheon of the Judge",
            "Pantheon of the Sinner",
            "Pantheon of the Void",
            "Pantheon of Pharloom",
        };

        /// <summary>One line of a Pantheon list.</summary>
        public sealed class Entry
        {
            public string DisplayName;
            /// <summary>The room to load, e.g. "Bone_05". Empty for a bench.</summary>
            public string Scene;

            /// <summary>
            /// An additive piece of that room holding the boss, e.g. "Bone_05_boss", or
            /// empty. Silksong composes rooms from a main scene plus pieces, and a piece
            /// has no _SceneManager or terrain of its own - loading one directly is what
            /// put the player in a void at the Bell Beast.
            /// </summary>
            public string SubScene;
            /// <summary>The boss object inside it, e.g. "Bone Beast".</summary>
            public string BossObject;
            public bool IsBench;

            public override string ToString() =>
                IsBench ? "Bench"
                        : $"{DisplayName} = {Scene}" +
                          (string.IsNullOrEmpty(SubScene) ? "" : " + " + SubScene) +
                          $" : {BossObject}";
        }

        private static Dictionary<string, BossSequence> _sequences;
        private static Dictionary<string, string[]> _raw;
        private static Dictionary<string, List<Entry>> _entries;

        /// <summary>Sequence name -> ordered arena scene names.</summary>
        public static Dictionary<string, string[]> Raw
        {
            get { Load(); return _raw; }
        }

        /// <summary>Sequence name -> the full entries, including benches.</summary>
        public static Dictionary<string, List<Entry>> Entries
        {
            get { Load(); return _entries; }
        }

        public static bool IsLoaded => _raw != null && _raw.Count > 0;

        /// <summary>The entry a run is on, so the arena knows which boss to expect.</summary>
        public static Entry EntryAt(string sequenceName, int index)
        {
            Load();
            if (!_entries.TryGetValue(sequenceName ?? "", out List<Entry> list)) return null;
            return index >= 0 && index < list.Count ? list[index] : null;
        }

        private static void Load()
        {
            if (_raw != null) return;

            _raw = new Dictionary<string, string[]>(StringComparer.Ordinal);
            _entries = new Dictionary<string, List<Entry>>(StringComparer.Ordinal);
            _sequences = new Dictionary<string, BossSequence>(StringComparer.Ordinal);

            var files = new Dictionary<string, List<Entry>>(StringComparer.OrdinalIgnoreCase);
            for (int i = 1; i <= 4; i++)
            {
                List<Entry> parsed = ReadList("pantheon" + i, files);
                if (parsed == null) continue;
                files["pantheon" + i] = parsed;

                string title = i - 1 < Titles.Length ? Titles[i - 1] : "Pantheon " + i;
                _entries[title] = parsed;

                var scenes = new List<string>();
                foreach (Entry e in parsed)
                {
                    if (!e.IsBench && !string.IsNullOrEmpty(e.Scene)) scenes.Add(e.Scene);
                }
                _raw[title] = scenes.ToArray();
                Plugin.Log.LogInfo(
                    $"Godhome: {title} - {scenes.Count} bosses" +
                    (parsed.Count > scenes.Count ? $", {parsed.Count - scenes.Count} bench(es)" : ""));
            }

            if (_raw.Count == 0)
            {
                Plugin.Log.LogWarning(
                    "Godhome: no pantheon lists found. Expected pantheons/pantheon1.txt " +
                    "beside the DLL or embedded in it; run tools/pantheons.py.");
            }
        }

        /// <summary>
        /// Parses one list. `@include pantheonN` splices another in, which is how the
        /// fourth Pantheon is the first three back to back without repeating them.
        /// </summary>
        private static List<Entry> ReadList(string name,
                                            Dictionary<string, List<Entry>> already)
        {
            Stream s = Rebuild.GodhomeResources.Open("pantheons/" + name + ".txt")
                       ?? Rebuild.GodhomeResources.Open(name + ".txt");
            if (s == null) return null;

            var outp = new List<Entry>();
            try
            {
                using (s)
                using (var r = new StreamReader(s))
                {
                    string line;
                    while ((line = r.ReadLine()) != null)
                    {
                        line = line.Trim();
                        if (line.Length == 0 || line[0] == '#') continue;

                        if (line.StartsWith("@include ", StringComparison.OrdinalIgnoreCase))
                        {
                            string other = line.Substring("@include ".Length).Trim();
                            if (!already.TryGetValue(other, out List<Entry> sub))
                            {
                                sub = ReadList(other, already);
                                if (sub != null) already[other] = sub;
                            }
                            if (sub != null) outp.AddRange(sub);
                            else Plugin.Log.LogWarning($"Godhome: {name} includes missing '{other}'.");
                            continue;
                        }

                        if (string.Equals(line, "Bench", StringComparison.OrdinalIgnoreCase))
                        {
                            outp.Add(new Entry { DisplayName = "Bench", IsBench = true });
                            continue;
                        }

                        int eq = line.IndexOf('=');
                        if (eq < 0)
                        {
                            Plugin.Log.LogWarning($"Godhome: {name}: can't read '{line}'.");
                            continue;
                        }
                        string display = line.Substring(0, eq).Trim();
                        string rhs = line.Substring(eq + 1).Trim();
                        int colon = rhs.IndexOf(':');
                        string left = colon < 0 ? rhs : rhs.Substring(0, colon).Trim();
                        string obj = colon < 0 ? "" : rhs.Substring(colon + 1).Trim();

                        // "Room + Piece" when the boss lives in an additive piece.
                        string scene = left, piece = "";
                        int plus = left.IndexOf('+');
                        if (plus >= 0)
                        {
                            scene = left.Substring(0, plus).Trim();
                            piece = left.Substring(plus + 1).Trim();
                        }

                        outp.Add(new Entry
                        {
                            DisplayName = display,
                            Scene = scene,
                            SubScene = piece,
                            BossObject = obj,
                        });
                    }
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Godhome: {name}.txt is unreadable: {e}");
                return null;
            }
            return outp;
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
