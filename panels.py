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

        can_create_texture = (
            context.view_layer.objects.active is not None
            and find_texture(context.view_layer.objects.active) is None
        )

        col = box.column(align=True)
        col.enabled = can_create_texture
        col.operator("view3d.pixpaint_create_texture")
        col.prop(context.scene, "pixpaint_texture_size")

        # row = col.row(align=True)
        # row.operator("view3d.pixpaint_detect_texture_size", text="", icon="EYEDROPPER")

        col = box.column(align=True)
        row = col.row(align=True)
        op = row.operator("view3d.pixpaint_resize_texture", text="Double (×2)")
        op.scale = 2
        op = row.operator("view3d.pixpaint_resize_texture", text="Halve (÷2)")
        op.scale = 0.5

        col.separator()

        row = col.row(align=True)
        row.operator(
            "view3d.pixpaint_set_uv_texel_density", text="", icon="MOD_MESHDEFORM"
        )
        row.prop(context.scene, "pixpaint_texel_density")

        #                     __    _    __   __          __
        # |  | |\ | |  /\  | |__)  /_\  |__) |__) | |\ | / __
        # \__/ | \|  \/  \/  |  \ /   \ |    |    | | \| \__|
        #
        box = layout.box()
        box.label(text="Unwrap")

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
        box.label(text="UV Modification")

        if bpy.context.object.mode != "EDIT":
            box.enabled = False

        prop = box.prop(context.scene, "pixpaint_modify_texture", text="Modify Texture")
        obj = bpy.context.view_layer.objects.active
        texture = find_texture(obj)
        if prop and texture is None:
            prop.enabled = False

        fold_box = box.box()
        fold_content = fold_box.column(align=True)
        row = fold_content.row()
        row.prop(context.scene, "pixpaint_fold_sections", text="Folds")
        row.prop(context.scene, "pixpaint_fold_alternate", text="Mirror")
        fold_content.separator()
        row = fold_content.row(align=True)

        fold_x = row.operator("view3d.pixpaint_uv_grid_fold", text="Fold X")
        fold_x.x_sections = context.scene.pixpaint_fold_sections
        fold_x.y_sections = 1
        fold_x.alternate = context.scene.pixpaint_fold_alternate

        fold_y = row.operator("view3d.pixpaint_uv_grid_fold", text="Fold Y")
        fold_y.x_sections = 1
        fold_y.y_sections = context.scene.pixpaint_fold_sections
        fold_y.alternate = context.scene.pixpaint_fold_alternate

        row = box.row(align=True)
        op = row.operator("view3d.pixpaint_uv_flip", text="Flip X")
        op.flip_axis = "X"
        op.modify_texture = context.scene.pixpaint_modify_texture

        op = row.operator("view3d.pixpaint_uv_flip", text="Flip Y")
        op.flip_axis = "Y"
        op.modify_texture = context.scene.pixpaint_modify_texture

        op = row.operator("view3d.pixpaint_uv_rot_90", text="Rot 90")
        op.modify_texture = context.scene.pixpaint_modify_texture

        col = box.column(align=True)
        op = col.operator("view3d.pixpaint_island_to_free_space", icon="UV_ISLANDSEL")
        op.modify_texture = context.scene.pixpaint_modify_texture

        op = col.operator(
            "view3d.pixpaint_island_to_random_position", icon="PIVOT_BOUNDBOX"
        )

        op = col.operator("view3d.pixpaint_repack_uvs", icon="ALIGN_BOTTOM")
        op.modify_texture = context.scene.pixpaint_modify_texture


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
