from math import cos, fabs, sin, sqrt, pi

import bpy
import bmesh
from bpy.types import Menu
from bpy.props import EnumProperty, BoolProperty

from mathutils import Vector

from .islands import UVFaceSet, get_connected_components, get_island_info


from .common import (
    is_outer_edge_of_selection,
    uvs_pin,
    uvs_scale_texel_density,
    uvs_snap_to_texel_corner,
    uvs_translate_rotate_scale,
)

from .grids import Grid, GridBuildException


def find_quad_groups(faces):
    quad_faces = []
    non_quad_faces = []
    for face in faces:
        if len(face.edges) == 4:
            quad_faces.append(face)
        else:
            non_quad_faces.append(face)

    # Find contiguous groups of quads. Those can be made into grids
    # The stray non-quad faces around it will have to be dealt with differently
    quad_groups = get_connected_components(quad_faces, connected_faces)

    if len(quad_groups) > 1:
        connected_non_quads = find_closest_group(non_quad_faces, quad_groups)
    else:
        connected_non_quads = [non_quad_faces]

    return (quad_groups, connected_non_quads)


def connected_faces(face):
    for edge in face.edges:
        for other_face in edge.link_faces:
            if other_face != face:
                yield other_face


def find_closest_group(faces, groups):
    output = [list() for _ in range(len(groups))]
    for face in faces:
        print(f"==== Finding closest group for {face.index}")
        closest_dist = float("inf")
        closest = -1
        for i, group in enumerate(groups):
            for group_face in group:
                dist = (
                    face.calc_center_bounds() - group_face.calc_center_bounds()
                ).length_squared
                print(f"distance to {i}/{group_face.index} is {dist}")
                if dist < closest_dist:
                    closest_dist = dist
                    closest = i

        print(f"Closest distance was {closest_dist} for group {closest}")
        output[closest].append(face)
    return output


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
    bl_options = {"UNDO"}

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

            grid.straighten_uv(uv_layer, texture_size, target_density)

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

            bpy.ops.view3d.pixpaint_selected_island_to_free_space(modify_texture=False)

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

        uvs_scale_texel_density(
            bm, selected_faces, uv_layer, texture_size, target_density
        )

        # Center
        face_set = UVFaceSet(selected_faces, uv_layer)
        center = 0.5 * (face_set.max + face_set.min)
        offset = Vector((0.5, 0.5)) - center
        uvs_translate_rotate_scale(selected_faces, uv_layer, offset)

        uvs_snap_to_texel_corner(
            selected_faces, uv_layer, texture_size, skip_pinned=True
        )
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
            return Vector((0.5 * cos(a) + 0.5, 0.5 * sin(a) + 0.5))

        # for face in selected_faces:
        # islands = get_island_info(obj, True)

        for face in selected_faces:
            v_count = len(face.loops)
            for v, loop in enumerate(face.loops):
                p = vert_pos(v, v_count) * target_size
                loop[uv_layer].uv = p

        uvs_pin(selected_faces, uv_layer, True)

        bmesh.update_edit_mesh(obj.data)

        bpy.ops.view3d.pixpaint_selected_island_to_free_space(modify_texture=False)

        return {"FINISHED"}


class PIXPAINT_OT_uv_grid_fold(bpy.types.Operator):
    """Fold the selected UV grid"""

    bl_idname = "view3d.pixpaint_uv_grid_fold"
    bl_label = "Fold UV Grid"
    bl_options = {"UNDO"}

    x_sections: bpy.props.IntProperty(default=2)
    y_sections: bpy.props.IntProperty(default=1)
    alternate: bpy.props.BoolProperty(default=True)

    def execute(self, context):

        obj = bpy.context.view_layer.objects.active
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
