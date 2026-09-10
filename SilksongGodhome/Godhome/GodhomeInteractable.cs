using System;
using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// Shared "stand here and press Up" behaviour for Godhome's interactables.
    ///
    /// In both games this is normally a PlayMaker FSM watching a trigger and listening
    /// for the Up input. Silksong's FSM graphs for Godhome don't exist, so the proximity
    /// test and the prompt are done here in C# instead - but everything the interaction
    /// then *does* goes through Silksong's own APIs.
    /// </summary>
    internal abstract class GodhomeInteractable : MonoBehaviour
    {
        /// <summary>How close the hero must be, in world units.</summary>
        public float Range = 2.5f;

        /// <summary>Text shown when in range.</summary>
        protected abstract string Prompt { get; }

        protected abstract void Interact();

        /// <summary>Set while the interactable owns the hero (e.g. sitting on a bench).</summary>
        protected bool Engaged;

        private bool _inRange;
        private bool _promptFailed;
        private static GUIStyle _style;

        protected virtual bool CanInteract() => true;

        private void Update()
        {
            HeroController hero = HeroController.SilentInstance;
            if (hero == null) { _inRange = false; return; }

            float d = Vector2.Distance(hero.transform.position, transform.position);
            _inRange = d <= Range;

            // A menu owns input while it's up; don't let a second interactable fire.
            if (PantheonChallengeUI.IsOpen) { _inRange = false; return; }

            if (!_inRange || !CanInteract()) return;

            if (UpPressed())
            {
                try { Interact(); }
                catch (Exception e) { Plugin.Log.LogError($"Godhome: interaction on '{name}' failed: {e}"); }
            }
        }

        /// <summary>
        /// Godhome is entered from a menu that doesn't rebind, so reading the raw Up keys
        /// is enough here and avoids depending on Silksong's input action layout.
        /// </summary>
        private static bool UpPressed()
        {
            return Input.GetKeyDown(KeyCode.UpArrow) || Input.GetKeyDown(KeyCode.W);
        }

        private void OnGUI()
        {
            if (!_inRange || Engaged || !CanInteract()) return;

            if (_style == null)
            {
                _style = new GUIStyle(GUI.skin.label)
                {
                    alignment = TextAnchor.MiddleCenter,
                    fontSize = 20,
                };
                _style.normal.textColor = Color.white;
            }

            // Prompt reaches into game state (sequences, unlock lists), and an exception
            // thrown from OnGUI silently draws nothing - which looks exactly like the
            // interactable not existing. Fail visibly instead.
            string text;
            try
            {
                text = Prompt;
            }
            catch (Exception e)
            {
                if (!_promptFailed)
                {
                    _promptFailed = true;
                    Plugin.Log.LogError($"Godhome: prompt for '{name}' threw: {e}");
                }
                text = "(unavailable - see log)";
            }
            if (string.IsNullOrEmpty(text)) return;

            var rect = new Rect(0f, Screen.height * 0.72f, Screen.width, 40f);
            GUI.Label(rect, text, _style);
        }
    }
}
