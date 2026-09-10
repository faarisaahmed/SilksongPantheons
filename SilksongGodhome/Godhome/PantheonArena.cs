using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
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
        private const float CastHeight = 30f;
        private const float CastDepth = 60f;

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
            // Let the room finish loading and its own Start() methods run.
            for (int i = 0; i < 4; i++) yield return null;
            yield return new WaitForSeconds(0.25f);

            if (!string.IsNullOrEmpty(_entry.SubScene)) yield return EnsurePiece(_entry.SubScene);

            GameObject boss = FindBoss(_entry.BossObject);
            if (boss == null)
            {
                Plugin.Log.LogWarning(
                    $"Godhome: '{_entry.BossObject}' is not in {_entry.Scene}" +
                    (string.IsNullOrEmpty(_entry.SubScene) ? "" : " + " + _entry.SubScene) +
                    " - the arena will have no fight in it.");
            }
            else
            {
                PlaceHeroNear(boss);
                InstallController(boss);
            }
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

            Plugin.Log.LogInfo($"Godhome: loading boss piece '{piece}' into {_entry.Scene}.");
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

        /// <summary>
        /// Beside the boss, standing on whatever the room's floor is.
        ///
        /// The cast starts above the boss and looks down, which is the one direction a
        /// 2D room reliably has ground in. If nothing is found the hero is left level
        /// with the boss rather than dropped - being next to the fight in mid-air is
        /// recoverable; being under the map is not.
        /// </summary>
        private static void PlaceHeroNear(GameObject boss)
        {
            HeroController hero = HeroController.instance;
            if (hero == null) return;

            Vector3 b = boss.transform.position;
            float side = UnityEngine.Random.value < 0.5f ? -SideOffset : SideOffset;
            var from = new Vector2(b.x + side, b.y + CastHeight);

            Vector3 target = new Vector3(b.x + side, b.y, b.z);
            RaycastHit2D hit = Physics2D.Raycast(from, Vector2.down, CastDepth,
                                                 1 << LayerMask.NameToLayer("Terrain"));
            if (hit.collider != null)
            {
                target = new Vector3(hit.point.x, hit.point.y + 1.5f, b.z);
            }
            else
            {
                // Try the other side before giving up on finding a floor.
                from = new Vector2(b.x - side, b.y + CastHeight);
                hit = Physics2D.Raycast(from, Vector2.down, CastDepth,
                                        1 << LayerMask.NameToLayer("Terrain"));
                if (hit.collider != null)
                    target = new Vector3(hit.point.x, hit.point.y + 1.5f, b.z);
                else
                    Plugin.Log.LogWarning(
                        $"Godhome: no floor found under '{boss.name}'; placing level with it.");
            }

            hero.transform.position = target;
            var rb = hero.GetComponent<Rigidbody2D>();
            if (rb != null) rb.linearVelocity = Vector2.zero;

            Plugin.Log.LogInfo($"Godhome: hero placed at {target} for '{boss.name}'.");
        }

        /// <summary>
        /// A BossSceneController watching this boss, so the room reports itself finished
        /// and PantheonRun moves on. Kept dormant for the same reason as everywhere else
        /// in this project: its Awake pulls on sequence loading and its Start wants a
        /// transition prefab, neither of which exist here.
        /// </summary>
        private static void InstallController(GameObject boss)
        {
            var hm = boss.GetComponent<HealthManager>();
            if (hm == null) return;

            try
            {
                var go = new GameObject("Godhome_BossSceneController");
                go.SetActive(false);
                var c = go.AddComponent<BossSceneController>();

                c.bosses = new[] { hm };
                c.doTransitionIn = false;
                c.doTransitionOut = false;
                c.BossLevel = BossSceneHost.AttunedLevel;
                c.CanTransition = true;

                SetPrivate(c, "BossHealthLookup",
                    new Dictionary<HealthManager, BossSceneController.BossHealthDetails>());
                SetPrivate(c, "HasTransitionedIn", true);

                BossSceneController.Instance = c;

                // Setup() is what subscribes to OnDeath; Hollow Knight calls it from
                // Awake, which is exactly the method we are avoiding running.
                typeof(BossSceneController)
                    .GetMethod("Setup", BindingFlags.NonPublic | BindingFlags.Instance)
                    ?.Invoke(c, null);

                c.OnBossSceneComplete += () =>
                {
                    Plugin.Log.LogInfo($"Godhome: '{boss.name}' is down - advancing the run.");
                    if (PantheonRun.IsActive) PantheonRun.Advance();
                };

                Plugin.Log.LogInfo($"Godhome: watching '{boss.name}' ({hm.hp} hp) for the run.");
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Godhome: couldn't watch '{boss.name}': {e}");
            }
        }

        private static void SetPrivate(object target, string property, object value)
        {
            PropertyInfo p = typeof(BossSceneController)
                .GetProperty(property, BindingFlags.Public | BindingFlags.Instance);
            MethodInfo setter = p != null ? p.GetSetMethod(nonPublic: true) : null;
            if (setter != null) { setter.Invoke(target, new[] { value }); return; }

            FieldInfo f = typeof(BossSceneController).GetField(
                "<" + property + ">k__BackingField",
                BindingFlags.NonPublic | BindingFlags.Instance);
            if (f != null) f.SetValue(target, value);
        }
    }
}
