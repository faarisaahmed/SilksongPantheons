using System;
using System.Collections.Generic;
using UnityEngine;

namespace SilksongGodhome.Rebuild
{
    /// <summary>
    /// Maps Hollow Knight's sprite shaders onto materials Silksong can actually render.
    ///
    /// Without this, every sprite gets the default sprite material and Godhome's light
    /// beams - 29 of GG_Atrium's renderers use <c>UI/BlendModes/Screen</c> - draw as
    /// solid white quads instead of glows.
    ///
    /// GG_Atrium uses six shaders:
    ///   Sprites/Lit (786), Sprites/Default (446), UI/BlendModes/Screen (21),
    ///   Sprites/Default-ColorFlash (9), UI/BlendModes/Optimized/Screen (8),
    ///   Sprites/Cherry-Default (7)
    ///
    /// Silksong ships stock <c>Sprites/Default</c>, so the opaque ones map straight
    /// across. The screen-blend ones have no stock equivalent, so we build a material
    /// with the right blend state by hand.
    /// </summary>
    internal static class MaterialMap
    {
        private static readonly Dictionary<string, Material> Cache =
            new Dictionary<string, Material>(StringComparer.Ordinal);

        private static Material _default;
        private static Material _screen;

        public static void Clear()
        {
            Cache.Clear();
            MeshCache.Clear();
            _default = null;
            _screen = null;
        }

        /// <summary>Material for a Hollow Knight shader name, or null to leave the default.</summary>
        public static Material For(string hkShader)
        {
            if (string.IsNullOrEmpty(hkShader)) return null;
            if (Cache.TryGetValue(hkShader, out Material m)) return m;

            m = Build(hkShader);
            Cache[hkShader] = m;
            return m;
        }

        private static Material Build(string hkShader)
        {
            bool isScreen = hkShader.IndexOf("Screen", StringComparison.OrdinalIgnoreCase) >= 0;
            Material m = isScreen ? ScreenBlend() : DefaultSprite();

            if (m == null)
            {
                Plugin.Log.LogWarning($"Godhome: no material for shader '{hkShader}'; using the renderer default.");
            }
            return m;
        }

        private static readonly Dictionary<int, Material> MeshCache = new Dictionary<int, Material>();

        /// <summary>
        /// Material for a tilemap chunk or other mesh renderer.
        ///
        /// Hollow Knight draws these with tk2d/BlendVertexColor over a small tile atlas.
        /// Silksong ships tk2d, so that shader is tried first; failing that an unlit
        /// transparent sprite material gives the same result for uniformly-white vertex
        /// colours, which is what the chunk meshes actually have.
        /// </summary>
        public static Material ForMesh(string hkShader, Texture2D tex)
        {
            int key = (tex != null ? tex.GetInstanceID() : 0) ^ (hkShader != null ? hkShader.GetHashCode() : 0);
            if (MeshCache.TryGetValue(key, out Material m)) return m;

            Shader s = null;
            if (!string.IsNullOrEmpty(hkShader)) s = Shader.Find(hkShader);
            if (s == null) s = Shader.Find("Sprites/Default");

            if (s == null)
            {
                Plugin.Log.LogWarning("Godhome: no usable shader for mesh rendering.");
                MeshCache[key] = null;
                return null;
            }

            m = new Material(s) { name = "Godhome_Mesh" };
            if (tex != null) m.mainTexture = tex;
            MeshCache[key] = m;
            return m;
        }

        private static Material DefaultSprite()
        {
            if (_default != null) return _default;

            Shader s = Shader.Find("Sprites/Default");
            if (s == null)
            {
                Plugin.Log.LogWarning("Godhome: 'Sprites/Default' not found in this build.");
                return null;
            }
            _default = new Material(s) { name = "Godhome_Sprite" };
            return _default;
        }

        /// <summary>
        /// Stand-in for Hollow Knight's UI/BlendModes/Screen, which Silksong doesn't ship.
        ///
        /// The first attempt set _SrcBlend/_DstBlend on a Sprites/Default material, which
        /// does nothing: Unity's built-in sprite shader hard-codes its blend state and
        /// exposes no such properties. The result was Godhome's glows drawing as opaque
        /// rectangles - bright white ones for the hazes, and dark occluding ones for the
        /// caustics, which are near-black and 96% opaque because screen blend treats black
        /// as transparent.
        ///
        /// The second attempt used Legacy Shaders/Particles/Additive, which blew the
        /// screen out: the extractor already premultiplies these sprites' RGB by their
        /// alpha, and additive then ignores alpha entirely, so every glow was counted
        /// twice and saturated to white.
        ///
        /// Premultiplied alpha is the right pairing for premultiplied textures - it is
        /// literally Blend One OneMinusSrcAlpha, so a glow adds its own colour and
        /// attenuates the background by its coverage instead of piling on top of it.
        /// That both keeps screen blend's "never darkens" behaviour and stays bounded.
        /// </summary>
        private static Material ScreenBlend()
        {
            if (_screen != null) return _screen;

            Shader s = Shader.Find("Legacy Shaders/Particles/Alpha Blended Premultiply")
                       ?? Shader.Find("Sprites/Default");
            if (s == null)
            {
                Plugin.Log.LogWarning("Godhome: no premultiplied shader available; glows will look wrong.");
                return DefaultSprite();
            }

            _screen = new Material(s) { name = "Godhome_Premultiplied" };

            // The legacy particle shaders default _TintColor to mid-grey, which would
            // halve every glow.
            if (_screen.HasProperty("_TintColor")) _screen.SetColor("_TintColor", Color.white);
            _screen.renderQueue = (int)UnityEngine.Rendering.RenderQueue.Transparent + 1;
            return _screen;
        }
    }
}
