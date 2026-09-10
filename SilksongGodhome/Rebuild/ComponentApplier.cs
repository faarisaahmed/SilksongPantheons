using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using UnityEngine;

namespace SilksongGodhome.Rebuild
{
    /// <summary>
    /// Adds a Hollow Knight component to a rebuilt object and configures it.
    ///
    /// This is what makes an arena a place rather than a picture of one. Silksong still
    /// defines nearly every component Godhome uses - 1863 of the 1892 instances across
    /// the Pantheon of the Master arenas have a type of the same name - so Recoil,
    /// EnemyDeathEffects, AlertRange, MusicRegion, BossSceneController and the rest are
    /// the game's own classes, running the game's own code.
    ///
    /// Fields are matched by *name*, never by position. Hollow Knight's HealthManager and
    /// Silksong's are five years apart and are not the same class; a positional copy
    /// would be nonsense. Anything Silksong has dropped is skipped, anything it has added
    /// keeps its default, and a value that will not convert is left alone rather than
    /// forced.
    /// </summary>
    internal static class ComponentApplier
    {
        // Wire kinds, mirroring compbake.py.
        private const int KBool = 0, KI32 = 1, KI64 = 2, KF32 = 3, KF64 = 4, KString = 5;
        private const int KVec2 = 6, KVec3 = 7, KVec4 = 8, KRef = 9, KArray = 10, KInline = 11;

        private const BindingFlags Fields =
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;

        private static readonly Dictionary<string, Type> TypeCache =
            new Dictionary<string, Type>(StringComparer.Ordinal);

        /// <summary>Names we deliberately never rebuild, with the reason.</summary>
        private static readonly HashSet<string> Skip = new HashSet<string>(StringComparer.Ordinal)
        {
            // Built by the geometry pass from baked data, and adding a second would
            // fight it.
            "tk2dSprite", "tk2dSpriteAnimator", "tk2dTileMap", "PlayMakerFSM",
            // Silksong's is CustomSceneManager, configured by SceneRebuilder itself.
            "SceneManager",
            // Would re-enter the scene loading we are standing inside.
            "SceneAdditiveLoadConditional", "ScenePreloader",

            // Components whose meaning belongs to the host game's camera rig rather than
            // to Godhome's content. These are the ones that took the background away.
            //
            // BlurPlane is the culprit. Silksong's camera does, every frame:
            //
            //     BlurPlane closestBlurPlane = BlurPlane.ClosestBlurPlane;
            //     if (closestBlurPlane != null)
            //         sceneCamera.farClipPlane = closestBlurPlane.PlaneZ - sceneCamera.z + eps;
            //
            // so eleven blur planes rebuilt at Hollow Knight's Z pulled Silksong's far
            // clip plane in and clipped everything behind it. The boss sits near z=0 and
            // survived; the architecture did not. The cost of skipping it is no
            // background blur, which is a great deal better than no background.
            "BlurPlane",
            // Deactivates its own GameObject when |world z - 0.004| exceeds a limit.
            // Same problem from the other side: a depth convention that does not
            // survive the move between two camera setups.
            "DisableIfZPos",
            // Rewrites transform.position.z, and can deParent - which would let an
            // object escape GodhomeRoot and leak into the next room. The baked transform
            // already carries the z it would set.
            "SetZ",
        };

        public static Type Resolve(string name)
        {
            if (string.IsNullOrEmpty(name)) return null;
            if (TypeCache.TryGetValue(name, out Type t)) return t;

            t = Type.GetType(name + ", Assembly-CSharp") ?? Type.GetType(name);
            if (t == null)
            {
                foreach (Assembly a in AppDomain.CurrentDomain.GetAssemblies())
                {
                    t = a.GetType(name, false);
                    if (t != null) break;
                }
            }
            TypeCache[name] = t;
            return t;
        }

        public sealed class Pending
        {
            public Component Target;
            public GodhomeData.FieldDef Field;
            public FieldInfo Info;
        }

        /// <summary>
        /// Adds one component and sets what it can. References to other objects in the
        /// room are collected into <paramref name="deferred"/> instead of being set now,
        /// because the object being pointed at may not exist yet.
        /// </summary>
        public static Component Apply(GameObject go, GodhomeData.ComponentDef def,
                                      List<Pending> deferred)
        {
            if (def == null || string.IsNullOrEmpty(def.TypeName)) return null;
            if (Skip.Contains(def.TypeName)) return null;

            Type t = Resolve(def.TypeName);
            if (t == null || !typeof(Component).IsAssignableFrom(t)) return null;

            Component c;
            try
            {
                c = go.GetComponent(t) ?? go.AddComponent(t);
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"Godhome: couldn't add {def.TypeName} to '{go.name}': {e.Message}");
                return null;
            }
            if (c == null) return null;

            // AddComponent leaves [Serializable] fields and arrays null, and this game's
            // code rarely checks. Same trap as everywhere else in this project.
            ComponentInit.FillNulls(c);

            foreach (GodhomeData.FieldDef f in def.Fields ?? new GodhomeData.FieldDef[0])
            {
                FieldInfo fi = t.GetField(f.Name, Fields);
                if (fi == null || fi.IsStatic || fi.IsLiteral) continue;

                if (NeedsDeferral(f))
                {
                    deferred.Add(new Pending { Target = c, Field = f, Info = fi });
                    continue;
                }
                TrySet(c, fi, f);
            }
            return c;
        }

        private static bool NeedsDeferral(GodhomeData.FieldDef f)
        {
            if (f.Kind == KRef) return f.RefObject >= 0;
            if (f.Kind == KArray && f.ElemKind == KRef) return true;
            if (f.Kind == KInline && f.Fields != null)
            {
                foreach (GodhomeData.FieldDef s in f.Fields)
                {
                    if (NeedsDeferral(s)) return true;
                }
            }
            return false;
        }

        /// <summary>
        /// Applies a baked field set to something that already exists - a ScriptableObject
        /// rather than a component. Same encoding, same rules.
        /// </summary>
        public static void ApplyTo(object target, GodhomeData.ComponentDef def)
        {
            if (target == null || def?.Fields == null) return;
            Type t = target.GetType();
            foreach (GodhomeData.FieldDef f in def.Fields)
            {
                FieldInfo fi = t.GetField(f.Name, Fields);
                if (fi == null || fi.IsStatic || fi.IsLiteral) continue;
                TrySet(target, fi, f);
            }
        }

        /// <summary>Sets the references held back until the whole room exists.</summary>
        public static void Resolve(List<Pending> deferred)
        {
            foreach (Pending p in deferred)
            {
                if (p.Target == null) continue;
                TrySet(p.Target, p.Info, p.Field);
            }
        }

        private static void TrySet(object target, FieldInfo fi, GodhomeData.FieldDef f)
        {
            try
            {
                object v = Convert(f, fi.FieldType);
                if (v != NoValue) fi.SetValue(target, v);
            }
            catch (Exception)
            {
                // A field that will not take the value keeps its default. Never worth
                // an exception: one awkward field must not cost the whole component.
            }
        }

        /// <summary>Sentinel for "leave this field alone".</summary>
        private static readonly object NoValue = new object();

        private static object Convert(GodhomeData.FieldDef f, Type want)
        {
            switch (f.Kind)
            {
                case KBool:
                    return want == typeof(bool) ? (object)f.B : NoValue;

                case KI32:
                case KI64:
                {
                    long l = f.Kind == KI32 ? f.I : f.L;
                    if (want.IsEnum) return Enum.ToObject(want, l);
                    if (want == typeof(int)) return (int)l;
                    if (want == typeof(long)) return l;
                    if (want == typeof(short)) return (short)l;
                    if (want == typeof(byte)) return (byte)l;
                    if (want == typeof(uint)) return (uint)l;
                    if (want == typeof(float)) return (float)l;
                    if (want == typeof(bool)) return l != 0;
                    if (want == typeof(LayerMask)) return (LayerMask)(int)l;
                    return NoValue;
                }

                case KF32:
                case KF64:
                {
                    double d = f.Kind == KF32 ? f.F : f.D;
                    if (want == typeof(float)) return (float)d;
                    if (want == typeof(double)) return d;
                    if (want == typeof(int)) return (int)d;
                    return NoValue;
                }

                case KString:
                    return want == typeof(string) ? (object)(f.S ?? "") : NoValue;

                case KVec2:
                    if (want == typeof(Vector2)) return new Vector2(f.V.x, f.V.y);
                    return NoValue;

                case KVec3:
                    if (want == typeof(Vector3)) return new Vector3(f.V.x, f.V.y, f.V.z);
                    return NoValue;

                case KVec4:
                    if (want == typeof(Vector4)) return f.V;
                    if (want == typeof(Color)) return new Color(f.V.x, f.V.y, f.V.z, f.V.w);
                    if (want == typeof(Quaternion)) return new Quaternion(f.V.x, f.V.y, f.V.z, f.V.w);
                    if (want == typeof(Rect)) return new Rect(f.V.x, f.V.y, f.V.z, f.V.w);
                    return NoValue;

                case KRef:
                {
                    UnityEngine.Object o = Reference(f, want);
                    return o != null ? (object)o : NoValue;
                }

                case KArray:
                {
                    Type elem = want.IsArray ? want.GetElementType()
                              : (want.IsGenericType ? want.GetGenericArguments()[0] : null);
                    if (elem == null) return NoValue;

                    var items = new List<object>();
                    foreach (GodhomeData.FieldDef e in f.Items ?? new GodhomeData.FieldDef[0])
                    {
                        object v = Convert(e, elem);
                        items.Add(v == NoValue ? null : v);
                    }

                    if (want.IsArray)
                    {
                        Array arr = Array.CreateInstance(elem, items.Count);
                        for (int i = 0; i < items.Count; i++)
                        {
                            if (items[i] != null) arr.SetValue(items[i], i);
                        }
                        return arr;
                    }

                    var list = (IList)Activator.CreateInstance(want);
                    foreach (object v in items) list.Add(v);
                    return list;
                }

                case KInline:
                {
                    // A [Serializable] struct or class, rebuilt field by field.
                    object inst;
                    try { inst = Activator.CreateInstance(want); }
                    catch (Exception) { return NoValue; }

                    foreach (GodhomeData.FieldDef s in f.Fields ?? new GodhomeData.FieldDef[0])
                    {
                        FieldInfo sfi = want.GetField(s.Name, Fields);
                        if (sfi == null) continue;
                        object v = Convert(s, sfi.FieldType);
                        if (v != NoValue) sfi.SetValue(inst, v);
                    }
                    return inst;
                }
            }
            return NoValue;
        }

        private static UnityEngine.Object Reference(GodhomeData.FieldDef f, Type want)
        {
            // An object in this room.
            if (f.RefObject >= 0)
            {
                GameObject g = SceneRebuilder.ObjectAt(f.RefObject);
                if (g == null) return null;
                if (want == typeof(GameObject)) return g;
                if (string.IsNullOrEmpty(f.RefComponent))
                    return typeof(Component).IsAssignableFrom(want) ? g.GetComponent(want) : g;

                Type ct = Resolve(f.RefComponent);
                Component c = ct != null ? g.GetComponent(ct) : null;
                if (c == null && typeof(Component).IsAssignableFrom(want)) c = g.GetComponent(want);
                return c;
            }

            // A baked asset: a prefab we rebuilt, or a sound.
            if (!string.IsNullOrEmpty(f.RefAsset))
            {
                GameObject prefab = SceneRebuilder.PrefabNamed(f.RefAsset);
                if (prefab != null)
                {
                    if (want == typeof(GameObject)) return prefab;
                    if (typeof(Component).IsAssignableFrom(want)) return prefab.GetComponent(want);
                    return prefab;
                }
                if (want == typeof(AudioClip)) return SceneRebuilder.ClipNamed(f.RefAsset);

                ScriptableObject so = Godhome.BehaviourBuilder.AssetNamed(f.RefAsset);
                if (so != null && want.IsInstanceOfType(so)) return so;
            }
            return null;
        }
    }
}
