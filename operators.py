import random
from itertools import chain
from math import cos, sin, pi

from .common import *
from .grids import Grid, GridBuildException, GridSnapModes
from .islands import *
from .packing import find_free_space_for_island, pack_rects
from .texture import PixelArray, copy_texture_region, copy_texture_region_transformed


def poll_edit_mode_selected_faces_uvsync(context):
    """Returns True if in edit mode, faces are selected, and UV sync is on."""
    obj = context.view_layer.objects.active
    if obj is None or obj.mode != "EDIT":
        return False

    if not context.scene.tool_settings.use_uv_select_sync:
        return False

    try:
        bm = bmesh.from_edit_mesh(obj.data)
        return any(face.select for face in bm.faces)
    except Exception:
        return False


class PIXUNWRAP_OT_create_texture(bpy.types.Operator):
    """Create and Link Texture for Selected Object"""

    bl_idname = "view3d.pixunwrap_create_texture"
    bl_label = "Create Texture"
    bl_options = {"UNDO"}

    texture_size: bpy.props.IntProperty(default=64)

    @classmethod
    def poll(cls, context):
        obj = context.view_layer.objects.active
        return obj is not None and get_first_texture_on_object(obj) is None

    def invoke(self, context, event):
        self.texture_size = context.scene.pixunwrap_default_texture_size
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        row = self.layout
        row.prop(self, "texture_size", text="Texture Size")

    def execute(self, context):
        obj = context.view_layer.objects.active

        #################################################
        # CREATE NEW TEXTURE AND FILL WITH DEFAULT GRID #
        #################################################
        new_texture = bpy.data.images.new(
            name=get_texture_name(obj.name),
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
            name = get_material_name(obj.name)
            mat = bpy.data.materials.new(name=name)
            obj.data.materials.append(mat)

        # Set up shader nodes
        mat.use_nodes = True
        image_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        image_node.image = new_texture
        image_node.interpolation = "Closest"

        bsdf_node = mat.node_tree.nodes["Principled BSDF"]
        mat.node_tree.links.new(image_node.outputs["Color"], bsdf_node.inputs["Base Color"])
        mat.node_tree.links.new(image_node.outputs["Alpha"], bsdf_node.inputs["Alpha"])

        location = bsdf_node.location.copy()
        location.x -= bsdf_node.width * 2
        image_node.location = location

        return {"FINISHED"}


class PIXUNWRAP_OT_duplicate_texture(bpy.types.Operator):
    """Duplicate Texture on Selected Object"""

    bl_idname = "view3d.pixunwrap_duplicate_texture"
    bl_label = "Duplicate Material & Texture"
    bl_options = {"UNDO"}

    new_name: bpy.props.StringProperty(name="New Name", default="new_name")

    @classmethod
    def poll(cls, context):
        obj = context.view_layer.objects.active
        return obj is not None and get_first_texture_on_object(obj) is not None

    def invoke(self, context, event):
        self.new_name = context.view_layer.objects.active.name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj = context.edit_object

        existing_texture = get_first_texture_on_object(obj)

        #####################
        # DUPLICATE TEXTURE #
        #####################
        new_texture_name = get_texture_name(self.new_name)
        new_path = f"//Textures/{new_texture_name}.png"

        # new_texture = existing_texture.save_as(False,True,filepath=new_path)
        new_texture = existing_texture.copy()
        new_texture.name = new_texture_name

        new_texture.pack()
        new_texture.filepath = new_path
        new_texture.filepath_raw = new_path  # dissociate from original linked image
        new_texture.save()
        new_texture.unpack(method="REMOVE")

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
        new_mat.name = get_material_name(self.new_name)

        for slot in obj.material_slots:
            if slot.material == existing_mat:
                slot.material = new_mat

        obj.active_material = new_mat

        # Replace in first found image node.
        for node in new_mat.node_tree.nodes:
            if node.type == "TEX_IMAGE":
                node.image = new_texture
                break

        return {"FINISHED"}


class PIXUNWRAP_OT_resize_texture(bpy.types.Operator):
    """Resize Texture on Selected Object"""

    bl_idname = "view3d.pixunwrap_resize_texture"
    bl_label = "Resize Texture"
    bl_options = {"UNDO"}

    scale: bpy.props.FloatProperty(default=2)
    only_update_uvs_on_active: bpy.props.BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        return poll_edit_mode_selected_faces_uvsync(context)

    def execute(self, context):
        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)

        selected_faces = [face for face in bm.faces if face.select]
        try:
            texture = get_texture_for_faces(obj, selected_faces)
            texture_size = texture.size[0] if texture is not None else context.scene.pixunwrap_default_texture_size
        except MultipleMaterialsError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        if texture is None:
            self.report({"ERROR"}, ERROR_NO_MATERIAL_OR_NO_TEXTURE)
            return {"CANCELLED"}

        material_index = selected_faces[0].material_index
        # Check if any face using this material is unselected
        if any(face.material_index == material_index and not face.select for face in bm.faces):
            self.report({"ERROR"}, ERROR_SELECT_ALL_FACES_USING_MATERIAL)
            return {"CANCELLED"}

        if texture.is_dirty:
            self.report({"ERROR"}, ERROR_TEXTURE_DIRTY)
            return {"CANCELLED"}

        new_size = round(texture_size * self.scale)

        if new_size < 16:
            self.report({"ERROR"}, "That's too small.")
            return {"CANCELLED"}

        if new_size > 8192:
            self.report({"ERROR"}, f"New texture would be {new_size} pixels, that's probably too big.")
            return {"CANCELLED"}

        # SCALE UP THE TEXTURE AND PRESERVE THE DATA
        # WHEN SCALING DOWN, TEXTURE IS CROPPED TO BOTTOM LEFT
        src_pixels = PixelArray(blender_image=texture)
        dst_pixels = PixelArray(size=new_size)

        copy_region_size = Vector2Int(dst_pixels.width, dst_pixels.height)
        dst_pixels.copy_region(src_pixels, Vector2Int(0, 0), copy_region_size, Vector2Int(0, 0))

        texture.scale(new_size, new_size)
        texture.pixels = dst_pixels.pixels
        texture.update()

        # UPDATE THE UVS TO SPAN THE SAME PIXELS
        # FIND ALL OBJECTS THAT USE THE SAME TEXTURE:
        # (if option enabled, otherwise just do it on active object)
        objs_to_update_uvs = [obj] if self.only_update_uvs_on_active else get_all_objects_with_texture(context, texture)

        actual_scale_inv = texture_size / new_size

        for obj_to_update in objs_to_update_uvs:
            bm = get_bmesh(obj_to_update)

            uv_layer = bm.loops.layers.uv.verify()
            uvs_scale(bm.faces, uv_layer, actual_scale_inv)

            update_and_free_bmesh(obj_to_update, bm)

        return {"FINISHED"}


class PIXUNWRAP_OT_transfer_texture(bpy.types.Operator):
    """Transfer texture from source UV map to current UV map"""

    bl_idname = "view3d.pixunwrap_transfer_texture"
    bl_label = "Transfer Texture"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            context.mode == "OBJECT"
            and context.active_object
            and context.active_object.type == "MESH"
            and len(context.active_object.data.uv_layers) >= 2
            and context.active_object.active_material
        )

    def execute(self, context):
        obj = context.active_object

        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Must be in Object mode")
            return {"CANCELLED"}

        # Get active UV map (target) and first non-active UV map (source)
        target_uv = obj.data.uv_layers.active
        source_uv = next(uv for uv in obj.data.uv_layers if uv != target_uv)

        # Find existing texture
        mat = obj.active_material
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        texture_node = None
        for node in nodes:
            if node.type == "TEX_IMAGE" and node.image:
                texture_node = node
                texture = node.image
                break

        if not texture_node:
            self.report({"ERROR"}, "No texture found in material")
            return {"CANCELLED"}

        # Create new image with same properties as existing
        bake_image = bpy.data.images.new(
            name=f"{texture.name}_new", width=texture.size[0], height=texture.size[1], alpha=True
        )

        # Store original active node
        original_active = nodes.active

        # Setup nodes for baking
        bake_node = nodes.new("ShaderNodeTexImage")
        bake_node.image = bake_image
        bake_node.interpolation = texture_node.interpolation
        bake_node.extension = texture_node.extension
        bake_node.projection = texture_node.projection
        bake_node.select = True
        nodes.active = bake_node

        # Create emission node for baking
        emit_node = nodes.new("ShaderNodeEmission")
        # Connect texture to emission
        links.new(texture_node.outputs[0], emit_node.inputs[0])

        # Store original output node and connection
        output_node = nodes.get("Material Output")
        if output_node:
            original_shader = None
            for link in output_node.inputs[0].links:
                original_shader = link.from_node
                break
            # Connect emission to output
            if original_shader:
                links.new(emit_node.outputs[0], output_node.inputs[0])

        # Setup UV maps for baking
        target_uv.active = True  # Set as active for node/editing
        source_uv.active_render = True  # Set as active for rendering/baking

        # Bake
        original_engine = context.scene.render.engine
        context.scene.render.engine = "CYCLES"
        bpy.ops.object.bake(type="EMIT")
        context.scene.render.engine = original_engine

        # Restore original material connections
        if output_node and original_shader:
            links.new(original_shader.outputs[0], output_node.inputs[0])

        # Cleanup temp nodes
        nodes.remove(bake_node)
        nodes.remove(emit_node)
        nodes.active = original_active

        # Rename and swap textures
        old_name = texture.name
        texture.name = f"{old_name}_old"
        bake_image.name = old_name

        # Update the original texture node to use new image
        texture_node.image = bake_image

        return {"FINISHED"}


class PIXUNWRAP_OT_swap_eraser(bpy.types.Operator):
    """Swap Eraser"""

    bl_idname = "view3d.pixunwrap_swap_eraser"
    bl_label = "Toggle Erase Alpha"
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.object.mode == "TEXTURE_PAINT"

    def execute(self, context):
        if not hasattr(self, "previous_blend"):
            self.previous_blend = "MIX"
        if bpy.context.tool_settings.image_paint.brush.blend != "ERASE_ALPHA":
            self.previous_blend = bpy.context.tool_settings.image_paint.brush.blend
            bpy.context.tool_settings.image_paint.brush.blend = "ERASE_ALPHA"
        else:
            bpy.context.tool_settings.image_paint.brush.blend = self.previous_blend

        return {"FINISHED"}


class PIXUNWRAP_OT_island_to_free_space(bpy.types.Operator):
    """Move the Selection to a free section on the UV map"""

    bl_idname = "view3d.pixunwrap_island_to_free_space"
    bl_label = "Selection to Free Space"
    bl_options = {"UNDO"}

    modify_texture: bpy.props.BoolProperty(default=False)

    # Should the entire UV island be moved, as opposed to just the
    # SELECTED part of the UV island
    move_entire_island: bpy.props.BoolProperty(default=False)

    # If True: only Islands with Pinned verts will count as occupied
    # (unpinned islands are considered free space)
    ignore_unpinned_islands: bpy.props.BoolProperty(default=True)

    # Should the Island stay in place if it's already in 'free space'
    # (or be moved to bottom left)
    prefer_current_position: bpy.props.BoolProperty(default=False)

    # Should OTHER objects' UV islands also be included (as occupied space)
    # if they use the same texture
    include_other_objects: bpy.props.BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        return poll_edit_mode_selected_faces_uvsync(context)

    def execute(self, context):
        obj = context.view_layer.objects.active

        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        # FIND ISLANDS

        if self.move_entire_island:
            all_islands = get_islands_from_obj(obj, False)
            selected_islands = [isl for isl in all_islands if any(uvf.face.select for uvf in isl.uv_faces)]
        else:
            selected_faces = [face for face in bm.faces if face.select]
            other_faces = [face for face in bm.faces if not face.select]
            selected_islands = get_islands_for_faces(bm, selected_faces, uv_layer)
            all_islands = get_islands_for_faces(bm, other_faces, uv_layer)

        # Now we need to make sure that all the islands we will act on (selected_islands)
        # share the same material index:
        used_faces = list(chain.from_iterable(island.get_faces() for island in selected_islands))

        try:
            texture = get_texture_for_faces(obj, used_faces)
            texture_size = texture.size[0] if texture is not None else context.scene.pixunwrap_default_texture_size
        except MultipleMaterialsError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        if texture is None:
            self.report({"ERROR"}, ERROR_NO_MATERIAL_OR_NO_TEXTURE)
            return {"CANCELLED"}

        selected_islands = merge_overlapping_islands(selected_islands)

        if self.include_other_objects and texture is not None:
            for other in get_all_objects_with_texture(context, texture):
                if other != obj:  # Exclude this
                    # print(f"Adding islands from {other}")
                    all_islands.extend(get_islands_from_obj(other, False))

        if self.ignore_unpinned_islands:
            all_islands = [isl for isl in all_islands if isl.is_any_pinned()]

        modify_texture = self.modify_texture

        for island in selected_islands:
            pixel_bounds_old = island.calc_pixel_bounds(texture_size)
            old_pos = pixel_bounds_old.min

            new_pos = find_free_space_for_island(island, all_islands, texture_size, self.prefer_current_position)

            # Do texture modification first because it could error + cancel the operator
            if texture is not None and modify_texture:
                if is_out_of_bounds(texture_size, new_pos, pixel_bounds_old.size):
                    self.report({"ERROR"}, ERROR_NO_TEXTURE_SPACE)
                    return {"CANCELLED"}

                if texture.is_dirty:
                    self.report({"ERROR"}, ERROR_TEXTURE_DIRTY)
                    return {"CANCELLED"}

                copy_texture_region(self.texture, old_pos, pixel_bounds_old.size, new_pos)

            offset = (new_pos - old_pos) / texture_size
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


class PIXUNWRAP_OT_repack_uvs(bpy.types.Operator):
    """Repack all UV islands in the editing mesh in a more efficient way"""

    bl_idname = "view3d.pixunwrap_repack_uvs"
    bl_label = "Repack All"
    bl_options = {"UNDO"}

    modify_texture: bpy.props.BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        return poll_edit_mode_selected_faces_uvsync(context)

    def execute(self, context):
        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        selected_faces = [face for face in bm.faces if face.select]
        try:
            texture = get_texture_for_faces(obj, selected_faces)
            texture_size = texture.size[0] if texture is not None else context.scene.pixunwrap_default_texture_size
        except MultipleMaterialsError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        if texture is None:
            self.report({"ERROR"}, ERROR_NO_MATERIAL_OR_NO_TEXTURE)
            return {"CANCELLED"}

        material_index = selected_faces[0].material_index
        # Check if any face using this material is unselected
        if any(face.material_index == material_index and not face.select for face in bm.faces):
            self.report({"ERROR"}, ERROR_SELECT_ALL_FACES_USING_MATERIAL)
            return {"CANCELLED"}

        if texture.is_dirty:
            self.report({"ERROR"}, ERROR_TEXTURE_DIRTY)
            return {"CANCELLED"}

        # FIND ISLANDS
        islands = get_islands_from_obj(obj, False)
        islands = merge_overlapping_islands(islands)

        sizes = []
        need_flip = []
        old_rects = []
        for uv_island in islands:
            pixel_bounds = uv_island.calc_pixel_bounds(texture_size)
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
        min_size = texture_size // 2 if (texture_size % 2 == 0) else texture_size
        new_positions, needed_size = pack_rects(sizes, min_size)

        modify_texture = self.modify_texture and texture is not None

        if modify_texture:
            if needed_size > texture_size:
                self.report({"ERROR"}, ERROR_NO_TEXTURE_SPACE)
                return {"CANCELLED"}

            if texture.is_dirty:
                self.report({"ERROR"}, ERROR_TEXTURE_DIRTY)
                return {"CANCELLED"}

            src_pixels = PixelArray(blender_image=self.texture)
            dst_pixels = PixelArray(size=self.texture_size)

        for new_pos, old_rect, island, flip in zip(new_positions, old_rects, islands, need_flip):
            new_pos = Vector2Int(new_pos[0], new_pos[1])

            old_pos = old_rect.min
            # print(f"ISLAND\n{old_pos=} {texture_size=} {new_pos=} {new_size=}\n")
            offset = new_pos - old_pos

            matrix = Matrix.Identity(3)
            matrix[0][2] = offset.x
            matrix[1][2] = offset.y

            faces = [face_info.face for face_info in island.uv_faces]

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

            matrix_uv = get_uv_space_matrix(matrix, texture_size)

            uvs_transform(faces, uv_layer, matrix_uv)

            if modify_texture:
                dst_pixels.copy_region_transformed(src_pixels, old_rect, matrix)

        bmesh.update_edit_mesh(obj.data)

        if modify_texture:
            self.texture.pixels = dst_pixels.pixels
            self.texture.update()

        # texture.save()
        return {"FINISHED"}


class PIXUNWRAP_OT_set_uv_texel_density(bpy.types.Operator):
    """Scale selected UV Islands to match the selected target density (Pixels Per Unit)"""

    bl_idname = "view3d.pixunwrap_set_uv_texel_density"
    bl_label = "Rescale Selection"
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context):
        return poll_edit_mode_selected_faces_uvsync(context)

    def execute(self, context):
        target_density = context.scene.pixunwrap_texel_density

        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        faces = [face for face in bm.faces if face.select]

        try:
            texture = get_texture_for_faces(obj, faces)
            texture_size = texture.size[0] if texture is not None else context.scene.pixunwrap_default_texture_size
        except MultipleMaterialsError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        (current_density, scale) = uvs_scale_texel_density(bm, faces, uv_layer, texture_size, target_density)
        self.report(
            {"INFO"}, f"Current: {current_density:.1f} PPU. Target: {target_density:.1f} PPU. Scale: {scale:.4f}"
        )

        bmesh.update_edit_mesh(obj.data)

        return {"FINISHED"}


class PIXUNWRAP_OT_unwrap_grid(bpy.types.Operator):
    """Unwrap Pixel Rect"""

    bl_idname = "view3d.pixunwrap_unwrap_grid"
    bl_label = "Grid Unwrap"
    bl_options = {"REGISTER", "UNDO"}

    snap: bpy.props.EnumProperty(name="Snap Vertices", items=GridSnapModes)

    @classmethod
    def poll(cls, context):
        return poll_edit_mode_selected_faces_uvsync(context)

    def execute(self, context):
        target_density = context.scene.pixunwrap_texel_density

        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        selected_faces = [face for face in bm.faces if face.select]

        for quad_group, connected_non_quads in zip(*find_quad_groups(selected_faces)):
            # print(
            #     f"UNWRAPPING QUAD ISLAND with {len(quad_group)} quads and {len(connected_non_quads)} attached non-quads"
            # )

            try:
                texture = get_texture_for_faces(obj, quad_group + connected_non_quads)
                texture_size = texture.size[0] if texture is not None else context.scene.pixunwrap_default_texture_size
            except MultipleMaterialsError as e:
                self.report({"ERROR"}, str(e))
                return {"CANCELLED"}

            for face in selected_faces:
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

            bpy.ops.view3d.pixunwrap_island_to_free_space(modify_texture=False)

        # Wrap things up: Reselect all faces (because we messed with selections)
        for face in selected_faces:
            face.select = True

        bmesh.update_edit_mesh(obj.data)

        return {"FINISHED"}


# class PIXUNWRAP_OT_unwrap_extend(TextureOperator, bpy.types.Operator):
#     """Standard Blender unwrap, preserves pinned UVs and snaps to pixels depending on setting"""
#
#     bl_idname = "view3d.pixunwrap_unwrap_extend"
#     bl_label = "Unwrap Extend"
#     bl_options = {"UNDO"}
#
#     def execute(self, context):
#         self.find_texture(context)
#
#         obj = context.edit_object
#         bm = bmesh.from_edit_mesh(obj.data)
#         uv_layer = bm.loops.layers.uv.verify()
#
#         bpy.ops.uv.unwrap(
#             method="ANGLE_BASED",
#             fill_holes=True,
#             correct_aspect=True,
#             use_subsurf_data=False,
#             margin=0.01,
#         )
#
#         selected_faces = list(face for face in bm.faces if face.select)
#
#         uvs_snap_to_texel_corner(
#             selected_faces, uv_layer, self.texture_size, skip_pinned=True
#         )
#         uvs_pin(selected_faces, uv_layer)
#
#         bmesh.update_edit_mesh(obj.data)
#
#         return {"FINISHED"}


class PIXUNWRAP_OT_unwrap_basic(bpy.types.Operator):
    """Standard blender unwrap, but scales to correct pixel density"""

    bl_idname = "view3d.pixunwrap_unwrap_basic"
    bl_label = "Basic Unwrap"
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context):
        return poll_edit_mode_selected_faces_uvsync(context)

    def execute(self, context):
        target_density = context.scene.pixunwrap_texel_density

        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        selected_faces = list(face for face in bm.faces if face.select)

        try:
            texture = get_texture_for_faces(obj, selected_faces)
            texture_size = texture.size[0] if texture is not None else context.scene.pixunwrap_default_texture_size
        except MultipleMaterialsError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        uvs_pin(selected_faces, uv_layer, False)

        bpy.ops.uv.unwrap(
            method="ANGLE_BASED",
            fill_holes=True,
            correct_aspect=True,
            use_subsurf_data=False,
            margin=0.01,
        )

        # Scale to texel density
        uvs_scale_texel_density(bm, selected_faces, uv_layer, texture_size, target_density)

        # Round the total size of the island to a whole number of pixels
        island = UVIsland(selected_faces, bm, uv_layer)
        size = island.max - island.min
        pixel_size = size * texture_size
        rounded_size = Vector((round(pixel_size.x), round(pixel_size.y))) / texture_size
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


class PIXUNWRAP_OT_unwrap_single_pixel(bpy.types.Operator):
    """Unwraps the selected faces to a single pixel, so they always
    have the same color when painting"""

    bl_idname = "view3d.pixunwrap_unwrap_single_pixel"
    bl_label = "Single Pixel (Fill)"
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context):
        return poll_edit_mode_selected_faces_uvsync(context)

    def execute(self, context):
        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        selected_faces = list(face for face in bm.faces if face.select)

        try:
            texture = get_texture_for_faces(obj, selected_faces)
            texture_size = texture.size[0] if texture is not None else context.scene.pixunwrap_default_texture_size
        except MultipleMaterialsError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

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
            f = floor(v * 4 / v_total) / 4.0
            # Start at 45 degrees
            a = pi * 2 * (f + 0.125)

            # Make the island ALMOST fill the texture pixel,
            # when moving with snapping on, this will actually snap
            # to pixel corners, so then we still need bleed on the texture, but eh.
            radius = sqrt(0.49)
            return Vector((radius * cos(a) + 0.5, radius * sin(a) + 0.5))

        for face in selected_faces:
            v_count = len(face.loops)
            for vert, loop in enumerate(face.loops):
                p = vert_pos(vert, v_count) * target_size
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


class PIXUNWRAP_OT_uv_flip(bpy.types.Operator):
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

    @classmethod
    def poll(cls, context):
        return poll_edit_mode_selected_faces_uvsync(context)

    def execute(self, context):
        obj = context.view_layer.objects.active
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        # FIND ISLANDS
        islands = get_islands_from_obj(obj, True)
        islands = merge_overlapping_islands(islands)

        for island in islands:
            try:
                texture = get_texture_for_faces(obj, island.get_faces())
                texture_size = texture.size[0] if texture is not None else context.scene.pixunwrap_default_texture_size
            except MultipleMaterialsError as e:
                self.report({"ERROR"}, str(e))
                return {"CANCELLED"}

            island_rect = island.calc_pixel_bounds(texture_size)

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

            if self.modify_texture and texture is not None:
                copy_texture_region_transformed(texture, island_rect, matrix)

        bmesh.update_edit_mesh(obj.data)
        return {"FINISHED"}


class PIXUNWRAP_OT_uv_rot_90(bpy.types.Operator):
    """Rotate UVs of Selection 90 degrees (CCW)"""

    bl_idname = "view3d.pixunwrap_uv_rot_90"
    bl_label = "Rotate UVs of Selection"
    bl_options = {"UNDO"}

    modify_texture: bpy.props.BoolProperty(default=False, name="Modify Texture")

    @classmethod
    def poll(cls, context):
        return poll_edit_mode_selected_faces_uvsync(context)

    def execute(self, context):
        bpy.ops.ed.undo_push()

        obj = context.view_layer.objects.active
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        # FIND ISLANDS
        islands = get_islands_from_obj(obj, True)
        islands = merge_overlapping_islands(islands)

        for island in islands:
            try:
                texture = get_texture_for_faces(obj, island.get_faces())
                texture_size = texture.size[0] if texture is not None else context.scene.pixunwrap_default_texture_size
            except MultipleMaterialsError as e:
                self.report({"ERROR"}, str(e))
                return {"CANCELLED"}

            texture_rect = RectInt(Vector2Int(0, 0), Vector2Int(texture_size, texture_size))

            island_rect = island.calc_pixel_bounds(texture_size)

            matrix = Matrix.Rotation(radians(90), 2).to_3x3()
            h = island_rect.size.y / 2
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
            old_pos = island_rect.min
            bpy.ops.view3d.pixunwrap_island_to_free_space(modify_texture=False, prefer_current_position=True)
            island.update_min_max()
            new_rect = island.calc_pixel_bounds(texture_size)
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


class PIXUNWRAP_OT_rectify(bpy.types.Operator):
    """Make selected UV islands more rectangular by snapping boundary vertices to their bounding rectangle"""

    bl_idname = "view3d.pixunwrap_rectify"
    bl_label = "Rectify"
    bl_options = {"UNDO"}

    deform_power: bpy.props.FloatProperty(default=4, name="Deform Power")

    @classmethod
    def poll(cls, context):
        return poll_edit_mode_selected_faces_uvsync(context)

    def execute(self, context):
        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        try:
            texture = get_texture_for_faces(obj, (face for face in bm.faces if face.select))
            texture_size = texture.size[0] if texture is not None else context.scene.pixunwrap_default_texture_size
        except MultipleMaterialsError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        islands = get_islands_from_obj(obj, only_selected=True)

        for island in islands:
            boundary_loops = island.get_boundary_loops()
            longest_loop = max(boundary_loops, key=calculate_loop_length)

            min_uv = Vector((round(island.min.x * texture_size), round(island.min.y * texture_size))) / texture_size
            max_uv = Vector((round(island.max.x * texture_size), round(island.max.y * texture_size))) / texture_size

            corner_uvs = [
                Vector((min_uv.x, min_uv.y)),  # bottom left
                Vector((max_uv.x, min_uv.y)),  # bottom right
                Vector((max_uv.x, max_uv.y)),  # top right
                Vector((min_uv.x, max_uv.y)),  # top left
            ]

            corner_points, corner_indices = find_corner_points(longest_loop, corner_uvs)
            # print(f"{[(v[0].index, v[1]) for v in corner_points]}")

            # Track all moved vertices and their movements
            moved_verts = {}  # vert -> (original_uv, new_uv)

            # print("MOVING CORNERS")

            # First move corners to their rectangle positions
            for i, (vert, original_uv) in enumerate(corner_points):
                new_uv = corner_uvs[i]
                moved_verts[vert] = (original_uv.copy(), new_uv)
                for loop in island.get_loops_for_vert(vert):
                    # print(f"moving corner vert v{vert.index} {original_uv} to {new_uv}")
                    loop[uv_layer].uv = new_uv

            # print("Moved Verts:")
            # for moved_vert, (before, after) in moved_verts.items():
            #     print(f"v{moved_vert.index} moved from {before} => {after}")

            # print("MOVING EDGES")
            # print(f"Full boundary: {[v.index for (v,_) in longest_loop]}")
            # Now handle points between corners
            # We need to process each edge of our rectangle
            for i in range(len(corner_indices)):
                start_idx = corner_indices[i]
                end_idx = corner_indices[(i + 1) % len(corner_indices)]

                # Get points between these corners (handling loop wraparound if needed)
                if end_idx < start_idx:
                    between_points = longest_loop[start_idx + 1 :] + longest_loop[0:end_idx]
                else:
                    between_points = longest_loop[start_idx + 1 : end_idx]

                # print(f"Aligning Edge Points {[v.index for (v,_) in between_points]}")

                # For each point between corners, snap to closest rectangle edge
                for vert, original_uv in between_points:
                    new_uv = get_nearest_point_on_rectangle(original_uv, min_uv, max_uv)
                    # print(f"moving edge vert v{vert.index} {original_uv} to {new_uv}")

                    for loop in island.get_loops_for_vert(vert):
                        moved_verts[vert] = (original_uv.copy(), new_uv)
                        loop[uv_layer].uv = new_uv

            # Now adjust all other vertices based on weighted influence
            for face in island.uv_faces:
                for loop in face.face.loops:
                    vert = loop.vert
                    if vert not in moved_verts:  # Only process unmoved vertices
                        current_uv = loop[uv_layer].uv
                        total_weight = 0
                        weighted_delta = Vector((0, 0))

                        # Calculate influence from all moved vertices
                        for moved_vert, (original_uv, new_uv) in moved_verts.items():
                            dist = (current_uv - original_uv).length
                            if dist < 0.0001:  # Avoid division by zero
                                dist = 0.0001

                            # Weight is inverse of distance squared
                            weight = 1.0 / (dist**self.deform_power)
                            delta = new_uv - original_uv

                            weighted_delta += delta * weight
                            total_weight += weight

                        if total_weight > 0:
                            # Apply weighted average of all movements
                            final_delta = weighted_delta / total_weight
                            loop[uv_layer].uv = current_uv + final_delta

        bmesh.update_edit_mesh(obj.data)
        return {"FINISHED"}


class PIXUNWRAP_OT_hotspot(bpy.types.Operator):
    """Map selected UV island onto a hotspot using the uv island bounds as a rectangle"""

    bl_idname = "view3d.pixunwrap_hotspot"
    bl_label = "Hotspot"
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context):
        return poll_edit_mode_selected_faces_uvsync(context)

    def execute(self, context):
        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()
        selected_faces = [face for face in bm.faces if face.select]

        material_index = get_material_index_from_faces(selected_faces)
        if material_index is None:
            self.report({"ERROR"}, ERROR_MULTIPLE_MATERIALS)
            return {"CANCELLED"}
        texture = get_texture_from_material_index(obj, material_index)
        texture_size = texture.size[0] if texture is not None else context.scene.pixunwrap_default_texture_size

        # FIND THE HOTSPOT OBJECT
        if material_index >= len(obj.material_slots):
            self.report({"ERROR"}, "Selected faces have no material")
            return {"CANCELLED"}

        material = obj.material_slots[material_index].material
        material_name = material.name
        # Find any object that has "hotspots" in name and uses this material
        hotspot_obj = None
        for other_obj in bpy.data.objects:
            obj_material = other_obj.material_slots[0].material if other_obj.material_slots else None
            if "hotspots" in other_obj.name.lower() and obj_material == material:
                hotspot_obj = other_obj
                break

        if not hotspot_obj:
            self.report({"ERROR"}, f"No object found that uses {material_name} and has 'hotspots' in the name")
            return {"CANCELLED"}

        island = UVIsland(selected_faces, bm, uv_layer)
        island_size = island.max - island.min
        hotspot_bounds = self.get_hotspot_uv_bounds(hotspot_obj)

        best_bounds = []  # List of (position, size, flipped) tuples
        best_diff = float("inf")
        size_threshold = 1.0 / texture_size  # Threshold for "similar enough" sizes

        for position, size in hotspot_bounds:
            # Check both normal and transposed orientations
            sizes_to_check = [
                (size, False),  # Normal orientation
                (Vector((size.y, size.x)), True)  # Transposed
            ]

            for check_size, is_flipped in sizes_to_check:
                size_diff = (check_size - island_size).length
                # print(f"{island_size=} {check_size=} {size_diff=} {is_flipped=}")

                if size_diff < best_diff - size_threshold:
                    # Found much better match, clear list and start new
                    best_bounds = [(position, size, is_flipped)]
                    best_diff = size_diff
                elif abs(size_diff - best_diff) <= size_threshold:
                    # Similar enough to best, add to candidates
                    best_bounds.append((position, size, is_flipped))

        if best_bounds:
            print(f"picking from {len(best_bounds)}")
            # Pick random candidate
            position, size, is_flipped = random.choice(best_bounds)


            # Calculate centers
            island_center = island.min + island_size / 2
            hotspot_center = position + size / 2

            # Apply transformations in logical order
            # 1. Translate island center to origin
            to_origin = Matrix.Identity(3)
            to_origin[0][2] = -island_center.x  # X translation in 3rd column, 1st row
            to_origin[1][2] = -island_center.y  # Y translation in 3rd column, 2nd row
            matrix = to_origin

            # 3. Rotate (if needed)
            if is_flipped:
                matrix = Matrix.Rotation(radians(90), 3, 'Z') @ matrix
                island_size.x, island_size.y = island_size.y, island_size.x


            # Scale factors - same regardless of flipped state
            scale_x = size.x / island_size.x if island_size.x != 0 else 1
            scale_y = size.y / island_size.y if island_size.y != 0 else 1

            # 2. Scale
            matrix = Matrix.Scale(scale_x, 3, Vector((1, 0, 0))) @ matrix
            matrix = Matrix.Scale(scale_y, 3, Vector((0, 1, 0))) @ matrix

            # 4. Translate to hotspot center
            to_center = Matrix.Identity(3)
            to_center[0][2] = hotspot_center.x  # X translation in 3rd column, 1st row
            to_center[1][2] = hotspot_center.y  # Y translation in 3rd column, 2nd row
            matrix =  to_center @ matrix

            uvs_transform(island.get_faces(), uv_layer, matrix)

        bmesh.update_edit_mesh(obj.data)
        return {"FINISHED"}

        # min_uv = Vector((round(island.min.x * texture_size), round(island.min.y * texture_size))) / texture_size
        # max_uv = Vector((round(island.max.x * texture_size), round(island.max.y * texture_size))) / texture_size

    @staticmethod
    def get_hotspot_uv_bounds(obj):
        """Returns a list of (position, size) tuples for each face's UV bounds"""
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        bounds = []
        for face in bm.faces:
            uvs = [loop[uv_layer].uv for loop in face.loops]
            if not uvs:
                continue

            min_uv = Vector((min(uv.x for uv in uvs), min(uv.y for uv in uvs)))
            max_uv = Vector((max(uv.x for uv in uvs), max(uv.y for uv in uvs)))

            position = min_uv
            size = max_uv - min_uv
            bounds.append((position, size))

        bm.free()
        return bounds


class PIXUNWRAP_OT_stack_islands(bpy.types.Operator):
    """Move all selected islands to the position of the island containing the *active* face"""

    bl_idname = "view3d.pixunwrap_stack_islands"
    bl_label = "Stack Islands"
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context):
        return poll_edit_mode_selected_faces_uvsync(context)

    def execute(self, context):
        bpy.ops.ed.undo_push()

        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        active_face = bm.faces.active  # Get the active face

        if not active_face or not active_face.select:
            self.report({"ERROR"}, "No active face selected")
            return {"CANCELLED"}

        try:
            texture = get_texture_for_faces(obj, (face for face in bm.faces if face.select))
            texture_size = texture.size[0] if texture is not None else context.scene.pixunwrap_default_texture_size
        except MultipleMaterialsError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        # FIND ISLANDS
        islands = get_islands_from_obj(obj, True)

        if len(islands) > 1:
            # Find which island contains the active face
            active_island = next((island for island in islands if active_face in island.get_faces()), None)

            if not active_island:
                self.report({"ERROR"}, "Active face not found in UV islands")
                return {"CANCELLED"}

            island_rect = active_island.calc_pixel_bounds(texture_size)
            x = island_rect.min.x
            y = island_rect.min.y

            # Move all other islands to this position
            for other_island in islands:
                if other_island is not active_island:  # Skip the active island
                    other_island_rect = other_island.calc_pixel_bounds(texture_size)
                    tx = (x - other_island_rect.min.x) / texture_size
                    ty = (y - other_island_rect.min.y) / texture_size

                    matrix_uv = Matrix.Translation(Vector((tx, ty, 0)))
                    uvs_transform(other_island.get_faces(), uv_layer, matrix_uv)

        bmesh.update_edit_mesh(obj.data)
        return {"FINISHED"}


class PIXUNWRAP_OT_nudge_islands(bpy.types.Operator):
    """Move selected islands by the set number of pixels"""

    bl_idname = "view3d.pixunwrap_nudge_islands"
    bl_label = "Nudge Islands"
    bl_options = {"UNDO", "REGISTER"}

    move_x: bpy.props.IntProperty(name="Move X", default=1, min=-128, max=128)
    move_y: bpy.props.IntProperty(name="Move Y", default=0, min=-128, max=128)

    @classmethod
    def poll(cls, context):
        return poll_edit_mode_selected_faces_uvsync(context)

    def execute(self, context):
        bpy.ops.ed.undo_push()

        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        selected_faces = [face for face in bm.faces if face.select]
        try:
            texture = get_texture_for_faces(obj, selected_faces)
            texture_size = texture.size[0] if texture is not None else context.scene.pixunwrap_default_texture_size
        except MultipleMaterialsError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        tx = self.move_x / texture_size
        ty = self.move_y / texture_size

        matrix_uv = Matrix.Translation(Vector((tx, ty, 0)))

        uvs_transform(selected_faces, uv_layer, matrix_uv)

        bmesh.update_edit_mesh(obj.data)
        return {"FINISHED"}


class PIXUNWRAP_OT_randomize_islands(bpy.types.Operator):
    """Move the selected islands to random positions inside the UV bounds"""

    bl_idname = "view3d.pixunwrap_randomize_islands"
    bl_label = "Randomize Islands"
    bl_options = {"UNDO", "REGISTER"}

    x_min: bpy.props.FloatProperty(name="X Min", default=0, min=0, max=1)
    x_max: bpy.props.FloatProperty(name="X Max", default=1, min=0, max=1)
    y_min: bpy.props.FloatProperty(name="Y Min", default=0, min=0, max=1)
    y_max: bpy.props.FloatProperty(name="Y Max", default=1, min=0, max=1)

    @classmethod
    def poll(cls, context):
        return poll_edit_mode_selected_faces_uvsync(context)

    def execute(self, context):
        bpy.ops.ed.undo_push()

        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        selected_faces = [face for face in bm.faces if face.select]
        try:
            texture = get_texture_for_faces(obj, selected_faces)
            texture_size = texture.size[0] if texture is not None else context.scene.pixunwrap_default_texture_size
        except MultipleMaterialsError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        min_x = floor(texture_size * self.x_min)
        min_y = floor(texture_size * self.y_min)

        # ensure no negative coords
        max_x_bound = ceil(texture_size * self.x_max)
        max_y_bound = ceil(texture_size * self.y_max)

        # FIND ISLANDS
        islands = get_islands_from_obj(obj, True)

        for island in islands:
            island_rect = island.calc_pixel_bounds(texture_size)

            max_x = max(min_x, max_x_bound - island_rect.size.x)
            max_y = max(min_y, max_y_bound - island_rect.size.y)

            tx = (random.randint(min_x, max_x) - island_rect.min.x) / texture_size
            ty = (random.randint(min_y, max_y) - island_rect.min.y) / texture_size

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
        textures = get_all_textures_on_object(active_obj)
        textures = list(set(textures))

        objects_sharing_texture = []
        for tex in textures:
            for obj in context.view_layer.objects:
                if obj.type == "MESH":
                    obj_textures = get_all_textures_on_object(obj)
                    if tex in obj_textures:
                        objects_sharing_texture.append(obj)

        tex_names = ", ".join(tex.name for tex in textures)
        obj_names = ", ".join(ob.name for ob in objects_sharing_texture)
        self.report({"INFO"}, f"Used textures: [{tex_names}] Other objects: [{obj_names}]")

        return {"FINISHED"}
