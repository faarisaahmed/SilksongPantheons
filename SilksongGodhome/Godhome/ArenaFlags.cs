using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using GenericVariableExtension;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// The save flags an arena needs before it will compose itself correctly.
    ///
    /// A Silksong room decides its own contents by testing the player's save. Bone_05
    /// loads Bone_05_boss while `defeatedBellBeast` is false and the bellway station
    /// once it is true; inside the boss piece, `seenBellBeast` separates the first
    /// meeting - with its cutscene - from a rematch.
    ///
    /// A Godseeker save has none of these set, which was right by luck for some arenas
    /// and wrong for others. Rather than force-loading pieces and skipping cutscenes by
    /// hand, the conditions are read out of each room by tools/arenaflags.py and set
    /// here, so the game builds the arena the way it already knows how.
    ///
    /// Every `seen...` flag is set true, which is what makes a Pantheon fight always a
    /// rematch rather than an introduction.
    /// </summary>
    internal static class ArenaFlags
    {
        private static Dictionary<string, List<KeyValuePair<string, bool>>> _flags;

        private static void Load()
        {
            if (_flags != null) return;
            _flags = new Dictionary<string, List<KeyValuePair<string, bool>>>(
                StringComparer.OrdinalIgnoreCase);

            Stream s = Rebuild.GodhomeResources.Open("pantheons/flags.txt");
            if (s == null)
            {
                Plugin.Log.LogInfo("Godhome: no arena flags file; arenas load as the save says.");
                return;
            }

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
                        int colon = line.IndexOf(':');
                        if (colon < 0) continue;

                        string scene = line.Substring(0, colon).Trim();
                        var list = new List<KeyValuePair<string, bool>>();
                        foreach (string part in line.Substring(colon + 1).Split(','))
                        {
                            string[] kv = part.Split('=');
                            if (kv.Length != 2) continue;
                            string field = kv[0].Trim();
                            bool value = kv[1].Trim().Equals("true", StringComparison.OrdinalIgnoreCase);
                            if (field.Length > 0) list.Add(new KeyValuePair<string, bool>(field, value));
                        }
                        if (list.Count > 0) _flags[scene] = list;
                    }
                }
                Plugin.Log.LogInfo($"Godhome: arena flags for {_flags.Count} scene(s).");
            }
            catch (Exception e)
            {
                Plugin.Log.LogError("Godhome: flags.txt is unreadable: " + e);
            }
        }

        /// <summary>Applies the flags for a room and, if it has one, its boss piece.</summary>
        public static void Apply(PantheonRegistry.Entry entry)
        {
            if (entry == null) return;
            Load();

            ApplyFor(entry.Scene);
            if (!string.IsNullOrEmpty(entry.SubScene)) ApplyFor(entry.SubScene);
        }

        private static void ApplyFor(string scene)
        {
            if (string.IsNullOrEmpty(scene)) return;
            if (!_flags.TryGetValue(scene, out List<KeyValuePair<string, bool>> list)) return;

            PlayerData pd = PlayerData.instance;
            if (pd == null) return;

            var set = new List<string>();
            foreach (KeyValuePair<string, bool> f in list)
            {
                try
                {
                    pd.SetVariable(f.Key, f.Value);
                    set.Add($"{f.Key}={(f.Value ? "true" : "false")}");
                }
                catch (Exception e)
                {
                    Plugin.Log.LogWarning($"Godhome: couldn't set '{f.Key}': {e.Message}");
                }
            }
            if (set.Count > 0)
            {
                Plugin.Log.LogInfo($"Godhome: {scene} - set {string.Join(", ", set)}.");
            }
        }
    }
}
