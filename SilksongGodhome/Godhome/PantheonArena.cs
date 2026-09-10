using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// Turns one of Silksong's own rooms into a Pantheon arena.
    ///
    /// Three jobs, in order.
    ///
    /// **Make sure the boss is there.** Silksong composes a room from a main scene plus
    /// additive pieces, and its bosses usually live in a piece: `Bone_05_boss` is 202
    /// objects with no _SceneManager, no _Managers and no TileMap. Whether that piece
    /// loads is decided by SceneAdditiveLoadConditional against the player's save, and a
    /// Godseeker save has none of the flags it looks for - so the room comes up empty.
    ///
    /// **Put the hero somewhere solid.** With no entry gate, GameManager falls back to
    /// LocateSpawnPoint, which looks for a marker named after playerData.respawnMarkerName -
    /// a Godhome bench that does not exist in a Silksong room. It finds nothing and the
    /// hero is left at the origin, which in a room whose floor is a hundred units away is
    /// the "teleported out of bounds" you saw. The hero is placed beside the boss
    /// instead, on ground found by casting downwards.
    ///
    /// **End the fight.** A BossSceneController pointed at the boss's HealthManager, so
    /// the game's own machinery reports the arena complete and the run moves on.
    /// </summary>
    internal class PantheonArena : MonoBehaviour
    {
        private const float SideOffset = 6f;

        /// <summary>
        /// How near a respawn marker has to be to count as part of the fight. Beyond
        /// this it is somewhere else in the room - Tut_03's is by the exit.
        /// </summary>
        private const float ArenaMarkerRange = 18f;

        /// <summary>
        /// A beat between the last boss falling and the next arena loading, so a death
        /// has time to land rather than being cut off by a fade.
        /// </summary>
        private const float BeatBetweenArenas = 1.75f;

        private PantheonRegistry.Entry _entry;
        private static PantheonArena _current;

        public static void Install(PantheonRegistry.Entry entry)
        {
            if (entry == null || string.IsNullOrEmpty(entry.Scene)) return;
            if (_current != null) UnityEngine.Object.Destroy(_current.gameObject);

            var go = new GameObject("Godhome_PantheonArena");
            UnityEngine.Object.DontDestroyOnLoad(go);
            var a = go.AddComponent<PantheonArena>();
            a._entry = entry;
            _current = a;
            a.StartCoroutine(a.Run());
        }

        private IEnumerator Run()
        {
            // Wait for *this room* to be the one we are standing in, and for the hero
            // to be in control. Waiting on GameState alone was not enough: the arena is
            // installed before the transition starts, so the game was still PLAYING back
            // in the Atrium and the very first check passed - which is how it came to
            // report the boss missing from a room that had not begun loading.
            float deadline = Time.realtimeSinceStartup + 60f;
            bool arrived = false;
            while (Time.realtimeSinceStartup < deadline)
            {
                GameManager gm = GameManager.instance;
                if (gm != null && gm.GameState == GlobalEnums.GameState.PLAYING &&
                    string.Equals(SceneManager.GetActiveScene().name, _entry.Scene,
                                  StringComparison.OrdinalIgnoreCase))
                {
                    arrived = true;
                    break;
                }
                yield return null;
            }
            if (!arrived)
            {
                Plugin.Log.LogWarning(
                    $"Godhome: never arrived in '{_entry.Scene}' (still in " +
                    $"'{SceneManager.GetActiveScene().name}') - giving up on this arena.");
                yield break;
            }
            Plugin.Log.LogInfo($"Godhome: arrived in '{_entry.Scene}'.");
            yield return null;

            if (!string.IsNullOrEmpty(_entry.SubScene)) yield return EnsurePiece(_entry.SubScene);

            var bosses = new List<GameObject>();
            foreach (string want in Names())
            {
                GameObject g = FindBoss(want);
                if (g != null) bosses.Add(g);
                else Plugin.Log.LogWarning($"Godhome: '{want}' is not in {Where()}.");
            }

            if (bosses.Count == 0)
            {
                Plugin.Log.LogWarning($"Godhome: no fight found in {Where()}.");
                yield break;
            }

            PlaceHeroAt(bosses[0]);
            BossSceneHost.Install(null);
            Watch(bosses);
        }

        /// <summary>
        /// Loads the boss piece if the room's own conditions did not.
        ///
        /// Asked for by Addressables key the same way SceneAdditiveLoadConditional asks,
        /// so this is the game's own load path rather than anything invented.
        /// </summary>
        private IEnumerator EnsurePiece(string piece)
        {
            for (int i = 0; i < SceneManager.sceneCount; i++)
            {
                if (string.Equals(SceneManager.GetSceneAt(i).name, piece,
                                  StringComparison.OrdinalIgnoreCase))
                {
                    Plugin.Log.LogInfo($"Godhome: '{piece}' is already loaded.");
                    yield break;
                }
            }

            // The room should have loaded it itself once ArenaFlags set the conditions
            // it tests; this is the fallback for an arena whose conditions we have not
            // worked out.
            Plugin.Log.LogInfo(
                $"Godhome: {_entry.Scene} did not load '{piece}' on its own - forcing it. " +
                "Its conditions are probably missing from pantheons/flags.txt.");
            var op = UnityEngine.AddressableAssets.Addressables.LoadSceneAsync(
                "Scenes/" + piece, LoadSceneMode.Additive);
            yield return op;

            if (op.Status != UnityEngine.ResourceManagement.AsyncOperations
                                        .AsyncOperationStatus.Succeeded)
            {
                Plugin.Log.LogError($"Godhome: couldn't load '{piece}': {op.OperationException}");
                yield break;
            }
            // Give its objects a frame to wake up before anything looks for the boss.
            yield return null;
        }

        private static GameObject FindBoss(string wanted)
        {
            if (string.IsNullOrEmpty(wanted)) return null;

            HealthManager best = null;
            foreach (HealthManager hm in UnityEngine.Object.FindObjectsByType<HealthManager>(
                         FindObjectsInactive.Include, FindObjectsSortMode.None))
            {
                if (hm == null) continue;
                if (!string.Equals(hm.name, wanted, StringComparison.Ordinal)) continue;
                // Prefer the one that is actually switched on.
                if (best == null || (!best.gameObject.activeInHierarchy &&
                                     hm.gameObject.activeInHierarchy))
                {
                    best = hm;
                }
            }
            return best != null ? best.gameObject : null;
        }

        private string[] Names() =>
            _entry.BossObjects != null && _entry.BossObjects.Length > 0
                ? _entry.BossObjects
                : new[] { _entry.BossObject };

        private string Where() =>
            _entry.Scene + (string.IsNullOrEmpty(_entry.SubScene) ? "" : " + " + _entry.SubScene);

        /// <summary>
        /// Puts the hero on ground the room's own designers marked as safe.
        ///
        /// The first version cast a ray downwards from beside the boss and used whatever
        /// it hit. That fails in exactly the rooms it matters in - a boss standing over
        /// a pit, a platform the ray misses, a room whose floor is a collider the mask
        /// does not include - and dropping the player through the world is a great deal
        /// worse than putting them a few metres off.
        ///
        /// Every Silksong room already contains positions guaranteed to be safe standing
        /// ground: its RespawnMarkers and HazardRespawnMarkers, which are where the game
        /// itself puts you after a fall.
        ///
        /// But only if one is actually *in the arena*. Tut_03's nearest marker to Moss
        /// Mother is by the room's exit, so taking the nearest unconditionally spawned
        /// the player at the door and left them to walk back. A marker is only used when
        /// it is close enough to be part of the same fight; otherwise the boss's own
        /// feet are the better reference, since a boss is standing on the floor by
        /// definition.
        /// </summary>
        private static void PlaceHeroAt(GameObject boss)
        {
            HeroController hero = HeroController.instance;
            if (hero == null || boss == null) return;

            Vector3 b = boss.transform.position;
            Vector3 target = b;
            string how = "the boss's own position";
            float best = float.MaxValue;

            foreach (RespawnMarker m in UnityEngine.Object.FindObjectsByType<RespawnMarker>(
                         FindObjectsInactive.Include, FindObjectsSortMode.None))
            {
                if (m == null) continue;
                float dd = (m.transform.position - b).sqrMagnitude;
                if (dd < best) { best = dd; target = m.transform.position; how = "respawn marker '" + m.name + "'"; }
            }
            foreach (HazardRespawnMarker m in UnityEngine.Object.FindObjectsByType<HazardRespawnMarker>(
                         FindObjectsInactive.Include, FindObjectsSortMode.None))
            {
                if (m == null) continue;
                float dd = (m.transform.position - b).sqrMagnitude;
                if (dd < best) { best = dd; target = m.transform.position; how = "hazard marker '" + m.name + "'"; }
            }

            // A marker has to be part of this fight to be worth using. Beyond that,
            // stand beside the boss - level with its feet, a few metres to one side.
            if (best > ArenaMarkerRange * ArenaMarkerRange)
            {
                float side = hero.transform.position.x <= b.x ? -SideOffset : SideOffset;
                target = new Vector3(b.x + side, b.y, b.z);
                how = $"beside the boss (nearest marker was {Mathf.Sqrt(best):F0}m away)";
            }

            // Last guard: never leave the hero outside the room.
            GameManager gm = GameManager.instance;
            if (gm != null && gm.sceneWidth > 0f && gm.sceneHeight > 0f)
            {
                float x = Mathf.Clamp(target.x, 2f, gm.sceneWidth - 2f);
                float y = Mathf.Clamp(target.y, 2f, gm.sceneHeight - 2f);
                if (!Mathf.Approximately(x, target.x) || !Mathf.Approximately(y, target.y))
                {
                    how += " (clamped into the room)";
                }
                target = new Vector3(x, y, target.z);
            }

            hero.transform.position = target;
            var rb = hero.GetComponent<Rigidbody2D>();
            if (rb != null) rb.linearVelocity = Vector2.zero;

            Plugin.Log.LogInfo($"Godhome: hero placed at {target} via {how}, boss at {b}.");
        }

        /// <summary>
        /// Watches the fight, and moves the run on the moment the last boss has finished
        /// dying.
        ///
        /// Hollow Knight's own BossSceneController waits a flat five seconds after the
        /// last death before it reports the arena complete, which is a beat too long and
        /// unrelated to what is on screen. This instead waits for the death *animation*
        /// to end - the boss's tk2d animator stopping, or the object going away - so the
        /// next arena begins as the corpse settles.
        /// </summary>
        private void Watch(List<GameObject> bosses)
        {
            _alive = new List<HealthManager>();
            foreach (GameObject g in bosses)
            {
                HealthManager hm = g.GetComponent<HealthManager>();
                if (hm != null) _alive.Add(hm);
            }
            if (_alive.Count == 0) return;

            var names = new List<string>();
            foreach (HealthManager hm in _alive) names.Add($"{hm.name} ({hm.hp} hp)");
            Plugin.Log.LogInfo($"Godhome: watching {string.Join(", ", names)}.");

            StartCoroutine(WatchRoutine());
        }

        private List<HealthManager> _alive;
        private bool _advanced;

        private IEnumerator WatchRoutine()
        {
            // Poll rather than subscribe: OnDeath is per-HealthManager and a boss that is
            // replaced by a corpse object mid-fight would take its subscription with it.
            while (true)
            {
                bool anyAlive = false;
                foreach (HealthManager hm in _alive)
                {
                    if (hm != null && !hm.isDead) { anyAlive = true; break; }
                }
                if (!anyAlive) break;
                yield return null;
            }

            Plugin.Log.LogInfo("Godhome: last boss down - waiting for the death animation.");

            // Give the death animation up to a few seconds, and stop as soon as it ends.
            float deadline = Time.time + 6f;
            while (Time.time < deadline)
            {
                bool stillPlaying = false;
                foreach (HealthManager hm in _alive)
                {
                    if (hm == null) continue;
                    var an = hm.GetComponent<tk2dSpriteAnimator>();
                    if (an != null && an.Playing && hm.gameObject.activeInHierarchy)
                    {
                        stillPlaying = true;
                        break;
                    }
                }
                if (!stillPlaying) break;
                yield return null;
            }

            if (_advanced) yield break;
            _advanced = true;

            // Let the death land before the screen goes.
            yield return new WaitForSeconds(BeatBetweenArenas);

            Plugin.Log.LogInfo($"Godhome: {_entry.DisplayName} finished - next arena.");
            if (PantheonRun.IsActive) PantheonRun.Advance();
        }

    }
}
