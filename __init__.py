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
    "name": "PixPaint",
    "author": "Thomas 'noio' van den Berg",
    "description": "",
    "blender": (2, 80, 0),
    "version": (0, 0, 1),
    "location": "",
    "warning": "",
    "category": "Generic",
}

import bpy
from . import auto_load

auto_load.init()


def register():
    auto_load.register()

    bpy.types.Scene.pixpaint_texture_size = bpy.props.IntProperty(
        name="Texture Size",
        default=64,
        description="",
    )

    bpy.types.Scene.pixpaint_texel_density = bpy.props.FloatProperty(
        name="Pixels Per Unit",
        default=16,
        description="",
    )

    bpy.types.Scene.pixpaint_modify_texture = bpy.props.BoolProperty(
        name="Modify Texture",
        default=False,
        description="Should the texture be modified to keep painted pixels in place on the model, or can UV's be moved freely.",
    )

    bpy.types.Scene.pixpaint_fold_sections = bpy.props.IntProperty(
        name="Fold Sections",
        default=2,
        description="How many sections to fold the selected UV grid into.",
    )

    bpy.types.Scene.pixpaint_fold_alternate = bpy.props.BoolProperty(
        name="Fold Alternate",
        default=True,
        description="Alternate directions of folded sections: like folding a letter versus cutting and stacking it",
    )


    


def unregister():
    auto_load.unregister()
