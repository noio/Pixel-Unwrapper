# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTIBILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

bl_info = {
    "name": "PixPaint",
    "author": "Thomas van den Berg",
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
