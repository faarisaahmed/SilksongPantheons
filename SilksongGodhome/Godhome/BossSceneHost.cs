using System;
using System.Reflection;
using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// Puts a <see cref="BossSceneController"/> in a rebuilt arena, because Hollow
    /// Knight's bosses ask whether they are in one.
    ///
    /// This was the single biggest behaviour bug in the port. Silksong still ships every
    /// Godhome PlayMaker action, and three of them branch on this one object:
    ///
    ///   GGCheckIfBossScene            - fires bossSceneEvent if IsBossScene, else
    ///                                   regularSceneEvent
    ///   CheckGGBossLevel              - level1/2/3 from BossLevel, else notGG
    ///   GGWaitForBossSceneTransitionIn- only fires its finish event once
    ///                                   HasTransitionedIn is true
    ///
    /// and `IsBossScene` is simply `Instance != null`. With no instance, every boss took
    /// its normal-game branch:
    ///
    ///   False Knight's Dormant state runs SetPosition - which pins him above the arena
    ///   ready to drop in - and only leaves on BATTLE START, the event
    ///   GGCheckIfBossScene fires in a boss scene. Without it he stood at the top of the
    ///   room forever.
    ///
    ///   Mega Moss Charger's Init routes GG BOSS -> GG Pause -> Shake -> emerge. Without
    ///   it, FINISHED took it to Sleep, waiting on a dream-nail hit that never comes.
    ///
    ///   And GGWaitForBossSceneTransitionIn never finishing is a silent hang: the FSM
    ///   sits in a state whose only exit is an event it will never receive.
    ///
    /// The instance is deliberately kept dormant. Awake would call
    /// BossSequenceController.CheckLoadSequence, which pulls on Silksong's sequence
    /// loading for a BossSequence that does not exist here, and Start would try to
    /// instantiate a transition prefab we cannot bring across. Adding the component to an
    /// inactive GameObject skips both - Unity runs neither Awake nor Start - and the
    /// static Instance is public, so it can be assigned directly. The fields Awake would
    /// have set are set here instead.
    /// </summary>
    internal static class BossSceneHost
    {
        /// <summary>
        /// Attuned. Hollow Knight's Pantheon of the Master runs at boss level 0, and
        /// CheckGGBossLevel maps 0 -> level1.
        /// </summary>
        public const int AttunedLevel = 0;

        public static BossSceneController Install(GameObject parent, int bossLevel = AttunedLevel)
        {
            try
            {
                if (BossSceneController.Instance != null)
                {
                    BossSceneController.Instance.BossLevel = bossLevel;
                    return BossSceneController.Instance;
                }

                var go = new GameObject("Godhome_BossSceneController");
                if (parent != null) go.transform.SetParent(parent.transform, false);

                // Inactive *before* AddComponent, so Awake never runs.
                go.SetActive(false);
                var c = go.AddComponent<BossSceneController>();

                // Everything Awake and Setup would have done, minus the sequence load.
                c.bosses = new HealthManager[0];
                c.doTransitionIn = false;
                c.doTransitionOut = false;
                c.transitionInHoldTime = 0f;
                c.transitionOutHoldTime = 0f;
                c.BossLevel = bossLevel;
                c.CanTransition = true;

                // ReportHealth writes into this dictionary for any boss it is told about,
                // and HealthManager calls it unconditionally. Awake builds it; we must.
                SetPrivate(c, "BossHealthLookup",
                    new System.Collections.Generic.Dictionary<HealthManager,
                        BossSceneController.BossHealthDetails>());

                // The arena is already built and the hero is already standing in it, so
                // the transition is, as far as any boss is concerned, over.
                SetPrivate(c, "HasTransitionedIn", true);

                BossSceneController.Instance = c;
                Plugin.Log.LogInfo(
                    $"Godhome: installed BossSceneController (level {bossLevel}) - " +
                    "GG boss FSMs will now take their Godhome branch.");
                return c;
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Godhome: couldn't install BossSceneController: {e}");
                return null;
            }
        }

        /// <summary>
        /// Clears the static so a destroyed controller never lingers.
        ///
        /// OnDestroy would normally do this, but Unity only calls OnDestroy on a
        /// component whose Awake ran - and this one's deliberately never did. In practice
        /// `Instance != null` is already false for a destroyed object, so this is
        /// tidiness rather than a fix.
        /// </summary>
        public static void Clear()
        {
            if (BossSceneController.Instance == null) BossSceneController.Instance = null;
        }

        private static void SetPrivate(object target, string propertyName, object value)
        {
            PropertyInfo p = typeof(BossSceneController)
                .GetProperty(propertyName, BindingFlags.Public | BindingFlags.Instance);
            MethodInfo setter = p != null ? p.GetSetMethod(nonPublic: true) : null;
            if (setter != null)
            {
                setter.Invoke(target, new[] { value });
                return;
            }

            FieldInfo f = typeof(BossSceneController).GetField(
                "<" + propertyName + ">k__BackingField",
                BindingFlags.NonPublic | BindingFlags.Instance);
            if (f != null) f.SetValue(target, value);
            else Plugin.Log.LogWarning($"Godhome: BossSceneController.{propertyName} not settable.");
        }
    }
}
