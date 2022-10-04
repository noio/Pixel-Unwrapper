from collections import namedtuple
from dataclasses import dataclass
from math import ceil, floor

import bpy
import bmesh
from mathutils import Vector

from .texture import PixelArray, copy_texture_region
from .common import (
    RectInt,
    Vector2Int,
    any_pinned,
    find_image,
    uvs_rotate_90_degrees,
    uvs_translate_rotate_scale,
)
from .islands import (
    UVFaceSet,
    get_island_info,
    get_island_info_from_faces,
    merge_overlapping_islands,
)


@dataclass
class BoxPackingStrip:
    y: int
    height: int
    filled: int

    def fits_rect(self, rect, space_size):
        """
        What is a Level?
        (y, height, filled_width)
        Something fits if rect.h <= height AND rect.w <= space_size - filled_width
        """
        return rect[1] <= self.height and rect[0] < space_size - self.filled


def pack_rects(rect_sizes, initial_space_size=16):
    """
    rect_sizes is a list of rectangles with integer sizes

    FFDH packs the next item R (in non-increasing height) on the first level where R fits. If no level can accommodate R, a new level is created.
    Time complexity of FFDH: O(n·log n).
    Approximation ratio: FFDH(I)<=(17/10)·OPT(I)+1; the asymptotic bound of 17/10 is tight.
    """

    # Prefix indices so that we can refer to those later
    rects = enumerate(rect_sizes)
    # Sort the rectangles by height
    rects = sorted(rects, key=lambda p: p[1][1], reverse=True)

    output_positions = []
    levels = []
    space_size = initial_space_size

    while len(output_positions) < len(rects):
        # This starts a new iteration at a larger size
        output_positions = []
        levels = []
        for idx, rect in rects:
            level_where_fits = next(
                filter(lambda level: level.fits_rect(rect, space_size), levels), None
            )

            if level_where_fits is None:
                y = 0 if not levels else (levels[-1].y + levels[-1].height)
                height = rect[1]

                # If we ran out of space, increase the space size and start over
                # output_positions will not be filled, so the while loop runs again
                if (y + height) > space_size:
                    space_size *= 2
                    break

                level_where_fits = BoxPackingStrip(y, height, -1)
                levels.append(level_where_fits)

            # Add the rect to the level:
            output_positions.append(
                (idx, (level_where_fits.filled + 1, level_where_fits.y))
            )
            level_where_fits.filled += rect[0]

    output_positions = [pos for (idx, pos) in sorted(output_positions)]
    return output_positions, space_size


def find_free_space_for_island(
    target_island: UVFaceSet, all_islands: "list[UVFaceSet]", texture_size: int
):

    candidate_positions = [Vector2Int(0, 0)]

    rects = []
    for uv_island in all_islands:
        uv_island.calc_pixel_pos(texture_size)
        if uv_island != target_island:
            rects.append(uv_island.pixel_pos)
            candidate_positions.append(
                Vector2Int(uv_island.pixel_pos.max.x, uv_island.pixel_pos.min.y)
            )
            candidate_positions.append(
                Vector2Int(uv_island.pixel_pos.min.x, uv_island.pixel_pos.max.y)
            )

    candidate_positions.sort(key=lambda p: (p.y, p.x))

    # Try at the existing position first! No need to move islands if space is free
    candidate_positions.insert(0, target_island.pixel_pos.min)

    tex_min = Vector2Int(0, 0)
    tex_max = Vector2Int(texture_size, texture_size)
    tex_rect = RectInt(tex_min, tex_max)

    size = target_island.pixel_pos.size
    for p in candidate_positions:
        if tex_rect.contains(p, size):
            if not any(r.overlaps(p, size) for r in rects):
                return p

    # Fallback: Disregard texture size and put the island
    # outside the texture bounds if necessary
    for p in candidate_positions:
        if not any(r.overlaps(p, size) for r in rects):
            return p

    # fallback:
    return Vector2Int(0, 0)


class PIXPAINT_OT_selected_island_to_free_space(bpy.types.Operator):
    """Move the selected UV island to a free section on the UV map.
    This is based only on UV islands in the current mesh."""

    bl_idname = "view3d.pixpaint_selected_island_to_free_space"
    bl_label = "Selection to Free Space"
    bl_options = {"UNDO"}

    modify_texture: bpy.props.BoolProperty(default=False)
    selection_is_island: bpy.props.BoolProperty(default=True)
    ignore_unpinned_islands: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        obj = bpy.context.view_layer.objects.active
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        texture_size = context.scene.pixpaint_texture_size

        # FIND ISLANDS

        if self.selection_is_island:
            selected_faces = [face for face in bm.faces if face.select]
            other_faces = [face for face in bm.faces if not face.select]
            selected_islands = get_island_info_from_faces(bm, selected_faces, uv_layer)
            all_islands = get_island_info_from_faces(bm, other_faces, uv_layer)
        else:
            all_islands = get_island_info(obj, False)
            selected_islands = [
                isl for isl in all_islands if any(uvf.face.select for uvf in isl.faces)
            ]

        if self.ignore_unpinned_islands:
            all_islands = [isl for isl in all_islands if any_pinned((uvf.face for uvf in isl.faces), uv_layer)]

        modify_texture = self.modify_texture

        for island in selected_islands:
            island.calc_pixel_pos(texture_size)
            # old_pos = island.pixel_pos.min
            # h = island.pixel_pos.size.y / 2
            # pivot = Vector((old_pos.x + h, old_pos.y + h)) / texture_size
            # faces = (faceinfo.face for faceinfo in island.faces)
            # uvs_rotate_90_degrees(faces, uv_layer, pivot)

            # continue
            new_pos = find_free_space_for_island(island, all_islands, texture_size)
            old_pos = island.pixel_pos.min

            offset = (new_pos - old_pos) / texture_size

            faces = (faceinfo.face for faceinfo in island.faces)
            uvs_translate_rotate_scale(faces, uv_layer, translate=offset)

            if modify_texture:
                texture = find_image(obj)
                if texture:
                    copy_texture_region(
                        texture, old_pos, island.pixel_pos.size, new_pos
                    )

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

        texture = find_image(obj)
        if texture is not None:
            texture_size = texture.size[0]
        else:
            texture_size: int = context.scene.pixpaint_texture_size

        # FIND ISLANDS
        islands = get_island_info(obj, False)

        for island in islands:
            island.calc_pixel_pos(texture_size)

        islands = merge_overlapping_islands(islands)

        rects = []
        need_flip = []
        for uv_island in islands:
            rect_size = uv_island.pixel_pos.size

            # Flip all rectangles to lay flat (wider than they are high)
            if rect_size.y < rect_size.x:
                rect_size = Vector2Int(rect_size.y, rect_size.x)
                need_flip.append(True)
            else:
                need_flip.append(False)

            rects.append(rect_size)

        # Try one size smaller (but only if the texture can be divided by 2) 
        # and only if we're allowed to modify the texture
        try_size = texture_size // 2 if (self.modify_texture and texture_size % 2 == 0) else texture_size
        new_positions, new_size = pack_rects(rects, try_size)

        modify_texture = self.modify_texture and texture is not None

        if modify_texture:
            src_pixels = PixelArray(blender_image=texture)
            dst_pixels = PixelArray(size=new_size)

        scale = new_size / texture_size

        for (new_pos, island, flip) in zip(new_positions, islands, need_flip):
            new_pos = Vector2Int(new_pos[0], new_pos[1])
            old_pos = island.pixel_pos.min

            print(f"ISLAND\n{old_pos=} {texture_size=} {new_pos=} {new_size=}\n")
            offset = (old_pos * (scale - 1)) / new_size + (new_pos / new_size) - (old_pos / texture_size)

            faces = [faceinfo.face for faceinfo in island.faces]

            # Should the rectangular UV island be flipped?
            # We do this in a way that preserves the bottom left point
            # so that translation below can happen as usual,
            # regardless of whether the island was flipped
            # H is a point halfway the left side of the rect, which.. well draw it out yourself
            if flip:
                h = island.pixel_pos.size.y / 2
                pivot = Vector((old_pos.x + h, old_pos.y + h)) / texture_size
                uvs_rotate_90_degrees(faces, uv_layer, pivot)

            uvs_translate_rotate_scale(
                faces, uv_layer, scale=1 / scale, translate=offset
            )

            if modify_texture:
                dst_pixels.copy_region(
                    src_pixels, old_pos, island.pixel_pos.size, new_pos, flip
                )

        bmesh.update_edit_mesh(obj.data)

        if modify_texture:
            if new_size != texture_size:
                texture.scale(new_size, new_size)
                # texture.generated_width = texture.generated_height = new_size
                context.scene.pixpaint_texture_size = new_size
            texture.pixels = dst_pixels.pixels
            texture.update()

        # texture.save()
        return {"FINISHED"}
