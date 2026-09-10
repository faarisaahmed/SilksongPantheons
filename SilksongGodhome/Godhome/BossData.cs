using System;
using System.IO;
using System.Reflection;
using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// Reads a baked Hollow Knight boss.
    ///
    /// Written by tools/bossbake.py. A boss is a hierarchy: Brooding Mawlek's body, head
    /// and arms are four objects, each with its own sprite, animator and FSMs. They share
    /// their art, so collections and animation libraries live in tables at the top of the
    /// file and each node references them by index.
    ///
    /// tk2dSpriteDefinition, tk2dSpriteCollectionData, tk2dSpriteAnimation,
    /// tk2dSpriteAnimationClip and tk2dSpriteAnimationFrame are byte-identical between
    /// Hollow Knight's tk2d and Silksong's TeamCherry.TK2D, so these rebuild as real
    /// tk2d assets rather than as an approximation.
    /// </summary>
    internal static class BossData
    {
        private const string Prefix = "Godhome.";
        private const string Magic = "GGBS";
        private const int Version = 6;

        public sealed class SpriteDef
        {
            public string Name;
            public int MaterialId;
            public Vector2 TexelSize;
            public Vector3[] Positions;
            public Vector2[] Uvs;
            public Vector3[] BoundsData;
            public Vector3[] UntrimmedBoundsData;
            public int[] Indices;
        }

        public sealed class Frame
        {
            public int CollectionIndex;
            public int SpriteId;
            public bool TriggerEvent;
            public string EventInfo;
            public int EventInt;
            public float EventFloat;
        }

        public sealed class Clip
        {
            public string Name;
            public float Fps;
            public int LoopStart;
            public int WrapMode;
            public Frame[] Frames;
        }

        public sealed class BoxDef
        {
            public Vector2 Offset, Size;
            public bool Trigger, Enabled;
        }

        public sealed class CircleDef
        {
            public Vector2 Offset;
            public float Radius;
            public bool Trigger, Enabled;
        }

        /// <summary>A collection plus the atlas pages behind it, shared between nodes.</summary>
        public sealed class Collection
        {
            public string Name;
            public string[] Textures;
            public SpriteDef[] Defs;
        }

        /// <summary>An animation library, shared between nodes.</summary>
        public sealed class Library
        {
            public string Name;
            public Clip[] Clips;
        }

        /// <summary>One object in the boss's hierarchy, with the parts that make it a fight.</summary>
        public sealed class Node
        {
            public string Name;
            public int Layer;
            public bool Active;
            public Vector3 Position, Scale;
            public Quaternion Rotation;

            public bool HasSprite;
            public int CollectionIndex, SpriteId, RenderLayer;
            public Color SpriteColor;
            public Vector3 SpriteScale;

            public bool HasAnimator;
            public int LibraryIndex, DefaultClipId;
            public bool PlayAutomatically;

            public System.Collections.Generic.List<FsmData.Fsm> Fsms =
                new System.Collections.Generic.List<FsmData.Fsm>();

            public bool HasBody;
            public float Mass, GravityScale, LinearDrag, AngularDrag;
            public int BodyType, Constraints, CollisionDetection, Interpolate;

            public BoxDef[] Boxes;
            public CircleDef[] Circles;

            public bool HasHealth;
            public int Hp;

            public bool HasDamage;
            public int DamageDealt, HazardType;

            public Node[] Children;
        }

        public struct ClipInfo
        {
            public int SampleCount, Rate;
        }

        /// <summary>A prefab a boss's FSMs spawn, baked as its own hierarchy.</summary>
        public sealed class Prefab
        {
            public string Name;
            public Node Root;
        }

        public sealed class Boss
        {
            public string Name;
            public string Scene;
            public Collection[] Collections;
            public Library[] Libraries;
            public Prefab[] Prefabs;
            public Node Root;
            /// <summary>Clips the FSMs reference, by resource name.</summary>
            public System.Collections.Generic.Dictionary<string, ClipInfo> FsmClips =
                new System.Collections.Generic.Dictionary<string, ClipInfo>();
        }

        public static Boss Load(string bossName)
        {
            string safe = Sanitize(bossName);
            Stream s = Rebuild.GodhomeResources.Open("boss_" + safe + ".boss");
            if (s == null)
            {
                Plugin.Log.LogWarning($"Godhome: no baked boss '{bossName}'.");
                return null;
            }

            try
            {
                using (s)
                using (var r = new BinaryReader(s))
                {
                    var magic = new string(r.ReadChars(4));
                    if (magic != Magic) throw new InvalidDataException($"bad magic '{magic}'");
                    int v = r.ReadInt32();
                    if (v != Version) throw new InvalidDataException($"version {v}, expected {Version}");

                    var b = new Boss
                    {
                        Name = r.ReadString(),
                        Scene = r.ReadString(),
                    };

                    b.Collections = new Collection[r.ReadInt32()];
                    for (int ci = 0; ci < b.Collections.Length; ci++)
                        b.Collections[ci] = ReadCollection(r);

                    b.Libraries = new Library[r.ReadInt32()];
                    for (int li = 0; li < b.Libraries.Length; li++)
                        b.Libraries[li] = ReadLibrary(r);

                    int nclips = r.ReadInt32();
                    for (int i = 0; i < nclips; i++)
                    {
                        string cn = r.ReadString();
                        b.FsmClips[cn] = new ClipInfo { SampleCount = r.ReadInt32(), Rate = r.ReadInt32() };
                    }

                    b.Prefabs = new Prefab[r.ReadInt32()];
                    for (int i = 0; i < b.Prefabs.Length; i++)
                    {
                        b.Prefabs[i] = new Prefab { Name = r.ReadString(), Root = ReadNode(r) };
                    }

                    b.Root = ReadNode(r);

                    int nodes = 0, st = 0, ac = 0, nf = 0;
                    Walk(b.Root, ref nodes, ref nf, ref st, ref ac);
                    Plugin.Log.LogInfo(
                        $"Godhome: loaded boss '{b.Name}' - {nodes} nodes, {b.Collections.Length} " +
                        $"collection(s), {b.Libraries.Length} librar(ies), " +
                        $"{b.Prefabs.Length} prefab(s), {nf} FSMs " +
                        $"({st} states, {ac} actions).");
                    return b;
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Godhome: baked boss '{bossName}' is unreadable: {e}");
                return null;
            }
        }

        private static void Walk(Node n, ref int nodes, ref int fsms, ref int states, ref int actions)
        {
            if (n == null) return;
            nodes++;
            fsms += n.Fsms.Count;
            foreach (FsmData.Fsm f in n.Fsms)
            {
                states += f.States.Length;
                foreach (FsmData.State s in f.States) actions += s.Actions.ActionNames.Length;
            }
            foreach (Node c in n.Children) Walk(c, ref nodes, ref fsms, ref states, ref actions);
        }

        /// <summary>
        /// One tk2d sprite collection. Shared with the scene format, since an arena's
        /// objects index the same tables its bosses do.
        /// </summary>
        public static Collection ReadCollection(BinaryReader r)
        {
            var col = new Collection { Name = r.ReadString() };
            col.Textures = new string[r.ReadInt32()];
            for (int i = 0; i < col.Textures.Length; i++) col.Textures[i] = r.ReadString();
            col.Defs = new SpriteDef[r.ReadInt32()];
            for (int i = 0; i < col.Defs.Length; i++)
            {
                var d = new SpriteDef
                {
                    Name = r.ReadString(),
                    MaterialId = r.ReadInt32(),
                    TexelSize = new Vector2(r.ReadSingle(), r.ReadSingle()),
                };
                d.Positions = ReadV3(r);
                d.Uvs = ReadV2(r);
                d.BoundsData = ReadV3(r);
                d.UntrimmedBoundsData = ReadV3(r);
                int n = r.ReadInt32();
                d.Indices = new int[n];
                for (int k = 0; k < n; k++) d.Indices[k] = r.ReadInt32();
                col.Defs[i] = d;
            }
            return col;
        }

        public static Library ReadLibrary(BinaryReader r)
        {
            var lib = new Library { Name = r.ReadString() };
            lib.Clips = new Clip[r.ReadInt32()];
            for (int i = 0; i < lib.Clips.Length; i++)
            {
                var c = new Clip
                {
                    Name = r.ReadString(),
                    Fps = r.ReadSingle(),
                    LoopStart = r.ReadInt32(),
                    WrapMode = r.ReadInt32(),
                };
                c.Frames = new Frame[r.ReadInt32()];
                for (int k = 0; k < c.Frames.Length; k++)
                {
                    c.Frames[k] = new Frame
                    {
                        CollectionIndex = r.ReadInt32(),
                        SpriteId = r.ReadInt32(),
                        TriggerEvent = r.ReadBoolean(),
                        EventInfo = r.ReadString(),
                        EventInt = r.ReadInt32(),
                        EventFloat = r.ReadSingle(),
                    };
                }
                lib.Clips[i] = c;
            }
            return lib;
        }

        private static Node ReadNode(BinaryReader r)
        {
            var n = new Node
            {
                Name = r.ReadString(),
                Layer = r.ReadInt32(),
                Active = r.ReadBoolean(),
                Position = new Vector3(r.ReadSingle(), r.ReadSingle(), r.ReadSingle()),
                Rotation = new Quaternion(r.ReadSingle(), r.ReadSingle(), r.ReadSingle(), r.ReadSingle()),
                Scale = new Vector3(r.ReadSingle(), r.ReadSingle(), r.ReadSingle()),
            };

            n.HasSprite = r.ReadBoolean();
            if (n.HasSprite)
            {
                n.CollectionIndex = r.ReadInt32();
                n.SpriteId = r.ReadInt32();
                n.SpriteColor = new Color(r.ReadSingle(), r.ReadSingle(), r.ReadSingle(), r.ReadSingle());
                n.SpriteScale = new Vector3(r.ReadSingle(), r.ReadSingle(), r.ReadSingle());
                n.RenderLayer = r.ReadInt32();
            }

            n.HasAnimator = r.ReadBoolean();
            if (n.HasAnimator)
            {
                n.LibraryIndex = r.ReadInt32();
                n.DefaultClipId = r.ReadInt32();
                n.PlayAutomatically = r.ReadBoolean();
            }

            n.HasBody = r.ReadBoolean();
            if (n.HasBody)
            {
                n.Mass = r.ReadSingle();
                n.GravityScale = r.ReadSingle();
                n.LinearDrag = r.ReadSingle();
                n.AngularDrag = r.ReadSingle();
                n.BodyType = r.ReadInt32();
                n.Constraints = r.ReadInt32();
                n.CollisionDetection = r.ReadInt32();
                n.Interpolate = r.ReadInt32();
            }

            n.Boxes = new BoxDef[r.ReadInt32()];
            for (int i = 0; i < n.Boxes.Length; i++)
            {
                n.Boxes[i] = new BoxDef
                {
                    Offset = new Vector2(r.ReadSingle(), r.ReadSingle()),
                    Size = new Vector2(r.ReadSingle(), r.ReadSingle()),
                    Trigger = r.ReadBoolean(),
                    Enabled = r.ReadBoolean(),
                };
            }

            n.Circles = new CircleDef[r.ReadInt32()];
            for (int i = 0; i < n.Circles.Length; i++)
            {
                n.Circles[i] = new CircleDef
                {
                    Offset = new Vector2(r.ReadSingle(), r.ReadSingle()),
                    Radius = r.ReadSingle(),
                    Trigger = r.ReadBoolean(),
                    Enabled = r.ReadBoolean(),
                };
            }

            n.HasHealth = r.ReadBoolean();
            if (n.HasHealth) n.Hp = r.ReadInt32();

            n.HasDamage = r.ReadBoolean();
            if (n.HasDamage) { n.DamageDealt = r.ReadInt32(); n.HazardType = r.ReadInt32(); }

            int nfsm = r.ReadInt32();
            for (int i = 0; i < nfsm; i++) n.Fsms.Add(FsmData.ReadFsm(r));

            n.Children = new Node[r.ReadInt32()];
            for (int i = 0; i < n.Children.Length; i++) n.Children[i] = ReadNode(r);
            return n;
        }

        public static string Sanitize(string n)
        {
            var sb = new System.Text.StringBuilder();
            foreach (char c in n ?? "")
                sb.Append(char.IsLetterOrDigit(c) || c == '.' || c == '_' || c == '-' ? c : '_');
            return sb.ToString();
        }

        internal static Vector3[] ReadV3(BinaryReader r)
        {
            var a = new Vector3[r.ReadInt32()];
            for (int i = 0; i < a.Length; i++)
                a[i] = new Vector3(r.ReadSingle(), r.ReadSingle(), r.ReadSingle());
            return a;
        }

        internal static Vector2[] ReadV2(BinaryReader r)
        {
            var a = new Vector2[r.ReadInt32()];
            for (int i = 0; i < a.Length; i++)
                a[i] = new Vector2(r.ReadSingle(), r.ReadSingle());
            return a;
        }
    }
}
