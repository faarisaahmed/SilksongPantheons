#!/usr/bin/env python3
"""
Decode a PlayMaker action's parameter values out of an ActionData block.

Reading action *names* only gets you so far. "SetIsKinematic2d" tells you the boss's
rigidbody changes; it does not tell you whether it becomes kinematic or stops being
kinematic, and that is the difference between a boss that lands and one that flies off
the top of the arena. Same for GGCheckIfBossScene, whose whole meaning is which event it
fires.

ActionData stores parameters flat: actionStartIndex[i] is the first parameter belonging
to action i, paramDataType[j] says what type parameter j is, and paramDataPos[j] is
either an index into the matching typed list or a byte offset into byteData. This mirrors
ActionData.LoadActionField, including the detail that from DataVersion 2 onwards FsmEvent
parameters live in stringParams rather than byteData.
"""
import struct

# HutongGames.PlayMaker.ParamDataType, in declaration order.
TYPES = [
    "Integer", "Boolean", "Float", "String", "Color", "ObjectReference", "LayerMask",
    "Enum", "Vector2", "Vector3", "Vector4", "Rect", "Array", "Character",
    "AnimationCurve", "FsmFloat", "FsmInt", "FsmBool", "FsmString", "FsmGameObject",
    "FsmOwnerDefault", "FunctionCall", "FsmAnimationCurve", "FsmEvent", "FsmObject",
    "FsmColor", "Unsupported", "GameObject", "FsmVector3", "LayoutOption", "FsmRect",
    "FsmEventTarget", "FsmMaterial", "FsmTexture", "Quaternion", "FsmQuaternion",
    "FsmProperty", "FsmVector2", "FsmTemplateControl", "FsmVar", "CustomClass",
    "FsmArray", "FsmEnum",
]

# Parameter type -> the ActionData list it indexes into.
LISTS = {
    "FsmFloat": "fsmFloatParams", "FsmInt": "fsmIntParams", "FsmBool": "fsmBoolParams",
    "FsmString": "fsmStringParams", "FsmGameObject": "fsmGameObjectParams",
    "FsmOwnerDefault": "fsmOwnerDefaultParams", "FunctionCall": "functionCallParams",
    "FsmAnimationCurve": "animationCurveParams", "FsmObject": "fsmObjectParams",
    "FsmColor": "fsmColorParams", "FsmVector3": "fsmVector3Params",
    "LayoutOption": "layoutOptionParams", "FsmRect": "fsmRectParams",
    "FsmEventTarget": "fsmEventTargetParams", "FsmQuaternion": "fsmQuaternionParams",
    "FsmProperty": "fsmPropertyParams", "FsmVector2": "fsmVector2Params",
    "FsmTemplateControl": "fsmTemplateControlParams", "FsmVar": "fsmVarParams",
    "FsmArray": "fsmArrayParams", "FsmEnum": "fsmEnumParams",
}

# Fixed-width values packed straight into byteData.
RAW = {
    "Integer": ("<i", 4), "Boolean": ("<?", 1), "Float": ("<f", 4),
    "LayerMask": ("<i", 4), "Enum": ("<i", 4), "Character": ("<h", 2),
    "Color": ("<4f", 16), "Vector2": ("<2f", 8), "Vector3": ("<3f", 12),
    "Vector4": ("<4f", 16), "Rect": ("<4f", 16), "Quaternion": ("<4f", 16),
}


def _short(v):
    """A parameter value trimmed to what is worth reading in a dump."""
    if isinstance(v, dict):
        # Fsm* wrappers: the interesting part is the variable name, or the constant.
        if v.get("name"):
            return f"${v['name']}"
        for k in ("value", "gameObject", "target", "ownerOption"):
            if k in v:
                return _short(v[k])
        keep = {k: v[k] for k in list(v)[:4] if not isinstance(v[k], (dict, list))}
        return keep or "{...}"
    if isinstance(v, (list, tuple)):
        return "(" + ", ".join(f"{x:g}" if isinstance(x, float) else str(x) for x in v) + ")"
    if isinstance(v, float):
        return f"{v:g}"
    return v


def decode(ad):
    """
    [(action_name, [(param_name, type_name, value), ...]), ...] for one ActionData.
    """
    names = ad["actionNames"]
    starts = ad["actionStartIndex"]
    types = ad["paramDataType"]
    pnames = ad["paramName"]
    pos = ad["paramDataPos"]
    sizes = ad["paramByteDataSize"]
    blob = ad["byteData"] or b""
    strings = ad["stringParams"]

    out = []
    for i, aname in enumerate(names):
        lo = starts[i] if i < len(starts) else 0
        hi = starts[i + 1] if i + 1 < len(starts) else len(types)
        params = []
        for j in range(lo, min(hi, len(types))):
            t = TYPES[types[j]] if 0 <= types[j] < len(TYPES) else f"?{types[j]}"
            p = pos[j] if j < len(pos) else -1
            val = None
            try:
                if t == "FsmEvent":
                    # DataVersion 2+ keeps the event name in stringParams. Hollow
                    # Knight's FSMs predate that, so the name is raw UTF-8 sitting in
                    # byteData - which is why reading stringParams alone showed every
                    # GGCheckIfBossScene as having no events at all.
                    if 0 <= p < len(strings):
                        val = strings[p]
                    else:
                        n = sizes[j] if j < len(sizes) else 0
                        val = blob[p:p + n].decode("utf8", "replace") or None
                elif t == "String":
                    n = sizes[j] if j < len(sizes) else 0
                    val = blob[p:p + n].decode("utf8", "replace")
                elif t in ("ObjectReference", "GameObject", "FsmMaterial", "FsmTexture"):
                    up = ad["unityObjectParams"]
                    val = up[p] if 0 <= p < len(up) else None
                elif t in RAW:
                    fmt, n = RAW[t]
                    if p >= 0 and p + n <= len(blob):
                        v = struct.unpack_from(fmt, blob, p)
                        val = v[0] if len(v) == 1 else v
                elif t in LISTS:
                    lst = ad[LISTS[t]]
                    val = lst[p] if 0 <= p < len(lst) else None
                elif t == "Array":
                    val = f"{ad['arrayParamTypes'][p]}[{ad['arrayParamSizes'][p]}]"
                elif t == "CustomClass":
                    val = ad["customTypeNames"][p]
            except Exception:
                val = "<undecodable>"
            params.append((pnames[j] if j < len(pnames) else "?", t, val))
        out.append((aname, params))
    return out


def describe(ad, indent="      "):
    """One line per action, with its parameters, for a dump."""
    lines = []
    for aname, params in decode(ad):
        short = aname.split(".")[-1]
        bits = []
        for pn, t, v in params:
            s = _short(v)
            if s in (None, "", {}):
                continue
            bits.append(f"{pn}={s}")
        lines.append(f"{indent}. {short}" + (f"  ({', '.join(bits)})" if bits else ""))
    return lines
