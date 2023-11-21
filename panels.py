import os
import bpy

from .texture import PixelArray
from .common import find_all_textures, find_texture, get_path_true_case
from .islands import get_islands_from_obj


class PIXUNWRAP_PT_uv_tools(bpy.types.Panel):
    """Pixel Unwrapper UV Operations Panel"""

    bl_label = "Pixel Unwrapper: UV Tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Pixel Unwrapper"

    def draw(self, context):
        # addon_prefs = prefs()
        layout = self.layout

        #  __   __ ___       __
        # (__' |__  |  |  | |__)
        # .__) |__  |  \__/ |
        #
        box = layout.box()
        header = box.row()
        header.label(text="Texture Setup")
        header.operator("view3d.pixunwrap_object_info", text="", icon="QUESTION")
        
        content = box.column()

        has_texture = (
            context.view_layer.objects.active is not None
            and find_texture(context.view_layer.objects.active) is not None
        )
        
        can_create_texture = (
            context.view_layer.objects.active is not None and not has_texture
        )

        row = content.row(align=True)
        # col.enabled = can_create_texture
        row.operator("view3d.pixunwrap_create_texture", text="Create New")
        row.operator("view3d.pixunwrap_duplicate_texture", text="Duplicate")

        content.prop(context.scene, "pixunwrap_texel_density")


        # row = col.row(align=True)
        # row.operator("view3d.pixunwrap_detect_texture_size", text="", icon="EYEDROPPER")

        row = content.row(align=True)
        row.enabled = has_texture
        op = row.operator("view3d.pixunwrap_resize_texture", text="Double (×2)")
        op.scale = 2
        op = row.operator("view3d.pixunwrap_resize_texture", text="Halve (÷2)")
        op.scale = 0.5

        content.label(text="Fill Colors")
        row = content.row(align=True)
        row.prop(context.scene, "pixunwrap_texture_fill_color_tl", text="")
        row.prop(context.scene, "pixunwrap_texture_fill_color_tr", text="")
        row.prop(context.scene, "pixunwrap_texture_fill_color_bl", text="")
        row.prop(context.scene, "pixunwrap_texture_fill_color_br", text="")

        

        # row = col.row(align=True)

        #                     __    _    __   __          __
        # |  | |\ | |  /\  | |__)  /_\  |__) |__) | |\ | / __
        # \__/ | \|  \/  \/  |  \ /   \ |    |    | | \| \__|
        #
        box = layout.box()
        box.label(text="Unwrapping")

        if bpy.context.object is None or bpy.context.object.mode != "EDIT":
            box.enabled = False

        col = box.column(align=True)
        col.operator("view3d.pixunwrap_unwrap_pixel_grid", icon="VIEW_ORTHO")
        col.operator("view3d.pixunwrap_unwrap_basic", icon="SELECT_SET")
        # col.operator("view3d.pixunwrap_unwrap_extend", icon="SELECT_SUBTRACT")
        col.operator("view3d.pixunwrap_unwrap_single_pixel", icon="GPBRUSH_FILL")

        # row = col.row()
        # row.operator("view3d.pixunwrap_unwrap_single_pixel", icon="COPYDOWN")
        # row.operator("view3d.pixunwrap_unwrap_single_pixel", icon="PASTEDOWN")

        #  __  __    ___               __
        # |__ |  \ |  |     |  | \  / (__'
        # |__ |__/ |  |     \__/  \/  .__)
        #
        box = layout.box()
        if bpy.context.object.mode != "EDIT":
            box.enabled = False

        header = box.row()
        header.label(text="UV Editing")
        header.prop(context.scene, "pixunwrap_uv_behavior", text="")
        
        preserve_texture = context.scene.pixunwrap_uv_behavior == "PRESERVE"

        ###################
        # FLIP AND ROTATE #
        ###################
        col = box.column(align=True)
        op = col.operator("view3d.pixunwrap_uv_flip", text="Flip Horizontal")
        op.flip_axis = "X"
        op.modify_texture = preserve_texture

        op = col.operator("view3d.pixunwrap_uv_flip", text="Flip Vertical")
        op.flip_axis = "Y"
        op.modify_texture = preserve_texture

        op = col.operator("view3d.pixunwrap_uv_rot_90", text="Rotate 90° CCW")
        op.modify_texture = preserve_texture


        ###########
        # FOLDING #
        ###########
        fold_box = box.column()
        fold_box.enabled = not preserve_texture
        fold_content = fold_box.column()
        row = fold_content.row()
        row.prop(context.scene, "pixunwrap_fold_sections", text="Folds")
        row.prop(context.scene, "pixunwrap_fold_alternate", text="Mirror")
        # fold_content.separator()
        row = fold_content.row(align=True)

        fold_x = row.operator("view3d.pixunwrap_uv_grid_fold", text="Fold X")
        fold_x.x_sections = context.scene.pixunwrap_fold_sections
        fold_x.y_sections = 1
        fold_x.alternate = context.scene.pixunwrap_fold_alternate

        fold_y = row.operator("view3d.pixunwrap_uv_grid_fold", text="Fold Y")
        fold_y.x_sections = 1
        fold_y.y_sections = context.scene.pixunwrap_fold_sections
        fold_y.alternate = context.scene.pixunwrap_fold_alternate

        ######################
        # OTHER UV OPERATORS #
        ######################
        # These operators can NEVER preserve texturing
        col = box.column()
        row = col.row()
        row.enabled = not preserve_texture
        op = row.operator("view3d.pixunwrap_set_uv_texel_density", icon="MOD_MESHDEFORM")

        row = col.row()
        row.enabled = not preserve_texture
        op = row.operator("view3d.pixunwrap_randomize_islands", icon="PIVOT_BOUNDBOX")

        op = col.row().operator(
            "view3d.pixunwrap_island_to_free_space", icon="UV_ISLANDSEL"
        )
        op.modify_texture = preserve_texture

        op = col.row().operator("view3d.pixunwrap_repack_uvs", icon="ALIGN_BOTTOM")
        op.modify_texture = preserve_texture


class PIXUNWRAP_PT_paint_tools(bpy.types.Panel):
    """Pixel Unwrapper Texture Painting Panel"""

    bl_label = "Pixel Unwrapper: Paint Tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Pixel Unwrapper"

    def draw(self, context):
        # addon_prefs = prefs()
        layout = self.layout

        box = layout.box()
        box.label(text="Texture Paint Tools")
        col = box.column(align=True)

        if bpy.context.object is None or bpy.context.object.mode != "TEXTURE_PAINT":
            box.enabled = False

        col.operator("view3d.pixunwrap_swap_eraser", icon="GPBRUSH_ERASE_HARD")
