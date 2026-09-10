"""
Parsing Hollow Knight's PlayMaker FSMs out of raw MonoBehaviour bytes.

Why this is worth doing: Hollow Knight ships PlayMaker 1.9.0 and Silksong 1.9.9, and
every [SerializeField] in ActionData - the structure that actually holds a state's
actions - is identical between them. So an FSM parsed out of Hollow Knight can be handed
back to Silksong's own PlayMaker, and *PlayMaker* does the work of turning the byte blob
into live action instances via ActionData.LoadActions. We never have to understand what
any individual action means.

Layouts here come from decompiling Hollow Knight's PlayMaker.dll, and are checked the
only way that really proves them: parse the whole component and assert the cursor lands
exactly on the end of the buffer. A wrong field order fails that immediately.

Unity serialisation rules that matter:
  * bool/byte fields align to 4 bytes *after each one*
  * string  = int32 length + utf8 + align 4
  * T[] and List<T> = int32 count + elements
  * base class fields come before derived class fields
"""

import struct

from monoread import MonoReader, HEADER


class FsmReader(MonoReader):
    """MonoReader plus the composite types PlayMaker serialises."""

    def boolean(self):
        v = self.u8() != 0
        self.align(4)
        return v

    def raw_byte(self):
        return self.u8()

    def vector2(self):
        return (self.f32(), self.f32())

    def vector3(self):
        return (self.f32(), self.f32(), self.f32())

    def vector4(self):
        return (self.f32(), self.f32(), self.f32(), self.f32())

    def rect(self):
        return (self.f32(), self.f32(), self.f32(), self.f32())

    def array(self, fn):
        n = self.i32()
        if n < 0 or n > 5_000_000:
            raise EOFError(f"implausible array length {n} at {self.i}")
        return [fn() for _ in range(n)]

    def bool_array(self):
        n = self.i32()
        out = [self._take(1)[0] != 0 for _ in range(n)]
        self.align(4)
        return out

    def byte_array(self):
        n = self.i32()
        out = self._take(n)
        self.align(4)
        return out

    def int_array(self):
        return self.array(self.i32)

    def float_array(self):
        return self.array(self.f32)

    def string_array(self):
        return self.array(self.string)

    def pptr_array(self):
        return self.array(self.pptr)

    # -- PlayMaker variables -------------------------------------------

    def named_variable(self):
        """NamedVariable base: every Fsm* type starts with these."""
        return {
            "useVariable": self.boolean(),
            "name": self.string(),
            "tooltip": self.string(),
            "showInInspector": self.boolean(),
            "networkSync": self.boolean(),
        }

    def fsm_float(self):
        v = self.named_variable(); v["value"] = self.f32(); return v

    def fsm_int(self):
        v = self.named_variable(); v["value"] = self.i32(); return v

    def fsm_bool(self):
        v = self.named_variable(); v["value"] = self.boolean(); return v

    def fsm_string(self):
        v = self.named_variable(); v["value"] = self.string(); return v

    def fsm_vector2(self):
        v = self.named_variable(); v["value"] = self.vector2(); return v

    def fsm_vector3(self):
        v = self.named_variable(); v["value"] = self.vector3(); return v

    def fsm_color(self):
        v = self.named_variable(); v["value"] = self.vector4(); return v

    def fsm_rect(self):
        v = self.named_variable(); v["value"] = self.rect(); return v

    def fsm_quaternion(self):
        v = self.named_variable(); v["value"] = self.vector4(); return v

    def fsm_gameobject(self):
        v = self.named_variable(); v["value"] = self.pptr(); return v

    def fsm_object(self):
        v = self.named_variable()
        v["typeName"] = self.string()
        v["value"] = self.pptr()
        return v

    # FsmMaterial and FsmTexture derive from FsmObject, not NamedVariable, so they
    # carry its typeName string as well - 36 bytes each rather than 32.
    def fsm_material(self):
        return self.fsm_object()

    def fsm_texture(self):
        return self.fsm_object()

    def fsm_enum(self):
        v = self.named_variable()
        v["enumName"] = self.string()
        v["intValue"] = self.i32()
        return v

    def fsm_array(self):
        v = self.named_variable()
        v["type"] = self.i32()
        v["objectTypeName"] = self.string()
        v["floatValues"] = self.float_array()
        v["intValues"] = self.int_array()
        v["boolValues"] = self.bool_array()
        v["stringValues"] = self.string_array()
        v["vector4Values"] = self.array(self.vector4)
        v["objectReferences"] = self.pptr_array()
        return v

    def fsm_variables(self):
        return {
            "float": self.array(self.fsm_float),
            "int": self.array(self.fsm_int),
            "bool": self.array(self.fsm_bool),
            "string": self.array(self.fsm_string),
            "vector2": self.array(self.fsm_vector2),
            "vector3": self.array(self.fsm_vector3),
            "color": self.array(self.fsm_color),
            "rect": self.array(self.fsm_rect),
            "quaternion": self.array(self.fsm_quaternion),
            "gameObject": self.array(self.fsm_gameobject),
            "object": self.array(self.fsm_object),
            "material": self.array(self.fsm_material),
            "texture": self.array(self.fsm_texture),
            "array": self.array(self.fsm_array),
            "enum": self.array(self.fsm_enum),
            "categories": self.string_array(),
            "variableCategoryIDs": self.int_array(),
        }

    # -- graph ---------------------------------------------------------

    def fsm_event(self):
        return {
            "name": self.string(),
            "isSystemEvent": self.boolean(),
            "isGlobal": self.boolean(),
        }

    def fsm_transition(self):
        return {
            "event": self.fsm_event(),
            "toState": self.string(),
            "linkStyle": self.i32(),
            "linkConstraint": self.i32(),
            "colorIndex": (self.raw_byte(), self.align(4))[0],
        }

    def action_data(self):
        """
        The payload that matters. Field order is identical in Silksong's PlayMaker,
        so these lists can be handed straight back to ActionData.LoadActions.
        """
        d = {}
        d["actionNames"] = self.string_array()
        d["customNames"] = self.string_array()
        d["actionEnabled"] = self.bool_array()
        d["actionIsOpen"] = self.bool_array()
        d["actionStartIndex"] = self.int_array()
        d["actionHashCodes"] = self.int_array()
        d["unityObjectParams"] = self.pptr_array()
        d["fsmGameObjectParams"] = self.array(self.fsm_gameobject)
        d["fsmOwnerDefaultParams"] = self.array(self.fsm_owner_default)
        d["animationCurveParams"] = self.array(self.fsm_animation_curve)
        d["functionCallParams"] = self.array(self.function_call)
        d["fsmTemplateControlParams"] = self.array(self.fsm_template_control)
        d["fsmEventTargetParams"] = self.array(self.fsm_event_target)
        d["fsmPropertyParams"] = self.array(self.fsm_property)
        d["layoutOptionParams"] = self.array(self.layout_option)
        d["fsmStringParams"] = self.array(self.fsm_string)
        d["fsmObjectParams"] = self.array(self.fsm_object)
        d["fsmVarParams"] = self.array(self.fsm_var)
        d["fsmArrayParams"] = self.array(self.fsm_array)
        d["fsmEnumParams"] = self.array(self.fsm_enum)
        d["fsmFloatParams"] = self.array(self.fsm_float)
        d["fsmIntParams"] = self.array(self.fsm_int)
        d["fsmBoolParams"] = self.array(self.fsm_bool)
        d["fsmVector2Params"] = self.array(self.fsm_vector2)
        d["fsmVector3Params"] = self.array(self.fsm_vector3)
        d["fsmColorParams"] = self.array(self.fsm_color)
        d["fsmRectParams"] = self.array(self.fsm_rect)
        d["fsmQuaternionParams"] = self.array(self.fsm_quaternion)
        d["stringParams"] = self.string_array()
        d["byteData"] = self.byte_array()
        # byteDataAsArray is [NonSerialized] - a runtime cache, not part of the stream.
        d["arrayParamSizes"] = self.int_array()
        d["arrayParamTypes"] = self.string_array()
        d["customTypeSizes"] = self.int_array()
        d["customTypeNames"] = self.string_array()
        d["paramDataType"] = self.int_array()
        d["paramName"] = self.string_array()
        d["paramDataPos"] = self.int_array()
        d["paramByteDataSize"] = self.int_array()
        # nextParamIndex is private with no [SerializeField]; ActionData ends here.
        return d

    def fsm_state(self):
        return {
            "name": self.string(),
            "description": self.string(),
            "colorIndex": (self.raw_byte(), self.align(4))[0],
            "position": self.rect(),
            "isBreakpoint": self.boolean(),
            "isSequence": self.boolean(),
            "hideUnused": self.boolean(),
            "transitions": self.array(self.fsm_transition),
            "actionData": self.action_data(),
        }

    def fsm(self):
        d = {}
        d["dataVersion"] = self.i32()
        d["usedInTemplate"] = self.pptr()
        d["name"] = self.string()
        d["startState"] = self.string()
        d["states"] = self.array(self.fsm_state)
        d["events"] = self.array(self.fsm_event)
        d["globalTransitions"] = self.array(self.fsm_transition)
        d["variables"] = self.fsm_variables()
        d["description"] = self.string()
        d["docUrl"] = self.string()
        d["showStateLabel"] = self.boolean()
        d["maxLoopCount"] = self.i32()
        d["watermark"] = self.string()
        d["password"] = self.string()
        d["locked"] = self.boolean()
        d["manualUpdate"] = self.boolean()
        d["keepDelayedEventsOnStateExit"] = self.boolean()
        d["preprocessed"] = self.boolean()
        d["ExposedEvents"] = self.array(self.fsm_event)
        d["RestartOnEnable"] = self.boolean()
        d["EnableDebugFlow"] = self.boolean()
        d["EnableBreakpoints"] = self.boolean()
        d["editorFlags"] = self.i32()
        d["activeStateName"] = self.string()
        d["mouseEvents"] = self.boolean()
        d["handleLevelLoaded"] = self.boolean()
        d["handleTriggerEnter2D"] = self.boolean()
        d["handleTriggerExit2D"] = self.boolean()
        d["handleTriggerStay2D"] = self.boolean()
        d["handleCollisionEnter2D"] = self.boolean()
        d["handleCollisionExit2D"] = self.boolean()
        d["handleCollisionStay2D"] = self.boolean()
        d["handleTriggerEnter"] = self.boolean()
        d["handleTriggerExit"] = self.boolean()
        d["handleTriggerStay"] = self.boolean()
        d["handleCollisionEnter"] = self.boolean()
        d["handleCollisionExit"] = self.boolean()
        d["handleCollisionStay"] = self.boolean()
        d["handleParticleCollision"] = self.boolean()
        d["handleControllerColliderHit"] = self.boolean()
        d["handleJointBreak"] = self.boolean()
        d["handleJointBreak2D"] = self.boolean()
        d["handleOnGUI"] = self.boolean()
        d["handleFixedUpdate"] = self.boolean()
        d["handleLateUpdate"] = self.boolean()
        d["handleApplicationEvents"] = self.boolean()
        d["handleUiEvents"] = self.i32()
        d["handleLegacyNetworking"] = self.boolean()
        d["handleAnimatorMove"] = self.boolean()
        d["handleAnimatorIK"] = self.boolean()
        return d

    # -- composite action params ---------------------------------------

    def fsm_owner_default(self):
        return {"ownerOption": self.i32(), "gameObject": self.fsm_gameobject()}

    def fsm_animation_curve(self):
        """FsmAnimationCurve wraps a single Unity AnimationCurve."""
        n = self.i32()
        keys = [(self.f32(), self.f32(), self.f32(), self.f32(),
                 self.i32(), self.f32(), self.f32()) for _ in range(n)]
        self.align(4)
        return {"keys": keys, "preInfinity": self.i32(), "postInfinity": self.i32(),
                "rotationOrder": self.i32()}

    def function_call(self):
        return {
            "FunctionName": self.string(),
            "parameterType": self.string(),
            "BoolParameter": self.fsm_bool(),
            "FloatParameter": self.fsm_float(),
            "IntParameter": self.fsm_int(),
            "GameObjectParameter": self.fsm_gameobject(),
            "ObjectParameter": self.fsm_object(),
            "StringParameter": self.fsm_string(),
            "Vector2Parameter": self.fsm_vector2(),
            "Vector3Parameter": self.fsm_vector3(),
            "RectParamater": self.fsm_rect(),
            "QuaternionParameter": self.fsm_quaternion(),
            "MaterialParameter": self.fsm_material(),
            "TextureParameter": self.fsm_texture(),
            "ColorParameter": self.fsm_color(),
            "EnumParameter": self.fsm_enum(),
            "ArrayParameter": self.fsm_array(),
        }

    def fsm_var_override(self):
        # `variable` is declared as the base NamedVariable, and Unity serialises a
        # non-[SerializeReference] polymorphic field as its declared type only.
        return {
            "variable": self.named_variable(),
            "fsmVar": self.fsm_var(),
            "isEdited": self.boolean(),
        }

    def fsm_template_control(self):
        return {
            "fsmTemplate": self.pptr(),
            "fsmVarOverrides": self.array(self.fsm_var_override),
        }

    def fsm_event_target(self):
        return {
            "target": self.i32(),
            "excludeSelf": self.fsm_bool(),
            "gameObject": self.fsm_owner_default(),
            "fsmName": self.fsm_string(),
            "sendToChildren": self.fsm_bool(),
            "fsmComponent": self.pptr(),
        }

    def fsm_var(self):
        """
        Note there is no per-type value here beyond a single Vector4 - FsmVar stores
        vector2/3, rect, quaternion and colour all in vector4Value.
        """
        return {
            "variableName": self.string(),
            "objectType": self.string(),
            "useVariable": self.boolean(),
            "type": self.i32(),
            "floatValue": self.f32(),
            "intValue": self.i32(),
            "boolValue": self.boolean(),
            "stringValue": self.string(),
            "vector4Value": self.vector4(),
            "objectReference": self.pptr(),
            "arrayValue": self.fsm_array(),
        }

    def fsm_property(self):
        return {
            "TargetObject": self.fsm_object(),
            "TargetTypeName": self.string(),
            "PropertyName": self.string(),
            "BoolParameter": self.fsm_bool(),
            "FloatParameter": self.fsm_float(),
            "IntParameter": self.fsm_int(),
            "GameObjectParameter": self.fsm_gameobject(),
            "StringParameter": self.fsm_string(),
            "Vector2Parameter": self.fsm_vector2(),
            "Vector3Parameter": self.fsm_vector3(),
            "RectParamater": self.fsm_rect(),
            "QuaternionParameter": self.fsm_quaternion(),
            "ObjectParameter": self.fsm_object(),
            "MaterialParameter": self.fsm_material(),
            "TextureParameter": self.fsm_texture(),
            "ColorParameter": self.fsm_color(),
            "EnumParameter": self.fsm_enum(),
            "ArrayParameter": self.fsm_array(),
            "setProperty": self.boolean(),
        }

    def layout_option(self):
        return {"option": self.i32(), "floatParam": self.fsm_float(),
                "boolParam": self.fsm_bool()}
