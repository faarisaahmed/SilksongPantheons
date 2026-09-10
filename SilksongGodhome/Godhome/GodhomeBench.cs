using System;
using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// Makes Godhome's bench usable.
    ///
    /// Both games drive benches from a PlayMaker FSM called "Bench Control" - Silksong
    /// still looks one up by that exact name in HeroController's respawn path:
    ///
    ///     PlayMakerFSM benchFSM = FSMUtility.LocateFSM(spawnPoint.gameObject, "Bench Control");
    ///     benchFSM.FsmVariables.GetFsmBool("RespawnResting").Value = true;
    ///     benchFSM.SendEvent("RESPAWN");
    ///
    /// Godhome's FSM graphs aren't ported, so this reimplements what the FSM does using
    /// Silksong's own public API rather than emulating the graph:
    ///
    ///   sit  - PlayerData.atBench, relinquish control, stop gravity, snap to the bench,
    ///          heal to full and save.
    ///   rise - the reverse, mirroring RestBenchHelper.OnDisable, which is Silksong's own
    ///          "get off the bench" path.
    ///
    /// Note it does *not* become your respawn point. Godhome's bench is a place to heal
    /// and swap tools between attempts; dying in a Pantheon returns you to the Atrium,
    /// not to the bench, so calling SetBenchRespawn here would be wrong.
    /// </summary>
    internal class GodhomeBench : GodhomeInteractable
    {
        /// <summary>Set by the rebuilder from the scene the bench belongs to.</summary>
        public string SceneName;

        private Vector3 _sitPoint;

        protected override string Prompt =>
            Engaged ? "Press Up to rise" : "Press Up to rest\n(restores health and silk)";

        private void Awake()
        {
            _sitPoint = transform.position;
        }

        protected override void Interact()
        {
            if (Engaged) Rise();
            else Sit();
        }

        private void Sit()
        {
            HeroController hero = HeroController.instance;
            PlayerData pd = PlayerData.instance;
            if (hero == null || pd == null) return;

            Engaged = true;

            hero.RelinquishControl();
            hero.AffectedByGravity(gravityApplies: false);
            hero.transform.position = new Vector3(_sitPoint.x, _sitPoint.y, hero.transform.position.z);

            var rb = hero.GetComponent<Rigidbody2D>();
            if (rb != null) rb.linearVelocity = Vector2.zero;

            pd.atBench = true;

            // Restore health and silk - the reason to rest at all.
            try
            {
                pd.SetInt(nameof(PlayerData.health), pd.maxHealth);
                pd.SetInt(nameof(PlayerData.silk), pd.CurrentSilkMax);
                hero.MaxHealth();
                EventRegister.SendEvent(EventRegisterEvents.HealthUpdate);
                EventRegister.SendEvent(EventRegisterEvents.HeroHealedToMax);
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning("Godhome: couldn't restore health at the bench: " + e.Message);
            }

            // Hornet's own sit animation. The BENCHREST events turned out to be a dead
            // end - the hero carries no bench FSM (its FSM list is Sprint, Mantle, Nail
            // Arts and so on), because in a real Silksong scene that FSM lives on the
            // bench, not on her. The clips themselves are on the hero though: the
            // animation library has "Rest Start", "Sit", "Sit Idle" and "Rest End".
            //
            // StopAnimationControl hands the animator over, otherwise HeroController
            // drives it straight back to Idle on the next frame.
            hero.StopAnimationControl();
            PlaySit();

            try
            {
                GameManager.instance.SaveGame(delegate(bool ok)
                {
                    Plugin.Log.LogInfo("Godhome: rested at the bench" + (ok ? " and saved." : " (save failed)."));
                });
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning("Godhome: bench save failed: " + e.Message);
            }
        }

        private static tk2dSpriteAnimator HeroAnimator()
        {
            HeroController hero = HeroController.instance;
            return hero != null ? hero.GetComponent<tk2dSpriteAnimator>() : null;
        }

        /// <summary>Plays a clip if the hero's library has it. Returns false if it doesn't.</summary>
        private static bool PlayClip(string clip)
        {
            tk2dSpriteAnimator anim = HeroAnimator();
            if (anim == null) return false;

            try
            {
                if (anim.GetClipByName(clip) == null) return false;
                anim.Play(clip);
                return true;
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"Godhome: couldn't play '{clip}': {e.Message}");
                return false;
            }
        }

        private void PlaySit()
        {
            if (!PlayClip("Rest Start") && !PlayClip("Sit"))
            {
                Plugin.Log.LogWarning("Godhome: no sit clip on the hero; she'll rest standing up.");
                return;
            }
            StartCoroutine(nameof(SitRoutine));
        }

        /// <summary>Holds the settled pose once the sit-down clip has played out.</summary>
        private System.Collections.IEnumerator SitRoutine()
        {
            tk2dSpriteAnimator anim = HeroAnimator();
            float wait = 0.6f;
            if (anim != null && anim.CurrentClip != null && anim.CurrentClip.fps > 0f)
            {
                wait = anim.CurrentClip.frames.Length / anim.CurrentClip.fps;
            }
            yield return new WaitForSeconds(wait);

            if (Engaged) PlayClip("Sit Idle");
        }

        private void Rise()
        {
            HeroController hero = HeroController.instance;
            PlayerData pd = PlayerData.instance;
            Engaged = false;

            if (pd != null) pd.atBench = false;
            if (hero == null) return;

            // Same order RestBenchHelper.OnDisable uses.
            StopCoroutine(nameof(SitRoutine));
            PlayClip("Rest End");

            hero.AffectedByGravity(gravityApplies: true);
            hero.RegainControl();
            hero.StartAnimationControlToIdle();
        }
    }
}
