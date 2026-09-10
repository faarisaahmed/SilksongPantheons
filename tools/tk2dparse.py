"""
Parsing Hollow Knight's tk2d sprite collections and animations.

A boss is invisible without these, and every Tk2dPlayAnimation action in its FSM needs a
real tk2dSpriteAnimator with a real library behind it. Both games ship tk2d, and
tk2dSpriteDefinition, tk2dSpriteCollectionData, tk2dSpriteAnimation, tk2dSpriteAnimationClip
and tk2dSpriteAnimationFrame are all *byte-identical* between Hollow Knight's copy and
Silksong's TeamCherry.TK2D - so a collection lifted from one can be rebuilt in the other.

Same validation rule as the FSM parser: parse and land exactly on the end of the buffer.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fsmparse import FsmReader


class Tk2dReader(FsmReader):
    """FsmReader already has aligned bools, strings, arrays and PPtrs."""

    def vector3_array(self):
        return self.array(self.vector3)

    def vector2_array(self):
        return self.array(self.vector2)

    def vector4_array(self):
        return self.array(self.vector4)

    def attach_point(self):
        return {"name": self.string(), "position": self.vector3(), "angle": self.f32()}

    def collider_definition(self):
        return {
            "type": self.i32(),
            "origin": self.vector3(),
            "angle": self.f32(),
            "name": self.string(),
            "vectors": self.vector3_array(),
            "floats": self.float_array(),
        }

    def collider2d_data(self):
        return {"points": self.vector2_array()}

    def sprite_definition(self):
        return {
            "name": self.string(),
            "boundsData": self.vector3_array(),
            "untrimmedBoundsData": self.vector3_array(),
            "texelSize": self.vector2(),
            "positions": self.vector3_array(),
            "normals": self.vector3_array(),
            "tangents": self.vector4_array(),
            "uvs": self.vector2_array(),
            "normalizedUvs": self.vector2_array(),
            "indices": self.int_array(),
            "material": self.pptr(),
            "materialId": self.i32(),
            "sourceTextureGUID": self.string(),
            "extractRegion": self.boolean(),
            "regionX": self.i32(),
            "regionY": self.i32(),
            "regionW": self.i32(),
            "regionH": self.i32(),
            "flipped": self.i32(),
            "complexGeometry": self.boolean(),
            "physicsEngine": self.i32(),
            "colliderType": self.i32(),
            "customColliders": self.array(self.collider_definition),
            "colliderVertices": self.vector3_array(),
            "colliderIndicesFwd": self.int_array(),
            "colliderIndicesBack": self.int_array(),
            "colliderConvex": self.boolean(),
            "colliderSmoothSphereCollisions": self.boolean(),
            "polygonCollider2D": self.array(self.collider2d_data),
            "edgeCollider2D": self.array(self.collider2d_data),
            "attachPoints": self.array(self.attach_point),
        }

    def sprite_collection(self):
        return {
            "version": self.i32(),
            "materialIdsValid": self.boolean(),
            "needMaterialInstance": self.boolean(),
            "spriteDefinitions": self.array(self.sprite_definition),
            "premultipliedAlpha": self.boolean(),
            "material": self.pptr(),
            "materials": self.pptr_array(),
            "textures": self.pptr_array(),
            "pngTextures": self.pptr_array(),
            "materialPngTextureId": self.int_array(),
            "textureFilterMode": self.i32(),
            "textureMipMaps": self.boolean(),
            "allowMultipleAtlases": self.boolean(),
            "spriteCollectionGUID": self.string(),
            "spriteCollectionName": self.string(),
            "assetName": self.string(),
            "loadable": self.boolean(),
            "invOrthoSize": self.f32(),
            "halfTargetHeight": self.f32(),
            "buildKey": self.i32(),
            "dataGuid": self.string(),
            "managedSpriteCollection": self.boolean(),
            "hasPlatformData": self.boolean(),
            "spriteCollectionPlatforms": self.string_array(),
            "spriteCollectionPlatformGUIDs": self.string_array(),
        }

    def animation_frame(self):
        return {
            "spriteCollection": self.pptr(),
            "spriteId": self.i32(),
            "triggerEvent": self.boolean(),
            "eventInfo": self.string(),
            "eventInt": self.i32(),
            "eventFloat": self.f32(),
        }

    def animation_clip(self):
        return {
            "name": self.string(),
            "frames": self.array(self.animation_frame),
            "fps": self.f32(),
            "loopStart": self.i32(),
            "wrapMode": self.i32(),
        }

    def sprite_animation(self):
        return {"clips": self.array(self.animation_clip)}
