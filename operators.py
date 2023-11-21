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


class TextureOperator:
    
    can_preserve_texture = False
    
    preserve_texture: bpy.props.BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        obj = context.view_layer.objects.active
        return obj is not None and find_texture(obj) is not None

    def find_texture(self, context):
        self.texture = find_texture(context.view_layer.objects.active)
        self.texture_size = self.texture.size[0]

    def error_if_texture_dirty(self):
        if self.texture.is_dirty:
            self.report(
                {"ERROR"},
                f'Please save "{self.texture.name}" first, because undo doesn\'t work for textures.',
            )
            return True
        return False

    def error_if_out_of_bounds(self, pos: "Vector2Int", size: "Vector2Int"):
        max = pos + size
        if not (
            pos.x >= 0
            and max.x <= self.texture_size
            and pos.y >= 0
            and max.y <= self.texture_size
        ):
            self.report(
                {"ERROR"},
                f'Not enough space to preserve texture data. Resize texture or turn off "Modify Texture"',
            )
            return True
        return False

    def all_objects_with_texture(self, context) -> "list[bpy.types.Object]":
        objects = []
        for obj in context.view_layer.objects:
            if obj.type == "MESH":
                obj_textures = find_all_textures(obj)
                if self.texture in obj_textures:
                    objects.append(obj)
        return objects


class PIXUNWRAP_OT_create_texture(bpy.types.Operator):
    """Create and Link Texture for Selected Object"""

    bl_idname = "view3d.pixunwrap_create_texture"
    bl_label = "Create Texture"
    bl_options = {"UNDO"}

    texture_size: bpy.props.IntProperty(default=64)

    @classmethod
    def poll(cls, context):
        obj = context.view_layer.objects.active
        return find_texture(obj) is None
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        row = self.layout
        row.prop(self, "texture_size", text="Texture Size")

    def execute(self, context):
        obj = bpy.context.view_layer.objects.active

        #################################################
        # CREATE NEW TEXTURE AND FILL WITH DEFAULT GRID #
        #################################################
        new_texture = bpy.data.images.new(
            name=get_texture_name(obj),
            width=self.texture_size,
            height=self.texture_size,
            alpha=True,
        )

        pixels = PixelArray(None, self.texture_size)
        new_texture.pixels = pixels.pixels
    

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
            name = get_material_name(obj)
            mat = bpy.data.materials.new(name=name)
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
    
class PIXUNWRAP_OT_duplicate_texture(bpy.types.Operator):
    """Duplicate Texture on Selected Object"""

    bl_idname = "view3d.pixunwrap_duplicate_texture"
    bl_label = "duplicate Texture"
    bl_options = {"UNDO"}

    texture_size: bpy.props.IntProperty(default=64)

    @classmethod
    def poll(cls, context):
        obj = context.view_layer.objects.active
        return find_texture(obj) is not None

    def execute(self, context):
        obj = bpy.context.view_layer.objects.active

        existing_texture = find_texture(obj)

        #####################
        # DUPLICATE TEXTURE #
        #####################
        new_texture = existing_texture.copy()
        new_texture.name = get_texture_name(obj)

        new_path = existing_texture.filepath_raw.replace(existing_texture.name, new_texture.name)
    
        new_texture.pack()
        new_texture.filepath = new_path
        new_texture.filepath_raw = new_path # dissociate from original linked image

        ##############################
        # SET UV EDITOR TO NEW IMAGE #
        ##############################
        for area in bpy.context.screen.areas:
            if area.type == "IMAGE_EDITOR":
                area.spaces.active.image = new_texture

        ######################
        # DUPLICATE MATERIAL #
        ######################

        existing_mat = obj.active_material
        new_mat = existing_mat.copy()
        new_mat.name = get_material_name(obj)

        for slot in obj.material_slots:
            if slot.material == existing_mat:
                slot.material = new_mat
    
        obj.active_material = new_mat

        # Replace in first found image node.
        for node in new_mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE':
                node.image = new_texture
                break
        
        return {"FINISHED"}


class PIXUNWRAP_OT_resize_texture(TextureOperator, bpy.types.Operator):
    """Resize Texture on Selected Object"""

    bl_idname = "view3d.pixunwrap_resize_texture"
    bl_label = "Resize Texture"
    bl_options = {"UNDO"}

    scale: bpy.props.FloatProperty(default=2)
    only_update_uvs_on_active: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        active_obj = context.view_layer.objects.active
        self.find_texture(context)
        new_size = round(self.texture_size * self.scale)

        if self.error_if_texture_dirty():
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
        src_pixels = PixelArray(blender_image=self.texture)
        dst_pixels = PixelArray(size=new_size)

        copy_region_size = Vector2Int(dst_pixels.width, dst_pixels.height)
        dst_pixels.copy_region(
            src_pixels, Vector2Int(0, 0), copy_region_size, Vector2Int(0, 0)
        )

        self.texture.scale(new_size, new_size)
        self.texture.pixels = dst_pixels.pixels
        self.texture.update()

        # UPDATE THE UVS TO SPAN THE SAME PIXELS
        # FIND ALL OBJECTS THAT USE THE SAME TEXTURE:
        # (if option enabled, otherwise just do it on active object)
        objs_to_update_uvs = (
            [active_obj]
            if self.only_update_uvs_on_active
            else self.all_objects_with_texture(context)
        )

        actual_scale_inv = self.texture_size / new_size

        for obj_to_update in objs_to_update_uvs:
            bm = get_bmesh(obj_to_update)

            uv_layer = bm.loops.layers.uv.verify()
            uvs_scale(bm.faces, uv_layer, actual_scale_inv)

            update_and_free_bmesh(obj_to_update, bm)

        return {"FINISHED"}


class PIXUNWRAP_OT_swap_eraser(bpy.types.Operator):
    """Swap Eraser"""

    bl_idname = "view3d.pixunwrap_swap_eraser"
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


class PIXUNWRAP_OT_island_to_free_space(TextureOperator, bpy.types.Operator):
    """Move the Selection to a free section on the UV map"""

    bl_idname = "view3d.pixunwrap_island_to_free_space"
    bl_label = "Selection to Free Space"
    bl_options = {"UNDO"}

    modify_texture: bpy.props.BoolProperty(default=False)

    # Should the entire UV island be moved, as opposed to just the
    # SELECTED part of the UV island
    move_entire_island: bpy.props.BoolProperty(default=True)

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
        obj = context.view_layer.objects.active
        self.find_texture(context)

        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        # FIND ISLANDS

        if not self.move_entire_island:
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
            for other in self.all_objects_with_texture(context):
                if other != obj:  # Exclude this
                    # print(f"Adding islands from {other}")
                    all_islands.extend(get_islands_from_obj(other, False))

        if self.ignore_unpinned_islands:
            all_islands = [isl for isl in all_islands if isl.is_any_pinned()]

        modify_texture = self.modify_texture

        for island in selected_islands:
            pixel_bounds_old = island.calc_pixel_bounds(self.texture_size)
            old_pos = pixel_bounds_old.min

            new_pos = find_free_space_for_island(
                island, all_islands, self.texture_size, self.prefer_current_position
            )

            # Do texture modification first because it could error + cancel the operator
            if modify_texture:
                if self.error_if_out_of_bounds(new_pos, pixel_bounds_old.size):
                    return {"CANCELLED"}

                if self.error_if_texture_dirty():
                    return {"CANCELLED"}

                copy_texture_region(
                    self.texture, old_pos, pixel_bounds_old.size, new_pos
                )

            offset = (new_pos - old_pos) / self.texture_size
            faces = island.get_faces()
            uvs_translate_rotate_scale(faces, uv_layer, translate=offset)

            uvs_pin(island.get_faces(), uv_layer)

            island.update_min_max()

            # Append the moved island to all_islands,
            # so that it is taken into account (as occupied space)
            # when finding a place for the next island in this loop
            all_islands.append(island)

        bmesh.update_edit_mesh(obj.data)

        return {"FINISHED"}


class PIXUNWRAP_OT_repack_uvs(TextureOperator, bpy.types.Operator):
    """Repack all UV islands in the editing mesh in a more efficient way"""

    bl_idname = "view3d.pixunwrap_repack_uvs"
    bl_label = "Repack All"
    bl_options = {"UNDO"}

    modify_texture: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        obj = bpy.context.view_layer.objects.active

        self.find_texture(context)

        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

    
        # FIND ISLANDS
        islands = get_islands_from_obj(obj, False)
        islands = merge_overlapping_islands(islands)

        sizes = []
        need_flip = []
        old_rects = []
        for uv_island in islands:
            pixel_bounds = uv_island.calc_pixel_bounds(self.texture_size)
            rect_size = pixel_bounds.size

            locked = uv_island.is_any_orientation_locked()
            # Flip all rectangles to lay flat (wider than they are high)
            if not locked and rect_size.y > rect_size.x:
                rect_size = Vector2Int(rect_size.y, rect_size.x)
                need_flip.append(True)
            else:
                need_flip.append(False)

            old_rects.append(pixel_bounds)
            sizes.append(rect_size)

        # Try one size smaller (but only if the texture can be divided by 2)
        # and only if we're allowed to modify the texture
        min_size = self.texture_size // 2 if (self.texture_size % 2 == 0) else self.texture_size
        new_positions, needed_size = pack_rects(sizes, min_size)

        modify_texture = self.modify_texture and self.texture is not None

        if modify_texture:
            if self.error_if_out_of_bounds(Vector2Int(0,0), Vector2Int(needed_size, 1)):
                return {"CANCELLED"}
            
            if self.error_if_texture_dirty():
                return {"CANCELLED"}

            src_pixels = PixelArray(blender_image=self.texture)
            dst_pixels = PixelArray(size=self.texture_size)

        for new_pos, old_rect, island, flip in zip(
            new_positions, old_rects, islands, need_flip
        ):
            new_pos = Vector2Int(new_pos[0], new_pos[1])

            old_pos = old_rect.min
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
                h = old_rect.size.y / 2
                pivot = Vector((old_pos.x + h, old_pos.y + h))
                flip_matrix = Matrix.Rotation(radians(90), 2).to_3x3()
                matrix_pin_pivot(flip_matrix, pivot)
                matrix = matrix @ flip_matrix

            matrix_uv = get_uv_space_matrix(matrix, self.texture_size)

            uvs_transform(faces, uv_layer, matrix_uv)

            if modify_texture:
                dst_pixels.copy_region_transformed(src_pixels, old_rect, matrix)

        bmesh.update_edit_mesh(obj.data)

        if modify_texture:
            self.texture.pixels = dst_pixels.pixels
            self.texture.update()

        # texture.save()
        return {"FINISHED"}


class PIXUNWRAP_OT_set_uv_texel_density(TextureOperator, bpy.types.Operator):
    """Scale selected UV Islands to match the selected target density (Pixels Per Unit)"""

    bl_idname = "view3d.pixunwrap_set_uv_texel_density"
    bl_label = "Rescale Selection"
    bl_options = {"UNDO"}

    def execute(self, context):
        self.find_texture(context)


        print(f"Preserve texture: {self.preserve_texture=}")

        target_density = context.scene.pixunwrap_texel_density

        obj = bpy.context.view_layer.objects.active
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        faces = [face for face in bm.faces if face.select]

        (current_density, scale) = uvs_scale_texel_density(bm, faces, uv_layer, self.texture_size, target_density)
        self.report({'INFO'}, f"Current: {current_density:.1f} PPU. Target: {target_density:.1f} PPU. Scale: {scale:.4f}")

        bmesh.update_edit_mesh(obj.data)

        return {"FINISHED"}


class PIXUNWRAP_OT_unwrap_pixel_grid(TextureOperator, bpy.types.Operator):
    """Unwrap Pixel Rect"""

    bl_idname = "view3d.pixunwrap_unwrap_pixel_grid"
    bl_label = "Unwrap Grid"
    bl_options = {"REGISTER", "UNDO"}

    snap: bpy.props.EnumProperty(name="Snap Vertices", items=GridSnapModes)

    def execute(self, context):
        # bpy.ops.uv.select_split()
        self.find_texture(context)

        target_density = context.scene.pixunwrap_texel_density

        obj = bpy.context.view_layer.objects.active
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        all_target_faces = [face for face in bm.faces if face.select]

        for quad_group, connected_non_quads in zip(*find_quad_groups(all_target_faces)):
            # print(
            #     f"UNWRAPPING QUAD ISLAND with {len(quad_group)} quads and {len(connected_non_quads)} attached non-quads"
            # )

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

            grid.straighten_uv(uv_layer, self.snap, self.texture_size, target_density)

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

            bpy.ops.view3d.pixunwrap_island_to_free_space(modify_texture=False)

        # Wrap things up: Reselect all faces (because we messed with selections)
        for face in all_target_faces:
            face.select = True

        bmesh.update_edit_mesh(obj.data)

        return {"FINISHED"}


class PIXUNWRAP_OT_unwrap_extend(TextureOperator, bpy.types.Operator):
    """Standard Blender unwrap, preserves pinned UVs and snaps to pixels depending on setting"""

    bl_idname = "view3d.pixunwrap_unwrap_extend"
    bl_label = "Unwrap Extend"
    bl_options = {"UNDO"}

    def execute(self, context):
        self.find_texture(context)

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
            selected_faces, uv_layer, self.texture_size, skip_pinned=True
        )
        uvs_pin(selected_faces, uv_layer)

        bmesh.update_edit_mesh(obj.data)

        return {"FINISHED"}


class PIXUNWRAP_OT_unwrap_basic(TextureOperator, bpy.types.Operator):
    """Standard blender unwrap, but scales to correct pixel density"""

    bl_idname = "view3d.pixunwrap_unwrap_basic"
    bl_label = "Unwrap Basic"
    bl_options = {"UNDO"}

    def execute(self, context):
        self.find_texture(context)
        # bpy.ops.uv.select_split()

        target_density = context.scene.pixunwrap_texel_density

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
            bm, selected_faces, uv_layer, self.texture_size, target_density
        )

        # Round the total size of the island to a whole number of pixels
        island = UVIsland(selected_faces, bm, uv_layer)
        size = island.max - island.min
        pixel_size = size * self.texture_size
        rounded_size = Vector((round(pixel_size.x), round(pixel_size.y))) / self.texture_size
        scale = Vector((rounded_size.x / size.x, rounded_size.y / size.y))
        uvs_scale(selected_faces, uv_layer, scale)

        # Position it so that corners are on texel corners
        island = UVIsland(selected_faces, bm, uv_layer)
        center = 0.5 * (island.max + island.min)
        offset = rounded_size / 2 - center
        uvs_translate_rotate_scale(selected_faces, uv_layer, offset)

        bpy.ops.view3d.pixunwrap_island_to_free_space(modify_texture=False)

        uvs_pin(selected_faces, uv_layer)

        bmesh.update_edit_mesh(obj.data)

        return {"FINISHED"}


class PIXUNWRAP_OT_unwrap_single_pixel(TextureOperator, bpy.types.Operator):
    """Unwraps the selected faces to a single pixel, so they always
    have the same color when painting"""

    bl_idname = "view3d.pixunwrap_unwrap_single_pixel"
    bl_label = "Unwrap to Single Pixel"
    bl_options = {"UNDO"}

    def execute(self, context):
        self.find_texture(context)

        # bpy.ops.uv.select_split()

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

        target_size = 1.0 / self.texture_size

        def vert_pos(v, v_total):
            # a = pi * 2 * v / v_total
            
            f = floor(v * 4 / v_total) / 4.0
            print(f)
            # Start at 45 degrees
            a = pi * 2 * (f + .125)

            # Make the island ALMOST fill the texture pixel,
            # when moving with snapping on, this will actually snap
            # to pixel corners, so then we still need bleed on the texture, but eh.
            radius = sqrt(.49)
            return Vector((radius * cos(a) + 0.5, radius * sin(a) + 0.5))

        for face in selected_faces:
            v_count = len(face.loops)
            for v, loop in enumerate(face.loops):
                p = vert_pos(v, v_count) * target_size
                loop[uv_layer].uv = p

        uvs_pin(selected_faces, uv_layer, True)

        bmesh.update_edit_mesh(obj.data)

        bpy.ops.view3d.pixunwrap_island_to_free_space(modify_texture=False)

        return {"FINISHED"}


class PIXUNWRAP_OT_uv_grid_fold(bpy.types.Operator):
    """Fold the selected UV grid"""

    bl_idname = "view3d.pixunwrap_uv_grid_fold"
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


class PIXUNWRAP_OT_uv_flip(TextureOperator, bpy.types.Operator):
    """Flip the Selection"""

    bl_idname = "view3d.pixunwrap_uv_flip"
    bl_label = "Flip Selected UV"
    bl_options = {"UNDO"}

    FlipAxis = [
        ("X", "Flip X", "", 1),
        ("Y", "Flip Y", "", 2),
    ]

    flip_axis: bpy.props.EnumProperty(items=FlipAxis, name="Flip Axis")
    modify_texture: bpy.props.BoolProperty(default=False, name="Modify Texture")

    def execute(self, context):
        self.find_texture(context)
        obj = context.view_layer.objects.active
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        # FIND ISLANDS
        islands = get_islands_from_obj(obj, True)
        islands = merge_overlapping_islands(islands)

        texture = find_texture(obj)

        for island in islands:
            island_rect = island.calc_pixel_bounds(self.texture_size)

            # `matrix` is the matrix used for transforming texture pixels,
            # `matrix_uv` is the matrix used for transforming uv coords
            if self.flip_axis == "X":
                matrix = Matrix.Diagonal((-1, 1, 1))
                pivot = (island_rect.min + island_rect.max) / 2
            elif self.flip_axis == "Y":
                matrix = Matrix.Diagonal((1, -1, 1))
                pivot = (island_rect.min + island_rect.max) / 2

            matrix_pin_pivot(matrix, pivot)

            matrix_uv = get_uv_space_matrix(matrix, self.texture_size)

            uvs_transform(island.get_faces(), uv_layer, matrix_uv)

            if self.modify_texture:
                copy_texture_region_transformed(texture, island_rect, matrix)

        bmesh.update_edit_mesh(obj.data)
        return {"FINISHED"}


class PIXUNWRAP_OT_uv_rot_90(TextureOperator, bpy.types.Operator):
    """Rotate UVs of Selection 90 degrees (CCW)"""

    bl_idname = "view3d.pixunwrap_uv_rot_90"
    bl_label = "Rotate UVs of Selection"
    bl_options = {"UNDO"}

    modify_texture: bpy.props.BoolProperty(default=False, name="Modify Texture")

    def execute(self, context):
        bpy.ops.ed.undo_push()
        
        self.find_texture(context)

        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        texture_rect = RectInt(Vector2Int(0, 0), Vector2Int(self.texture_size, self.texture_size))

        # FIND ISLANDS
        islands = get_islands_from_obj(obj, True)
        islands = merge_overlapping_islands(islands)

        texture = find_texture(obj)

        for island in islands:
            island_rect = island.calc_pixel_bounds(self.texture_size)

            matrix = Matrix.Rotation(radians(90), 2).to_3x3()
            h = island_rect.size.y / 2
            pivot = Vector((island_rect.min.x + h, island_rect.min.y + h))

            matrix_pin_pivot(matrix, pivot)

            matrix_uv = get_uv_space_matrix(matrix, self.texture_size)
            uvs_transform(island.get_faces(), uv_layer, matrix_uv)

            # When rotating, the bounds change, so we need to find some
            # FREE SPACE on the texture to move the island to.
            # We do this AFTER already having rotated the UV's, so
            # free space is found for the rotated island.
            # but we do the TEXTURE modification afterwards, for the
            # entire transformation in one (rotate + move to free space)
            old_pos = island_rect.min
            bpy.ops.view3d.pixunwrap_island_to_free_space(modify_texture=False)
            island.update_min_max()
            new_rect = island.calc_pixel_bounds(self.texture_size)
            new_pos = new_rect.min

            offset = new_pos - old_pos
            matrix[0][2] += offset.x
            matrix[1][2] += offset.y

            if self.modify_texture and texture is not None:
                if not texture_rect.contains(new_rect.min, new_rect.size):
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


class PIXUNWRAP_OT_randomize_islands(TextureOperator, bpy.types.Operator):
    """Move the selected islands to random positions inside the UV bounds"""

    bl_idname = "view3d.pixunwrap_randomize_islands"
    bl_label = "Randomize Islands"
    bl_options = {"UNDO", "REGISTER"}

    x_min: bpy.props.FloatProperty(name="X Min", default=0, min=0, max=1)
    x_max: bpy.props.FloatProperty(name="X Max", default=1, min=0, max=1)
    y_min: bpy.props.FloatProperty(name="Y Min", default=0, min=0, max=1)
    y_max: bpy.props.FloatProperty(name="Y Max", default=1, min=0, max=1)

    def execute(self, context):
        bpy.ops.ed.undo_push()

        self.find_texture(context)

        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        
        min_x = floor(self.texture_size * self.x_min)
        min_y = floor(self.texture_size * self.y_min)

        # ensure no negative coords
        max_x_bound = ceil(self.texture_size * self.x_max)
        max_y_bound = ceil(self.texture_size * self.y_max)

        # FIND ISLANDS
        islands = get_islands_from_obj(obj, True)

        for island in islands:
            island_rect = island.calc_pixel_bounds(self.texture_size)

            max_x = max(min_x, max_x_bound - island_rect.size.x)
            max_y = max(min_y, max_y_bound - island_rect.size.y)

            tx = (random.randint(min_x, max_x) - island_rect.min.x) / self.texture_size
            ty = (random.randint(min_y, max_y) - island_rect.min.y) / self.texture_size

            matrix_uv = Matrix.Translation(Vector((tx, ty, 0)))

            uvs_transform(island.get_faces(), uv_layer, matrix_uv)

        bmesh.update_edit_mesh(obj.data)
        return {"FINISHED"}


class PIXUNWRAP_OT_object_info(bpy.types.Operator):
    """Show Selected Object's Texture Info"""

    bl_idname = "view3d.pixunwrap_object_info"
    bl_label = "Object Info"


    def execute(self, context):
        active_obj = context.view_layer.objects.active
        textures = find_all_textures(active_obj)
        textures = list(set(textures))

        objects_sharing_texture = []
        for tex in textures:
            for obj in context.view_layer.objects:
                if obj.type == "MESH":
                    obj_textures = find_all_textures(obj)
                    if tex in obj_textures:
                        objects_sharing_texture.append(obj)
            
        tex_names = ", ".join(tex.name for tex in textures)
        obj_names = ", ".join(ob.name for ob in objects_sharing_texture)
        self.report({"INFO"}, f"Used textures: [{tex_names}] Other objects: [{obj_names}]")


        return {"FINISHED"}

