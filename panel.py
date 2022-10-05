import os
import bpy

from .texture import PixelArray
from .common import find_all_textures, find_texture, get_path_true_case
from .islands import get_islands_from_obj


class PIXPAINT_OT_detect_texture_size(bpy.types.Operator):
    """Set texture size from first image on selected object"""

    bl_idname = "view3d.pixpaint_detect_texture_size"
    bl_label = "Detect Texture Size from Selected Object"
    bl_options = {"UNDO"}

    def execute(self, context):
        obj = bpy.context.view_layer.objects.active
        texture = find_texture(obj)

        if texture:
            context.scene.pixpaint_texture_size = texture.size[0]

        return {"FINISHED"}


class PIXPAINT_OT_test_objects(bpy.types.Operator):
    """Just some debugging info on active objects"""

    bl_idname = "view3d.pixpaint_test_objects"
    bl_label = "TEST OBJECTS"
    bl_options = {"UNDO"}

    def execute(self, context):
        for ob in context.view_layer.objects:
            if ob.type == "MESH":
                islands = get_islands_from_obj(ob, False)
                print(f"OB: {ob} {find_all_textures(ob)} ISLANDS: {islands}")

        obj = bpy.context.view_layer.objects.active

        return {"FINISHED"}


class PIXPAINT_OT_create_texture(bpy.types.Operator):
    """Create and Link Texture"""

    bl_idname = "view3d.pixpaint_create_texture"
    bl_label = "Create and Link Texture"
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context):
        obj = bpy.context.view_layer.objects.active
        return find_texture(obj) is None

    def execute(self, context):
        obj = bpy.context.view_layer.objects.active

        #################################################
        # CREATE NEW TEXTURE AND FILL WITH DEFAULT GRID #
        #################################################
        new_texture = bpy.data.images.new(
            name=obj.name + "_tex",
            width=context.scene.pixpaint_texture_size,
            height=context.scene.pixpaint_texture_size,
            alpha=True,
        )

        pixels = PixelArray(None, context.scene.pixpaint_texture_size)
        new_texture.pixels = pixels.pixels

        # DON'T SAVE, this could be dangerous as it just whams the texture
        # over any existing file with the same name.
        # Prefer to just let the user click save and a destination.

        # if len(new_texture.filepath_raw) == 0 or new_texture.filepath_raw is None:
        #     # If the image was never saved, set the filepath
        #     texture_path = bpy.path.abspath("//Textures")
        #     if not os.path.exists(texture_path):
        #         os.mkdir(texture_path)
        #     else:
        #         # Ensure that the path is actually that of the OS
        #         # Avoid errors when textures are in "//textures" (lower case)
        #         texture_path = get_path_true_case(texture_path)

        #     filepath_rel = bpy.path.relpath(
        #         os.path.join(texture_path, new_texture.name + ".png")
        #     )
        #     new_texture.filepath_raw = filepath_rel
        #     new_texture.file_format = "PNG"
        # new_texture.save()

        ##############################
        # SET UV EDITOR TO NEW IMAGE #
        ##############################
        for area in bpy.context.screen.areas:
            if area.type == "IMAGE_EDITOR":
                area.spaces.active.image = new_texture

        ##########################
        # GET OR CREATE MATERIAL #
        ##########################
        mat = obj.active_material

        if mat is None:
            mat = bpy.data.materials.new(name=f"{obj.name}_mat")
            obj.data.materials.append(mat)

        # Set up shader nodes
        mat.use_nodes = True
        image_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        image_node.image = new_texture
        image_node.interpolation = "Closest"

        bsdf_node = mat.node_tree.nodes["Principled BSDF"]
        mat.node_tree.links.new(
            image_node.outputs["Color"], bsdf_node.inputs["Base Color"]
        )
        mat.node_tree.links.new(image_node.outputs["Alpha"], bsdf_node.inputs["Alpha"])

        location = bsdf_node.location.copy()
        location.x -= bsdf_node.width * 2
        image_node.location = location

        return {"FINISHED"}


class PIXPAINT_OT_swap_eraser(bpy.types.Operator):
    """Swap Eraser"""

    bl_idname = "view3d.pixpaint_swap_eraser"
    bl_label = "Toggle Erase Alpha"
    bl_options = {"UNDO"}

    def execute(self, context):

        if not hasattr(self, "previous_blend"):
            self.previous_blend = "MIX"
        if bpy.context.tool_settings.image_paint.brush.blend != "ERASE_ALPHA":
            self.previous_blend = bpy.context.tool_settings.image_paint.brush.blend
            bpy.context.tool_settings.image_paint.brush.blend = "ERASE_ALPHA"
        else:
            bpy.context.tool_settings.image_paint.brush.blend = self.previous_blend

        return {"FINISHED"}


class PIXPAINT_PT_uv_editing(bpy.types.Panel):
    """PixPaint UV Operations Panel"""

    bl_label = "UV Editing"
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
        box.label(text="Setup")

        col = box.column(align=True)
        row = col.row(align=True)
        row.operator("view3d.pixpaint_detect_texture_size", text="", icon="EYEDROPPER")
        row.prop(context.scene, "pixpaint_texture_size")

        row = col.row(align=True)
        row.operator(
            "view3d.pixpaint_set_uv_texel_density", text="", icon="MOD_MESHDEFORM"
        )
        row.prop(context.scene, "pixpaint_texel_density")

        row = col.row(align=True)
        row.operator("view3d.pixpaint_create_texture")

        col.operator("view3d.pixpaint_test_objects")

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

        col = box.column(align=True)
        op = col.operator(
            "view3d.pixpaint_selected_island_to_free_space", icon="UV_ISLANDSEL"
        )
        op.modify_texture = context.scene.pixpaint_modify_texture

        op = col.operator("view3d.pixpaint_repack_uvs", icon="ALIGN_BOTTOM")
        op.modify_texture = context.scene.pixpaint_modify_texture


class PIXPAINT_PT_texture_painting(bpy.types.Panel):
    """PixPaint Texture Painting Panel"""

    bl_label = "Texture Painting"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "PixPaint"

    def draw(self, context):
        # addon_prefs = prefs()
        layout = self.layout

        box = layout.box()
        box.label(text="Texture Paint Tools")
        col = box.column(align=True)

        if bpy.context.object.mode != "TEXTURE_PAINT":
            box.enabled = False

        col.operator("view3d.pixpaint_swap_eraser", icon="GPBRUSH_ERASE_HARD")
