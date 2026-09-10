"""
Serialising a parsed Hollow Knight FSM into the mod's own format.

The target on the other side is Silksong's `ActionData`, whose every [SerializeField] is
identical to Hollow Knight's. So the job here is to carry each state's ActionData lists
across faithfully; the C# side pushes them back in and calls `ActionData.LoadActions`,
which builds the real action instances. We never interpret an action.

Object references (PPtrs) cannot cross - they point into Hollow Knight's asset files - so
they are written as nulls. Actions that spawn prefabs or play clips will no-op; actions
that move, animate, time and branch will not.
"""

from ggformat import Writer

FSM_MAGIC = b"GGFS"
FSM_VERSION = 2


def _named(w, v):
    w.boolean(v["useVariable"])
    w.string(v["name"] or "")
    w.string(v["tooltip"] or "")
    w.boolean(v["showInInspector"])
    w.boolean(v["networkSync"])


def _simple_list(w, items, writer):
    w.i32(len(items))
    for it in items:
        writer(w, it)


def _w_float(w, v):   _named(w, v); w.f32(v["value"])
def _w_int(w, v):     _named(w, v); w.i32(v["value"])
def _w_bool(w, v):    _named(w, v); w.boolean(v["value"])
def _w_string(w, v):  _named(w, v); w.string(v["value"] or "")
def _w_vec2(w, v):    _named(w, v); w.vec2(*v["value"])
def _w_vec3(w, v):    _named(w, v); w.vec3(*v["value"])
def _w_vec4(w, v):    _named(w, v); w.vec4(*v["value"])
def _w_enum(w, v):    _named(w, v); w.string(v["enumName"] or ""); w.i32(v["intValue"])


# Set by bossbake: given an FsmObject's PPtr, return the resource name of a baked asset
# for it, or "" - this is how a boss keeps its own sound effects. AudioClips are the one
# referenced asset type we can carry across whole.
ASSET_RESOLVER = None


def _w_object(w, v):
    # The referenced asset lives in Hollow Knight, so the pointer itself can't cross.
    # If we baked the asset, its resource name goes here and the C# side re-links it.
    _named(w, v)
    w.string(v.get("typeName") or "")
    res = ""
    if ASSET_RESOLVER is not None:
        try:
            res = ASSET_RESOLVER(v.get("value")) or ""
        except Exception:
            res = ""
    w.string(res)


# Set by bossbake: given an FsmGameObject's PPtr, return the name of a baked prefab for
# it, or "". This is what lets Gorb throw needles - his FSM spawns a prefab, and without
# it the parameter arrives null and SpawnObjectFromGlobalPool quietly does nothing.
GAMEOBJECT_RESOLVER = None


def _w_gameobject(w, v):
    _named(w, v)
    res = ""
    if GAMEOBJECT_RESOLVER is not None:
        try:
            res = GAMEOBJECT_RESOLVER(v.get("value")) or ""
        except Exception:
            res = ""
    w.string(res)


def _w_owner_default(w, v):
    w.i32(v["ownerOption"])
    _w_gameobject(w, v["gameObject"])


def _w_array(w, v):
    _named(w, v)
    w.i32(v["type"])
    w.string(v["objectTypeName"] or "")
    w.i32(len(v["floatValues"]));  [w.f32(x) for x in v["floatValues"]]
    w.i32(len(v["intValues"]));    [w.i32(x) for x in v["intValues"]]
    w.i32(len(v["boolValues"]));   [w.boolean(x) for x in v["boolValues"]]
    w.i32(len(v["stringValues"])); [w.string(x or "") for x in v["stringValues"]]
    w.i32(len(v["vector4Values"]))
    for x in v["vector4Values"]:
        w.vec4(*x)


def _w_var(w, v):
    w.string(v["variableName"] or "")
    w.string(v["objectType"] or "")
    w.boolean(v["useVariable"])
    w.i32(v["type"])
    w.f32(v["floatValue"]); w.i32(v["intValue"]); w.boolean(v["boolValue"])
    w.string(v["stringValue"] or "")
    w.vec4(*v["vector4Value"])
    _w_array(w, v["arrayValue"])


def _w_event_target(w, v):
    w.i32(v["target"])
    _w_bool(w, v["excludeSelf"])
    _w_owner_default(w, v["gameObject"])
    _w_string(w, v["fsmName"])
    _w_bool(w, v["sendToChildren"])


def _w_layout_option(w, v):
    w.i32(v["option"]); _w_float(w, v["floatParam"]); _w_bool(w, v["boolParam"])


def _w_property(w, v):
    _w_object(w, v["TargetObject"])
    w.string(v["TargetTypeName"] or "")
    w.string(v["PropertyName"] or "")
    _w_bool(w, v["BoolParameter"]);   _w_float(w, v["FloatParameter"])
    _w_int(w, v["IntParameter"]);     _w_gameobject(w, v["GameObjectParameter"])
    _w_string(w, v["StringParameter"]); _w_vec2(w, v["Vector2Parameter"])
    _w_vec3(w, v["Vector3Parameter"]); _w_vec4(w, v["RectParamater"])
    _w_vec4(w, v["QuaternionParameter"]); _w_object(w, v["ObjectParameter"])
    _w_object(w, v["MaterialParameter"]); _w_object(w, v["TextureParameter"])
    _w_vec4(w, v["ColorParameter"]);  _w_enum(w, v["EnumParameter"])
    _w_array(w, v["ArrayParameter"]); w.boolean(v["setProperty"])


def _w_function_call(w, v):
    w.string(v["FunctionName"] or "")
    w.string(v["parameterType"] or "")
    _w_bool(w, v["BoolParameter"]);   _w_float(w, v["FloatParameter"])
    _w_int(w, v["IntParameter"]);     _w_gameobject(w, v["GameObjectParameter"])
    _w_object(w, v["ObjectParameter"]); _w_string(w, v["StringParameter"])
    _w_vec2(w, v["Vector2Parameter"]); _w_vec3(w, v["Vector3Parameter"])
    _w_vec4(w, v["RectParamater"]);   _w_vec4(w, v["QuaternionParameter"])
    _w_object(w, v["MaterialParameter"]); _w_object(w, v["TextureParameter"])
    _w_vec4(w, v["ColorParameter"]);  _w_enum(w, v["EnumParameter"])
    _w_array(w, v["ArrayParameter"])


def _w_curve(w, v):
    keys = v["keys"]
    w.i32(len(keys))
    for k in keys:
        w.f32(k[0]); w.f32(k[1]); w.f32(k[2]); w.f32(k[3])


def write_action_data(w, ad):
    def strs(key):
        items = ad[key]
        w.i32(len(items))
        for x in items:
            w.string(x or "")

    def ints(key):
        items = ad[key]
        w.i32(len(items))
        for x in items:
            w.i32(int(x))

    def bools(key):
        items = ad[key]
        w.i32(len(items))
        for x in items:
            w.boolean(bool(x))

    strs("actionNames"); strs("customNames")
    bools("actionEnabled"); bools("actionIsOpen")
    ints("actionStartIndex"); ints("actionHashCodes")

    # unityObjectParams are Hollow Knight asset pointers; only the count survives, so the
    # C# side can keep the list the right length for index lookups.
    w.i32(len(ad["unityObjectParams"]))

    _simple_list(w, ad["fsmGameObjectParams"], _w_gameobject)
    _simple_list(w, ad["fsmOwnerDefaultParams"], _w_owner_default)
    _simple_list(w, ad["animationCurveParams"], _w_curve)
    _simple_list(w, ad["functionCallParams"], _w_function_call)
    w.i32(len(ad["fsmTemplateControlParams"]))          # templates don't cross
    _simple_list(w, ad["fsmEventTargetParams"], _w_event_target)
    _simple_list(w, ad["fsmPropertyParams"], _w_property)
    _simple_list(w, ad["layoutOptionParams"], _w_layout_option)
    _simple_list(w, ad["fsmStringParams"], _w_string)
    _simple_list(w, ad["fsmObjectParams"], _w_object)
    _simple_list(w, ad["fsmVarParams"], _w_var)
    _simple_list(w, ad["fsmArrayParams"], _w_array)
    _simple_list(w, ad["fsmEnumParams"], _w_enum)
    _simple_list(w, ad["fsmFloatParams"], _w_float)
    _simple_list(w, ad["fsmIntParams"], _w_int)
    _simple_list(w, ad["fsmBoolParams"], _w_bool)
    _simple_list(w, ad["fsmVector2Params"], _w_vec2)
    _simple_list(w, ad["fsmVector3Params"], _w_vec3)
    _simple_list(w, ad["fsmColorParams"], _w_vec4)
    _simple_list(w, ad["fsmRectParams"], _w_vec4)
    _simple_list(w, ad["fsmQuaternionParams"], _w_vec4)

    strs("stringParams")

    data = ad["byteData"]
    w.i32(len(data))
    w.buf += bytes(data)

    ints("arrayParamSizes"); strs("arrayParamTypes")
    ints("customTypeSizes"); strs("customTypeNames")
    ints("paramDataType"); strs("paramName")
    ints("paramDataPos"); ints("paramByteDataSize")


def write_variables(w, v):
    _simple_list(w, v["float"], _w_float)
    _simple_list(w, v["int"], _w_int)
    _simple_list(w, v["bool"], _w_bool)
    _simple_list(w, v["string"], _w_string)
    _simple_list(w, v["vector2"], _w_vec2)
    _simple_list(w, v["vector3"], _w_vec3)
    _simple_list(w, v["color"], _w_vec4)
    _simple_list(w, v["rect"], _w_vec4)
    _simple_list(w, v["quaternion"], _w_vec4)
    _simple_list(w, v["gameObject"], _w_gameobject)
    _simple_list(w, v["object"], _w_object)
    _simple_list(w, v["array"], _w_array)
    _simple_list(w, v["enum"], _w_enum)


def write_fsm(w, fsm):
    w.string(fsm["name"] or "")
    w.string(fsm["startState"] or "")

    write_variables(w, fsm["variables"])

    w.i32(len(fsm["events"]))
    for e in fsm["events"]:
        w.string(e["name"] or "")
        w.boolean(e["isSystemEvent"])
        w.boolean(e["isGlobal"])

    w.i32(len(fsm["states"]))
    for st in fsm["states"]:
        w.string(st["name"] or "")
        w.i32(len(st["transitions"]))
        for t in st["transitions"]:
            w.string(t["event"]["name"] or "")
            w.string(t["toState"] or "")
        write_action_data(w, st["actionData"])
