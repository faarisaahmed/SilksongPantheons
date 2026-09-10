using System;
using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// A Hall of Gods plinth.
    ///
    /// In Hollow Knight a statue has three parts: the statue itself (<c>BossStatue</c>),
    /// a lever you strike with the nail (<c>BossStatueLever</c>) and a dream-nail toggle
    /// (<c>BossStatueDreamToggle</c>). All three classes still exist in Silksong, and its
    /// lever is fully implemented:
    ///
    ///     if (canToggle &amp;&amp; collision.tag == "Nail Attack")
    ///         bossStatue.SetDreamVersion(!bossStatue.UsingDreamVersion, useAltStatue: true);
    ///
    /// We don't attach the real <c>BossStatue</c> because its state lives in per-boss
    /// PlayerData fields ("statueStateGruzMother" and friends) that a Silksong save simply
    /// doesn't have, so reading it throws. Instead this keeps the same shape - strike to
    /// swap between the boss and its dream variant, press Up to fight - and uses the same
    /// "Nail Attack" tag Silksong's own lever checks for, so Hornet's needle drives it.
    ///
    /// Silksong has no dream nail, so the dream variant is reached by striking rather than
    /// by a separate dream-nail toggle.
    /// </summary>
    internal class GodhomeStatue : GodhomeInteractable
    {
        public string BossScene;
        public string DreamBossScene;

        /// <summary>False = base boss, true = the dream/Ascended variant.</summary>
        public bool UsingDream { get; private set; }

        private const string ArenaEntryGate = "door_dreamEnter";
        private float _lastToggle;

        public bool HasDream => !string.IsNullOrEmpty(DreamBossScene);

        public string CurrentScene => (UsingDream && HasDream) ? DreamBossScene : BossScene;

        private static string Pretty(string scene)
        {
            if (string.IsNullOrEmpty(scene)) return "?";
            string s = scene.StartsWith("GG_", StringComparison.Ordinal) ? scene.Substring(3) : scene;
            return s.Replace('_', ' ');
        }

        protected override bool CanInteract() => !string.IsNullOrEmpty(CurrentScene);

        protected override string Prompt
        {
            get
            {
                string scene = CurrentScene;
                string name = Pretty(scene);
                string swap = HasDream
                    ? (UsingDream ? "\nStrike to return to the base fight" : "\nStrike with your needle for the dream fight")
                    : "";

                if (!Rebuild.GodhomeData.HasScene(scene))
                    return $"{name}\n(arena not baked yet){swap}";

                return $"{name}\nPress Up to fight{swap}";
            }
        }

        private void Start()
        {
            BuildStrikeTarget();
        }

        /// <summary>
        /// Godhome's lever is a separate child object with its own collider. Rather than
        /// depend on that specific object surviving the rebuild, give the statue its own
        /// trigger so a needle swing anywhere on it counts.
        /// </summary>
        private void BuildStrikeTarget()
        {
            if (!HasDream) return;

            var go = new GameObject("Godhome_StatueLever");
            go.transform.SetParent(transform, false);
            go.layer = gameObject.layer;

            var box = go.AddComponent<BoxCollider2D>();
            box.isTrigger = true;
            box.size = new Vector2(3f, 5f);
            box.offset = new Vector2(0f, 2f);

            go.AddComponent<StatueStrikeTarget>().Statue = this;
        }

        /// <summary>Swaps between the boss and its dream variant. Called by the strike target.</summary>
        public void ToggleDream()
        {
            if (!HasDream) return;

            // The real lever latches canToggle to stop a single swing registering twice;
            // a short cooldown does the same job across multiple hitboxes.
            if (Time.unscaledTime - _lastToggle < 0.4f) return;
            _lastToggle = Time.unscaledTime;

            UsingDream = !UsingDream;
            Plugin.Log.LogInfo($"Godhome: {name} -> {(UsingDream ? "dream" : "base")} ({CurrentScene})");

            try
            {
                GameManager.instance.FreezeMoment(1);
                GameCameras.instance.cameraShakeFSM.SendEvent("EnemyKillShake");
            }
            catch (Exception)
            {
                // Feedback only; the toggle itself has already happened.
            }
        }

        protected override void Interact()
        {
            GodhomeSave.EnsureUnlocks();

            string scene = CurrentScene;
            if (!Rebuild.GodhomeData.HasScene(scene))
            {
                Plugin.Log.LogWarning(
                    $"Godhome: '{scene}' isn't baked. Add it with " +
                    $"tools/extract_godhome.py --scenes {scene}");
                return;
            }

            Plugin.Log.LogInfo($"Godhome: entering {scene} from {name}");

            // A statue fight is a single arena, not a sequence, so any sequence left over
            // from a Pantheon has to be cleared or BossSceneController would try to
            // advance one.
            try
            {
                BossSequenceController.Reset();
                PantheonRun.Clear();
            }
            catch (Exception) { }

            GameManager.instance.BeginSceneTransition(new GameManager.SceneLoadInfo
            {
                SceneName = scene,
                EntryGateName = ArenaEntryGate,
                Visualization = GameManager.SceneLoadVisualizations.Default,
                AlwaysUnloadUnusedAssets = true,
                WaitForSceneTransitionCameraFade = true,
            });
        }
    }

    /// <summary>
    /// Forwards needle hits to the statue, mirroring how Silksong's own BossStatueLever
    /// detects them - a trigger that checks for the "Nail Attack" tag.
    /// </summary>
    internal class StatueStrikeTarget : MonoBehaviour
    {
        public GodhomeStatue Statue;

        private void OnTriggerEnter2D(Collider2D other)
        {
            if (Statue == null || other == null) return;
            if (!other.CompareTag("Nail Attack")) return;
            Statue.ToggleDream();
        }
    }
}
