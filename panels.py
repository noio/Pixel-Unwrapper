import bpy

from .common import get_first_texture_on_object


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
                and get_first_texture_on_object(context.view_layer.objects.active) is not None
        )

        can_create_texture = (
                context.view_layer.objects.active is not None and not has_texture
        )

        row = content.row(align=True)
        # col.enabled = can_create_texture
        row.operator("view3d.pixunwrap_create_texture", text="Create New")
        row.operator("view3d.pixunwrap_duplicate_texture", text="Duplicate")

        content.prop(context.scene, "pixunwrap_texel_density")
        content.prop(context.scene, "pixunwrap_default_texture_size")

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

        # Add UV sync warning
        if not context.scene.tool_settings.use_uv_select_sync:
            warning = box.row()
            warning.alert = True  # Makes the text red
            warning.label(text="\"UV Sync Selection\" must be enabled", icon='ERROR')

        col = box.column(align=False)
        col.scale_y = 1.5
        col.operator("view3d.pixunwrap_unwrap_grid", icon="VIEW_ORTHO")
        col.operator("view3d.pixunwrap_unwrap_basic", icon="SELECT_SET")
        # col.operator("view3d.pixunwrap_unwrap_extend", icon="SELECT_SUBTRACT")
        col.operator("view3d.pixunwrap_unwrap_single_pixel", icon="GPBRUSH_FILL")


        #  __  __    ___               __
        # |__ |  \ |  |     |  | \  / (__'
        # |__ |__/ |  |     \__/  \/  .__)
        #
        box = layout.box()

        header = box.row()
        header.label(text="UV Editing")


        # Option 2: Bigger toggle with warning colors
        row = box.row()
        row.scale_y = 1.4  # Makes it bigger
        # row.alert = True  # Red warning color
        row.prop(context.scene, "pixunwrap_modify_texture",
                 icon='ERROR')  # or ERROR/WARNING icon

        modify_texture = context.scene.pixunwrap_modify_texture

        ###################
        # FLIP AND ROTATE #
        ###################
        col = box.column(align=True)
        op = col.operator("view3d.pixunwrap_uv_flip", text="Flip Horizontal")
        op.flip_axis = "X"
        op.modify_texture = modify_texture

        op = col.operator("view3d.pixunwrap_uv_flip", text="Flip Vertical")
        op.flip_axis = "Y"
        op.modify_texture = modify_texture

        op = col.operator("view3d.pixunwrap_uv_rot_90", text="Rotate 90° CCW")
        op.modify_texture = modify_texture

        ###########
        # FOLDING #
        ###########
        fold_box = box.column()
        fold_box.enabled = not modify_texture
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
        row.enabled = not modify_texture
        op = row.operator("view3d.pixunwrap_set_uv_texel_density", icon="MOD_MESHDEFORM")

        row = col.row(align=True)
        row.enabled = not modify_texture
        op = row.operator("view3d.pixunwrap_stack_islands", icon="DUPLICATE")

        row = col.row(align=True)
        row.enabled = not modify_texture
        op = row.operator("view3d.pixunwrap_rectify", icon="MESH_PLANE")

        row = col.row(align=True)
        row.enabled = not modify_texture
        op = row.operator("view3d.pixunwrap_nudge_islands", icon="BACK", text="")
        op.move_x = -1
        op.move_y = 0
        op = row.operator("view3d.pixunwrap_nudge_islands", icon="SORT_DESC", text="")
        op.move_x = 0
        op.move_y = 1
        op = row.operator("view3d.pixunwrap_nudge_islands", icon="SORT_ASC", text="")
        op.move_x = 0
        op.move_y = -1
        op = row.operator("view3d.pixunwrap_nudge_islands", icon="FORWARD", text="")
        op.move_x = 1
        op.move_y = 0
        row.separator()
        row.label(text="Nudge")

        row = col.row()
        row.enabled = not modify_texture
        op = row.operator("view3d.pixunwrap_randomize_islands", icon="PIVOT_BOUNDBOX")

        op = col.row().operator(
            "view3d.pixunwrap_island_to_free_space", icon="UV_ISLANDSEL"
        )
        op.modify_texture = modify_texture

        op = col.row().operator("view3d.pixunwrap_repack_uvs", icon="ALIGN_BOTTOM")
        op.modify_texture = modify_texture

        # ___  __     ___       __   __     __    _        __
        #  |  |__ \_/  |  |  | |__) |__    |__)  /_\  |_/ |__
        #  |  |__ / \  |  \__/ |  \ |__    |__) /   \ | \ |__
        #
        box = layout.box()
        header = box.row()
        header.label(text="Texture Bake")
        obj = context.active_object
        buttonlabel = "Bake Texture"
        if obj and len(obj.data.uv_layers) >= 2:
            target_uv = obj.data.uv_layers.active
            source_uv = next((uv for uv in obj.data.uv_layers if uv != target_uv), None)
            # Find texture name
            texture_name = None
            if obj.active_material and obj.active_material.use_nodes:
                for node in obj.active_material.node_tree.nodes:
                    if node.type == 'TEX_IMAGE' and node.image:
                        texture_name = node.image.name
                        break
            if source_uv and texture_name:
                buttonlabel = f"Bake into \"{texture_name}\""
                box.label(text=f"'{source_uv.name}' -> '{target_uv.name}'")
        else:
            box.label(text="Select an object that has 2 UV maps")

        box.operator("view3d.pixunwrap_transfer_texture", text=buttonlabel)


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
        col.operator("view3d.pixunwrap_swap_eraser", icon="GPBRUSH_ERASE_HARD")
