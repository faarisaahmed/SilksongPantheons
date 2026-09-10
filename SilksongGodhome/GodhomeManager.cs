using System;
using System.Collections;
using SilksongGodhome.Rebuild;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace SilksongGodhome
{
    /// <summary>
    /// Drives the per-frame and per-scene work: relabelling the menu entry, and
    /// rebuilding Godhome once the donor scene is live.
    /// </summary>
    internal class GodhomeManager : MonoBehaviour
    {
        /// <summary>Used to run coroutines from static rebuild code.</summary>
        public static GodhomeManager Instance { get; private set; }

        private void Awake() => Instance = this;

        private void OnEnable()
        {
            SceneManager.activeSceneChanged += OnActiveSceneChanged;
        }

        private void OnDisable()
        {
            SceneManager.activeSceneChanged -= OnActiveSceneChanged;
        }

        private void Update()
        {
            ModeUnlock.TryRelabel();

            if (Input.GetKeyDown(GodhomeConfig.WarpKey.Value)) WarpToHub();

            if (Input.GetKeyDown(GodhomeConfig.SkipBossKey.Value)) Godhome.PantheonRun.Skip();

            if (Input.GetKeyDown(GodhomeConfig.SpawnBossKey.Value)) SpawnBoss();
        }

        // ------------------------------------------------------------------

        /// <summary>
        /// Drops a baked boss in front of Hornet. Facing-aware so it lands where you're
        /// looking rather than on top of you.
        /// </summary>
        private void SpawnBoss()
        {
            HeroController hero = HeroController.instance;
            if (hero == null)
            {
                Plugin.Log.LogWarning("Godhome: no hero to spawn a boss near.");
                return;
            }

            Vector3 p = hero.transform.position;
            float dir = hero.cState != null && hero.cState.facingRight ? 1f : -1f;
            Vector3 at = new Vector3(p.x + dir * 6f, p.y + 2f, p.z);

            Godhome.BossBuilder.Spawn(GodhomeConfig.SpawnBossName.Value, at);
        }

        private static GUIStyle _runStyle;

        /// <summary>Shows how far through a Pantheon you are, since there's no boss HUD.</summary>
        private void OnGUI()
        {
            if (!Godhome.PantheonRun.IsActive) return;
            if (Godhome.PantheonChallengeUI.IsOpen) return;

            if (_runStyle == null)
            {
                _runStyle = new GUIStyle(GUI.skin.label)
                { alignment = TextAnchor.UpperCenter, fontSize = 18 };
                _runStyle.normal.textColor = new Color(1f, 1f, 1f, 0.75f);
            }

            string text = $"{Godhome.PantheonRun.Title}   {Godhome.PantheonRun.Index + 1} / {Godhome.PantheonRun.Count}" +
                          $"\n{GodhomeConfig.SkipBossKey.Value} to skip";
            GUI.Label(new Rect(0f, 24f, Screen.width, 52f), text, _runStyle);
        }

        private void OnActiveSceneChanged(Scene from, Scene to)
        {
            // A new menu screen instance means the relabel has to happen again.
            ModeUnlock.Forget();

            string pending = SceneRedirect.TakePending();
            if (string.IsNullOrEmpty(pending)) return;

            // Rebuild a frame late. At activeSceneChanged the donor's own Awake/Start
            // haven't all run, so stripping now would race objects into existence right
            // after we cleared them.
            StartCoroutine(RebuildNextFrame(pending));
        }

        private IEnumerator RebuildNextFrame(string sceneName)
        {
            yield return null;

            CrashWatch.Arm();
            bool built = SceneRebuilder.Build(sceneName);
            if (built) StartCoroutine(WatchForBlackScreen());
        }

        /// <summary>
        /// A rebuilt scene that never finishes entering leaves the screen black with no
        /// obvious cause. If the game hasn't got there on its own shortly after the
        /// rebuild, say so loudly and force the fade, so what we built is at least
        /// visible and the failure is diagnosable rather than a blank window.
        /// </summary>
        private IEnumerator WatchForBlackScreen()
        {
            const float timeout = 10f;
            float t = 0f;

            GameManager gm = GameManager.instance;
            while (t < timeout)
            {
                if (gm != null && gm.HasFinishedEnteringScene)
                {
                    Plugin.Log.LogInfo(
                        $"Godhome: scene entered normally ({CrashWatch.ErrorCount} game error(s) during load).");
                    SceneRebuilder.LogDiagnostics("entered");
                    CrashWatch.Disarm();
                    yield break;
                }
                t += Time.unscaledDeltaTime;
                yield return null;
            }

            SceneRebuilder.LogDiagnostics("timed out");

            Plugin.Log.LogWarning(
                $"Godhome: the game hadn't finished entering the scene after {timeout}s " +
                $"({CrashWatch.ErrorCount} game error(s) logged above). Forcing the fade so " +
                "the rebuild is at least visible - look for the first exception above for the real cause.");

            try
            {
                if (gm != null)
                {
                    gm.FadeSceneIn();
                    gm.FinishedEnteringScene();
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogError("Godhome: forcing the fade failed too: " + e);
            }

            CrashWatch.Disarm();
        }

        // ------------------------------------------------------------------

        /// <summary>
        /// Debug warp: goes to Godhome from anywhere without the menu, so the rebuild
        /// can be iterated on without restarting into a new save.
        /// </summary>
        private void WarpToHub()
        {
            GameManager gm = GameManager.instance;
            if (gm == null)
            {
                Plugin.Log.LogWarning("Godhome: no GameManager yet - can't warp.");
                return;
            }

            GodhomeLoadout.RegisterHubWithTeleportMap();

            Plugin.Log.LogInfo($"Godhome: warping to {GodhomeLoadout.HubScene}.");
            gm.BeginSceneTransition(new GameManager.SceneLoadInfo
            {
                SceneName = GodhomeLoadout.HubScene,
                EntryGateName = GodhomeLoadout.HubSpawnMarker,
                EntrySkip = true,
                PreventCameraFadeOut = false,
                WaitForSceneTransitionCameraFade = true,
                Visualization = GameManager.SceneLoadVisualizations.Default,
                AlwaysUnloadUnusedAssets = true,
            });
        }
    }
}
