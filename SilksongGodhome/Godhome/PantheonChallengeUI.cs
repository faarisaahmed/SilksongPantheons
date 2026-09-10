using System;
using UnityEngine;
using UnityEngine.UI;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// The binding screen you get when you inspect a Pantheon door.
    ///
    /// Hollow Knight shows <c>BossDoorChallengeUI</c>: the Pantheon's title and
    /// description, four binding buttons (Nail, Shell, Charms, Soul), and Begin. That
    /// class still exists in Silksong, but it's driven entirely by a prefab we can't
    /// reconstruct - an Animator with Open/Close clips, a Canvas, a CanvasGroup and four
    /// <c>BossDoorChallengeUIBindingButton</c>s, each a wired MenuButton. So the screen
    /// is drawn here.
    ///
    /// What the bindings *do* is not reimplemented. The four flags map onto Silksong's
    /// own <c>BossSequenceController.ChallengeBindings</c>, and its <c>ApplyBindings</c>,
    /// <c>BoundNailDamage</c> and <c>BoundMaxHealth</c> handle the rest exactly as they
    /// do in Hollow Knight.
    /// </summary>
    internal class PantheonChallengeUI : MonoBehaviour
    {
        private static PantheonChallengeUI _open;

        /// <summary>True while any challenge screen is up.</summary>
        public static bool IsOpen => _open != null;

        private PantheonDoor _door;
        private BossSequence _sequence;
        private string _title;

        private readonly bool[] _bound = new bool[4];
        private int _index;

        private static readonly string[] BindingNames =
        {
            "Bind Nail", "Bind Shell", "Bind Charms", "Bind Soul",
        };

        // Straight from BossSequenceController: nail damage drops to the sequence's
        // value, health is capped at sequence.maxHealth, charms are unequipped and soul
        // is reserved.
        private static readonly string[] BindingEffects =
        {
            "Your needle deals reduced damage",
            "You are reduced to five masks",
            "Your crests and tools are bound",
            "Your silk is bound",
        };

        private static GUIStyle _title1, _line, _hint;

        /// <summary>Hollow Knight's own binding icons, baked by tools/bake_ui.py.</summary>
        private static readonly string[] IconBase = { "nail", "shell", "charm", "soul" };
        private static Texture2D[] _iconOn, _iconOff;
        private static bool _iconsLoaded;

        private static void LoadIcons()
        {
            if (_iconsLoaded) return;
            _iconsLoaded = true;

            _iconOn = new Texture2D[4];
            _iconOff = new Texture2D[4];
            int found = 0;
            for (int i = 0; i < 4; i++)
            {
                _iconOn[i] = Rebuild.GodhomeData.LoadPage("ui_bind_" + IconBase[i] + "_on");
                _iconOff[i] = Rebuild.GodhomeData.LoadPage("ui_bind_" + IconBase[i] + "_off");
                if (_iconOn[i] != null && _iconOff[i] != null) found++;
            }
            Plugin.Log.LogInfo($"Godhome: challenge screen loaded {found}/4 binding icons.");
        }

        public static void Open(PantheonDoor door, BossSequence sequence, string title)
        {
            if (_open != null) return;

            var go = new GameObject("Godhome_ChallengeUI");
            var ui = go.AddComponent<PantheonChallengeUI>();
            ui._door = door;
            ui._sequence = sequence;
            ui._title = title;
            _open = ui;

            // Stop Hornet walking around behind the menu, the way the real screen does
            // by taking UI input.
            try { HeroController.instance?.RelinquishControl(); }
            catch (Exception) { }
        }

        private void Close()
        {
            _open = null;
            try { HeroController.instance?.RegainControl(); }
            catch (Exception) { }
            Destroy(gameObject);
        }

        private BossSequenceController.ChallengeBindings Bindings
        {
            get
            {
                var b = BossSequenceController.ChallengeBindings.None;
                if (_bound[0]) b |= BossSequenceController.ChallengeBindings.Nail;
                if (_bound[1]) b |= BossSequenceController.ChallengeBindings.Shell;
                if (_bound[2]) b |= BossSequenceController.ChallengeBindings.Charms;
                if (_bound[3]) b |= BossSequenceController.ChallengeBindings.Soul;
                return b;
            }
        }

        private void Update()
        {
            // 0-3 are the bindings, 4 is Begin.
            // Bindings sit in a row, so left/right moves along them and down drops to
            // Begin - the same shape as the real screen.
            if (Input.GetKeyDown(KeyCode.RightArrow) || Input.GetKeyDown(KeyCode.D))
                _index = Mathf.Min(_index + 1, 3);
            if (Input.GetKeyDown(KeyCode.LeftArrow) || Input.GetKeyDown(KeyCode.A))
                _index = Mathf.Max(_index - 1, 0);
            if (Input.GetKeyDown(KeyCode.DownArrow) || Input.GetKeyDown(KeyCode.S))
                _index = 4;
            if (Input.GetKeyDown(KeyCode.UpArrow) || Input.GetKeyDown(KeyCode.W))
                _index = Mathf.Min(_index, 3);

            bool confirm = Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.KeypadEnter)
                           || Input.GetKeyDown(KeyCode.Space);

            if (confirm)
            {
                if (_index < 4) _bound[_index] = !_bound[_index];
                else Begin();
                return;
            }

            if (Input.GetKeyDown(KeyCode.Escape) || Input.GetKeyDown(KeyCode.Backspace))
            {
                Close();
            }
        }

        private void Begin()
        {
            PantheonDoor door = _door;
            BossSequenceController.ChallengeBindings bindings = Bindings;
            Close();
            door.BeginRun(_sequence, bindings);
        }

        private void OnGUI()
        {
            EnsureStyles();

            LoadIcons();

            float w = 700f, h = 430f;
            var box = new Rect((Screen.width - w) * 0.5f, (Screen.height - h) * 0.5f, w, h);

            GUI.color = new Color(0f, 0f, 0f, 0.82f);
            GUI.DrawTexture(box, Texture2D.whiteTexture);
            GUI.color = Color.white;

            float y = box.y + 24f;
            GUI.Label(new Rect(box.x, y, w, 34f), _title, _title1);
            y += 40f;

            GUI.Label(new Rect(box.x, y, w, 24f),
                $"{_sequence.Count} bosses", _hint);
            y += 40f;

            // The four bindings, drawn as Hollow Knight's own icons: lit when bound,
            // dimmed when not, exactly as the real screen shows them.
            const float icon = 96f;
            const float gap = 34f;
            float rowW = 4f * icon + 3f * gap;
            float rowX = box.x + (w - rowW) * 0.5f;

            for (int i = 0; i < 4; i++)
            {
                float ix = rowX + i * (icon + gap);
                var r = new Rect(ix, y, icon, icon);

                Texture2D tex = null;
                if (_iconOn != null && _iconOff != null)
                    tex = _bound[i] ? _iconOn[i] : _iconOff[i];

                bool sel = _index == i;

                if (sel)
                {
                    GUI.color = new Color(1f, 0.86f, 0.45f, 0.25f);
                    GUI.DrawTexture(new Rect(ix - 8f, y - 8f, icon + 16f, icon + 16f),
                        Texture2D.whiteTexture);
                }

                GUI.color = _bound[i] ? Color.white : new Color(1f, 1f, 1f, 0.55f);
                if (tex != null) GUI.DrawTexture(r, tex, ScaleMode.ScaleToFit, true);
                else GUI.Label(r, BindingNames[i], _hint);

                GUI.color = sel ? new Color(1f, 0.86f, 0.45f) : new Color(1f, 1f, 1f, 0.7f);
                GUI.Label(new Rect(ix - gap * 0.5f, y + icon + 4f, icon + gap, 22f),
                    BindingNames[i], _hint);
            }

            y += icon + 34f;

            GUI.color = _index < 4 ? new Color(1f, 1f, 1f, 0.6f) : new Color(1f, 1f, 1f, 0f);
            GUI.Label(new Rect(box.x, y, w, 22f),
                _index < 4 ? BindingEffects[_index] : "", _hint);
            y += 30f;

            GUI.color = _index == 4 ? new Color(1f, 0.86f, 0.45f) : Color.white;
            GUI.Label(new Rect(box.x, y, w, 30f),
                _index == 4 ? "> Begin <" : "Begin", _title1);

            GUI.color = new Color(1f, 1f, 1f, 0.55f);
            GUI.Label(new Rect(box.x, box.yMax - 34f, w, 24f),
                "Left/Right to choose a binding    Down for Begin    Enter to confirm    Esc to leave", _hint);
            GUI.color = Color.white;
        }

        private static Font _gameFont;
        private static bool _fontSearched;

        /// <summary>
        /// Silksong's own menu font, so this screen doesn't render in Arial.
        ///
        /// The real BossDoorChallengeUI is a prefab we can't rebuild, but its text uses
        /// plain UGUI Text components - and so does every menu in the game. Borrowing the
        /// Font off one of them costs nothing and matches the rest of the UI.
        /// </summary>
        private static Font GameFont()
        {
            if (_fontSearched) return _gameFont;
            _fontSearched = true;

            try
            {
                foreach (Text t in Resources.FindObjectsOfTypeAll<Text>())
                {
                    if (t != null && t.font != null)
                    {
                        _gameFont = t.font;
                        Plugin.Log.LogInfo($"Godhome: challenge screen using the game font '{_gameFont.name}'.");
                        break;
                    }
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning("Godhome: couldn't find a game font: " + e.Message);
            }

            if (_gameFont == null) Plugin.Log.LogWarning("Godhome: no game font found; falling back to the default.");
            return _gameFont;
        }

        private static void EnsureStyles()
        {
            if (_title1 != null) return;

            Font f = GameFont();

            _title1 = new GUIStyle(GUI.skin.label)
            { alignment = TextAnchor.MiddleCenter, fontSize = 30 };
            _title1.normal.textColor = Color.white;

            _line = new GUIStyle(GUI.skin.label) { alignment = TextAnchor.MiddleLeft, fontSize = 22 };
            _line.normal.textColor = Color.white;

            _hint = new GUIStyle(GUI.skin.label) { alignment = TextAnchor.MiddleCenter, fontSize = 16 };
            _hint.normal.textColor = Color.white;

            if (f != null)
            {
                _title1.font = f;
                _line.font = f;
                _hint.font = f;
            }
        }
    }
}
