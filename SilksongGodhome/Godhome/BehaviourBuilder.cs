using System;
using System.Collections.Generic;
using UnityEngine;
using GodhomeData = SilksongGodhome.Rebuild.GodhomeData;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// The shared assets a rebuilt Godhome room's behaviour needs: its tk2d sprite
    /// collections and animation libraries, the sounds its components reference, and the
    /// prefabs its FSMs spawn.
    ///
    /// These are per-room tables rather than per-boss ones, because an arena and the boss
    /// standing in it draw on the same sheets. Everything is cached by name across rooms,
    /// so a Pantheon run does not accumulate a dozen copies of EnemyHitEffects.
    /// </summary>
    internal static class BehaviourBuilder
    {
        private static readonly Dictionary<string, tk2dSpriteCollectionData> CollectionCache =
            new Dictionary<string, tk2dSpriteCollectionData>(StringComparer.Ordinal);
        private static readonly Dictionary<string, tk2dSpriteAnimation> LibraryCache =
            new Dictionary<string, tk2dSpriteAnimation>(StringComparer.Ordinal);
        private static readonly Dictionary<string, GameObject> PrefabCache =
            new Dictionary<string, GameObject>(StringComparer.Ordinal);
        private static readonly Dictionary<string, AudioClip> ClipCache =
            new Dictionary<string, AudioClip>(StringComparer.Ordinal);

        private static tk2dSpriteCollectionData[] _colls = new tk2dSpriteCollectionData[0];
        private static tk2dSpriteAnimation[] _libs = new tk2dSpriteAnimation[0];

        /// <summary>Builds a room's tables, before any of its objects are configured.</summary>
        public static void BeginScene(GodhomeData.BakedScene baked,
                                      Dictionary<string, GameObject> prefabs,
                                      Dictionary<string, AudioClip> clips)
        {
            prefabs.Clear();
            clips.Clear();

            _colls = new tk2dSpriteCollectionData[baked.Collections?.Length ?? 0];
            for (int i = 0; i < _colls.Length; i++) _colls[i] = BuildCollection(baked.Collections[i]);

            _libs = new tk2dSpriteAnimation[baked.Libraries?.Length ?? 0];
            for (int i = 0; i < _libs.Length; i++) _libs[i] = BuildLibrary(baked.Libraries[i], _colls);

            foreach (GodhomeData.ClipDef c in baked.Clips ?? new GodhomeData.ClipDef[0])
            {
                if (c == null || string.IsNullOrEmpty(c.Name)) continue;
                if (!ClipCache.TryGetValue(c.Name, out AudioClip a) || a == null)
                {
                    // The def itself, not a copy of three of its fields: rebuilding it
                    // dropped Format, so every music track was looked up as .pcm and
                    // reported missing while its .adpcm sat in the DLL unread.
                    a = GodhomeData.LoadClip(c);
                    ClipCache[c.Name] = a;
                }
                if (a != null) clips[c.Name] = a;
            }

            // ScriptableObjects before prefabs and components, since either can name one.
            // MusicCue lives here: "Gods and Glory" is not played by code we call, it is
            // an asset an ApplyMusicCue action hands to the AudioManager at the moment
            // Hollow Knight wants it.
            BuildAssets(baked);

            // Sounds and assets have to be in the map before any prefab's FSMs are built.
            RefreshFsmAssets();

            // Prefabs before components, because a component field can point at one.
            foreach (GodhomeData.PrefabDef p in baked.Prefabs ?? new GodhomeData.PrefabDef[0])
            {
                GameObject g = BuildPrefab(p);
                if (g != null) prefabs[p.Name] = g;
            }

            RefreshFsmAssets();

            if (_colls.Length > 0 || prefabs.Count > 0)
            {
                Plugin.Log.LogInfo(
                    $"Godhome: behaviour tables - {_colls.Length} collections, " +
                    $"{_libs.Length} libraries, {prefabs.Count} prefabs, {clips.Count} sounds.");
            }
        }

        private static readonly Dictionary<string, ScriptableObject> AssetCache =
            new Dictionary<string, ScriptableObject>(StringComparer.Ordinal);

        public static ScriptableObject AssetNamed(string name)
        {
            return !string.IsNullOrEmpty(name) && AssetCache.TryGetValue(name, out ScriptableObject o)
                ? o : null;
        }

        private static void BuildAssets(GodhomeData.BakedScene baked)
        {
            if (baked.Assets == null) return;

            // Two passes. Create every instance first, then fill them in: assets
            // reference each other - a MusicCue names alternatives that are MusicCues -
            // and a one-pass build would leave those null.
            var made = new List<KeyValuePair<GodhomeData.AssetDef, ScriptableObject>>();
            foreach (GodhomeData.AssetDef a in baked.Assets)
            {
                if (a?.Data == null || string.IsNullOrEmpty(a.Name)) continue;
                if (AssetCache.TryGetValue(a.Name, out ScriptableObject existing) && existing != null)
                    continue;

                Type t = Rebuild.ComponentApplier.Resolve(a.Data.TypeName);
                if (t == null || !typeof(ScriptableObject).IsAssignableFrom(t)) continue;
                try
                {
                    var so = ScriptableObject.CreateInstance(t);
                    so.name = a.Name;
                    UnityEngine.Object.DontDestroyOnLoad(so);
                    AssetCache[a.Name] = so;
                    made.Add(new KeyValuePair<GodhomeData.AssetDef, ScriptableObject>(a, so));
                }
                catch (Exception e)
                {
                    Plugin.Log.LogWarning($"Godhome: asset '{a.Name}' ({a.Data.TypeName}): {e.Message}");
                }
            }

            foreach (KeyValuePair<GodhomeData.AssetDef, ScriptableObject> kv in made)
                Rebuild.ComponentApplier.ApplyTo(kv.Value, kv.Key.Data);

            if (made.Count > 0) Plugin.Log.LogInfo($"Godhome: built {made.Count} asset(s).");
        }

        public static void AddTk2d(GameObject go, GodhomeData.Tk2dDef d)
        {
            if (d == null) return;
            try
            {
                if (d.HasSprite && d.CollectionIndex >= 0 && d.CollectionIndex < _colls.Length)
                {
                    tk2dSpriteCollectionData coll = _colls[d.CollectionIndex];
                    if (coll != null)
                    {
                        int id = d.SpriteId >= 0 && d.SpriteId < coll.spriteDefinitions.Length
                            ? d.SpriteId : 0;
                        // tk2d's own entry point: it wires the mesh, material and bounds
                        // the way the engine expects.
                        tk2dSprite sp = tk2dSprite.AddComponent(go, coll, id);
                        if (sp != null)
                        {
                            sp.color = d.SpriteColor;
                            sp.scale = d.SpriteScale == Vector3.zero ? Vector3.one : d.SpriteScale;
                            sp.SortingOrder = d.RenderLayer;
                        }
                    }
                }

                if (d.HasAnimator && d.LibraryIndex >= 0 && d.LibraryIndex < _libs.Length)
                {
                    tk2dSpriteAnimation lib = _libs[d.LibraryIndex];
                    if (lib != null)
                    {
                        var an = go.AddComponent<tk2dSpriteAnimator>();
                        an.Library = lib;
                        an.DefaultClipId = d.DefaultClipId;
                        an.playAutomatically = d.PlayAutomatically;
                    }
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"Godhome: tk2d on '{go.name}' failed: {e.Message}");
            }
        }

        // Rebuilt once per room rather than per object: a room has hundreds of FSMs and
        // rebuilding this map for each of them was pure waste.
        private static Dictionary<string, UnityEngine.Object> _fsmAssets =
            new Dictionary<string, UnityEngine.Object>(StringComparer.Ordinal);

        private static void RefreshFsmAssets()
        {
            _fsmAssets = new Dictionary<string, UnityEngine.Object>(StringComparer.Ordinal);
            foreach (KeyValuePair<string, AudioClip> kv in ClipCache)
            {
                if (kv.Value != null) _fsmAssets[kv.Key] = kv.Value;
            }
            foreach (KeyValuePair<string, ScriptableObject> kv in AssetCache)
            {
                if (kv.Value != null) _fsmAssets[kv.Key] = kv.Value;
            }
            FsmBuilder.SetAssets(_fsmAssets, PrefabCache);
        }

        public static int AddFsms(GameObject go, FsmData.Fsm[] fsms)
        {
            if (fsms == null || fsms.Length == 0) return 0;
            return FsmBuilder.Attach(go, fsms);
        }

        // ------------------------------------------------------------------

        private static GameObject BuildPrefab(GodhomeData.PrefabDef p)
        {
            if (p == null || p.Nodes == null || p.Nodes.Length == 0) return null;
            if (PrefabCache.TryGetValue(p.Name, out GameObject cached) && cached != null)
                return cached;

            try
            {
                var made = new Transform[p.Nodes.Length];
                GameObject root = null;
                var deferred = new List<Rebuild.ComponentApplier.Pending>();

                for (int i = 0; i < p.Nodes.Length; i++)
                {
                    GodhomeData.PrefabNode n = p.Nodes[i];
                    var go = new GameObject(n.Name);
                    if (i == 0)
                    {
                        root = go;
                        // Inactive and outside the scene, so the template never runs
                        // itself; Instantiate copies it and PlayMaker switches the copy on.
                        go.SetActive(false);
                        UnityEngine.Object.DontDestroyOnLoad(go);
                    }
                    else
                    {
                        Transform parent = n.Parent >= 0 && n.Parent < i ? made[n.Parent] : made[0];
                        go.transform.SetParent(parent, false);
                    }

                    go.layer = n.Layer;
                    go.transform.localPosition = n.Position;
                    go.transform.localRotation = n.Rotation;
                    go.transform.localScale = n.Scale;
                    made[i] = go.transform;

                    AddPhysics(go, n);
                    if ((n.Mask & GodhomeData.HasTk2d) != 0) AddTk2d(go, n.Tk2d);

                    foreach (GodhomeData.ComponentDef c in n.Components ?? new GodhomeData.ComponentDef[0])
                        Rebuild.ComponentApplier.Apply(go, c, deferred);

                    if (i > 0 && !n.Active) go.SetActive(false);
                }

                Rebuild.ComponentApplier.Resolve(deferred);

                for (int i = 0; i < p.Nodes.Length; i++)
                {
                    GodhomeData.PrefabNode n = p.Nodes[i];
                    if ((n.Mask & GodhomeData.HasFsm) != 0 && made[i] != null)
                        AddFsms(made[i].gameObject, n.Fsms);
                }

                PrefabCache[p.Name] = root;
                return root;
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Godhome: prefab '{p.Name}' failed: {e}");
                return null;
            }
        }

        private static void AddPhysics(GameObject go, GodhomeData.PrefabNode n)
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

            foreach (GodhomeData.BoxDef b in n.Boxes ?? new GodhomeData.BoxDef[0])
            {
                var c = go.AddComponent<BoxCollider2D>();
                c.offset = b.Offset;
                c.size = b.Size;
                c.isTrigger = b.Trigger;
                c.enabled = b.Enabled;
            }

            foreach (GodhomeData.CircleDef cd in n.Circles ?? new GodhomeData.CircleDef[0])
            {
                var c = go.AddComponent<CircleCollider2D>();
                c.offset = cd.Offset;
                c.radius = cd.Radius;
                c.isTrigger = cd.Trigger;
                c.enabled = cd.Enabled;
            }

            foreach (GodhomeData.PolyDef pd in n.Polys ?? new GodhomeData.PolyDef[0])
            {
                var c = go.AddComponent<PolygonCollider2D>();
                c.offset = pd.Offset;
                c.pathCount = pd.Paths.Length;
                for (int i = 0; i < pd.Paths.Length; i++) c.SetPath(i, pd.Paths[i]);
                c.isTrigger = pd.Trigger;
                c.enabled = pd.Enabled;
            }

            foreach (GodhomeData.EdgeDef ed in n.Edges ?? new GodhomeData.EdgeDef[0])
            {
                var c = go.AddComponent<EdgeCollider2D>();
                c.offset = ed.Offset;
                c.points = ed.Points;
                c.isTrigger = ed.Trigger;
                c.enabled = ed.Enabled;
            }
        }

        private static tk2dSpriteCollectionData BuildCollection(BossData.Collection src)
        {
            if (src == null) return null;
            if (CollectionCache.TryGetValue(src.Name, out tk2dSpriteCollectionData c) && c != null)
                return c;
            return BossBuilder.BuildCollectionShared(src, CollectionCache);
        }

        private static tk2dSpriteAnimation BuildLibrary(BossData.Library src,
                                                        tk2dSpriteCollectionData[] colls)
        {
            if (src == null) return null;
            if (LibraryCache.TryGetValue(src.Name, out tk2dSpriteAnimation l) && l != null)
                return l;
            return BossBuilder.BuildLibraryShared(src, colls, LibraryCache);
        }
    }
}
