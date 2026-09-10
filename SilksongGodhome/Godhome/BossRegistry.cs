using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// Which bosses belong to which arena.
    ///
    /// Each baked boss records the Hollow Knight scene it came from, so rebuilding
    /// GG_Gruz_Mother can put Gruz Mother back where she was rather than waiting for a
    /// debug key. Only the header of each file is read to build the index - the sprite,
    /// animation and FSM payload is left alone until something actually spawns.
    /// </summary>
    internal static class BossRegistry
    {
        private const string Prefix = "Godhome.";
        private const string Suffix = ".boss";
        private const string Magic = "GGBS";

        private static Dictionary<string, List<string>> _byScene;

        /// <summary>Boss names baked from <paramref name="sceneName"/>.</summary>
        public static IList<string> ForScene(string sceneName)
        {
            Build();
            return _byScene.TryGetValue(sceneName, out List<string> l) ? l : (IList<string>)new string[0];
        }

        public static int Count
        {
            get { Build(); int n = 0; foreach (var kv in _byScene) n += kv.Value.Count; return n; }
        }

        private static void Build()
        {
            if (_byScene != null) return;
            _byScene = new Dictionary<string, List<string>>(StringComparer.Ordinal);

            foreach (string res in Rebuild.GodhomeResources.WithExtension(Suffix))
            {
                try
                {
                    using (Stream s = Rebuild.GodhomeResources.Open(res))
                    using (var r = new BinaryReader(s))
                    {
                        if (new string(r.ReadChars(4)) != Magic) continue;
                        r.ReadInt32();                        // version
                        string boss = r.ReadString();
                        string scene = r.ReadString();
                        if (string.IsNullOrEmpty(scene)) continue;

                        if (!_byScene.TryGetValue(scene, out List<string> list))
                        {
                            list = new List<string>();
                            _byScene[scene] = list;
                        }
                        list.Add(boss);
                    }
                }
                catch (Exception e)
                {
                    Plugin.Log.LogWarning($"Godhome: couldn't index '{res}': {e.Message}");
                }
            }

            int total = 0;
            foreach (var kv in _byScene) total += kv.Value.Count;
            Plugin.Log.LogInfo($"Godhome: {total} baked boss(es) across {_byScene.Count} arena(s).");
        }
    }
}
