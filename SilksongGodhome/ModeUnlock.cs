using System;
using UnityEngine;
using UnityEngine.UI;

namespace SilksongGodhome
{
    /// <summary>
    /// Reveals Silksong's own, already-built boss-rush entry in the play-mode menu.
    ///
    /// We deliberately don't clone a button here. Menu_Title already contains three
    /// StartGameEventTrigger components - (permaDeath 0, bossRush 0), (permaDeath 1,
    /// bossRush 0) and (permaDeath 0, bossRush 1). That third one is a fully authored
    /// menu entry with the right fonts, animators, flash effects, audio hooks and
    /// controller navigation already wired up; it's just gated off. Unhiding the real
    /// thing is both less code and more faithful than rebuilding it.
    ///
    /// The gate is StartGameEventTrigger.IsFulfilled():
    ///
    ///     if (bossRush &amp;&amp; GameManager.instance.GetStatusRecordInt("RecBossRushMode") == 0)
    ///         result = false;
    ///
    /// Status records are the game's own persistent unlock flags (Steel Soul uses the
    /// same mechanism via "RecPermadeathMode"), so setting it once sticks.
    /// </summary>
    internal static class ModeUnlock
    {
        /// <summary>
        /// Flips the record on. Called from a postfix on GameManager.SetupStatusModifiers,
        /// which is where the game itself would set this if gameConfig.unlockBossRushMode
        /// were true - so it lands at exactly the right point in the boot sequence,
        /// before the menu evaluates its button conditions.
        /// </summary>
        public static void Unlock(GameManager gm)
        {
            try
            {
                if (gm == null) return;

                if (gm.GetStatusRecordInt(Constants.RECORD_BOSSRUSH_MODE) != 0) return;

                gm.SetStatusRecordInt(Constants.RECORD_BOSSRUSH_MODE, 1);
                Plugin.Log.LogInfo("Godhome: unlocked the boss-rush menu entry (RecBossRushMode = 1).");
            }
            catch (Exception e)
            {
                Plugin.Log.LogError("Godhome: couldn't unlock the menu entry: " + e);
            }
        }

        // ------------------------------------------------------------------

        private static int _relabelledScreenId;

        public static void Forget() => _relabelledScreenId = 0;

        /// <summary>
        /// The shipped boss-rush button has no localisation entry left in Silksong's
        /// sheets, so it renders blank. Give it a name.
        ///
        /// Safe to call every frame - it bails once the current screen instance is done.
        /// </summary>
        public static void TryRelabel()
        {
            if (!GodhomeConfig.RelabelMenuEntry.Value) return;

            try
            {
                UIManager ui = UIManager.instance;
                if (ui == null) return;

                MenuScreen screen = ui.playModeMenuScreen;
                if (screen == null) return;

                int id = screen.gameObject.GetInstanceID();
                if (id == _relabelledScreenId) return;

                if (Relabel(screen)) _relabelledScreenId = id;
            }
            catch (Exception e)
            {
                Plugin.Log.LogError("Godhome: menu relabel failed: " + e);
                _relabelledScreenId = -1; // don't spin on a broken menu
            }
        }

        private static bool Relabel(MenuScreen screen)
        {
            StartGameEventTrigger target = null;
            foreach (StartGameEventTrigger t in screen.GetComponentsInChildren<StartGameEventTrigger>(true))
            {
                if (GodhomePatches.IsBossRushTrigger(t)) { target = t; break; }
            }

            if (target == null)
            {
                Plugin.Log.LogWarning(
                    "Godhome: no bossRush StartGameEventTrigger under playModeMenuScreen. " +
                    "The menu layout may have changed in a game update.");
                return false;
            }

            GameObject go = target.gameObject;

            // AutoLocalizeTextUI re-reads its string from the localisation sheet on every
            // language refresh, which would stamp straight over whatever we set.
            foreach (AutoLocalizeTextUI loc in go.GetComponentsInChildren<AutoLocalizeTextUI>(true))
            {
                UnityEngine.Object.DestroyImmediate(loc);
            }

            Text[] texts = go.GetComponentsInChildren<Text>(true);
            if (texts.Length == 0)
            {
                Plugin.Log.LogWarning("Godhome: boss-rush button has no Text component to relabel.");
                return false;
            }

            // Mode entries are a big title plus a smaller description line.
            Text title = texts[0];
            foreach (Text t in texts)
            {
                if (t.fontSize > title.fontSize) title = t;
            }

            foreach (Text t in texts)
            {
                t.text = (t == title)
                    ? GodhomeConfig.ModeName.Value
                    : GodhomeConfig.ModeDescription.Value;
            }

            Plugin.Log.LogInfo($"Godhome: menu entry labelled '{GodhomeConfig.ModeName.Value}'.");
            return true;
        }
    }
}
