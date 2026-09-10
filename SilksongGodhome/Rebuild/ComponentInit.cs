using System;
using System.Collections;
using System.Reflection;
using UnityEngine;

namespace SilksongGodhome.Rebuild
{
    /// <summary>
    /// Fills in the fields Unity would have populated if a component had come from a
    /// scene instead of from AddComponent.
    ///
    /// When Unity deserialises a component out of a scene it constructs every
    /// [Serializable] class field and every array. AddComponent at runtime does not - it
    /// only runs C# field initialisers - so any such field without an initialiser is
    /// left null, and game code that never expects null happily dereferences it.
    ///
    /// This has bitten this mod twice:
    ///
    ///   * CustomSceneManager.scenePools (an array) - Awake foreaches it.
    ///   * RespawnMarker.customFadeDuration (an OverrideFloat) - GameManager.EnterHero
    ///     reads `!respawnMarker.customFadeDuration.IsEnabled`, with no null check, and
    ///     only reaches it when the marker *was* found. So a correctly rebuilt spawn
    ///     point was what broke the load.
    ///
    /// Rather than hand-patch each field as it turns up, fill them all generically.
    /// Defaults match what an unconfigured scene object would hold (OverrideValue's
    /// IsEnabled defaults to false, empty arrays, empty lists).
    /// </summary>
    internal static class ComponentInit
    {
        public static void FillNulls(Component c)
        {
            if (c == null) return;

            try
            {
                foreach (FieldInfo f in c.GetType().GetFields(
                             BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
                {
                    if (!IsSerialised(f)) continue;
                    if (f.GetValue(c) != null) continue;

                    object filled = MakeDefault(f.FieldType);
                    if (filled != null) f.SetValue(c, filled);
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"Godhome: couldn't initialise {c.GetType().Name}: {e.Message}");
            }
        }

        private static bool IsSerialised(FieldInfo f)
        {
            if (f.IsStatic || f.IsInitOnly) return false;
            if (f.IsPublic) return true;
            return f.IsDefined(typeof(SerializeField), inherit: true);
        }

        private static object MakeDefault(Type t)
        {
            // Value types are never null, and strings are legitimately null.
            if (t.IsValueType || t == typeof(string)) return null;

            // Never fabricate a UnityEngine.Object - a fake Sprite or Transform would be
            // far worse than the null the game can at least test for.
            if (typeof(UnityEngine.Object).IsAssignableFrom(t)) return null;

            if (t.IsArray)
            {
                Type element = t.GetElementType();
                return element != null ? Array.CreateInstance(element, 0) : null;
            }

            if (t.IsGenericType && typeof(IEnumerable).IsAssignableFrom(t))
            {
                try { return Activator.CreateInstance(t); }
                catch { return null; }
            }

            // A [Serializable] class with a usable parameterless constructor is exactly
            // what Unity would have built during deserialisation.
            if (t.IsClass && !t.IsAbstract &&
                t.IsDefined(typeof(SerializableAttribute), inherit: false) &&
                t.GetConstructor(Type.EmptyTypes) != null)
            {
                try { return Activator.CreateInstance(t); }
                catch { return null; }
            }

            return null;
        }
    }
}
