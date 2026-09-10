using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// The baked form of a Hollow Knight FSM.
    ///
    /// Deliberately dumb: this mirrors PlayMaker's own `ActionData` field-for-field rather
    /// than trying to model what actions mean. <see cref="FsmBuilder"/> pushes these lists
    /// straight back into Silksong's ActionData and lets `LoadActions` construct the real
    /// action instances - which works because every [SerializeField] in ActionData is
    /// identical between Hollow Knight's PlayMaker 1.9.0 and Silksong's 1.9.9.
    /// </summary>
    internal static class FsmData
    {
        /// <summary>A PlayMaker variable of any type, in its baked form.</summary>
        public sealed class Var
        {
            public bool UseVariable;
            public string Name, Tooltip;
            public bool ShowInInspector, NetworkSync;

            public float F;
            public int I;
            public bool B;
            public string S;
            public Vector4 V;
            public string TypeName;      // FsmObject / FsmEnum
            /// <summary>Resource name of a baked asset for this reference, or empty.</summary>
            public string Resource;
        }

        public sealed class ActionData
        {
            public string[] ActionNames, CustomNames;
            public bool[] ActionEnabled, ActionIsOpen;
            public int[] ActionStartIndex, ActionHashCodes;

            public int UnityObjectCount, TemplateControlCount;

            public List<Var> GameObjects = new List<Var>();
            public List<Var> OwnerDefaults = new List<Var>();
            public List<int> OwnerOptions = new List<int>();
            public List<Var> Strings = new List<Var>();
            public List<Var> Objects = new List<Var>();
            public List<Var> Enums = new List<Var>();
            public List<Var> Floats = new List<Var>();
            public List<Var> Ints = new List<Var>();
            public List<Var> Bools = new List<Var>();
            public List<Var> Vector2s = new List<Var>();
            public List<Var> Vector3s = new List<Var>();
            public List<Var> Colors = new List<Var>();
            public List<Var> Rects = new List<Var>();
            public List<Var> Quaternions = new List<Var>();

            /// <summary>Composites we can't faithfully rebuild yet; only counts are kept.</summary>
            public int CurveCount, FunctionCallCount, EventTargetCount,
                       PropertyCount, LayoutOptionCount, VarCount, ArrayCount;

            public string[] StringParams;
            public byte[] ByteData;
            public int[] ArrayParamSizes, CustomTypeSizes;
            public string[] ArrayParamTypes, CustomTypeNames;
            public int[] ParamDataType, ParamDataPos, ParamByteDataSize;
            public string[] ParamName;
        }

        public sealed class Transition
        {
            public string EventName, ToState;
        }

        public sealed class State
        {
            public string Name;
            public Transition[] Transitions;
            public ActionData Actions;
        }

        public sealed class Event
        {
            public string Name;
            public bool IsSystem, IsGlobal;
        }

        public sealed class Fsm
        {
            public string Name, StartState;
            public List<Var> Floats = new List<Var>();
            public List<Var> Ints = new List<Var>();
            public List<Var> Bools = new List<Var>();
            public List<Var> Strings = new List<Var>();
            public List<Var> Vector2s = new List<Var>();
            public List<Var> Vector3s = new List<Var>();
            public List<Var> Colors = new List<Var>();
            public List<Var> Rects = new List<Var>();
            public List<Var> Quaternions = new List<Var>();
            public List<Var> GameObjects = new List<Var>();
            public List<Var> Objects = new List<Var>();
            public int ArrayCount;
            public List<Var> Enums = new List<Var>();
            public Event[] Events;
            public State[] States;
        }

        // ------------------------------------------------------------------

        private static Var ReadNamed(BinaryReader r)
        {
            return new Var
            {
                UseVariable = r.ReadBoolean(),
                Name = r.ReadString(),
                Tooltip = r.ReadString(),
                ShowInInspector = r.ReadBoolean(),
                NetworkSync = r.ReadBoolean(),
            };
        }

        private static Var F(BinaryReader r) { Var v = ReadNamed(r); v.F = r.ReadSingle(); return v; }
        private static Var I(BinaryReader r) { Var v = ReadNamed(r); v.I = r.ReadInt32(); return v; }
        private static Var B(BinaryReader r) { Var v = ReadNamed(r); v.B = r.ReadBoolean(); return v; }
        private static Var S(BinaryReader r) { Var v = ReadNamed(r); v.S = r.ReadString(); return v; }
        private static Var V2(BinaryReader r) { Var v = ReadNamed(r); v.V = new Vector4(r.ReadSingle(), r.ReadSingle(), 0, 0); return v; }
        private static Var V3(BinaryReader r) { Var v = ReadNamed(r); v.V = new Vector4(r.ReadSingle(), r.ReadSingle(), r.ReadSingle(), 0); return v; }
        private static Var V4(BinaryReader r) { Var v = ReadNamed(r); v.V = new Vector4(r.ReadSingle(), r.ReadSingle(), r.ReadSingle(), r.ReadSingle()); return v; }
        private static Var Obj(BinaryReader r)
        {
            Var v = ReadNamed(r);
            v.TypeName = r.ReadString();
            v.Resource = r.ReadString();
            return v;
        }
        /// <summary>
        /// An FsmGameObject. <see cref="Var.Resource"/> holds the name of a baked prefab
        /// when the pointer named one - a boss's needle, its hit effect - and is empty
        /// otherwise.
        /// </summary>
        private static Var GO(BinaryReader r)
        {
            Var v = ReadNamed(r);
            v.Resource = r.ReadString();
            return v;
        }
        private static Var En(BinaryReader r) { Var v = ReadNamed(r); v.TypeName = r.ReadString(); v.I = r.ReadInt32(); return v; }

        private static void ReadList(BinaryReader r, List<Var> into, System.Func<BinaryReader, Var> fn)
        {
            int n = r.ReadInt32();
            for (int i = 0; i < n; i++) into.Add(fn(r));
        }

        /// <summary>Skips an FsmArray, which we don't rebuild.</summary>
        private static void SkipArray(BinaryReader r)
        {
            ReadNamed(r);
            r.ReadInt32();                    // type
            r.ReadString();                   // objectTypeName
            int n = r.ReadInt32(); for (int i = 0; i < n; i++) r.ReadSingle();
            n = r.ReadInt32(); for (int i = 0; i < n; i++) r.ReadInt32();
            n = r.ReadInt32(); for (int i = 0; i < n; i++) r.ReadBoolean();
            n = r.ReadInt32(); for (int i = 0; i < n; i++) r.ReadString();
            n = r.ReadInt32(); for (int i = 0; i < n; i++) { r.ReadSingle(); r.ReadSingle(); r.ReadSingle(); r.ReadSingle(); }
        }

        private static string[] Strs(BinaryReader r)
        {
            var a = new string[r.ReadInt32()];
            for (int i = 0; i < a.Length; i++) a[i] = r.ReadString();
            return a;
        }

        private static int[] Ints(BinaryReader r)
        {
            var a = new int[r.ReadInt32()];
            for (int i = 0; i < a.Length; i++) a[i] = r.ReadInt32();
            return a;
        }

        private static bool[] Bools(BinaryReader r)
        {
            var a = new bool[r.ReadInt32()];
            for (int i = 0; i < a.Length; i++) a[i] = r.ReadBoolean();
            return a;
        }

        public static ActionData ReadActionData(BinaryReader r)
        {
            var d = new ActionData();
            d.ActionNames = Strs(r); d.CustomNames = Strs(r);
            d.ActionEnabled = Bools(r); d.ActionIsOpen = Bools(r);
            d.ActionStartIndex = Ints(r); d.ActionHashCodes = Ints(r);

            d.UnityObjectCount = r.ReadInt32();

            ReadList(r, d.GameObjects, GO);

            int n = r.ReadInt32();
            for (int i = 0; i < n; i++) { d.OwnerOptions.Add(r.ReadInt32()); d.OwnerDefaults.Add(GO(r)); }

            d.CurveCount = r.ReadInt32();
            for (int i = 0; i < d.CurveCount; i++)
            {
                int k = r.ReadInt32();
                for (int j = 0; j < k; j++) { r.ReadSingle(); r.ReadSingle(); r.ReadSingle(); r.ReadSingle(); }
            }

            d.FunctionCallCount = r.ReadInt32();
            for (int i = 0; i < d.FunctionCallCount; i++) SkipFunctionCall(r);

            d.TemplateControlCount = r.ReadInt32();

            d.EventTargetCount = r.ReadInt32();
            for (int i = 0; i < d.EventTargetCount; i++)
            {
                r.ReadInt32(); B(r); r.ReadInt32(); GO(r); S(r); B(r);
            }

            d.PropertyCount = r.ReadInt32();
            for (int i = 0; i < d.PropertyCount; i++) SkipProperty(r);

            d.LayoutOptionCount = r.ReadInt32();
            for (int i = 0; i < d.LayoutOptionCount; i++) { r.ReadInt32(); F(r); B(r); }

            ReadList(r, d.Strings, S);
            ReadList(r, d.Objects, Obj);

            d.VarCount = r.ReadInt32();
            for (int i = 0; i < d.VarCount; i++) SkipVar(r);

            d.ArrayCount = r.ReadInt32();
            for (int i = 0; i < d.ArrayCount; i++) SkipArray(r);

            ReadList(r, d.Enums, En);
            ReadList(r, d.Floats, F);
            ReadList(r, d.Ints, I);
            ReadList(r, d.Bools, B);
            ReadList(r, d.Vector2s, V2);
            ReadList(r, d.Vector3s, V3);
            ReadList(r, d.Colors, V4);
            ReadList(r, d.Rects, V4);
            ReadList(r, d.Quaternions, V4);

            d.StringParams = Strs(r);
            d.ByteData = r.ReadBytes(r.ReadInt32());
            d.ArrayParamSizes = Ints(r); d.ArrayParamTypes = Strs(r);
            d.CustomTypeSizes = Ints(r); d.CustomTypeNames = Strs(r);
            d.ParamDataType = Ints(r); d.ParamName = Strs(r);
            d.ParamDataPos = Ints(r); d.ParamByteDataSize = Ints(r);
            return d;
        }

        private static void SkipFunctionCall(BinaryReader r)
        {
            r.ReadString(); r.ReadString();
            B(r); F(r); I(r); GO(r); Obj(r); S(r); V2(r); V3(r); V4(r); V4(r);
            Obj(r); Obj(r); V4(r); En(r); SkipArray(r);
        }

        private static void SkipProperty(BinaryReader r)
        {
            Obj(r); r.ReadString(); r.ReadString();
            B(r); F(r); I(r); GO(r); S(r); V2(r); V3(r); V4(r); V4(r);
            Obj(r); Obj(r); Obj(r); V4(r); En(r); SkipArray(r); r.ReadBoolean();
        }

        private static void SkipVar(BinaryReader r)
        {
            r.ReadString(); r.ReadString(); r.ReadBoolean(); r.ReadInt32();
            r.ReadSingle(); r.ReadInt32(); r.ReadBoolean(); r.ReadString();
            r.ReadSingle(); r.ReadSingle(); r.ReadSingle(); r.ReadSingle();
            SkipArray(r);
        }

        public static Fsm ReadFsm(BinaryReader r)
        {
            var f = new Fsm { Name = r.ReadString(), StartState = r.ReadString() };

            ReadList(r, f.Floats, F); ReadList(r, f.Ints, I); ReadList(r, f.Bools, B);
            ReadList(r, f.Strings, S); ReadList(r, f.Vector2s, V2); ReadList(r, f.Vector3s, V3);
            ReadList(r, f.Colors, V4); ReadList(r, f.Rects, V4); ReadList(r, f.Quaternions, V4);
            ReadList(r, f.GameObjects, GO); ReadList(r, f.Objects, Obj);
            f.ArrayCount = r.ReadInt32();
            for (int i = 0; i < f.ArrayCount; i++) SkipArray(r);
            ReadList(r, f.Enums, En);

            f.Events = new Event[r.ReadInt32()];
            for (int i = 0; i < f.Events.Length; i++)
            {
                f.Events[i] = new Event
                {
                    Name = r.ReadString(),
                    IsSystem = r.ReadBoolean(),
                    IsGlobal = r.ReadBoolean(),
                };
            }

            f.States = new State[r.ReadInt32()];
            for (int i = 0; i < f.States.Length; i++)
            {
                var st = new State { Name = r.ReadString() };
                st.Transitions = new Transition[r.ReadInt32()];
                for (int k = 0; k < st.Transitions.Length; k++)
                {
                    st.Transitions[k] = new Transition
                    {
                        EventName = r.ReadString(),
                        ToState = r.ReadString(),
                    };
                }
                st.Actions = ReadActionData(r);
                f.States[i] = st;
            }
            return f;
        }
    }
}
