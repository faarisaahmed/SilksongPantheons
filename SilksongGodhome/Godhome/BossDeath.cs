using System;
using System.Collections;
using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// Kills a rebuilt boss properly: stops its behaviour, plays its own death animation,
    /// drops the corpse and clears it away.
    ///
    /// Hollow Knight doesn't do this in the boss's FSM - neither of Gruz Mother's FSMs
    /// even handles the "ZERO HP" event that HealthManager.Die sends. Death is
    /// `EnemyDeathEffects`, which spawns a separate corpse prefab and destroys the enemy.
    /// Those corpse prefabs are Hollow Knight assets that can't cross the engine gap.
    ///
    /// What *does* cross is the animation: Gruz Mother's own library contains `Death`,
    /// `Fall` and `Burst`. So instead of faking a corpse, the boss plays its real death
    /// clip in place, falls under gravity, and is cleaned up - which is what the corpse
    /// would have looked like anyway.
    /// </summary>
    internal class BossDeath : MonoBehaviour
    {
        /// <summary>
        /// Exact clip names to try first, then any clip beginning with "Death".
        ///
        /// The fallbacks aren't arbitrary. The Nailmasters have no death animation at all
        /// - in Hollow Knight they bow and sit down when beaten, so "Bow" then "Rest" is
        /// their defeat. Bosses whose death is entirely corpse-prefab driven (Brooding
        /// Mawlek) have nothing usable and simply fade.
        /// </summary>
        private static readonly string[] Preferred =
        {
            "Death", "Death Land", "Death Splat", "Death Sink", "Death Fall",
            "Death Air", "Death Fly", "Bow", "Fall", "Burst", "Stun",
        };

        private HealthManager _health;
        private tk2dSpriteAnimator _anim;
        private bool _dying;

        /// <summary>Seconds the corpse lingers after the clip finishes.</summary>
        public float LingerSeconds = 2.5f;

        private void Awake()
        {
            _health = GetComponent<HealthManager>();
            _anim = GetComponent<tk2dSpriteAnimator>();
            if (_health != null) _health.OnDeath += OnDied;
        }

        private void OnDestroy()
        {
            if (_health != null) _health.OnDeath -= OnDied;
        }

        private void Update()
        {
            // HealthManager.Die can be reached by paths that don't raise OnDeath, so the
            // flag is checked too - a boss that stops responding to hits but never falls
            // over is worse than one that dies twice.
            if (!_dying && _health != null && _health.isDead) OnDied();
        }

        private void OnDied()
        {
            if (_dying) return;
            _dying = true;
            StartCoroutine(DieRoutine());
        }

        private string PlayDeathClip(ref float wait)
        {
            if (_anim == null || _anim.Library == null) return null;

            foreach (string want in Preferred)
            {
                string got = TryPlay(want, ref wait);
                if (got != null) return got;
            }

            // Anything else the boss calls a death.
            foreach (tk2dSpriteAnimationClip c in _anim.Library.clips)
            {
                if (c == null || string.IsNullOrEmpty(c.name)) continue;
                if (!c.name.StartsWith("Death", StringComparison.OrdinalIgnoreCase)) continue;
                string got = TryPlay(c.name, ref wait);
                if (got != null) return got;
            }
            return null;
        }

        private string TryPlay(string clip, ref float wait)
        {
            try
            {
                if (_anim.GetClipByName(clip) == null) return null;
                _anim.Play(clip);
                tk2dSpriteAnimationClip c = _anim.CurrentClip;
                if (c != null && c.fps > 0f && c.frames != null) wait = c.frames.Length / c.fps;
                return clip;
            }
            catch (Exception)
            {
                return null;
            }
        }

        private IEnumerator RestAfterBow(float bowLength)
        {
            yield return new WaitForSeconds(bowLength);
            float ignored = 0f;
            TryPlay("Rest", ref ignored);
        }

        private IEnumerator DieRoutine()
        {
            Plugin.Log.LogInfo($"Godhome: '{name}' died.");

            // Behaviour first: an FSM left running would keep driving velocity and
            // animation over the top of the death clip.
            foreach (PlayMakerFSM f in GetComponents<PlayMakerFSM>())
            {
                try { f.enabled = false; }
                catch (Exception) { }
            }

            // Stop hurting the player, and stop being hittable.
            foreach (DamageHero d in GetComponentsInChildren<DamageHero>(true))
            {
                d.gameObject.SetActive(false);
            }
            foreach (Collider2D c in GetComponentsInChildren<Collider2D>(true))
            {
                c.enabled = false;
            }

            float wait = 1f;
            string played = PlayDeathClip(ref wait);

            if (played != null) Plugin.Log.LogInfo($"Godhome: '{name}' playing death clip '{played}'.");
            else Plugin.Log.LogWarning($"Godhome: '{name}' has no death clip; it will just fade.");

            // The Nailmasters bow, then settle into their rest pose.
            if (played == "Bow") StartCoroutine(RestAfterBow(wait));

            // Let it drop, the way a corpse does - unless it's bowing, which is a
            // deliberate standing pose.
            var rb = GetComponent<Rigidbody2D>();
            if (rb != null && played != "Bow")
            {
                rb.linearVelocity = Vector2.zero;
                rb.gravityScale = 1f;
                rb.constraints = RigidbodyConstraints2D.FreezeRotation;
            }

            yield return new WaitForSeconds(wait + LingerSeconds);

            // Fade rather than vanish.
            var sprite = GetComponent<tk2dSprite>();
            float t = 0f;
            const float fade = 0.6f;
            while (t < fade)
            {
                t += Time.deltaTime;
                if (sprite != null)
                {
                    Color c = sprite.color;
                    c.a = Mathf.Lerp(1f, 0f, t / fade);
                    sprite.color = c;
                }
                yield return null;
            }

            Destroy(gameObject);
        }
    }
}
