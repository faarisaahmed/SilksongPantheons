using System;
using System.Collections;
using System.Text;
using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// Reports which phase of a scene transition a load is stuck in.
    ///
    /// A hung transition looks identical to a crash from the outside - the game keeps
    /// running and the screen keeps showing the loading visual - but SceneLoad records
    /// begin/end times per phase (FetchBlocked, Fetch, ActivationBlocked, Activation,
    /// LoadBoss, ...). Polling those tells us exactly where it stopped instead of us
    /// guessing at it.
    /// </summary>
    internal static class LoadWatch
    {
        private static readonly SceneLoad.Phases[] AllPhases =
        {
            SceneLoad.Phases.FetchBlocked,
            SceneLoad.Phases.ClearMemPreFetch,
            SceneLoad.Phases.Fetch,
            SceneLoad.Phases.ActivationBlocked,
            SceneLoad.Phases.Activation,
            SceneLoad.Phases.ClearMemPostActivation,
            SceneLoad.Phases.GarbageCollect,
            SceneLoad.Phases.StartCall,
            SceneLoad.Phases.LoadBoss,
        };

        public static void Watch(MonoBehaviour runner, string label)
        {
            if (runner == null) return;
            runner.StartCoroutine(WatchRoutine(label));
        }

        private static IEnumerator WatchRoutine(string label)
        {
            float t = 0f;
            const float report = 3f;
            const float giveUp = 30f;
            float next = report;

            while (t < giveUp)
            {
                t += Time.unscaledDeltaTime;
                GameManager gm = GameManager.instance;

                if (gm == null) yield break;

                SceneLoad sl = gm.LastSceneLoad;
                if (sl != null && sl.IsFinished)
                {
                    Plugin.Log.LogInfo($"Godhome: load '{label}' finished after {t:F1}s.");
                    yield break;
                }

                if (t >= next)
                {
                    next += report;
                    Plugin.Log.LogWarning($"Godhome: load '{label}' still running at {t:F0}s - {Describe(sl, gm)}");
                }
                yield return null;
            }

            Plugin.Log.LogError(
                $"Godhome: load '{label}' has not finished after {giveUp:F0}s. " +
                Describe(GameManager.instance?.LastSceneLoad, GameManager.instance));
        }

        private static string Describe(SceneLoad sl, GameManager gm)
        {
            if (sl == null) return "no SceneLoad (the transition never started)";

            var sb = new StringBuilder();
            sb.Append("target=").Append(sl.TargetSceneName);
            sb.Append(" fetchAllowed=").Append(sl.IsFetchAllowed);
            sb.Append(" activationAllowed=").Append(sl.IsActivationAllowed);
            sb.Append(" waitForFade=").Append(sl.WaitForFade);
            sb.Append(" state=").Append(gm != null ? gm.GameState.ToString() : "?");
            sb.Append(" | phases:");

            foreach (SceneLoad.Phases p in AllPhases)
            {
                float? d = null;
                try { d = sl.GetDuration(p); } catch (Exception) { }
                if (d.HasValue) sb.Append(' ').Append(p).Append('=').Append(d.Value.ToString("F2"));
            }

            try
            {
                sb.Append(" | additiveBossPending=").Append(SceneAdditiveLoadConditional.ShouldLoadBoss);
            }
            catch (Exception) { }

            return sb.ToString();
        }
    }
}
