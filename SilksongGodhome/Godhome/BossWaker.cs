using System.Collections;
using System.Text;
using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// Walks a spawned boss through Hollow Knight's own wake chain.
    ///
    /// Gruz Mother's Big Fly Control starts in Init, which runs GGCheckIfBossScene:
    ///
    ///     GG BOSS  -> GG Boss Wake -> Wake -> Fly     (in a Godhome arena)
    ///     FINISHED -> Invincible                      (everywhere else)
    ///
    /// and from Invincible the normal-game route is
    /// `HERO ENTER -> Sleep -> TAKE DAMAGE -> Wake Sound -> Wake -> Fly`, where HERO ENTER
    /// comes from the arena's Battle Range trigger and TAKE DAMAGE from actually hitting
    /// her. A boss dropped in by the debug key has neither, so it would sit in Invincible
    /// forever.
    ///
    /// Rather than fake a BossSceneController - whose Awake pulls on sequence loading -
    /// this sends the same events the arena would, in the same order, and stops as soon
    /// as the FSM leaves its idle states. Nothing here overrides the boss's own logic;
    /// it only supplies the inputs the surrounding scene normally would.
    /// </summary>
    internal class BossWaker : MonoBehaviour
    {
        /// <summary>States that mean "not started yet".</summary>
        private static readonly string[] Idle = { "Init", "Invincible", "Sleep", "Dormant", "Inert" };

        private void Start() => StartCoroutine(Wake());

        private IEnumerator Wake()
        {
            // Let PlayMakerFSM.Start run, so Init has actually executed.
            yield return null;
            yield return null;

            PlayMakerFSM[] fsms = GetComponents<PlayMakerFSM>();
            if (fsms.Length == 0) yield break;

            string[] chain = { "GG BOSS", "HERO ENTER", "TAKE DAMAGE" };

            foreach (string ev in chain)
            {
                if (!AnyIdle(fsms))
                {
                    Plugin.Log.LogInfo($"Godhome: '{name}' woke - {StateSummary(fsms)}");
                    yield break;
                }

                foreach (PlayMakerFSM f in fsms)
                {
                    try { f.SendEvent(ev); }
                    catch (System.Exception) { /* an FSM that doesn't know the event is fine */ }
                }
                yield return null;
                yield return null;
            }

            Plugin.Log.LogInfo($"Godhome: '{name}' after wake chain - {StateSummary(fsms)}");
        }

        private static bool AnyIdle(PlayMakerFSM[] fsms)
        {
            foreach (PlayMakerFSM f in fsms)
            {
                string s = SafeState(f);
                foreach (string idle in Idle)
                {
                    if (s == idle) return true;
                }
            }
            return false;
        }

        private static string SafeState(PlayMakerFSM f)
        {
            try { return f.ActiveStateName; }
            catch (System.Exception) { return "?"; }
        }

        private static string StateSummary(PlayMakerFSM[] fsms)
        {
            var sb = new StringBuilder();
            foreach (PlayMakerFSM f in fsms)
            {
                if (sb.Length > 0) sb.Append(", ");
                sb.Append(f.FsmName).Append('=').Append(SafeState(f));
            }
            return sb.ToString();
        }
    }
}
