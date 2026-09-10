using System;
using UnityEngine;
using UnityEngine.UI;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// Makes a Godseeker save look like one on the save-select screen: Godhome's own art
    /// and the name "Godhome" instead of whatever map zone the save happens to record.
    ///
    /// Silksong already distinguishes these saves - `SaveStats.BossRushMode` is read
    /// straight out of the save file - so nothing has to be inferred. The game picks a
    /// slot's art and label in `SaveSlotButton.PresentSaveSlot` via
    /// `SaveSlotBackgrounds.GetBackground(SaveStats)`, which returns an `AreaBackground`
    /// holding a Sprite and a LocalisedString name override.
    ///
    /// We set the Image and the Text directly rather than building an `AreaBackground`:
    /// its `NameOverride` is a LocalisedString that resolves through a localisation sheet
    /// we don't ship, so it would render as a missing-key placeholder.
    /// </summary>
    internal static class GodhomeSaveSlot
    {
        private const string ArtResource = "ui_area_godhome";

        private static Sprite _art;
        private static bool _artTried;

        /// <summary>Shown on the slot. Hollow Knight calls the place Godhome.</summary>
        public static string AreaName = "Godhome";

        private static Sprite Art()
        {
            if (_artTried) return _art;
            _artTried = true;

            Texture2D tex = Rebuild.GodhomeData.LoadPage(ArtResource);
            if (tex == null)
            {
                Plugin.Log.LogWarning("Godhome: no save-slot art embedded; slots keep the default image.");
                return null;
            }

            _art = Sprite.Create(tex, new Rect(0f, 0f, tex.width, tex.height),
                                 new Vector2(0.5f, 0.5f), 100f, 0,
                                 SpriteMeshType.FullRect);
            if (_art != null) _art.name = "Godhome_AreaArt";
            Plugin.Log.LogInfo($"Godhome: save-slot art loaded ({tex.width}x{tex.height}).");
            return _art;
        }

        /// <summary>Called from a postfix on SaveSlotButton.PresentSaveSlot.</summary>
        public static void Apply(object button, SaveStats stats)
        {
            if (stats == null || !stats.BossRushMode) return;

            try
            {
                var slot = button as UnityEngine.UI.SaveSlotButton;
                if (slot == null) return;

                Sprite art = Art();
                if (art != null && slot.background != null) slot.background.sprite = art;

                if (slot.locationText != null) slot.locationText.text = AreaName;
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning("Godhome: couldn't dress the save slot: " + e.Message);
            }
        }
    }
}
