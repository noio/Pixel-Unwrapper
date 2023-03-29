import os
import bpy

from .texture import PixelArray
from .common import find_all_textures, find_texture, get_path_true_case
from .islands import get_islands_from_obj


class PIXPAINT_PT_pixpaint_uv_tools(bpy.types.Panel):
    """PixPaint UV Operations Panel"""

    bl_label = "PixPaint: UV Tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "PixPaint"

    def draw(self, context):
        # addon_prefs = prefs()
        layout = self.layout

        #  __   __ ___       __
        # (__' |__  |  |  | |__)
        # .__) |__  |  \__/ |
        #
        box = layout.box()
        box.label(text="Texture Setup")
        content = box.column()

        has_texture = (
            context.view_layer.objects.active is not None
            and find_texture(context.view_layer.objects.active) is not None
        )
        can_create_texture = (
            context.view_layer.objects.active is not None and not has_texture
        )

        row = content.row(align=True)
        row.enabled = can_create_texture
        row.operator("view3d.pixpaint_create_texture")
        row.prop(context.scene, "pixpaint_texture_size",text="Size")

        # row = col.row(align=True)
        # row.operator("view3d.pixpaint_detect_texture_size", text="", icon="EYEDROPPER")

        row = content.row(align=True)
        row.enabled = has_texture
        op = row.operator("view3d.pixpaint_resize_texture", text="Double (×2)")
        op.scale = 2
        op = row.operator("view3d.pixpaint_resize_texture", text="Halve (÷2)")
        op.scale = 0.5

        # row = col.row(align=True)
        content.prop(context.scene, "pixpaint_texel_density")

        #                     __    _    __   __          __
        # |  | |\ | |  /\  | |__)  /_\  |__) |__) | |\ | / __
        # \__/ | \|  \/  \/  |  \ /   \ |    |    | | \| \__|
        #
        box = layout.box()
        box.label(text="Unwrapping")

        if bpy.context.object.mode != "EDIT":
            box.enabled = False

        col = box.column(align=True)
        col.operator("view3d.pixpaint_unwrap_basic", icon="SELECT_SET")
        col.operator("view3d.pixpaint_unwrap_pixel_grid", icon="VIEW_ORTHO")
        col.operator("view3d.pixpaint_unwrap_extend", icon="SELECT_SUBTRACT")
        col.operator("view3d.pixpaint_unwrap_single_pixel", icon="GPBRUSH_FILL")

        # row = col.row()
        # row.operator("view3d.pixpaint_unwrap_single_pixel", icon="COPYDOWN")
        # row.operator("view3d.pixpaint_unwrap_single_pixel", icon="PASTEDOWN")

        #  __  __    ___               __
        # |__ |  \ |  |     |  | \  / (__'
        # |__ |__/ |  |     \__/  \/  .__)
        #
        box = layout.box()
        box.label(text="UV Editing")

        if bpy.context.object.mode != "EDIT":
            box.enabled = False

        row = box.row()
        prop = row.prop(context.scene, "pixpaint_uv_behavior", expand=True)
        # prop = box.prop(context.scene, "pixpaint_modify_texture", text="Modify Texture")

        preserve_texture = context.scene.pixpaint_uv_behavior == "PRESERVE"

        fold_box = box.column()
        fold_box.enabled = not preserve_texture
        fold_content = fold_box.column()
        row = fold_content.row()
        row.prop(context.scene, "pixpaint_fold_sections", text="Folds")
        row.prop(context.scene, "pixpaint_fold_alternate", text="Mirror")
        # fold_content.separator()
        row = fold_content.row(align=True)

        fold_x = row.operator("view3d.pixpaint_uv_grid_fold", text="Fold X")
        fold_x.x_sections = context.scene.pixpaint_fold_sections
        fold_x.y_sections = 1
        fold_x.alternate = context.scene.pixpaint_fold_alternate

        fold_y = row.operator("view3d.pixpaint_uv_grid_fold", text="Fold Y")
        fold_y.x_sections = 1
        fold_y.y_sections = context.scene.pixpaint_fold_sections
        fold_y.alternate = context.scene.pixpaint_fold_alternate

        col = box.column(align=True)
        op = col.operator("view3d.pixpaint_uv_flip", text="Flip Horizontal")
        op.flip_axis = "X"
        op.modify_texture = preserve_texture

        op = col.operator("view3d.pixpaint_uv_flip", text="Flip Vertical")
        op.flip_axis = "Y"
        op.modify_texture = preserve_texture

        op = col.operator("view3d.pixpaint_uv_rot_90", text="Rotate 90° CCW")
        op.modify_texture = preserve_texture

        col = box.column()

        # These operators can NEVER preserve texturing
        row = col.row()
        row.enabled = not preserve_texture
        op = row.operator("view3d.pixpaint_set_uv_texel_density", icon="MOD_MESHDEFORM")

        row = col.row()
        row.enabled = not preserve_texture
        op = row.operator(
            "view3d.pixpaint_island_to_random_position", icon="PIVOT_BOUNDBOX"
        )

        op = col.row().operator(
            "view3d.pixpaint_island_to_free_space", icon="UV_ISLANDSEL"
        )
        op.modify_texture = preserve_texture

        op = col.row().operator("view3d.pixpaint_repack_uvs", icon="ALIGN_BOTTOM")
        op.modify_texture = preserve_texture


class PIXPAINT_PT_paint_tools(bpy.types.Panel):
    """PixPaint Texture Painting Panel"""

    bl_label = "PixPaint: Paint Tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "PixPaint"

    def draw(self, context):
        # addon_prefs = prefs()
        layout = self.layout

        box = layout.box()
        box.label(text="Texture Paint Tools")
        col = box.column(align=True)

        if bpy.context.object is None or bpy.context.object.mode != "TEXTURE_PAINT":
            box.enabled = False

        col.operator("view3d.pixpaint_swap_eraser", icon="GPBRUSH_ERASE_HARD")
