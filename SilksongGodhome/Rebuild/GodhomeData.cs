using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using UnityEngine;
using SilksongGodhome.Godhome;

namespace SilksongGodhome.Rebuild
{
    /// <summary>
    /// Reads the baked Godhome scene data embedded in this DLL.
    ///
    /// The format is written by tools/extract_godhome.py; see tools/ggformat.py for the
    /// authoritative layout. Strings are .NET BinaryWriter-compatible, so a plain
    /// BinaryReader is all that's needed here.
    ///
    /// <see cref="FormatVersion"/> must match ggformat.FORMAT_VERSION.
    /// </summary>
    internal static class GodhomeData
    {
        public const int FormatVersion = 12;
        private const string Magic = "GGHM";

        /// <summary>
        /// A deflate wrapper around a baked room. The behaviour layer is mostly PlayMaker
        /// action names and strings, which repeat heavily - a room compresses to about
        /// 15% of its size, and across the seventeen rooms that is forty megabytes off
        /// the DLL.
        /// </summary>
        private const string ZMagic = "GGHZ";
        private const string ResourcePrefix = "Godhome.";

        // Component bits, mirroring ggformat.py.
        public const int HasSprite = 1 << 0;
        public const int HasBox    = 1 << 1;
        public const int HasEdge   = 1 << 2;
        public const int HasPoly   = 1 << 3;
        public const int HasCamLock = 1 << 4;
        public const int HasRespawn = 1 << 5;
        public const int HasHazard  = 1 << 6;
        public const int HasTransition = 1 << 7;
        public const int HasSimple = 1 << 8;
        public const int HasMesh = 1 << 9;
        public const int HasSeqDoor = 1 << 10;
        public const int HasStatue = 1 << 11;
        public const int HasAudio = 1 << 12;

        // v12: the behaviour layer. Godhome's rooms are not scenery - the objects that
        // start a fight, end it, knock a boss back and play its death are components and
        // FSMs on ordinary GameObjects.
        public const int HasTk2d  = 1 << 13;
        public const int HasFsm   = 1 << 14;
        public const int HasComps = 1 << 15;
        /// <summary>Rigidbody2D and CircleCollider2D. A boss without a body cannot move.</summary>
        public const int HasPhys  = 1 << 16;

        private static readonly Dictionary<string, BakedScene> Cache = new Dictionary<string, BakedScene>();
        private static HashSet<string> _available;

        // ------------------------------------------------------------------

        public sealed class SpriteDef
        {
            public string Name;
            public int Page;
            public Rect Rect;
            public Vector2 Pivot;
            public float Ppu;
            public Vector4 Border;
        }

        public sealed class BoxDef
        {
            public Vector2 Offset, Size;
            public bool Trigger, Enabled;
        }

        public sealed class EdgeDef
        {
            public Vector2 Offset;
            public Vector2[] Points;
            public bool Trigger, Enabled;
        }

        public sealed class PolyDef
        {
            public Vector2 Offset;
            public Vector2[][] Paths;
            public bool Trigger, Enabled;
        }

        public sealed class ObjectDef
        {
            public string Name;
            public int Parent;
            public int Layer;
            public bool Active;
            public Vector3 Position;
            public Quaternion Rotation;
            public Vector3 Scale;
            public int Mask;

            // SpriteRenderer
            public int SpriteIndex;
            public int ShaderIndex;
            public Color Color;
            public int SortingOrder;
            public int SortingLayerId;
            public bool FlipX, FlipY, RendererEnabled;

            // Colliders. Plural on purpose: Hollow Knight's tilemap chunks carry
            // several EdgeCollider2Ds on a single GameObject, and they are the floor.
            public BoxDef[] Boxes;
            public EdgeDef[] Edges;
            public PolyDef[] Polys;

            // CameraLockArea
            public float CamXMin, CamYMin, CamXMax, CamYMax;
            public bool PreventLookUp, PreventLookDown, MaxPriority;

            // RespawnMarker / HazardRespawnMarker
            public bool RespawnFacingRight;
            public bool HazardFacingRight;

            /// <summary>Components attachable by name alone.</summary>
            public string[] SimpleComponents;

            // BossSequenceDoor - a Pantheon entrance. The three indices point at the
            // objects BossSequenceDoor.Start() would normally toggle.
            public string DoorPlayerData, DoorSequence;
            public int DoorLockSet, DoorUnlockedSet, DoorPrompt;

            // AudioSource
            public int ClipIndex;
            public float Volume, Pitch, SpatialBlend;
            public bool Loop, PlayOnAwake, AudioEnabled;

            // BossStatue - a Hall of Gods plinth.
            public string StatueBoss, StatueDream;

            // MeshFilter + MeshRenderer. The tilemap chunks are Godhome's floors and
            // walls, so these are the level's actual structure.
            public Vector3[] MeshVerts;
            public Vector2[] MeshUVs;
            public int[] MeshTris;
            public int MeshPage, MeshShaderIndex, MeshSortingOrder, MeshSortingLayerId;
            public bool MeshEnabled;

            // TransitionPoint
            public string TargetScene, EntryPoint;
            public Vector2 EntryOffset;
            public float EntryDelay;
            public bool IsADoor, DontWalkOutOfDoor, AlwaysEnterRight, AlwaysEnterLeft;
            public bool HardLandOnExit, NonHazardGate;

            // Rigidbody2D + CircleCollider2D. Boxes, edges and polygons have their own
            // mask bits; these two had nowhere to go, and every SetVelocity2d in a
            // boss's FSM pushes a Rigidbody2D.
            public bool HasBody;
            public float Mass, GravityScale, LinearDrag, AngularDrag;
            public int BodyType, Constraints, CollisionDetection, Interpolate;
            public CircleDef[] Circles;

            // v12 behaviour.
            public Tk2dDef Tk2d;
            public FsmData.Fsm[] Fsms;
            public ComponentDef[] Components;
        }

        /// <summary>
        /// Hollow Knight's per-room colour grading, lifted from the scene's SceneManager.
        /// Silksong's CustomSceneManager has all of these under the same names.
        /// </summary>
        public sealed class Lighting
        {
            public int DarknessLevel;
            public float Saturation;
            public Color DefaultColor;
            public float DefaultIntensity;
            public Color HeroLightColor;
            public AnimationCurve Red, Green, Blue;
        }

        /// <summary>
        /// One field of a rebuilt component, named rather than positioned.
        ///
        /// Hollow Knight's HealthManager and Silksong's are not the same class, so fields
        /// are matched by name and anything that no longer exists is left alone.
        /// </summary>
        public sealed class FieldDef
        {
            public string Name;
            public int Kind;
            public bool B;
            public int I;
            public long L;
            public float F;
            public double D;
            public string S;
            public Vector4 V;

            /// <summary>A reference: an object in this room, or a baked asset by name.</summary>
            public int RefObject = -1;
            public string RefComponent, RefAsset;

            public int ElemKind;
            public FieldDef[] Items;      // array elements
            public FieldDef[] Fields;     // inline struct
        }

        public sealed class ComponentDef
        {
            public string TypeName;
            public FieldDef[] Fields;
        }

        /// <summary>tk2d sprite and animator, indexing the scene's shared tables.</summary>
        public sealed class Tk2dDef
        {
            public bool HasSprite;
            public int CollectionIndex, SpriteId, RenderLayer;
            public Color SpriteColor;
            public Vector3 SpriteScale;

            public bool HasAnimator;
            public int LibraryIndex, DefaultClipId;
            public bool PlayAutomatically;
        }

        /// <summary>A prefab the room's FSMs spawn, as its own flat node tree.</summary>
        public sealed class PrefabDef
        {
            public string Name;
            public PrefabNode[] Nodes;
        }

        public sealed class PrefabNode
        {
            public string Name;
            public int Parent, Layer;
            public bool Active;
            public Vector3 Position, Scale;
            public Quaternion Rotation;
            public int Mask;

            public bool HasBody;
            public float Mass, GravityScale, LinearDrag, AngularDrag;
            public int BodyType, Constraints, CollisionDetection, Interpolate;
            public BoxDef[] Boxes;
            public CircleDef[] Circles;
            public PolyDef[] Polys;
            public EdgeDef[] Edges;

            public Tk2dDef Tk2d;
            public FsmData.Fsm[] Fsms;
            public ComponentDef[] Components;
        }

        public sealed class CircleDef
        {
            public Vector2 Offset;
            public float Radius;
            public bool Trigger, Enabled;
        }

        /// <summary>One of Godhome's sounds: mono 16-bit PCM at 22050 Hz.</summary>
        public sealed class ClipDef
        {
            public string Name;
            public int SampleCount;
            public int Rate;
            /// <summary>0 = 16-bit PCM, 1 = IMA ADPCM (music).</summary>
            public int Format;
        }

        /// <summary>
        /// A ScriptableObject the room refers to - a MusicCue, an audio event table.
        /// Encoded exactly like a component, because it is the same problem.
        /// </summary>
        public sealed class AssetDef
        {
            public string Name;
            public ComponentDef Data;
        }

        public sealed class BakedScene
        {
            public string Name;
            public ClipDef[] Clips;
            public Lighting Light;

            /// <summary>
            /// Scene size in world units, read from Hollow Knight's tk2dTileMap.
            /// CameraController derives sceneWidth/sceneHeight and xLimit/yLimit from
            /// exactly these numbers.
            /// </summary>
            public float Width, Height;

            public string[] ShaderNames;
            public string[] PageNames;
            public SpriteDef[] Sprites;
            public ObjectDef[] Objects;

            // The behaviour layer's shared tables.
            public BossData.Collection[] Collections;
            public BossData.Library[] Libraries;
            public PrefabDef[] Prefabs;
            public AssetDef[] Assets;
        }

        // ------------------------------------------------------------------

        /// <summary>Names of every scene baked into this build.</summary>
        public static HashSet<string> Available
        {
            get
            {
                if (_available != null) return _available;

                _available = new HashSet<string>(StringComparer.Ordinal);
                foreach (string n in GodhomeResources.WithExtension(".scene"))
                {
                    _available.Add(n.Substring(0, n.Length - ".scene".Length));
                }

                if (_available.Count == 0)
                {
                    Plugin.Log.LogWarning(
                        "Godhome: no baked scenes found, either beside the DLL or in it. Run " +
                        "tools/extract_godhome.py and rebuild.");
                }
                else
                {
                    Plugin.Log.LogInfo($"Godhome: {_available.Count} baked scene(s): {string.Join(", ", ToArray(_available))}");
                }
                return _available;
            }
        }

        private static string[] ToArray(HashSet<string> set)
        {
            var a = new string[set.Count];
            set.CopyTo(a);
            Array.Sort(a, StringComparer.Ordinal);
            return a;
        }

        public static bool HasScene(string name) => Available.Contains(name);

        public static BakedScene Load(string name)
        {
            if (Cache.TryGetValue(name, out BakedScene cached)) return cached;

            Stream s = GodhomeResources.Open(name + ".scene");
            if (s == null)
            {
                Plugin.Log.LogError($"Godhome: no baked data for '{name}'.");
                return null;
            }

            try
            {
                using (s)
                using (Stream body = Inflate(s))
                using (var r = new BinaryReader(body))
                {
                    BakedScene scene = Read(r, name);
                    Cache[name] = scene;
                    return scene;
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Godhome: baked data for '{name}' is unreadable: {e}");
                return null;
            }
        }

        /// <summary>
        /// Unwraps a deflated room, or hands back the stream untouched if it is not one.
        /// The whole thing is inflated into memory rather than streamed, because the
        /// reader seeks and a DeflateStream cannot.
        /// </summary>
        private static Stream Inflate(Stream s)
        {
            var head = new byte[8];
            int got = s.Read(head, 0, 8);
            if (got == 8 &&
                head[0] == (byte)'G' && head[1] == (byte)'G' &&
                head[2] == (byte)'H' && head[3] == (byte)'Z')
            {
                int raw = head[4] | (head[5] << 8) | (head[6] << 16) | (head[7] << 24);
                var outp = new MemoryStream(raw > 0 ? raw : 0);
                using (var d = new DeflateStream(s, CompressionMode.Decompress, leaveOpen: true))
                {
                    d.CopyTo(outp);
                }
                if (raw > 0 && outp.Length != raw)
                {
                    Plugin.Log.LogWarning(
                        $"Godhome: room inflated to {outp.Length} bytes, header says {raw}.");
                }
                outp.Position = 0;
                return outp;
            }

            // Not compressed: rewind past what we peeked and read it straight.
            var all = new MemoryStream();
            all.Write(head, 0, got);
            s.CopyTo(all);
            all.Position = 0;
            return all;
        }

        /// <summary>
        /// Loads a baked clip into an AudioClip.
        ///
        /// The extractor stores mono 16-bit PCM, which is exactly what AudioClip.SetData
        /// wants once it's scaled to floats - so there's no decoder involved at runtime.
        /// </summary>
        public static AudioClip LoadClip(ClipDef def)
        {
            if (def == null || def.SampleCount <= 0) return null;

            string ext = def.Format == 1 ? ".adpcm" : ".pcm";
            Stream s = GodhomeResources.Open(def.Name + ext);
            if (s == null)
            {
                Plugin.Log.LogWarning($"Godhome: audio clip '{def.Name}' is missing from the DLL.");
                return null;
            }

            byte[] bytes;
            using (s)
            using (var ms = new MemoryStream())
            {
                s.CopyTo(ms);
                bytes = ms.ToArray();
            }

            float[] data;
            int count;
            if (def.Format == 1)
            {
                count = Mathf.Min(def.SampleCount, bytes.Length * 2);
                if (count <= 0) return null;
                data = DecodeAdpcm(bytes, count);
            }
            else
            {
                count = Mathf.Min(def.SampleCount, bytes.Length / 2);
                if (count <= 0) return null;
                data = new float[count];
                for (int i = 0; i < count; i++)
                {
                    short v = (short)(bytes[i * 2] | (bytes[i * 2 + 1] << 8));
                    data[i] = v / 32768f;
                }
            }

            AudioClip clip = AudioClip.Create(def.Name, count, 1, def.Rate, false);
            clip.SetData(data, 0);
            return clip;
        }

        private static readonly int[] AdpcmIndex =
            { -1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8 };

        private static readonly int[] AdpcmStep =
        {
            7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
            50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230,
            253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963,
            1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327,
            3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442,
            11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794,
            32767,
        };

        /// <summary>
        /// IMA ADPCM, mirroring tools/adpcm.py step for step.
        ///
        /// Godhome's music is minutes long, which is megabytes a track as 16-bit PCM.
        /// Four bits a sample is a quarter of that, and on orchestral material at 22 kHz
        /// it is a far better trade than halving the sample rate. Encoder and decoder
        /// must agree exactly, clamps included, or the track turns to noise - which is
        /// why both are written the same way round.
        /// </summary>
        private static float[] DecodeAdpcm(byte[] data, int count)
        {
            var outp = new float[count];
            int predictor = 0;
            int index = 0;
            for (int i = 0; i < count; i++)
            {
                byte b = data[i >> 1];
                int code = ((i & 1) != 0) ? (b >> 4) : (b & 0x0F);

                int step = AdpcmStep[index];
                int diff = step >> 3;
                if ((code & 4) != 0) diff += step;
                if ((code & 2) != 0) diff += step >> 1;
                if ((code & 1) != 0) diff += step >> 2;
                predictor += ((code & 8) != 0) ? -diff : diff;
                if (predictor > 32767) predictor = 32767;
                else if (predictor < -32768) predictor = -32768;

                index += AdpcmIndex[code];
                if (index < 0) index = 0;
                else if (index > 88) index = 88;

                outp[i] = predictor / 32768f;
            }
            return outp;
        }

        /// <summary>Loads an atlas page PNG into a Texture2D.</summary>
        public static Texture2D LoadPage(string pageName)
        {
            Stream s = GodhomeResources.Open(pageName + ".png");
            if (s == null)
            {
                Plugin.Log.LogError($"Godhome: atlas page '{pageName}' is missing from the DLL.");
                return null;
            }

            byte[] bytes;
            using (s)
            using (var ms = new MemoryStream())
            {
                s.CopyTo(ms);
                bytes = ms.ToArray();
            }

            // Size is a placeholder - LoadImage resizes to whatever the PNG holds.
            var tex = new Texture2D(2, 2, TextureFormat.RGBA32, mipChain: false)
            {
                name = pageName,
                // Godhome's art is authored at a fixed pixel scale and never filtered
                // in-game; Bilinear keeps it from crawling when the camera moves.
                filterMode = FilterMode.Bilinear,
                wrapMode = TextureWrapMode.Clamp,
            };

            if (!tex.LoadImage(bytes, markNonReadable: true))
            {
                Plugin.Log.LogError($"Godhome: atlas page '{pageName}' failed to decode.");
                UnityEngine.Object.Destroy(tex);
                return null;
            }
            return tex;
        }

        // ------------------------------------------------------------------

        /// <summary>
        /// The tk2d / FSM / component sections of one object, in mask-bit order.
        /// Shared by scene objects and prefab nodes, which carry the same payload.
        /// </summary>
        private static void ReadBehaviour(BinaryReader r, int mask, out Tk2dDef tk,
                                          out FsmData.Fsm[] fsms, out ComponentDef[] comps)
        {
            tk = null;
            fsms = null;
            comps = null;

            if ((mask & HasTk2d) != 0)
            {
                tk = new Tk2dDef();
                tk.HasSprite = r.ReadBoolean();
                if (tk.HasSprite)
                {
                    tk.CollectionIndex = r.ReadInt32();
                    tk.SpriteId = r.ReadInt32();
                    tk.SpriteColor = new Color(r.ReadSingle(), r.ReadSingle(),
                                               r.ReadSingle(), r.ReadSingle());
                    tk.SpriteScale = new Vector3(r.ReadSingle(), r.ReadSingle(), r.ReadSingle());
                    tk.RenderLayer = r.ReadInt32();
                }
                tk.HasAnimator = r.ReadBoolean();
                if (tk.HasAnimator)
                {
                    tk.LibraryIndex = r.ReadInt32();
                    tk.DefaultClipId = r.ReadInt32();
                    tk.PlayAutomatically = r.ReadBoolean();
                }
            }

            if ((mask & HasFsm) != 0)
            {
                fsms = new FsmData.Fsm[r.ReadInt32()];
                for (int i = 0; i < fsms.Length; i++) fsms[i] = FsmData.ReadFsm(r);
            }

            if ((mask & HasComps) != 0)
            {
                comps = new ComponentDef[r.ReadInt32()];
                for (int i = 0; i < comps.Length; i++)
                {
                    var c = new ComponentDef { TypeName = r.ReadString() };
                    c.Fields = new FieldDef[r.ReadInt32()];
                    for (int k = 0; k < c.Fields.Length; k++) c.Fields[k] = ReadField(r);
                    comps[i] = c;
                }
            }
        }

        // Wire kinds, mirroring compbake.py.
        private const int KBool = 0, KI32 = 1, KI64 = 2, KF32 = 3, KF64 = 4, KString = 5;
        private const int KVec2 = 6, KVec3 = 7, KVec4 = 8, KRef = 9, KArray = 10, KInline = 11;

        private static FieldDef ReadField(BinaryReader r)
        {
            var f = new FieldDef { Name = r.ReadString(), Kind = r.ReadInt32() };
            ReadValue(r, f, f.Kind);
            return f;
        }

        private static void ReadValue(BinaryReader r, FieldDef f, int kind)
        {
            switch (kind)
            {
                case KBool: f.B = r.ReadBoolean(); break;
                case KI32: f.I = r.ReadInt32(); break;
                case KI64: f.L = r.ReadInt64(); break;
                case KF32: f.F = r.ReadSingle(); break;
                case KF64: f.D = r.ReadDouble(); break;
                case KString: f.S = r.ReadString(); break;
                case KVec2: f.V = new Vector4(r.ReadSingle(), r.ReadSingle(), 0, 0); break;
                case KVec3: f.V = new Vector4(r.ReadSingle(), r.ReadSingle(), r.ReadSingle(), 0); break;
                case KVec4:
                    f.V = new Vector4(r.ReadSingle(), r.ReadSingle(), r.ReadSingle(), r.ReadSingle());
                    break;
                case KRef:
                    f.RefObject = r.ReadInt32();
                    f.RefComponent = r.ReadString();
                    f.RefAsset = r.ReadString();
                    break;
                case KArray:
                {
                    f.ElemKind = r.ReadInt32();
                    f.Items = new FieldDef[r.ReadInt32()];
                    for (int i = 0; i < f.Items.Length; i++)
                    {
                        var e = new FieldDef { Kind = f.ElemKind };
                        ReadValue(r, e, f.ElemKind);
                        f.Items[i] = e;
                    }
                    break;
                }
                case KInline:
                {
                    f.Fields = new FieldDef[r.ReadInt32()];
                    for (int i = 0; i < f.Fields.Length; i++) f.Fields[i] = ReadField(r);
                    break;
                }
                default:
                    throw new InvalidDataException($"unknown field kind {kind}");
            }
        }

        private static PolyDef ReadPoly(BinaryReader r)
        {
            var def = new PolyDef { Offset = new Vector2(r.ReadSingle(), r.ReadSingle()) };
            int paths = r.ReadInt32();
            def.Paths = new Vector2[paths][];
            for (int p = 0; p < paths; p++)
            {
                int n = r.ReadInt32();
                var pts = new Vector2[n];
                for (int q = 0; q < n; q++) pts[q] = new Vector2(r.ReadSingle(), r.ReadSingle());
                def.Paths[p] = pts;
            }
            def.Trigger = r.ReadBoolean();
            def.Enabled = r.ReadBoolean();
            return def;
        }

        private static EdgeDef ReadEdge(BinaryReader r)
        {
            var def = new EdgeDef { Offset = new Vector2(r.ReadSingle(), r.ReadSingle()) };
            int n = r.ReadInt32();
            def.Points = new Vector2[n];
            for (int p = 0; p < n; p++) def.Points[p] = new Vector2(r.ReadSingle(), r.ReadSingle());
            def.Trigger = r.ReadBoolean();
            def.Enabled = r.ReadBoolean();
            return def;
        }

        private static PrefabNode ReadPrefabNode(BinaryReader r)
        {
            var n = new PrefabNode
            {
                Name = r.ReadString(),
                Parent = r.ReadInt32(),
                Layer = r.ReadInt32(),
                Active = r.ReadBoolean(),
                Position = new Vector3(r.ReadSingle(), r.ReadSingle(), r.ReadSingle()),
                Rotation = new Quaternion(r.ReadSingle(), r.ReadSingle(), r.ReadSingle(), r.ReadSingle()),
                Scale = new Vector3(r.ReadSingle(), r.ReadSingle(), r.ReadSingle()),
            };
            n.Mask = r.ReadInt32();

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

            n.Polys = new PolyDef[r.ReadInt32()];
            for (int i = 0; i < n.Polys.Length; i++) n.Polys[i] = ReadPoly(r);

            n.Edges = new EdgeDef[r.ReadInt32()];
            for (int i = 0; i < n.Edges.Length; i++) n.Edges[i] = ReadEdge(r);

            ReadBehaviour(r, n.Mask, out n.Tk2d, out n.Fsms, out n.Components);
            return n;
        }

        private static AnimationCurve ReadCurve(BinaryReader r)
        {
            int n = r.ReadInt32();
            var keys = new Keyframe[n];
            for (int i = 0; i < n; i++)
            {
                keys[i] = new Keyframe(r.ReadSingle(), r.ReadSingle(), r.ReadSingle(), r.ReadSingle());
            }
            return new AnimationCurve(keys);
        }

        private static BakedScene Read(BinaryReader r, string expectedName)
        {
            var magic = new string(r.ReadChars(4));
            if (magic != Magic)
                throw new InvalidDataException($"bad magic '{magic}', expected '{Magic}'");

            int version = r.ReadInt32();
            if (version != FormatVersion)
                throw new InvalidDataException(
                    $"format version {version}, expected {FormatVersion} - re-run tools/extract_godhome.py");

            var scene = new BakedScene { Name = r.ReadString() };
            if (scene.Name != expectedName)
                Plugin.Log.LogWarning($"Godhome: '{expectedName}.scene' declares itself as '{scene.Name}'.");

            scene.Width = r.ReadSingle();
            scene.Height = r.ReadSingle();

            if (r.ReadBoolean())
            {
                var l = new Lighting
                {
                    DarknessLevel = r.ReadInt32(),
                    Saturation = r.ReadSingle(),
                    DefaultColor = new Color(r.ReadSingle(), r.ReadSingle(), r.ReadSingle(), r.ReadSingle()),
                    DefaultIntensity = r.ReadSingle(),
                    HeroLightColor = new Color(r.ReadSingle(), r.ReadSingle(), r.ReadSingle(), r.ReadSingle()),
                };
                l.Red = ReadCurve(r);
                l.Green = ReadCurve(r);
                l.Blue = ReadCurve(r);
                scene.Light = l;
            }

            int shaderCount = r.ReadInt32();
            scene.ShaderNames = new string[shaderCount];
            for (int i = 0; i < shaderCount; i++) scene.ShaderNames[i] = r.ReadString();

            int clipCount = r.ReadInt32();
            scene.Clips = new ClipDef[clipCount];
            for (int i = 0; i < clipCount; i++)
            {
                scene.Clips[i] = new ClipDef
                {
                    Name = r.ReadString(),
                    SampleCount = r.ReadInt32(),
                    Rate = r.ReadInt32(),
                };
            }

            int pageCount = r.ReadInt32();
            scene.PageNames = new string[pageCount];
            for (int i = 0; i < pageCount; i++) scene.PageNames[i] = r.ReadString();

            int spriteCount = r.ReadInt32();
            scene.Sprites = new SpriteDef[spriteCount];
            for (int i = 0; i < spriteCount; i++)
            {
                scene.Sprites[i] = new SpriteDef
                {
                    Name = r.ReadString(),
                    Page = r.ReadInt32(),
                    Rect = new Rect(r.ReadSingle(), r.ReadSingle(), r.ReadSingle(), r.ReadSingle()),
                    Pivot = new Vector2(r.ReadSingle(), r.ReadSingle()),
                    Ppu = r.ReadSingle(),
                    Border = new Vector4(r.ReadSingle(), r.ReadSingle(), r.ReadSingle(), r.ReadSingle()),
                };
            }

            // The behaviour layer's shared tables: sprite collections and animation
            // libraries the room's objects index into, then the prefabs its FSMs spawn.
            scene.Collections = new BossData.Collection[r.ReadInt32()];
            for (int i = 0; i < scene.Collections.Length; i++)
                scene.Collections[i] = BossData.ReadCollection(r);

            scene.Libraries = new BossData.Library[r.ReadInt32()];
            for (int i = 0; i < scene.Libraries.Length; i++)
                scene.Libraries[i] = BossData.ReadLibrary(r);

            scene.Assets = new AssetDef[r.ReadInt32()];
            for (int i = 0; i < scene.Assets.Length; i++)
            {
                var a = new AssetDef { Name = r.ReadString() };
                var c = new ComponentDef { TypeName = r.ReadString() };
                c.Fields = new FieldDef[r.ReadInt32()];
                for (int k = 0; k < c.Fields.Length; k++) c.Fields[k] = ReadField(r);
                a.Data = c;
                scene.Assets[i] = a;
            }

            int behaviourClips = r.ReadInt32();
            var extraClips = new List<ClipDef>(scene.Clips);
            for (int i = 0; i < behaviourClips; i++)
            {
                extraClips.Add(new ClipDef
                {
                    Name = r.ReadString(),
                    SampleCount = r.ReadInt32(),
                    Rate = r.ReadInt32(),
                    Format = r.ReadInt32(),
                });
            }
            scene.Clips = extraClips.ToArray();

            scene.Prefabs = new PrefabDef[r.ReadInt32()];
            for (int i = 0; i < scene.Prefabs.Length; i++)
            {
                var p = new PrefabDef { Name = r.ReadString() };
                p.Nodes = new PrefabNode[r.ReadInt32()];
                for (int k = 0; k < p.Nodes.Length; k++) p.Nodes[k] = ReadPrefabNode(r);
                scene.Prefabs[i] = p;
            }

            int objCount = r.ReadInt32();
            scene.Objects = new ObjectDef[objCount];
            for (int i = 0; i < objCount; i++)
            {
                var o = new ObjectDef
                {
                    Name = r.ReadString(),
                    Parent = r.ReadInt32(),
                    Layer = r.ReadInt32(),
                    Active = r.ReadBoolean(),
                    Position = new Vector3(r.ReadSingle(), r.ReadSingle(), r.ReadSingle()),
                    Rotation = new Quaternion(r.ReadSingle(), r.ReadSingle(), r.ReadSingle(), r.ReadSingle()),
                    Scale = new Vector3(r.ReadSingle(), r.ReadSingle(), r.ReadSingle()),
                };
                o.Mask = r.ReadInt32();

                if ((o.Mask & HasSprite) != 0)
                {
                    o.SpriteIndex = r.ReadInt32();
                    o.ShaderIndex = r.ReadInt32();
                    o.Color = new Color(r.ReadSingle(), r.ReadSingle(), r.ReadSingle(), r.ReadSingle());
                    o.SortingOrder = r.ReadInt32();
                    o.SortingLayerId = r.ReadInt32();
                    o.FlipX = r.ReadBoolean();
                    o.FlipY = r.ReadBoolean();
                    o.RendererEnabled = r.ReadBoolean();
                }

                if ((o.Mask & HasBox) != 0)
                {
                    o.Boxes = new BoxDef[r.ReadInt32()];
                    for (int b = 0; b < o.Boxes.Length; b++)
                    {
                        o.Boxes[b] = new BoxDef
                        {
                            Offset = new Vector2(r.ReadSingle(), r.ReadSingle()),
                            Size = new Vector2(r.ReadSingle(), r.ReadSingle()),
                            Trigger = r.ReadBoolean(),
                            Enabled = r.ReadBoolean(),
                        };
                    }
                }

                if ((o.Mask & HasEdge) != 0)
                {
                    o.Edges = new EdgeDef[r.ReadInt32()];
                    for (int e = 0; e < o.Edges.Length; e++)
                    {
                        var def = new EdgeDef
                        {
                            Offset = new Vector2(r.ReadSingle(), r.ReadSingle()),
                        };
                        int n = r.ReadInt32();
                        def.Points = new Vector2[n];
                        for (int p = 0; p < n; p++)
                            def.Points[p] = new Vector2(r.ReadSingle(), r.ReadSingle());
                        def.Trigger = r.ReadBoolean();
                        def.Enabled = r.ReadBoolean();
                        o.Edges[e] = def;
                    }
                }

                if ((o.Mask & HasPoly) != 0)
                {
                    o.Polys = new PolyDef[r.ReadInt32()];
                    for (int y = 0; y < o.Polys.Length; y++)
                    {
                        var def = new PolyDef
                        {
                            Offset = new Vector2(r.ReadSingle(), r.ReadSingle()),
                        };
                        int paths = r.ReadInt32();
                        def.Paths = new Vector2[paths][];
                        for (int p = 0; p < paths; p++)
                        {
                            int n = r.ReadInt32();
                            var pts = new Vector2[n];
                            for (int q = 0; q < n; q++)
                                pts[q] = new Vector2(r.ReadSingle(), r.ReadSingle());
                            def.Paths[p] = pts;
                        }
                        def.Trigger = r.ReadBoolean();
                        def.Enabled = r.ReadBoolean();
                        o.Polys[y] = def;
                    }
                }

                if ((o.Mask & HasCamLock) != 0)
                {
                    o.CamXMin = r.ReadSingle();
                    o.CamYMin = r.ReadSingle();
                    o.CamXMax = r.ReadSingle();
                    o.CamYMax = r.ReadSingle();
                    o.PreventLookUp = r.ReadBoolean();
                    o.PreventLookDown = r.ReadBoolean();
                    o.MaxPriority = r.ReadBoolean();
                }

                if ((o.Mask & HasRespawn) != 0) o.RespawnFacingRight = r.ReadBoolean();
                if ((o.Mask & HasHazard) != 0) o.HazardFacingRight = r.ReadBoolean();

                if ((o.Mask & HasSeqDoor) != 0)
                {
                    o.DoorPlayerData = r.ReadString();
                    o.DoorSequence = r.ReadString();
                    o.DoorLockSet = r.ReadInt32();
                    o.DoorUnlockedSet = r.ReadInt32();
                    o.DoorPrompt = r.ReadInt32();
                }

                if ((o.Mask & HasAudio) != 0)
                {
                    o.ClipIndex = r.ReadInt32();
                    o.Volume = r.ReadSingle();
                    o.Pitch = r.ReadSingle();
                    o.SpatialBlend = r.ReadSingle();
                    o.Loop = r.ReadBoolean();
                    o.PlayOnAwake = r.ReadBoolean();
                    o.AudioEnabled = r.ReadBoolean();
                }

                if ((o.Mask & HasStatue) != 0)
                {
                    o.StatueBoss = r.ReadString();
                    o.StatueDream = r.ReadString();
                }

                if ((o.Mask & HasMesh) != 0)
                {
                    int vn = r.ReadInt32();
                    o.MeshVerts = new Vector3[vn];
                    o.MeshUVs = new Vector2[vn];
                    for (int v = 0; v < vn; v++)
                    {
                        o.MeshVerts[v] = new Vector3(r.ReadSingle(), r.ReadSingle(), r.ReadSingle());
                        o.MeshUVs[v] = new Vector2(r.ReadSingle(), r.ReadSingle());
                    }
                    int tn = r.ReadInt32();
                    o.MeshTris = new int[tn * 3];
                    for (int t = 0; t < tn * 3; t++) o.MeshTris[t] = r.ReadInt32();
                    o.MeshPage = r.ReadInt32();
                    o.MeshShaderIndex = r.ReadInt32();
                    o.MeshSortingOrder = r.ReadInt32();
                    o.MeshSortingLayerId = r.ReadInt32();
                    o.MeshEnabled = r.ReadBoolean();
                }

                if ((o.Mask & HasSimple) != 0)
                {
                    o.SimpleComponents = new string[r.ReadInt32()];
                    for (int c = 0; c < o.SimpleComponents.Length; c++)
                        o.SimpleComponents[c] = r.ReadString();
                }

                if ((o.Mask & HasTransition) != 0)
                {
                    o.TargetScene = r.ReadString();
                    o.EntryPoint = r.ReadString();
                    o.EntryOffset = new Vector2(r.ReadSingle(), r.ReadSingle());
                    o.EntryDelay = r.ReadSingle();
                    o.IsADoor = r.ReadBoolean();
                    o.DontWalkOutOfDoor = r.ReadBoolean();
                    o.AlwaysEnterRight = r.ReadBoolean();
                    o.AlwaysEnterLeft = r.ReadBoolean();
                    o.HardLandOnExit = r.ReadBoolean();
                    o.NonHazardGate = r.ReadBoolean();
                }

                if ((o.Mask & HasPhys) != 0)
                {
                    o.HasBody = r.ReadBoolean();
                    if (o.HasBody)
                    {
                        o.Mass = r.ReadSingle();
                        o.GravityScale = r.ReadSingle();
                        o.LinearDrag = r.ReadSingle();
                        o.AngularDrag = r.ReadSingle();
                        o.BodyType = r.ReadInt32();
                        o.Constraints = r.ReadInt32();
                        o.CollisionDetection = r.ReadInt32();
                        o.Interpolate = r.ReadInt32();
                    }
                    o.Circles = new CircleDef[r.ReadInt32()];
                    for (int c = 0; c < o.Circles.Length; c++)
                    {
                        o.Circles[c] = new CircleDef
                        {
                            Offset = new Vector2(r.ReadSingle(), r.ReadSingle()),
                            Radius = r.ReadSingle(),
                            Trigger = r.ReadBoolean(),
                            Enabled = r.ReadBoolean(),
                        };
                    }
                }

                ReadBehaviour(r, o.Mask, out o.Tk2d, out o.Fsms, out o.Components);

                scene.Objects[i] = o;
            }

            return scene;
        }
    }
}
