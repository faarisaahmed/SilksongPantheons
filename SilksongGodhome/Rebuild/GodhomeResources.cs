using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;

namespace SilksongGodhome.Rebuild
{
    /// <summary>
    /// Where Godhome's baked data comes from: a folder beside the DLL, or the DLL itself.
    ///
    /// Both work, and the folder wins. That is what lets the mod ship as a small plugin
    /// with no Hollow Knight content in it: you run the extractor against your own copy
    /// of the game, it writes a `Godhome` folder next to the plugin, and the plugin picks
    /// it up. Rebuilding the DLL - and so installing the .NET SDK and having the game's
    /// assemblies to hand - is only needed by people working on the mod itself.
    ///
    /// Names are the logical resource names the baker produces: "GG_Atrium.scene",
    /// "audio_GG3_part_A.adpcm", "boss_Giant_Fly.boss".
    /// </summary>
    internal static class GodhomeResources
    {
        private const string Prefix = "Godhome.";

        private static string _dir;
        private static bool _looked;

        /// <summary>The folder beside the DLL, or null if there isn't one.</summary>
        public static string Directory
        {
            get
            {
                if (_looked) return _dir;
                _looked = true;
                try
                {
                    string asm = Assembly.GetExecutingAssembly().Location;
                    if (string.IsNullOrEmpty(asm)) return _dir;
                    string beside = Path.Combine(Path.GetDirectoryName(asm), "Godhome");
                    if (System.IO.Directory.Exists(beside))
                    {
                        _dir = beside;
                        Plugin.Log.LogInfo($"Godhome: reading baked data from '{beside}'.");
                    }
                }
                catch (Exception e)
                {
                    Plugin.Log.LogWarning("Godhome: couldn't look for a data folder: " + e.Message);
                }
                return _dir;
            }
        }

        /// <summary>Opens one baked file, or null. Caller disposes.</summary>
        public static Stream Open(string logicalName)
        {
            string dir = Directory;
            if (dir != null)
            {
                string path = Path.Combine(dir, logicalName);
                if (File.Exists(path))
                {
                    try { return File.OpenRead(path); }
                    catch (Exception e)
                    {
                        Plugin.Log.LogWarning($"Godhome: couldn't read '{path}': {e.Message}");
                    }
                }
            }
            return Assembly.GetExecutingAssembly().GetManifestResourceStream(Prefix + logicalName);
        }

        /// <summary>Every baked file with the given extension, by logical name.</summary>
        public static IEnumerable<string> WithExtension(string extension)
        {
            var seen = new HashSet<string>(StringComparer.Ordinal);

            string dir = Directory;
            if (dir != null)
            {
                string[] files;
                try { files = System.IO.Directory.GetFiles(dir, "*" + extension); }
                catch (Exception) { files = new string[0]; }
                foreach (string f in files)
                {
                    string n = Path.GetFileName(f);
                    if (seen.Add(n)) yield return n;
                }
            }

            foreach (string res in Assembly.GetExecutingAssembly().GetManifestResourceNames())
            {
                if (!res.StartsWith(Prefix, StringComparison.Ordinal) ||
                    !res.EndsWith(extension, StringComparison.Ordinal))
                {
                    continue;
                }
                string n = res.Substring(Prefix.Length);
                if (seen.Add(n)) yield return n;
            }
        }
    }
}
