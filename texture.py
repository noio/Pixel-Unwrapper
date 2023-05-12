import bpy

from itertools import cycle, islice
from math import ceil, floor
from mathutils import Vector, Matrix

from .common import RectInt, Vector2Int



def copy_texture_region(texture, src_pos, size, dst_pos):
    src_pixels = PixelArray(blender_image=texture)
    dst_pixels = PixelArray(blender_image=texture)
    dst_pixels.copy_region(src_pixels, src_pos, size, dst_pos)
    texture.pixels = dst_pixels.pixels
    texture.update()

def copy_texture_region_transformed(texture, region:RectInt, transform:Matrix):
    src_pixels = PixelArray(blender_image=texture)
    dst_pixels = PixelArray(blender_image=texture)
    dst_pixels.copy_region_transformed(src_pixels, region, transform)
    texture.pixels = dst_pixels.pixels
    texture.update()


class PixelArray:    

    def __init__(self, blender_image=None, size: int = None):
        if blender_image is not None:
            self.width = blender_image.size[0]
            self.height = blender_image.size[1]
            self.pixels = list(blender_image.pixels[:])
            assert (
                len(self.pixels) == self.width * self.height * 4
            ), "Pixels array is not the right size"
        elif size is not None:
            col_tl = tuple(bpy.context.scene.pixunwrap_texture_fill_color_tl) + (1,)
            col_tr = tuple(bpy.context.scene.pixunwrap_texture_fill_color_tr) + (1,)
            col_bl = tuple(bpy.context.scene.pixunwrap_texture_fill_color_bl) + (1,)
            col_br = tuple(bpy.context.scene.pixunwrap_texture_fill_color_br) + (1,)
            self.width = self.height = size
            pixels = list()
            for i in range(size * size):
                row = i // size
                col = i % size
                left = (col % 16) < 8
                top = (row % 16) < 8
                light = (row + col) % 2 == 0
                if left:
                    if top:
                        col = col_tl
                    else:
                        col = col_bl
                else:
                    if top:
                        col = col_tr
                    else:
                        col = col_br

                if not light:
                    col = [c * 0.92 for c in col]
                    col[3] = 1 # Fix alpha (we don't want to multiply that one with .7)
                pixels.extend(col)

            self.pixels = pixels  # list(islice(cycle(row_a + row_b), size * size * 4))

    def get_pixel(self, x, y):
        # MODE = WRAP
        x = x % self.width
        y = y % self.height
        idx = (y * self.width + x) * 4
        # RETURN R G B A
        return tuple(self.pixels[idx : idx + 4])

    def set_pixel(self, x, y, pix):
        x = x % self.width
        y = y % self.height
        idx = (y * self.width + x) * 4
        assert(len(pix) == 4)
        self.pixels[idx:idx+4] = pix

    def copy_region(
        self,
        source: "PixelArray",
        src_pos: Vector2Int,
        size: Vector2Int,
        dst_pos: Vector2Int,
    ):
        """
        Copy a region of the source texture to this one.
        The source texture uses wrap mode repeat, so a larger area can be copied
        without error.
        """
        matrix = Matrix.Identity(3)
        offset = dst_pos - src_pos
        src_rect = RectInt(src_pos, src_pos + size)
        matrix[0][2]=offset.x
        matrix[1][2]=offset.y
        self.copy_region_transformed(source, src_rect, matrix)


    def copy_region_transformed(
        self,
        source: "PixelArray",
        src_rect: RectInt,
        transform: "Matrix",
    ):
        original_pixels_len = len(self.pixels)

        # Determine bounds of the destination area
        # Add a half because we really only want to copy from the centers
        # pixels, not all the way to the bounds of the area.
        half = Vector((.5, .5, 0))
        bl = Vector(src_rect.min).to_3d() + half
        bl.z = 1
        tr = Vector(src_rect.max).to_3d() - half
        tr.z = 1
        tl = Vector(((bl.x, tr.y))).to_3d()
        tl.z = 1
        br = Vector(((tr.x, bl.y))).to_3d()
        br.z = 1
        
        # Transform source corners to dest. corners
        bl = transform @ bl
        tr = transform @ tr
        tl = transform @ tl
        br = transform @ br

        # Find the destination bounds, and also clamp it to be within image size
        # This means we're not wrap-around-writing, out-of-bounds destination pixels
        # is just ignored.
        dst_min_x = max(0,floor(min(bl.x, br.x, tl.x, tr.x)))
        dst_min_y = max(0,floor(min(bl.y, br.y, tl.y, tr.y)))
        dst_max_x = min(self.width, ceil(max(bl.x, br.x, tl.x, tr.x)))
        dst_max_y = min(self.height, ceil(max(bl.y, br.y, tl.y, tr.y)))

        # print(f"X: {dst_min_x}-{dst_max_x} Y: {dst_min_y}-{dst_max_y}")

        # We need the inverse transform, cause we want to check
        # for each point in the dest-bounds if it falls within the
        # src-bounds (so we inverse transform it)
        inv_transform = transform.inverted()

        for y in range(dst_min_y, dst_max_y):
            for x in range(dst_min_x, dst_max_x):
                src_point = inv_transform @ Vector((x+.5, y+.5, 1))
                # Nearest neighbor interpolation: 
                pix = source.get_pixel(floor(src_point.x), floor(src_point.y))
                self.set_pixel(x, y, pix)

        # # DO SOME BOUNDS CHECKS CAUSE YOU KNOW
        # dst_max = dst_pos + size - 1
        # if dst_pos.x < 0 or dst_pos.y < 0 or dst_max.x >= source.width or dst_max.y > source.height:
        #     raise Exception(f"Copy region is out of bounds for destination (min: {dst_pos} max {dst_max})")

        # for y in range(size.y):
        #     for x in range(size.x):
        #         read_pos = src_pos.offset(x, y)
        #         if rotate_90_degrees:
        #             write_pos = dst_pos.offset(size.y - 1 - y, x)
        #         else:
        #             write_pos = dst_pos.offset(x, y)
        #         self.set_pixel(write_pos, *source.get_pixel(read_pos))

        assert (
            len(self.pixels) == original_pixels_len
        ), f"Pixel Array was resized (from {original_pixels_len} to {len(self.pixels)}). That's a NOPE"