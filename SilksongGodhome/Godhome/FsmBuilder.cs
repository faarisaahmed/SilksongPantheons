using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;
using HutongGames.PlayMaker;
using UnityEngine;

namespace SilksongGodhome.Godhome
{
    /// <summary>
    /// Rebuilds a Hollow Knight FSM as a live PlayMaker graph on a Silksong GameObject.
    ///
    /// The trick that makes this tractable: we never interpret an action. Silksong's
    /// `ActionData` has the same [SerializeField] layout as Hollow Knight's, so pushing
    /// the baked lists back into a fresh ActionData and letting PlayMaker's own
    /// `LoadActions` run gives real, correctly-typed action instances.
    ///
    /// What doesn't cross: anything that was a pointer into Hollow Knight's asset files -
    /// audio clips, material references, spawned prefabs. Audio and prefabs are baked and
    /// re-linked by name; the rest come back null, so actions that use them no-op.
    /// Actions that move, animate, wait, branch, spawn and send events work.
    /// </summary>
    internal static class FsmBuilder
    {
        private static readonly Type ActionDataType = typeof(HutongGames.PlayMaker.ActionData);

        /// <summary>
        /// Assets we managed to bake for FSM references, keyed by resource name. Right
        /// now that's audio: a boss's own buzz, charge and slam, so it sounds like itself.
        /// </summary>
        private static Dictionary<string, UnityEngine.Object> _assets =
            new Dictionary<string, UnityEngine.Object>(StringComparer.Ordinal);

        /// <summary>
        /// Prefabs a boss's FSMs spawn, keyed by baked name. PlayMaker's spawn actions
        /// take an FsmGameObject and Instantiate it; give them a real object and Gorb
        /// throws needles again.
        /// </summary>
        private static Dictionary<string, GameObject> _prefabs =
            new Dictionary<string, GameObject>(StringComparer.Ordinal);

        public static void SetAssets(Dictionary<string, UnityEngine.Object> assets,
                                     Dictionary<string, GameObject> prefabs = null)
        {
            _assets = assets ?? new Dictionary<string, UnityEngine.Object>(StringComparer.Ordinal);
            _prefabs = prefabs ?? new Dictionary<string, GameObject>(StringComparer.Ordinal);
        }

        private static FsmGameObject MakeGameObject(FsmData.Var x)
        {
            var g = new FsmGameObject(x.Name);
            if (!string.IsNullOrEmpty(x.Resource) &&
                _prefabs.TryGetValue(x.Resource, out GameObject prefab) && prefab != null)
            {
                g.Value = prefab;
            }
            return g;
        }

        private static FsmObject MakeObject(FsmData.Var x)
        {
            var o = new FsmObject(x.Name);
            if (string.IsNullOrEmpty(x.Resource)) return o;

            if (_assets.TryGetValue(x.Resource, out UnityEngine.Object asset) && asset != null)
            {
                o.Value = asset;
                return o;
            }

            // A rebuilt ScriptableObject. This is the one that matters for music:
            // ApplyMusicCue takes its MusicCue as an FsmObject, so without this lookup
            // "Gods and Glory" arrives null and the action quietly plays nothing.
            ScriptableObject so = BehaviourBuilder.AssetNamed(x.Resource);
            if (so != null) o.Value = so;
            return o;
        }

        /// <summary>Attaches every baked FSM to <paramref name="go"/>.</summary>
        public static int Attach(GameObject go, IList<FsmData.Fsm> fsms)
        {
            int made = 0;
            foreach (FsmData.Fsm f in fsms)
            {
                try
                {
                    if (Build(go, f)) made++;
                }
                catch (Exception e)
                {
                    Plugin.Log.LogError($"Godhome: FSM '{f.Name}' failed to build: {e}");
                }
            }
            return made;
        }

        private static bool Build(GameObject go, FsmData.Fsm data)
        {
            var pm = go.AddComponent<PlayMakerFSM>();
            var fsm = new Fsm { Name = data.Name, StartState = data.StartState };

            fsm.Variables = BuildVariables(data);
            fsm.Events = BuildEvents(data.Events);

            var states = new FsmState[data.States.Length];
            for (int i = 0; i < states.Length; i++)
            {
                FsmData.State sd = data.States[i];
                var st = new FsmState(fsm) { Name = sd.Name };

                var trans = new FsmTransition[sd.Transitions.Length];
                for (int k = 0; k < trans.Length; k++)
                {
                    trans[k] = new FsmTransition
                    {
                        FsmEvent = FsmEvent.GetFsmEvent(sd.Transitions[k].EventName),
                        ToState = sd.Transitions[k].ToState,
                    };
                }
                st.Transitions = trans;

                PopulateActionData(st.ActionData, sd.Actions);
                states[i] = st;
            }
            fsm.States = states;

            // Setting the property is what installs and initialises the graph - its setter
            // calls fsm.Init(this).
            pm.Fsm = fsm;

            int actions = 0;
            foreach (FsmData.State s in data.States) actions += s.Actions.ActionNames.Length;
            Plugin.Log.LogInfo(
                $"Godhome: built FSM '{data.Name}' ({states.Length} states, {actions} actions).");
            return true;
        }

        // ------------------------------------------------------------------

        private static FsmEvent[] BuildEvents(FsmData.Event[] evs)
        {
            var list = new List<FsmEvent>();
            foreach (FsmData.Event e in evs)
            {
                if (string.IsNullOrEmpty(e.Name)) continue;
                list.Add(FsmEvent.GetFsmEvent(e.Name));
            }
            return list.ToArray();
        }

        private static FsmVariables BuildVariables(FsmData.Fsm d)
        {
            var v = new FsmVariables();
            v.FloatVariables = Map(d.Floats, x => new FsmFloat(x.Name) { Value = x.F });
            v.IntVariables = Map(d.Ints, x => new FsmInt(x.Name) { Value = x.I });
            v.BoolVariables = Map(d.Bools, x => new FsmBool(x.Name) { Value = x.B });
            v.StringVariables = Map(d.Strings, x => new FsmString(x.Name) { Value = x.S });
            v.Vector2Variables = Map(d.Vector2s, x => new FsmVector2(x.Name) { Value = new Vector2(x.V.x, x.V.y) });
            v.Vector3Variables = Map(d.Vector3s, x => new FsmVector3(x.Name) { Value = new Vector3(x.V.x, x.V.y, x.V.z) });
            v.ColorVariables = Map(d.Colors, x => new FsmColor(x.Name) { Value = new Color(x.V.x, x.V.y, x.V.z, x.V.w) });
            v.RectVariables = Map(d.Rects, x => new FsmRect(x.Name) { Value = new Rect(x.V.x, x.V.y, x.V.z, x.V.w) });
            v.QuaternionVariables = Map(d.Quaternions, x => new FsmQuaternion(x.Name) { Value = new Quaternion(x.V.x, x.V.y, x.V.z, x.V.w) });
            v.GameObjectVariables = Map(d.GameObjects, MakeGameObject);
            v.ObjectVariables = Map(d.Objects, MakeObject);
            return v;
        }

        private static TOut[] Map<TOut>(List<FsmData.Var> src, Func<FsmData.Var, TOut> fn)
        {
            var a = new TOut[src.Count];
            for (int i = 0; i < src.Count; i++) a[i] = fn(src[i]);
            return a;
        }

        // ------------------------------------------------------------------

        private static void Set(object target, string field, object value)
        {
            FieldInfo f = AccessTools.Field(ActionDataType, field);
            if (f == null)
            {
                Plugin.Log.LogWarning($"Godhome: ActionData has no field '{field}'.");
                return;
            }
            f.SetValue(target, value);
        }

        /// <summary>
        /// Fills a fresh ActionData so that LoadActions can reconstruct the actions.
        ///
        /// Lists that held Hollow Knight asset pointers are created at the right length
        /// but with null entries: the indices in paramDataPos still have to line up, or
        /// every later parameter in the state reads from the wrong slot.
        /// </summary>
        private static void PopulateActionData(HutongGames.PlayMaker.ActionData ad, FsmData.ActionData d)
        {
            Set(ad, "actionNames", new List<string>(d.ActionNames));
            Set(ad, "customNames", new List<string>(d.CustomNames));
            Set(ad, "actionEnabled", new List<bool>(d.ActionEnabled));
            Set(ad, "actionIsOpen", new List<bool>(d.ActionIsOpen));
            Set(ad, "actionStartIndex", new List<int>(d.ActionStartIndex));
            Set(ad, "actionHashCodes", new List<int>(d.ActionHashCodes));

            Set(ad, "unityObjectParams", NullList<UnityEngine.Object>(d.UnityObjectCount));

            Set(ad, "fsmGameObjectParams", Map(d.GameObjects, MakeGameObject).ToList());

            var owners = new List<FsmOwnerDefault>();
            for (int i = 0; i < d.OwnerDefaults.Count; i++)
            {
                owners.Add(new FsmOwnerDefault
                {
                    OwnerOption = (OwnerDefaultOption)d.OwnerOptions[i],
                    GameObject = MakeGameObject(d.OwnerDefaults[i]),
                });
            }
            Set(ad, "fsmOwnerDefaultParams", owners);

            Set(ad, "animationCurveParams", NullList<FsmAnimationCurve>(d.CurveCount));
            Set(ad, "functionCallParams", NullList<FunctionCall>(d.FunctionCallCount));
            Set(ad, "fsmTemplateControlParams", NullList<FsmTemplateControl>(d.TemplateControlCount));
            Set(ad, "fsmEventTargetParams", NullList<FsmEventTarget>(d.EventTargetCount));
            Set(ad, "fsmPropertyParams", NullList<FsmProperty>(d.PropertyCount));
            Set(ad, "layoutOptionParams", NullList<LayoutOption>(d.LayoutOptionCount));

            Set(ad, "fsmStringParams", Map(d.Strings, x => new FsmString(x.Name) { Value = x.S }).ToList());
            Set(ad, "fsmObjectParams", Map(d.Objects, MakeObject).ToList());
            Set(ad, "fsmVarParams", NullList<FsmVar>(d.VarCount));
            Set(ad, "fsmArrayParams", NullList<FsmArray>(d.ArrayCount));
            Set(ad, "fsmEnumParams", Map(d.Enums, x => new FsmEnum(x.Name)).ToList());
            Set(ad, "fsmFloatParams", Map(d.Floats, x => new FsmFloat(x.Name) { Value = x.F }).ToList());
            Set(ad, "fsmIntParams", Map(d.Ints, x => new FsmInt(x.Name) { Value = x.I }).ToList());
            Set(ad, "fsmBoolParams", Map(d.Bools, x => new FsmBool(x.Name) { Value = x.B }).ToList());
            Set(ad, "fsmVector2Params", Map(d.Vector2s, x => new FsmVector2(x.Name) { Value = new Vector2(x.V.x, x.V.y) }).ToList());
            Set(ad, "fsmVector3Params", Map(d.Vector3s, x => new FsmVector3(x.Name) { Value = new Vector3(x.V.x, x.V.y, x.V.z) }).ToList());
            Set(ad, "fsmColorParams", Map(d.Colors, x => new FsmColor(x.Name) { Value = new Color(x.V.x, x.V.y, x.V.z, x.V.w) }).ToList());
            Set(ad, "fsmRectParams", Map(d.Rects, x => new FsmRect(x.Name) { Value = new Rect(x.V.x, x.V.y, x.V.z, x.V.w) }).ToList());
            Set(ad, "fsmQuaternionParams", Map(d.Quaternions, x => new FsmQuaternion(x.Name) { Value = new Quaternion(x.V.x, x.V.y, x.V.z, x.V.w) }).ToList());

            Set(ad, "stringParams", new List<string>(d.StringParams));
            Set(ad, "byteData", new List<byte>(d.ByteData));
            Set(ad, "arrayParamSizes", new List<int>(d.ArrayParamSizes));
            Set(ad, "arrayParamTypes", new List<string>(d.ArrayParamTypes));
            Set(ad, "customTypeSizes", new List<int>(d.CustomTypeSizes));
            Set(ad, "customTypeNames", new List<string>(d.CustomTypeNames));

            var types = new List<ParamDataType>();
            foreach (int t in d.ParamDataType) types.Add((ParamDataType)t);
            Set(ad, "paramDataType", types);

            Set(ad, "paramName", new List<string>(d.ParamName));
            Set(ad, "paramDataPos", new List<int>(d.ParamDataPos));
            Set(ad, "paramByteDataSize", new List<int>(d.ParamByteDataSize));
        }

        private static List<T> NullList<T>(int count) where T : class
        {
            var l = new List<T>(count);
            for (int i = 0; i < count; i++) l.Add(null);
            return l;
        }
    }

    internal static class ArrayExt
    {
        public static List<T> ToList<T>(this T[] a) => new List<T>(a);
    }
}
