using System.Collections.Generic;
using System.Text;
using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// Logs every state change in a spawned boss's FSMs.
    ///
    /// Worth its weight because the alternative is guesswork. "False Knight is stuck at
    /// the top" and "Moss Charger doesn't wake up" were the same bug - both FSMs sitting
    /// in a state whose only exit was an event that needed a BossSceneController - but
    /// telling that from the outside took reading both graphs out of Hollow Knight and
    /// decoding their action parameters. A line saying
    ///
    ///     Godhome trace: FalseyControl  Init -> Dormant
    ///
    /// followed by silence says it immediately.
    ///
    /// Cheap: one string compare per FSM per frame, and it only logs on change.
    /// </summary>
    internal class BossTrace : MonoBehaviour
    {
        private PlayMakerFSM[] _fsms;
        private string[] _last;
        private string _who;

        private void Start()
        {
            _who = name.StartsWith("Godhome_") ? name.Substring("Godhome_".Length) : name;
            // Children too: a multi-part boss keeps its arms and head on their own FSMs.
            _fsms = GetComponentsInChildren<PlayMakerFSM>(includeInactive: true);
            _last = new string[_fsms.Length];
            for (int i = 0; i < _fsms.Length; i++) _last[i] = null;
        }

        private void Update()
        {
            if (_fsms == null) return;
            for (int i = 0; i < _fsms.Length; i++)
            {
                PlayMakerFSM f = _fsms[i];
                if (f == null) continue;
                string s;
                try { s = f.ActiveStateName; }
                catch (System.Exception) { continue; }
                if (s == _last[i]) continue;

                string from = _last[i] ?? "(start)";
                _last[i] = s;
                Plugin.Log.LogInfo($"Godhome trace: {_who}/{f.FsmName}  {from} -> {s}");
            }
        }

        /// <summary>A one-shot snapshot of every FSM's current state, for a debug key.</summary>
        public static string Snapshot()
        {
            var sb = new StringBuilder();
            foreach (BossTrace t in Object.FindObjectsByType<BossTrace>(FindObjectsSortMode.None))
            {
                if (t == null || t._fsms == null) continue;
                sb.Append(t._who).Append(": ");
                var parts = new List<string>();
                foreach (PlayMakerFSM f in t._fsms)
                {
                    if (f == null) continue;
                    string s;
                    try { s = f.ActiveStateName; }
                    catch (System.Exception) { s = "?"; }
                    parts.Add(f.FsmName + "=" + s);
                }
                sb.Append(string.Join(", ", parts.ToArray())).Append('\n');
            }
            return sb.Length > 0 ? sb.ToString() : "no bosses spawned";
        }
    }
}
