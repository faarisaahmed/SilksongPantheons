using System;
using System.Collections.Generic;
using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// Rebuilds a Hollow Knight boss as live tk2d assets.
    ///
    /// The whole approach rests on one fact: tk2d's serialised structures are identical
    /// between Hollow Knight's copy and Silksong's TeamCherry.TK2D. So collections and
    /// animation libraries are reconstructed as *real* tk2dSpriteCollectionData and
    /// tk2dSpriteAnimation objects - which matters beyond looks, because every
    /// Tk2dPlayAnimation action in the boss's FSMs drives a real tk2dSpriteAnimator.
    ///
    /// Every node in the hierarchy gets its own sprite, animator and FSMs. Brooding
    /// Mawlek's root object carries a sprite you never see; its head and arms are what's
    /// on screen, and they animate and behave independently.
    /// </summary>
    internal static class BossBuilder
    {
        // Keyed by asset name, not by boss: Mato and Oro share "Nailmasters", and every
        // boss with a hit effect shares "EnemyHitEffects". Rebuilding those once keeps a
        // Pantheon run from accumulating a dozen copies of the same 9 MB atlas.
        private static readonly Dictionary<string, tk2dSpriteCollectionData> CollectionCache =
            new Dictionary<string, tk2dSpriteCollectionData>(StringComparer.Ordinal);
        private static readonly Dictionary<string, tk2dSpriteAnimation> LibraryCache =
            new Dictionary<string, tk2dSpriteAnimation>(StringComparer.Ordinal);

        /// <summary>
        /// Spawns every boss baked for an arena, each at the position it occupied in
        /// Hollow Knight.
        /// </summary>
        public static int SpawnForScene(string sceneName)
        {
            int n = 0;
            foreach (string name in BossRegistry.ForScene(sceneName))
            {
                if (Spawn(name, null) != null) n++;
            }
            if (n > 0) Plugin.Log.LogInfo($"Godhome: spawned {n} boss(es) for '{sceneName}'.");
            return n;
        }

        /// <summary>
        /// Spawns a boss. A null position means "where Hollow Knight had it".
        /// </summary>
        public static GameObject Spawn(string bossName, Vector3? position, string clip = null)
        {
            BossData.Boss boss = BossData.Load(bossName);
            if (boss == null) return null;

            BossData.Node root = boss.Root;
            Vector3 at = position ?? (root != null ? root.Position : Vector3.zero);

            try
            {
                // Shared art first: every node indexes into these.
                var colls = new tk2dSpriteCollectionData[boss.Collections.Length];
                for (int i = 0; i < colls.Length; i++) colls[i] = BuildCollection(boss.Collections[i]);

                var libs = new tk2dSpriteAnimation[boss.Libraries.Length];
                for (int i = 0; i < libs.Length; i++) libs[i] = BuildLibrary(boss.Libraries[i], colls);

                if (root == null)
                {
                    Plugin.Log.LogError($"Godhome: baked boss '{bossName}' has no hierarchy.");
                    return null;
                }

                FsmBuilder.SetAssets(LoadFsmAssets(boss), BuildPrefabs(boss, colls, libs));

                var go = new GameObject("Godhome_" + boss.Name);

                // Parent to the scene root, or the boss outlives the room. Swapping
                // arenas destroys GodhomeRoot; a boss spawned as its own root object
                // survived that and followed the player into every later arena - which is
                // how a sleeping Moss Charger ended up hanging over Soul Warrior's fight.
                Transform sceneRoot = Rebuild.SceneRebuilder.CurrentRoot != null
                    ? Rebuild.SceneRebuilder.CurrentRoot.transform
                    : null;
                if (sceneRoot != null) go.transform.SetParent(sceneRoot, worldPositionStays: false);

                var built = new BuildStats();
                BuildNode(go, root, colls, libs, clip, built, isRoot: true);

                go.transform.position = at;

                Plugin.Log.LogInfo(
                    $"Godhome: spawned '{boss.Name}' at {at} - {built.Nodes} objects, " +
                    $"{built.Sprites} sprite(s), {built.Animators} animator(s), {built.Fsms} FSM(s).");

                // The arena normally supplies the events that start a fight; a spawned
                // boss has no arena, so BossWaker sends them instead.
                if (built.Fsms > 0) go.AddComponent<BossWaker>();

                // Death is EnemyDeathEffects' job in Hollow Knight, and that needs a
                // corpse prefab we can't bring across - so the boss plays its own death
                // clip instead. Added outside the FSM check: a boss with no behaviour
                // should still die when you kill it.
                if (HasHealth(root)) go.AddComponent<BossDeath>();

                if (GodhomeConfig.TraceBossStates.Value) go.AddComponent<BossTrace>();

                // A boss that leaves the room takes the fight with it. This reports how
                // and brings it back; see BossLeash for why it is a net and not a fix.
                go.AddComponent<BossLeash>();

                return go;
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Godhome: couldn't spawn '{bossName}': {e}");
                return null;
            }
        }

        private sealed class BuildStats
        {
            public int Nodes, Sprites, Animators, Fsms;
        }

        /// <summary>
        /// Builds the prefabs a boss's FSMs spawn, each as an inactive template.
        ///
        /// Hollow Knight's bosses do not carry all their weapons: Gorb's Attacking FSM
        /// calls SpawnObjectFromGlobalPool on a needle prefab twenty-six times, and with
        /// a null parameter that call silently does nothing, which is why he stood there
        /// defenseless. The templates are inactive and kept out of the scene so that
        /// Instantiate copies them without them ever running themselves; PlayMaker's own
        /// spawn actions activate the copies.
        /// </summary>
        private static Dictionary<string, GameObject> BuildPrefabs(
            BossData.Boss boss, tk2dSpriteCollectionData[] colls, tk2dSpriteAnimation[] libs)
        {
            var map = new Dictionary<string, GameObject>(StringComparer.Ordinal);
            if (boss.Prefabs == null) return map;

            foreach (BossData.Prefab p in boss.Prefabs)
            {
                if (p == null || p.Root == null || string.IsNullOrEmpty(p.Name)) continue;
                if (PrefabCache.TryGetValue(p.Name, out GameObject cached) && cached != null)
                {
                    map[p.Name] = cached;
                    continue;
                }

                try
                {
                    var go = new GameObject("Godhome_Prefab_" + p.Name);
                    go.SetActive(false);
                    UnityEngine.Object.DontDestroyOnLoad(go);

                    var stats = new BuildStats();
                    // isRoot: a prefab's own root may ship inactive, and the template has
                    // to stay inactive regardless - the copy is what gets switched on.
                    BuildNode(go, p.Root, colls, libs, null, stats, isRoot: true);
                    go.SetActive(false);

                    PrefabCache[p.Name] = go;
                    map[p.Name] = go;
                }
                catch (Exception e)
                {
                    Plugin.Log.LogError($"Godhome: prefab '{p.Name}' failed: {e}");
                }
            }

            if (map.Count > 0)
                Plugin.Log.LogInfo($"Godhome: built {map.Count} prefab(s) for '{boss.Name}'.");
            return map;
        }

        private static readonly Dictionary<string, GameObject> PrefabCache =
            new Dictionary<string, GameObject>(StringComparer.Ordinal);

        /// <summary>
        /// Builds one object of the hierarchy onto <paramref name="go"/>, then its
        /// children. Order within a node matters: sprite and animator before physics
        /// before FSMs, because an FSM's first state pushes velocity and plays a clip.
        /// </summary>
        private static void BuildNode(GameObject go, BossData.Node n,
                                      tk2dSpriteCollectionData[] colls, tk2dSpriteAnimation[] libs,
                                      string clip, BuildStats stats, bool isRoot = false)
        {
            stats.Nodes++;
            go.layer = n.Layer;
            go.transform.localRotation = n.Rotation;
            go.transform.localScale = n.Scale;

            tk2dSpriteAnimation library = null;
            if (n.HasSprite && n.CollectionIndex < colls.Length && colls[n.CollectionIndex] != null)
            {
                tk2dSpriteCollectionData coll = colls[n.CollectionIndex];
                int id = n.SpriteId >= 0 && n.SpriteId < coll.spriteDefinitions.Length ? n.SpriteId : 0;

                // AddComponent(go, collection, spriteId) is tk2d's own entry point; it
                // wires the mesh, material and bounds the way the engine expects.
                tk2dSprite sprite = tk2dSprite.AddComponent(go, coll, id);
                if (sprite != null)
                {
                    stats.Sprites++;
                    sprite.color = n.SpriteColor;
                    sprite.scale = n.SpriteScale == Vector3.zero ? Vector3.one : n.SpriteScale;
                    sprite.SortingOrder = n.RenderLayer;
                }
            }

            if (n.HasAnimator && n.LibraryIndex < libs.Length && libs[n.LibraryIndex] != null)
            {
                library = libs[n.LibraryIndex];
                var animator = go.AddComponent<tk2dSpriteAnimator>();
                animator.Library = library;
                stats.Animators++;

                animator.DefaultClipId = n.DefaultClipId;
                animator.playAutomatically = n.PlayAutomatically;

                // Only the root is posed. Forcing a clip on every part is what put Dung
                // Defender's effects on screen: an effect object sits on a deliberately
                // blank sprite until its FSM fires, and playing "the first clip that
                // looks idle" on it draws a full-size dung ball across the arena instead.
                string want = isRoot ? clip : null;
                if (isRoot && string.IsNullOrEmpty(want))
                    want = PickIdleClip(library, n.DefaultClipId);
                if (!string.IsNullOrEmpty(want)) animator.Play(want);
            }

            ApplyPhysics(go, n);

            foreach (BossData.Node c in n.Children)
            {
                var child = new GameObject(c.Name);
                child.transform.SetParent(go.transform, false);
                child.transform.localPosition = c.Position;
                BuildNode(child, c, colls, libs, null, stats);
            }

            if (n.Fsms.Count > 0) stats.Fsms += FsmBuilder.Attach(go, n.Fsms);

            // Last, so children are parented onto a live object first. Hollow Knight
            // ships the Hero Damager inactive and an FSM switches it on mid-attack.
            //
            // The root is the exception: Brooding Mawlek's own body object is inactive in
            // GG_Brooding_Mawlek because the arena's FSM turns it on when the fight
            // starts. There is no arena here, so honouring that flag would spawn a boss
            // that is switched off - which is a second way to get an invisible Mawlek.
            if (!n.Active && !isRoot) go.SetActive(false);
        }

        /// <summary>
        /// Rigidbody, colliders, health and damage - the difference between a picture of
        /// a boss and an enemy. Values are Hollow Knight's own: Gruz Mother is a dynamic
        /// body with zero gravity and frozen rotation, a 3.52 x 1.52 body hitbox, and a
        /// separate trigger on a child that deals the contact damage.
        /// </summary>
        private static void ApplyPhysics(GameObject go, BossData.Node n)
        {
            if (n.HasBody)
            {
                var rb = go.AddComponent<Rigidbody2D>();
                rb.mass = n.Mass;
                rb.gravityScale = n.GravityScale;
                rb.linearDamping = n.LinearDrag;
                rb.angularDamping = n.AngularDrag;
                rb.bodyType = (RigidbodyType2D)n.BodyType;
                rb.constraints = (RigidbodyConstraints2D)n.Constraints;
                rb.collisionDetectionMode = (CollisionDetectionMode2D)n.CollisionDetection;
                rb.interpolation = (RigidbodyInterpolation2D)n.Interpolate;
            }

            foreach (BossData.BoxDef b in n.Boxes)
            {
                var c = go.AddComponent<BoxCollider2D>();
                c.offset = b.Offset;
                c.size = b.Size;
                c.isTrigger = b.Trigger;
                c.enabled = b.Enabled;
            }

            foreach (BossData.CircleDef cd in n.Circles)
            {
                var c = go.AddComponent<CircleCollider2D>();
                c.offset = cd.Offset;
                c.radius = cd.Radius;
                c.isTrigger = cd.Trigger;
                c.enabled = cd.Enabled;
            }

            if (n.HasHealth)
            {
                var hm = go.AddComponent<HealthManager>();
                ComponentInitSafe(hm);
                hm.hp = n.Hp;
            }

            if (n.HasDamage)
            {
                var dh = go.AddComponent<DamageHero>();
                ComponentInitSafe(dh);
                dh.damageDealt = n.DamageDealt;
                dh.hazardType = (GlobalEnums.HazardType)n.HazardType;
            }
        }

        private static void ComponentInitSafe(Component c)
        {
            // Same trap as everywhere else: AddComponent leaves [Serializable] fields and
            // arrays null, and this game's code rarely checks.
            Rebuild.ComponentInit.FillNulls(c);
        }

        private static bool HasHealth(BossData.Node n)
        {
            if (n.HasHealth) return true;
            foreach (BossData.Node c in n.Children)
            {
                if (HasHealth(c)) return true;
            }
            return false;
        }

        private static readonly Dictionary<string, UnityEngine.Object> AssetCache =
            new Dictionary<string, UnityEngine.Object>(StringComparer.Ordinal);

        /// <summary>
        /// Builds the AudioClips this boss's FSMs reference, so its sound effects survive
        /// the port. Everything else a Hollow Knight FSM points at - spawned prefabs,
        /// mixer snapshots - still can't cross.
        /// </summary>
        private static Dictionary<string, UnityEngine.Object> LoadFsmAssets(BossData.Boss boss)
        {
            var map = new Dictionary<string, UnityEngine.Object>(StringComparer.Ordinal);
            foreach (KeyValuePair<string, BossData.ClipInfo> kv in boss.FsmClips)
            {
                if (!AssetCache.TryGetValue(kv.Key, out UnityEngine.Object a) || a == null)
                {
                    a = Rebuild.GodhomeData.LoadClip(new Rebuild.GodhomeData.ClipDef
                    {
                        Name = kv.Key,
                        SampleCount = kv.Value.SampleCount,
                        Rate = kv.Value.Rate,
                    });
                    AssetCache[kv.Key] = a;
                }
                if (a != null) map[kv.Key] = a;
            }
            if (map.Count > 0) Plugin.Log.LogInfo($"Godhome: re-linked {map.Count} sound(s) for '{boss.Name}'.");
            return map;
        }

        /// <summary>
        /// A resting pose, so a boss that has not been woken is not stuck mid-attack.
        /// Hollow Knight's own default clip id wins when it is set to something real -
        /// effect objects like Mawlek's Spit Effect default to a clip that is a single
        /// blank frame, which is exactly right for something that should be invisible
        /// until it fires.
        /// </summary>
        private static string PickIdleClip(tk2dSpriteAnimation library, int defaultClipId)
        {
            if (defaultClipId > 0 && defaultClipId < library.clips.Length
                && library.clips[defaultClipId] != null)
                return library.clips[defaultClipId].name;

            string[] preferred = { "Idle", "Fly", "Sleep", "Walk" };
            foreach (string p in preferred)
            {
                foreach (tk2dSpriteAnimationClip c in library.clips)
                {
                    if (c != null && string.Equals(c.name, p, StringComparison.OrdinalIgnoreCase))
                        return c.name;
                }
            }
            return library.clips.Length > 0 && library.clips[0] != null ? library.clips[0].name : null;
        }

        // ------------------------------------------------------------------

        private static tk2dSpriteCollectionData BuildCollection(BossData.Collection src)
        {
            return BuildCollectionShared(src, CollectionCache);
        }

        /// <summary>
        /// Rebuilds one tk2d collection. Shared with the scene path, since an arena's own
        /// objects draw from the same sheets its bosses do.
        /// </summary>
        public static tk2dSpriteCollectionData BuildCollectionShared(
            BossData.Collection src, Dictionary<string, tk2dSpriteCollectionData> cache)
        {
            if (cache.TryGetValue(src.Name, out tk2dSpriteCollectionData cached) && cached != null)
                return cached;

            var pages = new List<Texture>();
            var mats = new List<Material>();

            // tk2d's own shader, which Silksong ships - it multiplies the atlas by the
            // per-vertex colour tk2dSprite writes.
            Shader shader = Shader.Find("tk2d/BlendVertexColor") ?? Shader.Find("Sprites/Default");
            for (int i = 0; i < src.Textures.Length; i++)
            {
                Texture2D tex = Rebuild.GodhomeData.LoadPage(src.Textures[i]);
                if (tex == null) continue;
                pages.Add(tex);
                mats.Add(new Material(shader) { name = src.Name + "_mat" + i, mainTexture = tex });
            }
            if (mats.Count == 0)
            {
                Plugin.Log.LogError($"Godhome: collection '{src.Name}' has no usable atlas texture.");
                return null;
            }

            // tk2d keeps these on GameObjects, not as ScriptableObjects - in Hollow
            // Knight they live on inactive prefabs. A hidden, DontDestroyOnLoad host
            // gives them the same lifetime without appearing in the scene.
            var host = new GameObject("Godhome_Collection_" + src.Name);
            host.SetActive(false);
            UnityEngine.Object.DontDestroyOnLoad(host);

            var coll = host.AddComponent<tk2dSpriteCollectionData>();
            coll.name = src.Name;
            coll.spriteCollectionName = src.Name;
            coll.materials = mats.ToArray();
            coll.textures = pages.ToArray();
            coll.premultipliedAlpha = false;

            // Keep tk2d out of its platform-variant and material-instancing paths: `inst`
            // then returns this object, and Init() uses our materials directly.
            coll.hasPlatformData = false;
            coll.needMaterialInstance = false;
            coll.materialIdsValid = true;
            coll.spriteCollectionPlatforms = new string[0];
            coll.spriteCollectionPlatformGUIDs = new string[0];
            coll.pngTextures = new TextAsset[0];
            coll.materialPngTextureId = new int[0];

            var defs = new tk2dSpriteDefinition[src.Defs.Length];
            for (int i = 0; i < defs.Length; i++)
            {
                BossData.SpriteDef s = src.Defs[i];
                int mid = s.MaterialId >= 0 && s.MaterialId < mats.Count ? s.MaterialId : 0;
                defs[i] = new tk2dSpriteDefinition
                {
                    name = s.Name ?? ("sprite" + i),
                    material = mats[mid],
                    materialId = mid,
                    texelSize = s.TexelSize,
                    positions = s.Positions,
                    uvs = s.Uvs,
                    indices = s.Indices,
                    boundsData = s.BoundsData,
                    untrimmedBoundsData = s.UntrimmedBoundsData,
                    normals = new Vector3[0],
                    tangents = new Vector4[0],
                    normalizedUvs = new Vector2[0],
                    customColliders = new tk2dSpriteColliderDefinition[0],
                    polygonCollider2D = new tk2dCollider2DData[0],
                    edgeCollider2D = new tk2dCollider2DData[0],
                    attachPoints = new tk2dSpriteDefinition.AttachPoint[0],
                    colliderType = tk2dSpriteDefinition.ColliderType.None,
                };
            }
            coll.spriteDefinitions = defs;

            cache[src.Name] = coll;
            Plugin.Log.LogInfo($"Godhome: built collection '{src.Name}' " +
                               $"({defs.Length} sprites, {mats.Count} page(s)).");
            return coll;
        }

        private static tk2dSpriteAnimation BuildLibrary(BossData.Library src,
                                                        tk2dSpriteCollectionData[] colls)
        {
            return BuildLibraryShared(src, colls, LibraryCache);
        }

        public static tk2dSpriteAnimation BuildLibraryShared(
            BossData.Library src, tk2dSpriteCollectionData[] colls,
            Dictionary<string, tk2dSpriteAnimation> cache)
        {
            if (cache.TryGetValue(src.Name, out tk2dSpriteAnimation cached) && cached != null)
                return cached;
            if (src.Clips == null || src.Clips.Length == 0) return null;

            var host = new GameObject("Godhome_Anim_" + src.Name);
            host.SetActive(false);
            UnityEngine.Object.DontDestroyOnLoad(host);

            var lib = host.AddComponent<tk2dSpriteAnimation>();
            lib.name = src.Name;

            var clips = new tk2dSpriteAnimationClip[src.Clips.Length];
            for (int i = 0; i < clips.Length; i++)
            {
                BossData.Clip c = src.Clips[i];
                var frames = new tk2dSpriteAnimationFrame[c.Frames.Length];
                for (int k = 0; k < frames.Length; k++)
                {
                    BossData.Frame f = c.Frames[k];
                    // Each frame names its own collection. Usually that is the library's
                    // own sheet, but Hollow Knight's effect libraries do borrow frames.
                    tk2dSpriteCollectionData fc =
                        f.CollectionIndex >= 0 && f.CollectionIndex < colls.Length
                            ? colls[f.CollectionIndex]
                            : null;
                    frames[k] = new tk2dSpriteAnimationFrame
                    {
                        spriteCollection = fc,
                        spriteId = f.SpriteId,
                        triggerEvent = f.TriggerEvent,
                        eventInfo = f.EventInfo ?? "",
                        eventInt = f.EventInt,
                        eventFloat = f.EventFloat,
                    };
                }
                clips[i] = new tk2dSpriteAnimationClip
                {
                    name = c.Name,
                    fps = c.Fps,
                    loopStart = c.LoopStart,
                    wrapMode = (tk2dSpriteAnimationClip.WrapMode)c.WrapMode,
                    frames = frames,
                };
            }
            lib.clips = clips;

            cache[src.Name] = lib;
            Plugin.Log.LogInfo($"Godhome: built library '{src.Name}' ({clips.Length} clips).");
            return lib;
        }
    }
}
