# MIT License

# Copyright (c) 2023 Thomas van den Berg

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

bl_info = {
    "name": "Pixel Unwrapper",
    "author": "Thomas 'noio' van den Berg",
    "description": "",
    "blender": (2, 80, 0),
    "version": (0, 0, 4),
    "location": "",
    "warning": "",
    "category": "Generic",
}

import bpy
from . import auto_load

auto_load.init()


def register():
    auto_load.register()

    bpy.types.Scene.pixunwrap_texel_density = bpy.props.FloatProperty(
        name="Pixels Per Unit",
        default=16,
        description="",
    )

    bpy.types.Scene.pixunwrap_texture_fill_color_tl = bpy.props.FloatVectorProperty(
        name="Texture Fill A",
        default=[0.92, 0.69, 0.69],
        description="Color used to fill top left quadrant of empty texture",
        subtype="COLOR",
    )
    bpy.types.Scene.pixunwrap_texture_fill_color_bl = bpy.props.FloatVectorProperty(
        name="Texture Fill B",
        default=[0.72, 0.72, 0.84],
        description="Color used to fill bottom left quadrant of empty texture",
        subtype="COLOR",
    )

    bpy.types.Scene.pixunwrap_texture_fill_color_tr = bpy.props.FloatVectorProperty(
        name="Texture Fill C",
        default=[0.64, 0.91, 0.64],
        description="Color used to fill top right quadrant of empty texture",
        subtype="COLOR",
    )
    # YELLOW
    bpy.types.Scene.pixunwrap_texture_fill_color_br = bpy.props.FloatVectorProperty(
        name="Texture Fill D",
        default=[1, 0.79, 0.48],
        description="Color used to fill bottom right quadrant of empty texture",
        subtype="COLOR",
    )

    uv_behaviors = (
        ("DESTRUCTIVE", "Destructive", ""),
        ("PRESERVE", "Preserve Texture", ""),
    )

    bpy.types.Scene.pixunwrap_uv_behavior = bpy.props.EnumProperty(
        name="UV Change Behavior",
        default=0,
        description="When using UV operators, should the image be modified to preserve texturing",
        items=uv_behaviors,
    )

    bpy.types.Scene.pixunwrap_modify_texture = bpy.props.BoolProperty(
        name="Modify Texture",
        default=False,
        description="Should the texture be modified to keep painted pixels in place on the model, or can UV's be moved freely.",
    )

    bpy.types.Scene.pixunwrap_fold_sections = bpy.props.IntProperty(
        name="Fold Sections",
        default=2,
        description="How many sections to fold the selected UV grid into.",
    )

    bpy.types.Scene.pixunwrap_fold_alternate = bpy.props.BoolProperty(
        name="Fold Alternate",
        default=False,
        description="Alternate directions of folded sections in a zig-zag way. Turn off to cut and stack sections",
    )


def unregister():
    auto_load.unregister()
