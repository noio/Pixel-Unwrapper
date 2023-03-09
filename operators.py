from cgitb import text
from math import cos, sin, pi
import random

import bpy
import bmesh
from mathutils import Vector


from .common import *
from .texture import PixelArray, copy_texture_region, copy_texture_region_transformed
from .packing import find_free_space_for_island, pack_rects
from .islands import *
from .grids import Grid, GridBuildException, GridSnapModes


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
        is_title_case = " " in obj.name or any(letter.isupper() for letter in obj.name)

        #################################################
        # CREATE NEW TEXTURE AND FILL WITH DEFAULT GRID #
        #################################################
        new_texture = bpy.data.images.new(
            name=f"{obj.name} Texture" if is_title_case else f"{obj.name}_tex",
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
            name = f"{obj.name} Material" if is_title_case else "{obj.name}_mat"
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


class PIXPAINT_OT_resize_texture(bpy.types.Operator):
    """Resize Texture on Selected Object"""

    bl_idname = "view3d.pixpaint_resize_texture"
    bl_label = "Resize Texture"
    bl_options = {"UNDO"}

    scale: bpy.props.FloatProperty(default=2)
    only_update_uvs_on_active: bpy.props.BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        obj = context.view_layer.objects.active
        return obj is not None and find_texture(obj) is not None

    def execute(self, context):
        active_obj = context.view_layer.objects.active
        texture = find_texture(active_obj)
        texture_size = texture.size[0]
        new_size = round(texture_size * self.scale)

        if texture.is_dirty:
            self.report(
                {"ERROR"},
                f'Please save "{texture.name}" first, because undo doesn\'t work for textures.',
            )
            return {"CANCELLED"}

        if new_size < 2:
            self.report({"ERROR"}, "That's too small.")
            return {"CANCELLED"}

        if new_size > 8192:
            self.report(
                {"ERROR"},
                f"New texture would be {new_size} pixels, that's probably too big.",
            )
            return {"CANCELLED"}

        # SCALE UP THE TEXTURE AND PRESERVE THE DATA
        # WHEN SCALING DOWN, TEXTURE IS CROPPED TO BOTTOM LEFT
        src_pixels = PixelArray(blender_image=texture)
        dst_pixels = PixelArray(size=new_size)

        copy_region_size = Vector2Int(dst_pixels.width, dst_pixels.height)
        dst_pixels.copy_region(
            src_pixels, Vector2Int(0, 0), copy_region_size, Vector2Int(0, 0)
        )

        texture.scale(new_size, new_size)
        texture.pixels = dst_pixels.pixels
        texture.update()

        # UPDATE THE UVS TO SPAN THE SAME PIXELS
        # FIND ALL OBJECTS THAT USE THE SAME TEXTURE:
        # (if option enabled, otherwise just do it on active object)
        objs_to_update_uvs = (
            [active_obj]
            if self.only_update_uvs_on_active
            else context.view_layer.objects
        )

        actual_scale_inv = texture_size / new_size

        for obj_to_update in objs_to_update_uvs:
            if obj_to_update.type == "MESH":
                obj_textures = find_all_textures(obj_to_update)

                if texture in obj_textures:
                    print(f"updating object {obj_to_update}")
                    if obj_to_update.data.is_editmode:
                        bm = bmesh.from_edit_mesh(obj_to_update.data)
                    else:
                        bm = bmesh.new()
                        bm.from_mesh(obj_to_update.data)

                    uv_layer = bm.loops.layers.uv.verify()

                    uvs_scale(bm.faces, uv_layer, actual_scale_inv)

                    if obj_to_update.data.is_editmode:
                        bmesh.update_edit_mesh(obj_to_update.data)
                    else:
                        bm.to_mesh(obj_to_update.data)
                    bm.free()

        context.scene.pixpaint_texture_size = new_size

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


class PIXPAINT_OT_island_to_free_space(bpy.types.Operator):
    """Move the selected UV island(s) to a free section on the UV map.
    This is based only on UV islands in the current mesh."""

    bl_idname = "view3d.pixpaint_island_to_free_space"
    bl_label = "Island to Free Space"
    bl_options = {"UNDO"}

    modify_texture: bpy.props.BoolProperty(default=False)
    selection_is_island: bpy.props.BoolProperty(default=True)

    # If True: only Islands with Pinned verts will count as occupied
    # (unpinned islands are considered free space)
    ignore_unpinned_islands: bpy.props.BoolProperty(default=True)

    # Should the Island stay in place if it's already in 'free space'
    # (or be moved to bottom left)
    prefer_current_position: bpy.props.BoolProperty(default=False)

    # Should OTHER objects' UV islands also be included (as occupied space)
    # if they use the same texture
    include_other_objects: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        obj = bpy.context.view_layer.objects.active
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        texture_size = context.scene.pixpaint_texture_size

        # FIND ISLANDS

        if self.selection_is_island:
            selected_faces = [face for face in bm.faces if face.select]
            other_faces = [face for face in bm.faces if not face.select]
            selected_islands = get_islands_for_faces(bm, selected_faces, uv_layer)
            all_islands = get_islands_for_faces(bm, other_faces, uv_layer)
        else:
            all_islands = get_islands_from_obj(obj, False)
            selected_islands = [
                isl
                for isl in all_islands
                if any(uvf.face.select for uvf in isl.uv_faces)
            ]

        selected_islands = merge_overlapping_islands(selected_islands)

        if self.include_other_objects:
            obj_texture = find_texture(obj)
            for other in context.view_layer.objects:
                if other != obj:  # Exclude myself
                    if other.type == "MESH":
                        other_textures = find_all_textures(other)
                        if obj_texture in other_textures:
                            all_islands.extend(get_islands_from_obj(other, False))

        if self.ignore_unpinned_islands:
            all_islands = [isl for isl in all_islands if isl.is_any_pinned()]

        modify_texture = self.modify_texture

        for island in selected_islands:
            island.calc_pixel_bounds(texture_size)

            # continue
            new_pos = find_free_space_for_island(
                island, all_islands, texture_size, self.prefer_current_position
            )
            old_pos = island.pixel_bounds.min

            offset = (new_pos - old_pos) / texture_size

            faces = island.get_faces()
            uvs_translate_rotate_scale(faces, uv_layer, translate=offset)

            if modify_texture:
                texture = find_texture(obj)
                if texture:
                    copy_texture_region(
                        texture, old_pos, island.pixel_bounds.size, new_pos
                    )

            uvs_pin(island.get_faces(), uv_layer)

        bmesh.update_edit_mesh(obj.data)

        return {"FINISHED"}


class PIXPAINT_OT_repack_uvs(bpy.types.Operator):
    """Repack all UV islands in the editing mesh in a more efficient way."""

    bl_idname = "view3d.pixpaint_repack_uvs"
    bl_label = "Repack All Islands"
    bl_options = {"UNDO"}

    modify_texture: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        obj = bpy.context.view_layer.objects.active
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        texture = find_texture(obj)
        if texture is not None:
            texture_size = texture.size[0]
        else:
            texture_size: int = context.scene.pixpaint_texture_size

        # FIND ISLANDS
        islands = get_islands_from_obj(obj, False)

        for island in islands:
            island.calc_pixel_bounds(texture_size)

        islands = merge_overlapping_islands(islands)

        rects = []
        need_flip = []
        for uv_island in islands:
            rect_size = uv_island.pixel_bounds.size

            locked = uv_island.is_any_orientation_locked()
            # Flip all rectangles to lay flat (wider than they are high)
            if not locked and rect_size.y > rect_size.x:
                rect_size = Vector2Int(rect_size.y, rect_size.x)
                need_flip.append(True)
            else:
                need_flip.append(False)

            rects.append(rect_size)

        # Try one size smaller (but only if the texture can be divided by 2)
        # and only if we're allowed to modify the texture
        min_size = texture_size // 2 if (texture_size % 2 == 0) else texture_size
        new_positions, needed_size = pack_rects(rects, min_size)

        if needed_size > texture_size:
            self.report(
                {"ERROR"},
                "Texture is not big enough for UV islands. Repacking might lose data. Resize texture first.",
            )
            return {"CANCELLED"}

        modify_texture = self.modify_texture and texture is not None

        if modify_texture:
            if texture.is_dirty:
                self.report(
                    {"ERROR"},
                    f'Please save "{texture.name}" first, because undo doesn\'t work for textures.',
                )
                return {"CANCELLED"}

            src_pixels = PixelArray(blender_image=texture)
            dst_pixels = PixelArray(size=texture_size)

        for (new_pos, island, flip) in zip(new_positions, islands, need_flip):
            new_pos = Vector2Int(new_pos[0], new_pos[1])
            old_pos = island.pixel_bounds.min

            # print(f"ISLAND\n{old_pos=} {texture_size=} {new_pos=} {new_size=}\n")
            offset = new_pos - old_pos

            matrix = Matrix.Identity(3)
            matrix[0][2] = offset.x
            matrix[1][2] = offset.y

            faces = [faceinfo.face for faceinfo in island.uv_faces]

            # Should the rectangular UV island be flipped?
            # We do this in a way that preserves the bottom left point
            # so that translation below can happen as usual,
            # regardless of whether the island was flipped
            # H is a point halfway the left side of the rect, which.. well draw it out yourself
            if flip:
                h = island.pixel_bounds.size.y / 2
                pivot = Vector((old_pos.x + h, old_pos.y + h))
                flip_matrix = Matrix.Rotation(radians(90), 2).to_3x3()
                matrix_pin_pivot(flip_matrix, pivot)
                matrix = matrix @ flip_matrix

            matrix_uv = get_uv_space_matrix(matrix, texture_size)

            uvs_transform(faces, uv_layer, matrix_uv)

            if modify_texture:
                dst_pixels.copy_region_transformed(
                    src_pixels, island.pixel_bounds, matrix
                )

        bmesh.update_edit_mesh(obj.data)

        if modify_texture:
            texture.pixels = dst_pixels.pixels
            texture.update()

        # texture.save()
        return {"FINISHED"}


class PIXPAINT_OT_set_uv_texel_density(bpy.types.Operator):
    """Set UV Texel Density to Target Value"""

    bl_idname = "view3d.pixpaint_set_uv_texel_density"
    bl_label = "Rescale all UV islands to average this target density"
    bl_options = {"UNDO"}

    def execute(self, context):

        texture_size = context.scene.pixpaint_texture_size
        target_density = context.scene.pixpaint_texel_density

        obj = bpy.context.view_layer.objects.active
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        faces = [face for face in bm.faces if face.select]

        uvs_scale_texel_density(bm, faces, uv_layer, texture_size, target_density)

        bmesh.update_edit_mesh(obj.data)

        return {"FINISHED"}


class PIXPAINT_OT_unwrap_pixel_grid(bpy.types.Operator):
    """Unwrap Pixel Rect"""

    bl_idname = "view3d.pixpaint_unwrap_pixel_grid"
    bl_label = "Unwrap Grid"
    bl_options = {"REGISTER", "UNDO"}

    snap: bpy.props.EnumProperty(name="Snap Vertices", items=GridSnapModes)

    def execute(self, context):
        # bpy.ops.uv.select_split()

        texture_size = context.scene.pixpaint_texture_size
        target_density = context.scene.pixpaint_texel_density

        obj = bpy.context.view_layer.objects.active
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        all_target_faces = [face for face in bm.faces if face.select]

        for quad_group, connected_non_quads in zip(*find_quad_groups(all_target_faces)):
            print(
                f"UNWRAPPING QUAD ISLAND with {len(quad_group)} quads and {len(connected_non_quads)} attached non-quads"
            )

            for face in all_target_faces:
                face.select = False

            for face in quad_group:
                face.select = True

            bpy.ops.uv.unwrap(
                method="ANGLE_BASED",
                fill_holes=True,
                correct_aspect=True,
                use_subsurf_data=False,
                margin=0.01,
            )

            try:
                grid = Grid(bm, quad_group)
            except GridBuildException as e:
                self.report({"ERROR"}, str(e))
                return {"CANCELLED"}

            grid.straighten_uv(uv_layer, self.snap, texture_size, target_density)

            # Attach the non-quad faces to the quad grid:
            uvs_pin(quad_group, uv_layer)
            uvs_pin(connected_non_quads, uv_layer, False)

            for face in connected_non_quads:
                face.select = True

            bpy.ops.uv.unwrap(
                method="ANGLE_BASED",
                fill_holes=True,
                correct_aspect=True,
                use_subsurf_data=False,
                margin=0.01,
            )
            # uvs_snap_to_texel_corner(
            #     non_quad_group, uv_layer, texture_size, skip_pinned=True
            # )
            uvs_pin(connected_non_quads, uv_layer)

            bpy.ops.view3d.pixpaint_island_to_free_space(modify_texture=False)

        # Wrap things up: Reselect all faces (because we messed with selections)
        for face in all_target_faces:
            face.select = True

        bmesh.update_edit_mesh(obj.data)

        return {"FINISHED"}


class PIXPAINT_OT_unwrap_extend(bpy.types.Operator):
    """Standard Blender unwrap, preserves pinned UVs and snaps to pixels depending on setting"""

    bl_idname = "view3d.pixpaint_unwrap_extend"
    bl_label = "Unwrap Extend"
    bl_options = {"UNDO"}

    def execute(self, context):

        # bpy.ops.uv.select_split()

        texture_size = context.scene.pixpaint_texture_size

        obj = bpy.context.view_layer.objects.active
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        bpy.ops.uv.unwrap(
            method="ANGLE_BASED",
            fill_holes=True,
            correct_aspect=True,
            use_subsurf_data=False,
            margin=0.01,
        )

        selected_faces = list(face for face in bm.faces if face.select)

        uvs_snap_to_texel_corner(
            selected_faces, uv_layer, texture_size, skip_pinned=True
        )
        uvs_pin(selected_faces, uv_layer)

        bmesh.update_edit_mesh(obj.data)

        return {"FINISHED"}


class PIXPAINT_OT_unwrap_basic(bpy.types.Operator):
    """Standard blender unwrap, but scales to correct pixel density"""

    bl_idname = "view3d.pixpaint_unwrap_basic"
    bl_label = "Unwrap Basic"
    bl_options = {"UNDO"}

    def execute(self, context):

        # bpy.ops.uv.select_split()

        texture_size = context.scene.pixpaint_texture_size
        target_density = context.scene.pixpaint_texel_density

        obj = bpy.context.view_layer.objects.active
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        selected_faces = list(face for face in bm.faces if face.select)
        uvs_pin(selected_faces, uv_layer, False)

        bpy.ops.uv.unwrap(
            method="ANGLE_BASED",
            fill_holes=True,
            correct_aspect=True,
            use_subsurf_data=False,
            margin=0.01,
        )

        # Scale to texel density
        uvs_scale_texel_density(
            bm, selected_faces, uv_layer, texture_size, target_density
        )

        # Round the total size of the island to a whole number of pixels
        island = UVIsland(selected_faces, bm, uv_layer)
        size = island.max - island.min
        pixel_size = size * texture_size
        rounded_size = Vector((round(pixel_size.x), round(pixel_size.y))) / texture_size
        scale = Vector((rounded_size.x / size.x, rounded_size.y / size.y))
        uvs_scale(selected_faces, uv_layer, scale)

        # Position it so that corners are on texel corners
        center = 0.5 * (island.max + island.min)
        offset = rounded_size / 2 - center
        uvs_translate_rotate_scale(selected_faces, uv_layer, offset)

        # uvs_snap_to_texel_corner(
        #     selected_faces, uv_layer, texture_size, skip_pinned=True
        # )

        bpy.ops.view3d.pixpaint_island_to_free_space(modify_texture=False)

        uvs_pin(selected_faces, uv_layer)

        bmesh.update_edit_mesh(obj.data)

        return {"FINISHED"}


class PIXPAINT_OT_unwrap_single_pixel(bpy.types.Operator):
    """Unwraps the selected faces to a single pixel, so they always
    have the same color when painting"""

    bl_idname = "view3d.pixpaint_unwrap_single_pixel"
    bl_label = "Unwrap to Single Pixel"
    bl_options = {"UNDO"}

    def execute(self, context):

        # bpy.ops.uv.select_split()

        texture_size = context.scene.pixpaint_texture_size

        obj = bpy.context.view_layer.objects.active
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        selected_faces = list(face for face in bm.faces if face.select)
        uvs_pin(selected_faces, uv_layer, False)

        bpy.ops.uv.unwrap(
            method="ANGLE_BASED",
            fill_holes=True,
            correct_aspect=True,
            use_subsurf_data=False,
            margin=0.01,
        )

        target_size = 1.0 / texture_size

        def vert_pos(v, v_total):
            a = pi * 2 * v / v_total
            # radius is slightly bigger than a pixel to make sure that they take
            # up more than a pixel, and have some margin for bleed from other islands..
            # I think.
            radius = 0.49
            return Vector((radius * cos(a) + 0.5, radius * sin(a) + 0.5))

        for face in selected_faces:
            v_count = len(face.loops)
            for v, loop in enumerate(face.loops):
                p = vert_pos(v, v_count) * target_size
                loop[uv_layer].uv = p

        uvs_pin(selected_faces, uv_layer, True)

        bmesh.update_edit_mesh(obj.data)

        bpy.ops.view3d.pixpaint_island_to_free_space(modify_texture=False)

        return {"FINISHED"}


class PIXPAINT_OT_uv_grid_fold(bpy.types.Operator):
    """Fold the selected UV grid"""

    bl_idname = "view3d.pixpaint_uv_grid_fold"
    bl_label = "Fold UV Grid"
    bl_options = {"REGISTER", "UNDO"}

    x_sections: bpy.props.IntProperty(default=2, name="X Sections")
    y_sections: bpy.props.IntProperty(default=1, name="Y Sections")
    alternate: bpy.props.BoolProperty(default=True, name="Alternate Direction")

    def execute(self, context):
        obj = context.view_layer.objects.active
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        all_target_faces = [face for face in bm.faces if face.select]

        for quad_group, _ in zip(*find_quad_groups(all_target_faces)):
            try:
                grid = Grid(bm, quad_group)
                grid.realign_to_uv_map(uv_layer)
                grid.fold(uv_layer, self.x_sections, self.y_sections, self.alternate)
            except GridBuildException as e:
                self.report({"ERROR"}, str(e))
                return {"CANCELLED"}

        bmesh.update_edit_mesh(obj.data)
        return {"FINISHED"}


class PIXPAINT_OT_uv_flip(bpy.types.Operator):
    """Flip the selected UV Island"""

    bl_idname = "view3d.pixpaint_uv_flip"
    bl_label = "Flip UV Island"
    bl_options = {"UNDO"}

    FlipAxis = [
        ("X", "Flip X", "", 1),
        ("Y", "Flip Y", "", 2),
    ]

    flip_axis: bpy.props.EnumProperty(items=FlipAxis, name="Flip Axis")
    modify_texture: bpy.props.BoolProperty(default=False, name="Modify Texture")

    def execute(self, context):
        obj = context.view_layer.objects.active
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        texture_size = context.scene.pixpaint_texture_size

        # FIND ISLANDS
        islands = get_islands_from_obj(obj, True)
        islands = merge_overlapping_islands(islands)

        texture = find_texture(obj)

        for island in islands:

            island.calc_pixel_bounds(texture_size)
            island_rect = island.pixel_bounds

            # `matrix` is the matrix used for transforming texture pixels,
            # `matrix_uv` is the matrix used for transforming uv coords
            if self.flip_axis == "X":
                matrix = Matrix.Diagonal((-1, 1, 1))
                pivot = (island_rect.min + island_rect.max) / 2
            elif self.flip_axis == "Y":
                matrix = Matrix.Diagonal((1, -1, 1))
                pivot = (island_rect.min + island_rect.max) / 2

            matrix_pin_pivot(matrix, pivot)

            matrix_uv = get_uv_space_matrix(matrix, texture_size)

            uvs_transform(island.get_faces(), uv_layer, matrix_uv)

            if self.modify_texture:
                copy_texture_region_transformed(texture, island_rect, matrix)

        bmesh.update_edit_mesh(obj.data)
        return {"FINISHED"}


class PIXPAINT_OT_uv_rot_90(bpy.types.Operator):
    """Rotate the selected UV Island by 90 degrees (CCW)"""

    bl_idname = "view3d.pixpaint_uv_rot_90"
    bl_label = "Rotate UV Island 90 Degrees"
    bl_options = {"UNDO"}

    modify_texture: bpy.props.BoolProperty(default=False, name="Modify Texture")

    def execute(self, context):

        bpy.ops.ed.undo_push()
        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        texture_size = context.scene.pixpaint_texture_size
        texture_rect = RectInt(Vector2Int(0, 0), Vector2Int(texture_size, texture_size))

        # FIND ISLANDS
        islands = get_islands_from_obj(obj, True)
        islands = merge_overlapping_islands(islands)

        texture = find_texture(obj)

        for island in islands:

            island.calc_pixel_bounds(texture_size)
            island_rect = island.pixel_bounds

            matrix = Matrix.Rotation(radians(90), 2).to_3x3()
            h = island.pixel_bounds.size.y / 2
            pivot = Vector((island_rect.min.x + h, island_rect.min.y + h))

            matrix_pin_pivot(matrix, pivot)

            matrix_uv = get_uv_space_matrix(matrix, texture_size)
            uvs_transform(island.get_faces(), uv_layer, matrix_uv)

            # When rotating, the bounds change, so we need to find some
            # FREE SPACE on the texture to move the island to.
            # We do this AFTER already having rotated the UV's, so
            # free space is found for the rotated island.
            # but we do the TEXTURE modification afterwards, for the
            # entire transformation in one (rotate + move to free space)
            old_pos = island.pixel_bounds.min
            bpy.ops.view3d.pixpaint_island_to_free_space(modify_texture=False)
            new_pos = island.pixel_bounds.min
            offset = new_pos - old_pos
            matrix[0][2] += offset.x
            matrix[1][2] += offset.y

            if self.modify_texture and texture is not None:
                
                island.calc_info()
                island.calc_pixel_bounds(texture_size)
                if not texture_rect.contains(
                    island.pixel_bounds.min, island.pixel_bounds.size
                ):
                    self.report(
                        {"ERROR"},
                        f"Not enough free space on texture to rotate island. Increase texture size or turn off 'Modify Texture'",
                    )
                    bpy.ops.ed.undo()
                    return {"CANCELLED"}
                

                copy_texture_region_transformed(texture, island_rect, matrix)

        # THIS INVALIDATES ALL FACE DATA, SO DO IT OUTSIDE OF MAIN LOOP
        lock_orientation(bm, [face.index for face in bm.faces if face.select], True)

        bmesh.update_edit_mesh(obj.data)
        return {"FINISHED"}


class PIXPAINT_OT_island_to_random_position(bpy.types.Operator):
    """
    Move the selected island(s) to a random position inside the
    UV bounds
    """

    bl_idname = "view3d.pixpaint_island_to_random_position"
    bl_label = "Island to Random"
    bl_options = {"UNDO", "REGISTER"}

    x_min: bpy.props.FloatProperty(name="X Min", default=0, min=0, max=1)
    x_max: bpy.props.FloatProperty(name="X Max", default=1, min=0, max=1)
    y_min: bpy.props.FloatProperty(name="Y Min", default=0, min=0, max=1)
    y_max: bpy.props.FloatProperty(name="Y Max", default=1, min=0, max=1)

    def execute(self, context):

        bpy.ops.ed.undo_push()
        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        texture_size = context.scene.pixpaint_texture_size
        min_x = floor(texture_size * self.x_min)
        min_y = floor(texture_size * self.y_min)

        # ensure no negative coords
        max_x_bound = ceil(texture_size * self.x_max)
        max_y_bound = ceil(texture_size * self.y_max)

        # FIND ISLANDS
        islands = get_islands_from_obj(obj, True)

        for island in islands:

            island.calc_pixel_bounds(texture_size)
            island_rect = island.pixel_bounds

            max_x = max(min_x, max_x_bound - island_rect.size.x)
            max_y = max(min_y, max_y_bound - island_rect.size.y)

            tx = (random.randint(min_x, max_x) - island_rect.min.x) / texture_size
            ty = (random.randint(min_y, max_y) - island_rect.min.y) / texture_size

            matrix_uv = Matrix.Translation(Vector((tx, ty, 0)))

            uvs_transform(island.get_faces(), uv_layer, matrix_uv)

        bmesh.update_edit_mesh(obj.data)
        return {"FINISHED"}
