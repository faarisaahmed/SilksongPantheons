using System;
using System.Collections.Generic;
using System.Collections;
using System.Diagnostics;
using System.Reflection;
using HarmonyLib;
using GlobalEnums;
using SilksongGodhome.Godhome;
using UnityEngine;

namespace SilksongGodhome.Rebuild
{
    /// <summary>
    /// Rebuilds a baked Godhome scene inside the donor room that <see cref="SceneRedirect"/>
    /// arranged to be loaded.
    ///
    /// Two halves: strip the donor's own content, then construct Godhome's. Stripping is
    /// the delicate one - the donor has to keep the scene-level infrastructure that
    /// GameManager.SetupSceneRefs goes looking for (its SceneManager component, tilemap
    /// info, camera rig) or the game breaks around us, while losing everything that
    /// would visibly belong to another room.
    /// </summary>
    internal static class SceneRebuilder
    {
        /// <summary>Root object holding everything we create, for easy teardown.</summary>
        public const string RootName = "GodhomeRoot";

        /// <summary>
        /// Components that make a donor root worth keeping.
        ///
        /// The first version of this matched on name prefixes and kept nothing at all -
        /// Bone_05_bellway's four roots are "Bone Beast NPC", "Bellbeast Children",
        /// "First Appear Trigger" and "CameraLockArea (7)", none of which look like
        /// plumbing. Matching on component type instead is robust against any room being
        /// used as the donor, and against Team Cherry renaming things.
        /// </summary>
        /// <summary>
        /// Root objects a real Silksong room uses for its scene plumbing. Kept by name as
        /// well as by component, since some carry no component we can name at compile time.
        /// </summary>
        private static readonly string[] KeepNames =
        {
            "_SceneManager",
            "_Managers",
            "TileMap",
            "TileMap Render Data",
            "Template-TileMap",
            "Template-TileMap Render Data",
            "_Transition Gates",
        };

        private static readonly Type[] KeepComponents =
        {
            typeof(CustomSceneManager),  // gm.sm - dereferenced unguarded in OnNextLevelReady
            typeof(tk2dTileMap),         // where CameraController reads scene bounds
            typeof(HeroController),
            typeof(Camera),
        };

        private static readonly Dictionary<string, Sprite[]> SpriteCache =
            new Dictionary<string, Sprite[]>(StringComparer.Ordinal);

        /// <summary>Atlas pages per scene, shared by sprites and mesh materials.</summary>
        private static readonly Dictionary<string, Texture2D[]> PageCache =
            new Dictionary<string, Texture2D[]>(StringComparer.Ordinal);

        public static GameObject CurrentRoot { get; private set; }

        // ------------------------------------------------------------------

        /// <summary>
        /// Swaps to another Godhome room without a Unity scene transition.
        ///
        /// Once we're inside Godhome every room is a rebuild into the same donor scene,
        /// so a scene load buys nothing and costs a lot: the full transition pipeline runs
        /// for a scene whose contents we immediately replace, and that pipeline is where
        /// loads were hanging. Tearing down GodhomeRoot and building the next room into
        /// the live scene is both faster and far less to go wrong.
        /// </summary>
        public static void RequestSwap(string sceneName, string entryGate)
        {
            GodhomeManager mgr = GodhomeManager.Instance;
            if (mgr == null)
            {
                Plugin.Log.LogError("Godhome: no manager to run the room swap.");
                return;
            }
            mgr.StartCoroutine(SwapRoutine(sceneName, entryGate));
        }

        private static IEnumerator SwapRoutine(string sceneName, string entryGate)
        {
            GameManager gm = GameManager.instance;
            HeroController hero = HeroController.instance;

            // Take control away for the swap so Hornet can't act mid-teardown.
            if (hero != null)
            {
                hero.RelinquishControl();
                hero.StopAnimationControl();
            }

            if (gm != null)
            {
                try { gm.screenFader_fsm.SendEventSafe("SCENE FADE OUT"); }
                catch (Exception) { }
            }

            yield return new WaitForSecondsRealtime(0.35f);

            if (CurrentRoot != null)
            {
                UnityEngine.Object.Destroy(CurrentRoot);
                CurrentRoot = null;
                // Let the destroy land before rebuilding, or the old colliders are still
                // present when the hero is repositioned.
                yield return null;
            }

            bool built = Build(sceneName, strip: false);
            yield return null;

            if (built) PlaceHero(sceneName, entryGate);

            if (hero != null)
            {
                hero.AffectedByGravity(gravityApplies: true);
                hero.RegainControl();
                hero.StartAnimationControlToIdle();
            }

            if (gm != null)
            {
                try
                {
                    gm.cameraCtrl.PositionToHeroInstant(forceDirect: true);
                    gm.FadeSceneIn();
                }
                catch (Exception e)
                {
                    Plugin.Log.LogWarning("Godhome: camera/fade after swap failed: " + e.Message);
                }
            }

            Plugin.Log.LogInfo($"Godhome: swapped to '{sceneName}'.");
        }

        /// <summary>
        /// Puts the hero at the named entry gate, falling back to a respawn marker and
        /// then to any transition point - mirroring GameManager.FindEntryPoint's own
        /// fallbackToAnyAvailable behaviour.
        /// </summary>
        private static void PlaceHero(string sceneName, string entryGate)
        {
            HeroController hero = HeroController.instance;
            if (hero == null || CurrentRoot == null) return;

            Transform target = null;

            if (!string.IsNullOrEmpty(entryGate))
            {
                foreach (TransitionPoint tp in CurrentRoot.GetComponentsInChildren<TransitionPoint>(true))
                {
                    if (tp.name == entryGate) { target = tp.transform; break; }
                }
            }

            if (target == null)
            {
                foreach (RespawnMarker m in CurrentRoot.GetComponentsInChildren<RespawnMarker>(true))
                {
                    if (m.name == GodhomeLoadout.HubSpawnMarker) { target = m.transform; break; }
                }
            }

            if (target == null)
            {
                RespawnMarker any = CurrentRoot.GetComponentInChildren<RespawnMarker>(true);
                if (any != null) target = any.transform;
            }

            if (target == null)
            {
                TransitionPoint anyTp = CurrentRoot.GetComponentInChildren<TransitionPoint>(true);
                if (anyTp != null) target = anyTp.transform;
            }

            if (target == null)
            {
                Plugin.Log.LogWarning($"Godhome: no entry point in '{sceneName}'; leaving the hero where it is.");
                return;
            }

            Vector3 p = target.position;
            hero.transform.position = new Vector3(p.x, p.y + 1f, hero.transform.position.z);

            var rb = hero.GetComponent<Rigidbody2D>();
            if (rb != null) rb.linearVelocity = Vector2.zero;

            Plugin.Log.LogInfo($"Godhome: placed hero at '{target.name}' {p}.");
        }

        /// <summary>
        /// Builds <paramref name="sceneName"/> into the currently active scene.
        /// Returns true if anything was constructed.
        /// </summary>
        public static bool Build(string sceneName, bool strip = true)
        {
            GodhomeData.BakedScene baked = GodhomeData.Load(sceneName);
            if (baked == null) return false;

            var sw = Stopwatch.StartNew();

            try
            {
                if (strip) StripDonor();

                Texture2D[] pages = GetPages(baked);
                if (pages == null) return false;

                Sprite[] sprites = GetSprites(baked, pages);
                if (sprites == null) return false;

                // Set before Construct so components built during it (the bench) can read it.
                SceneRedirect.CurrentGodhomeScene = sceneName;

                var root = new GameObject(RootName);
                root.transform.position = Vector3.zero;
                CurrentRoot = root;

                int built = Construct(baked, sprites, pages, root.transform);

                EnsureSceneManager();
                ApplySceneBounds(baked);
                ApplySceneLighting(baked);


                Plugin.Log.LogInfo(
                    $"Godhome: rebuilt '{sceneName}' - {built} objects, " +
                    $"{sprites.Length} sprites, {baked.PageNames.Length} page(s) in {sw.ElapsedMilliseconds} ms.");

                // A room baked with its behaviour layer brings its own everything: the
                // boss, the BossSceneController beside it, and the Battle Scene FSMs that
                // start and end the fight. Only fall back to spawning a boss on top when
                // the room predates that.
                try
                {
                    if (HasBehaviour(baked))
                    {
                        if (BossSceneController.Instance == null)
                        {
                            Plugin.Log.LogInfo(
                                "Godhome: room carries its own behaviour but no " +
                                "BossSceneController - installing one.");
                            Godhome.BossSceneHost.Install(root);
                        }
                    }
                    else
                    {
                        // Before the bosses, not after: their FSMs read
                        // BossSceneController.IsBossScene in their very first state, and
                        // that is what decides whether they fight or stand still.
                        Godhome.BossSceneHost.Install(root);
                        BossBuilder.SpawnForScene(sceneName);
                    }
                }
                catch (Exception e)
                {
                    Plugin.Log.LogError($"Godhome: spawning bosses for '{sceneName}' failed: {e}");
                }

                LogDiagnostics("after rebuild");
                return true;
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Godhome: rebuilding '{sceneName}' failed: {e}");
                return false;
            }
        }

        // ------------------------------------------------------------------

        /// <summary>
        /// Empties the donor room of its own scenery, keeping the scene plumbing.
        ///
        /// Only root objects are considered: destroying a root takes its children with
        /// it, and walking the whole tree would be both slower and more likely to orphan
        /// something the game holds a reference to.
        /// </summary>
        private static void StripDonor()
        {
            UnityEngine.SceneManagement.Scene active =
                UnityEngine.SceneManagement.SceneManager.GetActiveScene();
            if (!active.IsValid())
            {
                Plugin.Log.LogWarning("Godhome: no valid active scene to strip.");
                return;
            }

            int destroyed = 0, kept = 0;
            foreach (GameObject go in active.GetRootGameObjects())
            {
                if (go == null) continue;

                string why = KeepReason(go);
                if (why != null)
                {
                    kept++;
                    Plugin.Log.LogInfo($"Godhome:   keeping donor root '{go.name}' ({why}).");
                    continue;
                }

                UnityEngine.Object.Destroy(go);
                destroyed++;
            }

            Plugin.Log.LogInfo($"Godhome: stripped donor room - destroyed {destroyed} roots, kept {kept}.");

            NeutraliseDonorTerrain(active);
        }

        /// <summary>
        /// Silences the donor room's terrain without deleting it.
        ///
        /// The TileMap roots have to survive - GameManager.RefreshTilemapInfo needs a
        /// tk2dTileMap to exist, and CameraController reads the scene's dimensions off it.
        /// But keeping them intact would leave the donor's geometry drawn and solid
        /// underneath Godhome, so Hornet would stand on invisible Bone_05 ledges.
        ///
        /// Disabling the renderers and colliders keeps the component graph (and therefore
        /// the bounds lookup) working while making the terrain neither visible nor solid.
        /// </summary>
        private static void NeutraliseDonorTerrain(UnityEngine.SceneManagement.Scene active)
        {
            int renderers = 0, colliders = 0;

            foreach (GameObject go in active.GetRootGameObjects())
            {
                if (go == null) continue;

                bool isTerrain = false;
                foreach (string n in KeepNames)
                {
                    if (n.IndexOf("TileMap", StringComparison.OrdinalIgnoreCase) >= 0 &&
                        string.Equals(go.name, n, StringComparison.Ordinal))
                    {
                        isTerrain = true;
                        break;
                    }
                }
                if (!isTerrain) continue;

                foreach (Renderer r in go.GetComponentsInChildren<Renderer>(true))
                {
                    if (r.enabled) { r.enabled = false; renderers++; }
                }
                foreach (Collider2D c in go.GetComponentsInChildren<Collider2D>(true))
                {
                    if (c.enabled) { c.enabled = false; colliders++; }
                }
            }

            if (renderers > 0 || colliders > 0)
            {
                Plugin.Log.LogInfo(
                    $"Godhome: neutralised donor terrain - disabled {renderers} renderers, {colliders} colliders.");
            }
        }

        /// <summary>Why this root should survive, or null to destroy it.</summary>
        private static string KeepReason(GameObject go)
        {
            if (go.CompareTag("SceneManager")) return "tagged SceneManager";

            foreach (string n in KeepNames)
            {
                if (string.Equals(go.name, n, StringComparison.Ordinal)) return "infrastructure name";
            }

            foreach (Type t in KeepComponents)
            {
                if (go.GetComponentInChildren(t, true) != null) return t.Name;
            }
            return null;
        }

        /// <summary>
        /// Guarantees the scene has a CustomSceneManager, because GameManager assumes one.
        ///
        /// This is what the black screen was: GameManager.OnNextLevelReady does
        ///
        ///     if (!IsMemoryScene(sm.mapZone))
        ///
        /// with no null check, so a missing (or destroyed) scene manager throws before
        /// FadeSceneIn() is ever reached and the fade never lifts.
        ///
        /// The object is built inactive and activated last: CustomSceneManager.Awake
        /// iterates scenePools, which is null on a freshly added component and would
        /// throw if Awake ran on construction.
        /// </summary>
        private static void EnsureSceneManager()
        {
            GameManager gm = GameManager.instance;
            if (gm == null) return;

            // Prefer the donor room's own scene manager, always. It comes with a
            // configured SceneColorManager - colour curves, lighting, ambient - and a
            // synthetic one does not: CustomSceneManager.Start() calls UpdateScene(),
            // which walks SceneColorManager's AnimationCurves and throws on the null
            // ones. That exception then cascades: GameCameras.StartScene() dies the same
            // way, leaving screenFader_fsm null, and EnterHero() throws on it. One bad
            // scene manager is enough to black-screen the whole load.
            GameObject existing = GameObject.FindGameObjectWithTag("SceneManager");
            CustomSceneManager donor = existing != null
                ? existing.GetComponent<CustomSceneManager>()
                : null;

            if (donor != null)
            {
                if (gm.sm == null) RepointSceneManager(gm, donor);
                Plugin.Log.LogInfo($"Godhome: using the donor's scene manager '{existing.name}'.");
                return;
            }

            Plugin.Log.LogWarning(
                "Godhome: the donor room has no CustomSceneManager - building a bare one. " +
                "Expect flat lighting; pick a different DonorScene if the scene looks wrong.");

            // Built inactive and activated last: Awake iterates scenePools, which is null
            // on a freshly added component.
            var go = new GameObject("Godhome_SceneManager");
            go.SetActive(false);
            try { go.tag = "SceneManager"; }
            catch (Exception) { Plugin.Log.LogWarning("Godhome: no 'SceneManager' tag in this build."); }

            CustomSceneManager csm = go.AddComponent<CustomSceneManager>();
            ComponentInit.FillNulls(csm);
            csm.mapZone = MapZone.NONE;
            go.SetActive(true);

            RepointSceneManager(gm, csm);
        }

        /// <summary>
        /// GameManager.sm has a private setter and is only assigned by FindSceneManager
        /// during SetupSceneRefs, which may not have run yet when we rebuild.
        /// </summary>
        private static void RepointSceneManager(GameManager gm, CustomSceneManager csm)
        {
            FieldInfo backing = AccessTools.Field(typeof(GameManager), "<sm>k__BackingField");
            if (backing == null)
            {
                Plugin.Log.LogError("Godhome: couldn't find GameManager's sm backing field.");
                return;
            }
            backing.SetValue(gm, csm);
            Plugin.Log.LogInfo($"Godhome: repointed GameManager.sm to '{csm.name}'.");
        }

        /// <summary>
        /// Rebuilds a tilemap chunk - Godhome's actual floors, walls and platform tops.
        ///
        /// These are drawn by the tk2d tilemap's generated meshes rather than by sprites,
        /// so a sprite-only rebuild leaves the level's decoration hanging in mid-air over
        /// invisible (but solid) ground.
        /// </summary>
        private static void AddMesh(GameObject go, GodhomeData.ObjectDef d,
                                    GodhomeData.BakedScene baked, Texture2D[] pages)
        {
            if (d.MeshVerts == null || d.MeshTris == null || d.MeshTris.Length == 0) return;

            var mesh = new Mesh { name = go.name + "_mesh" };
            // Chunks run to tens of thousands of vertices; 16-bit indices top out at 65535.
            if (d.MeshVerts.Length > 65000) mesh.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;
            mesh.vertices = d.MeshVerts;
            mesh.uv = d.MeshUVs;
            mesh.triangles = d.MeshTris;
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();

            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            MeshRenderer mr = go.AddComponent<MeshRenderer>();
            mr.enabled = d.MeshEnabled;
            mr.sortingOrder = d.MeshSortingOrder;
            if (d.MeshSortingLayerId != 0 && SortingLayer.IsValid(d.MeshSortingLayerId))
            {
                mr.sortingLayerID = d.MeshSortingLayerId;
            }

            Texture2D tex = (d.MeshPage >= 0 && d.MeshPage < pages.Length) ? pages[d.MeshPage] : null;
            string shader = (d.MeshShaderIndex >= 0 && d.MeshShaderIndex < baked.ShaderNames.Length)
                ? baked.ShaderNames[d.MeshShaderIndex] : null;
            mr.sharedMaterial = MaterialMap.ForMesh(shader, tex);
        }

        private static readonly Dictionary<string, Type> SimpleTypes =
            new Dictionary<string, Type>(StringComparer.Ordinal);

        /// <summary>
        /// Attaches Hollow Knight components that Silksong still has under the same name
        /// and that need no configuring - the component itself is the behaviour.
        /// RestBench is the reason this exists: it does nothing but tell HeroController
        /// it's near a bench.
        /// </summary>
        private static void AddSimpleComponents(GameObject go, GodhomeData.ObjectDef d)
        {
            foreach (string name in d.SimpleComponents)
            {
                if (!SimpleTypes.TryGetValue(name, out Type t))
                {
                    t = AccessTools.TypeByName(name);
                    SimpleTypes[name] = t;
                    if (t == null)
                        Plugin.Log.LogWarning($"Godhome: Silksong has no component called '{name}'; skipping it.");
                }
                if (t == null || !typeof(Component).IsAssignableFrom(t)) continue;

                Component c = go.AddComponent(t);
                ComponentInit.FillNulls(c);
            }
        }

        /// <summary>
        /// Rebuilds a door between Godhome's rooms.
        ///
        /// TransitionPoint survives in Silksong with the same public fields, and it is
        /// what SceneRedirect then catches: walking into one asks for e.g. "GG_Workshop",
        /// which we intercept and rebuild exactly like the Atrium. The gate is also
        /// registered with SceneTeleportMap so the arrival side resolves.
        /// </summary>
        private static void AddTransitionPoint(GameObject go, GodhomeData.ObjectDef d, string sceneName)
        {
            var t = go.AddComponent<TransitionPoint>();
            ComponentInit.FillNulls(t);

            t.targetScene = d.TargetScene;
            t.entryPoint = d.EntryPoint;
            t.entryOffset = d.EntryOffset;
            t.entryDelay = d.EntryDelay;
            t.isADoor = d.IsADoor;
            t.dontWalkOutOfDoor = d.DontWalkOutOfDoor;
            t.alwaysEnterRight = d.AlwaysEnterRight;
            t.alwaysEnterLeft = d.AlwaysEnterLeft;
            t.hardLandOnExit = d.HardLandOnExit;
            t.nonHazardGate = d.NonHazardGate;

            // This gate is an arrival point for whatever room leads here.
            try { SceneTeleportMap.AddTransitionGate(sceneName, go.name); }
            catch (Exception) { /* map is advisory; the transition still works */ }
        }

        /// <summary>
        /// Gives Godhome its own colour grading instead of the donor room's.
        ///
        /// CustomSceneManager.Start() will overwrite these with Silksong's map-zone
        /// defaults unless IsOverridingMapZoneColorSettings() is true, so the private
        /// overrideColorSettings flag has to be set as well - otherwise the values are
        /// applied and then immediately thrown away.
        /// </summary>
        private static void ApplySceneLighting(GodhomeData.BakedScene baked)
        {
            GodhomeData.Lighting l = baked.Light;
            if (l == null) return;

            GameManager gm = GameManager.instance;
            CustomSceneManager sm = gm != null ? gm.sm : null;
            if (sm == null) return;

            try
            {
                sm.darknessLevel = l.DarknessLevel;
                sm.saturation = l.Saturation;
                sm.defaultColor = l.DefaultColor;
                sm.defaultIntensity = l.DefaultIntensity;
                sm.heroLightColor = l.HeroLightColor;
                sm.redChannel = l.Red;
                sm.greenChannel = l.Green;
                sm.blueChannel = l.Blue;

                FieldInfo ov = AccessTools.Field(typeof(CustomSceneManager), "overrideColorSettings");
                if (ov != null) ov.SetValue(sm, true);
                else Plugin.Log.LogWarning("Godhome: overrideColorSettings not found; the grading may be overwritten.");

                // Pushing the values in is the part that matters; UpdateScene only asks
                // the game to act on them and reaches into the hero's light and the
                // colour grading, either of which can be absent this early. Letting it
                // throw used to lose the grading that had already been set.
                try
                {
                    sm.UpdateScene();
                }
                catch (Exception e)
                {
                    Plugin.Log.LogWarning(
                        "Godhome: grading set, but UpdateScene threw: " + e.Message);
                }

                Plugin.Log.LogInfo(
                    $"Godhome: applied Hollow Knight's grading (saturation {l.Saturation:F2}, " +
                    $"darkness {l.DarknessLevel}).");
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning("Godhome: couldn't apply scene lighting: " + e.Message);
            }
        }

        /// <summary>Dump of the things most likely to be wrong after a rebuild.</summary>
        public static void LogDiagnostics(string when)
        {
            try
            {
                // The spawn marker is the single most load-bearing object we create:
                // HeroController.LocateSpawnPoint matches on GameObject name, and
                // GameManager.EnterHero then dereferences fields on whatever it finds.
                int markers = RespawnMarker.Markers != null ? RespawnMarker.Markers.Count : -1;
                bool found = false;
                if (RespawnMarker.Markers != null)
                {
                    foreach (RespawnMarker m in RespawnMarker.Markers)
                    {
                        if (m != null && m.name == GodhomeLoadout.HubSpawnMarker) { found = true; break; }
                    }
                }
                Plugin.Log.LogInfo(
                    $"Godhome: [{when}] respawn markers registered={markers}, " +
                    $"'{GodhomeLoadout.HubSpawnMarker}' present={found}");
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning("Godhome: marker diagnostics failed: " + e.Message);
            }

            try
            {
                GameManager gm = GameManager.instance;
                HeroController hero = HeroController.SilentInstance;
                Camera cam = Camera.main;

                Plugin.Log.LogInfo(
                    $"Godhome: [{when}] sm={(gm != null && gm.sm != null ? gm.sm.name : "NULL")}, " +
                    $"tilemap={(gm != null && gm.tilemap != null ? "ok" : "NULL")}, " +
                    $"hero={(hero != null ? hero.transform.position.ToString("F1") : "NULL")}, " +
                    $"camera={(cam != null ? cam.transform.position.ToString("F1") : "NULL")}, " +
                    $"state={(gm != null ? gm.GameState.ToString() : "?")}");
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning("Godhome: diagnostics failed: " + e.Message);
            }
        }

        // ------------------------------------------------------------------

        private static Texture2D[] GetPages(GodhomeData.BakedScene baked)
        {
            if (PageCache.TryGetValue(baked.Name, out Texture2D[] cachedPages)) return cachedPages;

            var pages = new Texture2D[baked.PageNames.Length];
            for (int i = 0; i < pages.Length; i++)
            {
                pages[i] = GodhomeData.LoadPage(baked.PageNames[i]);
                if (pages[i] == null)
                {
                    Plugin.Log.LogError($"Godhome: '{baked.Name}' can't be built without page '{baked.PageNames[i]}'.");
                    return null;
                }
            }
            PageCache[baked.Name] = pages;
            return pages;
        }

        private static Sprite[] GetSprites(GodhomeData.BakedScene baked, Texture2D[] pages)
        {
            if (SpriteCache.TryGetValue(baked.Name, out Sprite[] cached)) return cached;

            var sprites = new Sprite[baked.Sprites.Length];
            for (int i = 0; i < sprites.Length; i++)
            {
                GodhomeData.SpriteDef d = baked.Sprites[i];
                if (d.Page < 0 || d.Page >= pages.Length) continue;

                // The rect and pivot were converted to Unity's bottom-left convention by
                // the extractor, so this is the same call the engine would have made.
                sprites[i] = Sprite.Create(
                    pages[d.Page], d.Rect, d.Pivot, d.Ppu, 0,
                    SpriteMeshType.FullRect, d.Border, false);
                if (sprites[i] != null) sprites[i].name = d.Name;
            }

            SpriteCache[baked.Name] = sprites;
            return sprites;
        }

        // The room being built, so a component field pointing at another object in it can
        // be resolved. Baked references are indices into this list.
        private static Transform[] _made = new Transform[0];
        private static Dictionary<string, GameObject> _prefabs =
            new Dictionary<string, GameObject>(StringComparer.Ordinal);
        private static Dictionary<string, AudioClip> _behaviourClips =
            new Dictionary<string, AudioClip>(StringComparer.Ordinal);

        private static void OnArenaComplete()
        {
            if (!PantheonRun.IsActive) return;
            Plugin.Log.LogInfo("Godhome: arena complete - advancing the run.");
            PantheonRun.Advance();
        }

        /// <summary>Whether a baked room carries components and FSMs of its own.</summary>
        private static bool HasBehaviour(GodhomeData.BakedScene baked)
        {
            foreach (GodhomeData.ObjectDef o in baked.Objects)
            {
                if ((o.Mask & (GodhomeData.HasFsm | GodhomeData.HasComps)) != 0) return true;
            }
            return false;
        }

        public static GameObject ObjectAt(int index)
        {
            if (index < 0 || index >= _made.Length) return null;
            Transform t = _made[index];
            return t != null ? t.gameObject : null;
        }

        public static GameObject PrefabNamed(string name)
        {
            return !string.IsNullOrEmpty(name) && _prefabs.TryGetValue(name, out GameObject g)
                ? g : null;
        }

        public static AudioClip ClipNamed(string name)
        {
            return !string.IsNullOrEmpty(name) && _behaviourClips.TryGetValue(name, out AudioClip c)
                ? c : null;
        }

        private static int Construct(GodhomeData.BakedScene baked, Sprite[] sprites,
                                     Texture2D[] pages, Transform root)
        {
            var made = new Transform[baked.Objects.Length];
            _made = made;
            var pendingDoors = new List<GodhomeData.ObjectDef>();
            bool verbose = GodhomeConfig.VerboseRebuildLogging.Value;
            int count = 0;

            // The behaviour layer's shared assets, before any object needs them.
            Godhome.BehaviourBuilder.BeginScene(baked, _prefabs, _behaviourClips);

            // Components are added in a second pass and their object references in a
            // third: a field pointing at another object in the room can only be set once
            // that object exists, and Hollow Knight's are full of forward references.
            var deferred = new List<ComponentApplier.Pending>();

            for (int i = 0; i < baked.Objects.Length; i++)
            {
                GodhomeData.ObjectDef d = baked.Objects[i];

                var go = new GameObject(d.Name);
                Transform t = go.transform;

                // Objects are baked parent-before-child, so the parent always exists.
                Transform parent = (d.Parent >= 0 && d.Parent < i) ? made[d.Parent] : root;
                t.SetParent(parent ?? root, false);

                t.localPosition = d.Position;
                t.localRotation = d.Rotation;
                t.localScale = d.Scale;
                go.layer = d.Layer;

                made[i] = t;
                count++;

                if ((d.Mask & GodhomeData.HasSprite) != 0) AddSprite(go, d, sprites, baked.ShaderNames);
                if ((d.Mask & GodhomeData.HasBox) != 0) AddBox(go, d);
                if ((d.Mask & GodhomeData.HasEdge) != 0) AddEdge(go, d);
                if ((d.Mask & GodhomeData.HasPoly) != 0) AddPoly(go, d);
                if ((d.Mask & GodhomeData.HasCamLock) != 0) AddCameraLock(go, d);
                if ((d.Mask & GodhomeData.HasRespawn) != 0) AddRespawnMarker(go, d);
                if ((d.Mask & GodhomeData.HasHazard) != 0) AddHazardMarker(go, d);
                if ((d.Mask & GodhomeData.HasSeqDoor) != 0) AddPantheonDoor(go, d, pendingDoors);
                if ((d.Mask & GodhomeData.HasAudio) != 0) AddAudio(go, d, baked);
                if ((d.Mask & GodhomeData.HasStatue) != 0) AddStatue(go, d);
                if ((d.Mask & GodhomeData.HasMesh) != 0) AddMesh(go, d, baked, pages);
                if ((d.Mask & GodhomeData.HasSimple) != 0) AddSimpleComponents(go, d);
                if ((d.Mask & GodhomeData.HasTransition) != 0) AddTransitionPoint(go, d, baked.Name);

                if ((d.Mask & GodhomeData.HasPhys) != 0) AddPhysics(go, d);
                if ((d.Mask & GodhomeData.HasTk2d) != 0)
                    Godhome.BehaviourBuilder.AddTk2d(go, d.Tk2d);

                // Applied last: deactivating early would stop later children from being
                // parented onto a live object, and AddComponent on an inactive object is
                // fine but the ordering is easier to reason about this way.
                if (!d.Active) go.SetActive(false);

                if (verbose) Plugin.Log.LogInfo($"  + {d.Name} (mask {d.Mask})");
            }

            // Pass two: Hollow Knight's own components, by name.
            //
            // Each object is switched off while its components go on, and switched back
            // on once their fields are set. Unity runs Awake and OnEnable inside
            // AddComponent, but only fills serialised fields when it deserialises - so a
            // component added to a live object wakes up with every array still null.
            // ShineAnimSequence.OnEnable walks its shineObjects array immediately and
            // threw on every one of them. Deactivating first gives these components the
            // order they were written for: fields, then Awake.
            int comps = 0;
            var reactivate = new List<GameObject>();
            for (int i = 0; i < baked.Objects.Length; i++)
            {
                GodhomeData.ObjectDef d = baked.Objects[i];
                if ((d.Mask & GodhomeData.HasComps) == 0 || made[i] == null) continue;

                GameObject go = made[i].gameObject;
                bool wasActive = go.activeSelf;
                if (wasActive)
                {
                    go.SetActive(false);
                    reactivate.Add(go);
                }

                foreach (GodhomeData.ComponentDef c in d.Components)
                {
                    if (ComponentApplier.Apply(go, c, deferred) != null) comps++;
                }
            }

            // Pass three: the references held back until the room existed.
            ComponentApplier.Resolve(deferred);

            // Now they may wake, with everything they expect in place.
            foreach (GameObject go in reactivate)
            {
                if (go != null) go.SetActive(true);
            }

            // BossSceneController.Setup() subscribes to its bosses' OnDeath, which is
            // what ends a Godhome fight. Hollow Knight calls it from Awake, but only when
            // a SetupEvent is pending; here the controller's `bosses` array is a baked
            // reference and does not exist until the pass above, so it is called now.
            BossSceneController bsc = BossSceneController.Instance;
            if (bsc != null)
            {
                try
                {
                    typeof(BossSceneController)
                        .GetMethod("Setup", BindingFlags.NonPublic | BindingFlags.Instance)
                        ?.Invoke(bsc, null);
                    // The room's own controller now decides when the fight is over, so
                    // the Pantheon follows it rather than a key press. This is Hollow
                    // Knight's own signal: BossSceneController fires it once every boss
                    // in its list is dead and the hero is still standing.
                    bsc.OnBossSceneComplete += OnArenaComplete;
                    Plugin.Log.LogInfo("Godhome: BossSceneController from the room is set up.");
                }
                catch (Exception e)
                {
                    Plugin.Log.LogWarning("Godhome: BossSceneController.Setup failed: " + e.Message);
                }
            }

            // Pass four: behaviour. FSMs last of all, because their first state reads the
            // components and children the earlier passes created.
            int fsms = 0;
            for (int i = 0; i < baked.Objects.Length; i++)
            {
                GodhomeData.ObjectDef d = baked.Objects[i];
                if ((d.Mask & GodhomeData.HasFsm) == 0 || made[i] == null) continue;
                fsms += Godhome.BehaviourBuilder.AddFsms(made[i].gameObject, d.Fsms);
            }

            // Anything with a HealthManager is a boss as far as diagnosis goes. Tracing
            // its FSM state changes is the fastest way to tell a boss that is
            // misbehaving from one sitting in a state waiting for an event.
            if (GodhomeConfig.TraceBossStates.Value)
            {
                foreach (HealthManager hm in root.GetComponentsInChildren<HealthManager>(true))
                {
                    if (hm != null && hm.GetComponent<Godhome.BossTrace>() == null)
                        hm.gameObject.AddComponent<Godhome.BossTrace>();
                }
            }

            if (comps > 0 || fsms > 0)
            {
                Plugin.Log.LogInfo(
                    $"Godhome: behaviour - {comps} components, {fsms} FSMs, " +
                    $"{_prefabs.Count} prefabs, {deferred.Count} references resolved.");
            }

            UnlockDoors(pendingDoors, made);

            return count;
        }

        /// <summary>
        /// A body and its round hitboxes. Without the Rigidbody2D a boss is scenery:
        /// every SetVelocity2d in its FSM pushes one, and Recoil needs one to knock back.
        /// </summary>
        private static void AddPhysics(GameObject go, GodhomeData.ObjectDef d)
        {
            if (d.HasBody)
            {
                var rb = go.AddComponent<Rigidbody2D>();
                rb.mass = d.Mass;
                rb.gravityScale = d.GravityScale;
                rb.linearDamping = d.LinearDrag;
                rb.angularDamping = d.AngularDrag;
                rb.bodyType = (RigidbodyType2D)d.BodyType;
                rb.constraints = (RigidbodyConstraints2D)d.Constraints;
                rb.collisionDetectionMode = (CollisionDetectionMode2D)d.CollisionDetection;
                rb.interpolation = (RigidbodyInterpolation2D)d.Interpolate;
            }

            foreach (GodhomeData.CircleDef c in d.Circles ?? new GodhomeData.CircleDef[0])
            {
                var cc = go.AddComponent<CircleCollider2D>();
                cc.offset = c.Offset;
                cc.radius = c.Radius;
                cc.isTrigger = c.Trigger;
                cc.enabled = c.Enabled;
            }
        }

        private static void AddSprite(GameObject go, GodhomeData.ObjectDef d, Sprite[] sprites,
                                      string[] shaderNames)
        {
            if (d.SpriteIndex < 0 || d.SpriteIndex >= sprites.Length) return;
            Sprite s = sprites[d.SpriteIndex];
            if (s == null) return;

            SpriteRenderer sr = go.AddComponent<SpriteRenderer>();

            // Godhome's glows and dream beams are screen-blended; the default sprite
            // material would draw them as opaque white.
            if (d.ShaderIndex >= 0 && d.ShaderIndex < shaderNames.Length)
            {
                Material m = MaterialMap.For(shaderNames[d.ShaderIndex]);
                if (m != null) sr.sharedMaterial = m;
            }

            sr.sprite = s;
            sr.color = d.Color;
            sr.flipX = d.FlipX;
            sr.flipY = d.FlipY;
            sr.enabled = d.RendererEnabled;

            sr.sortingOrder = d.SortingOrder;

            // The two games' sorting layers are the same list with the same uniqueIDs -
            // Silksong only appends 'Scene Border' and 'Inventory' - so Hollow Knight's
            // IDs transfer directly. Most of Godhome sits on Default, but the 28
            // renderers on 'Over' need it to draw in front.
            if (d.SortingLayerId != 0 && SortingLayer.IsValid(d.SortingLayerId))
            {
                sr.sortingLayerID = d.SortingLayerId;
            }
        }

        private static void AddBox(GameObject go, GodhomeData.ObjectDef d)
        {
            foreach (GodhomeData.BoxDef b in d.Boxes)
            {
                BoxCollider2D c = go.AddComponent<BoxCollider2D>();
                c.offset = b.Offset;
                c.size = b.Size;
                c.isTrigger = b.Trigger;
                c.enabled = b.Enabled;
            }
        }

        private static void AddEdge(GameObject go, GodhomeData.ObjectDef d)
        {
            foreach (GodhomeData.EdgeDef e in d.Edges)
            {
                if (e.Points == null || e.Points.Length < 2) continue;
                EdgeCollider2D c = go.AddComponent<EdgeCollider2D>();
                c.offset = e.Offset;
                c.points = e.Points;
                c.isTrigger = e.Trigger;
                c.enabled = e.Enabled;
            }
        }

        /// <summary>
        /// CameraLockArea still exists in Silksong with the same public fields
        /// (cameraXMin/YMin/XMax/YMax, preventLookUp, preventLookDown, maxPriority), so
        /// Godhome's camera behaviour is re-attached rather than reimplemented.
        /// Silksong added lookYMin/lookYMax/priority, which Hollow Knight didn't have;
        /// leaving those at their defaults is the correct no-op.
        /// </summary>
        private static void AddCameraLock(GameObject go, GodhomeData.ObjectDef d)
        {
            var c = go.AddComponent<CameraLockArea>();
            ComponentInit.FillNulls(c);
            c.cameraXMin = d.CamXMin;
            c.cameraYMin = d.CamYMin;
            c.cameraXMax = d.CamXMax;
            c.cameraYMax = d.CamYMax;
            c.preventLookUp = d.PreventLookUp;
            c.preventLookDown = d.PreventLookDown;
        }

        /// <summary>
        /// HeroController.LocateSpawnPoint() matches on the *GameObject* name, which the
        /// rebuild already preserves - so Hollow Knight's own "Death Respawn Marker"
        /// works as the Godseeker spawn without inventing anything.
        /// </summary>
        private static void AddRespawnMarker(GameObject go, GodhomeData.ObjectDef d)
        {
            var m = go.AddComponent<RespawnMarker>();
            ComponentInit.FillNulls(m);
            m.respawnFacingRight = d.RespawnFacingRight;

            // GameManager.GetRespawnInfo validates a saved respawn point against
            // SceneTeleportMap and silently falls back to Tut_01 on a miss, so every
            // marker we rebuild has to be registered - not just the Godseeker spawn.
            try { SceneTeleportMap.AddRespawnPoint(SceneRedirect.CurrentGodhomeScene, go.name); }
            catch (Exception) { }

            // Godhome's bench is a RespawnMarker on an object called "RestBench" - the
            // same object that carries the RestBench component. Attaching the bench
            // behaviour here means it always lands on the marker the respawn path uses.
            if (go.name.StartsWith("RestBench", StringComparison.Ordinal))
            {
                var bench = go.AddComponent<GodhomeBench>();
                bench.SceneName = SceneRedirect.CurrentGodhomeScene;
            }
        }

        /// <summary>
        /// Attaches our Pantheon entrance. See <see cref="PantheonDoor"/> for why the real
        /// BossSequenceDoor isn't used - short version: it needs a dozen wired prefab
        /// references we can't reconstruct, but the thing that actually starts a run
        /// (BossSequenceController.SetupNewSequence) is public and is what we call.
        /// </summary>
        private static readonly Dictionary<string, AudioClip> ClipCache =
            new Dictionary<string, AudioClip>(StringComparer.Ordinal);

        /// <summary>
        /// Godhome's ambience and one-shots - waterfalls, the golden hum, door locks.
        /// Clips are cached across scenes, since several rooms share the same sounds.
        /// </summary>
        private static void AddAudio(GameObject go, GodhomeData.ObjectDef d, GodhomeData.BakedScene baked)
        {
            if (baked.Clips == null || d.ClipIndex < 0 || d.ClipIndex >= baked.Clips.Length) return;

            GodhomeData.ClipDef def = baked.Clips[d.ClipIndex];
            if (def == null) return;

            if (!ClipCache.TryGetValue(def.Name, out AudioClip clip))
            {
                clip = GodhomeData.LoadClip(def);
                ClipCache[def.Name] = clip;
            }
            if (clip == null) return;

            AudioSource src = go.AddComponent<AudioSource>();
            src.clip = clip;
            src.volume = d.Volume;
            src.pitch = d.Pitch;
            src.loop = d.Loop;
            src.playOnAwake = d.PlayOnAwake;
            src.spatialBlend = d.SpatialBlend;
            src.enabled = d.AudioEnabled;

            // AddComponent misses the playOnAwake window, so anything that should already
            // be sounding has to be started by hand.
            if (d.PlayOnAwake && d.AudioEnabled && go.activeInHierarchy) src.Play();
        }

        /// <summary>
        /// A Hall of Gods plinth. See <see cref="GodhomeStatue"/> for why the real
        /// BossStatue isn't attached - its state lives in per-boss PlayerData fields that
        /// don't exist in a Silksong save.
        /// </summary>
        private static void AddStatue(GameObject go, GodhomeData.ObjectDef d)
        {
            if (string.IsNullOrEmpty(d.StatueBoss) && string.IsNullOrEmpty(d.StatueDream)) return;

            var st = go.AddComponent<GodhomeStatue>();
            st.BossScene = d.StatueBoss;
            st.DreamBossScene = d.StatueDream;
            st.Range = 3.5f;
        }

        private static void AddPantheonDoor(GameObject go, GodhomeData.ObjectDef d,
                                            List<GodhomeData.ObjectDef> pending)
        {
            // Queued regardless of whether the door leads anywhere. GG_Atrium's fifth
            // door carries no sequence (Hollow Knight only opens it once the other four
            // are done), and skipping it entirely left its padlock on screen - which
            // reads as "one of the Pantheons is still locked".
            pending.Add(d);

            if (string.IsNullOrEmpty(d.DoorSequence)) return;

            var door = go.AddComponent<PantheonDoor>();
            door.SequenceName = d.DoorSequence;
            door.PlayerDataName = d.DoorPlayerData;
            door.Range = 3.5f;
        }

        /// <summary>
        /// What BossSequenceDoor.Start() does for an unlocked door: hide the padlock,
        /// reveal the open state, drop the "inspect the lock" prompt. Without it the
        /// Pantheons are enterable but still look sealed.
        /// </summary>
        private static void UnlockDoors(List<GodhomeData.ObjectDef> doors, Transform[] made)
        {
            foreach (GodhomeData.ObjectDef d in doors)
            {
                SetActiveByIndex(made, d.DoorLockSet, false);
                SetActiveByIndex(made, d.DoorPrompt, false);
                SetActiveByIndex(made, d.DoorUnlockedSet, true);
            }
            if (doors.Count > 0) Plugin.Log.LogInfo($"Godhome: unlocked {doors.Count} pantheon door(s).");
        }

        private static void SetActiveByIndex(Transform[] made, int index, bool active)
        {
            if (index < 0 || index >= made.Length) return;
            Transform t = made[index];
            if (t != null) t.gameObject.SetActive(active);
        }

        /// <summary>
        /// Silksong reworked HazardRespawnMarker's facing into a private
        /// FacingDirection enum, so unlike RespawnMarker there's no public field to set.
        /// The component alone is what matters - it's the hazard respawn point - and the
        /// facing is a cosmetic detail, so it's set by reflection when the old field is
        /// still there and skipped when it isn't.
        /// </summary>
        private static void AddHazardMarker(GameObject go, GodhomeData.ObjectDef d)
        {
            var m = go.AddComponent<HazardRespawnMarker>();
            ComponentInit.FillNulls(m);

            FieldInfo f = AccessTools.Field(typeof(HazardRespawnMarker), "respawnFacingRight");
            if (f != null && f.FieldType == typeof(bool))
            {
                try { f.SetValue(m, d.HazardFacingRight); }
                catch { /* cosmetic only */ }
            }
        }

        /// <summary>
        /// Points the camera at Godhome's dimensions instead of the donor room's.
        ///
        /// CameraController normally reads these off the scene's tk2dTileMap
        /// (sceneWidth = tilemap.width, xLimit = sceneWidth - 14.6f). The donor keeps its
        /// own tilemap - GameManager.RefreshTilemapInfo needs one to exist - so we resize
        /// that tilemap to Godhome's bounds and push the derived limits through.
        /// </summary>
        private static void ApplySceneBounds(GodhomeData.BakedScene baked)
        {
            if (baked.Width <= 0f || baked.Height <= 0f) return;

            GameManager gm = GameManager.instance;
            if (gm == null) return;

            try
            {
                tk2dTileMap tilemap = gm.tilemap;
                if (tilemap != null)
                {
                    tilemap.width = Mathf.RoundToInt(baked.Width);
                    tilemap.height = Mathf.RoundToInt(baked.Height);
                }

                gm.sceneWidth = baked.Width;
                gm.sceneHeight = baked.Height;

                CameraController cam = gm.cameraCtrl;
                if (cam != null)
                {
                    cam.sceneWidth = baked.Width;
                    cam.sceneHeight = baked.Height;
                    // Same derivation CameraController uses itself.
                    cam.xLimit = baked.Width - 14.6f;
                    cam.yLimit = baked.Height - 8.3f;
                }

                Plugin.Log.LogInfo($"Godhome: scene bounds set to {baked.Width} x {baked.Height}.");
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning("Godhome: couldn't apply scene bounds: " + e.Message);
            }
        }

        private static void AddPoly(GameObject go, GodhomeData.ObjectDef d)
        {
            foreach (GodhomeData.PolyDef p in d.Polys)
            {
                if (p.Paths == null || p.Paths.Length == 0) continue;
                PolygonCollider2D c = go.AddComponent<PolygonCollider2D>();
                c.offset = p.Offset;
                c.pathCount = p.Paths.Length;
                for (int i = 0; i < p.Paths.Length; i++) c.SetPath(i, p.Paths[i]);
                c.isTrigger = p.Trigger;
                c.enabled = p.Enabled;
            }
        }
    }
}
