from itertools import cycle, islice

from .common import Vector2Int


def copy_texture_region(texture, src_pos, size, dst_pos):
    src_pixels = PixelArray(blender_image=texture)
    dst_pixels = PixelArray(blender_image=texture)
    dst_pixels.copy_region(src_pixels, src_pos, size, dst_pos)
    texture.pixels = dst_pixels.pixels
    texture.update()


class PixelArray:
    PINK = [0.5, 0, 0.5, 1]
    PINK_ALT = [0.5, 0.2, 0.5, 1]

    def __init__(self, blender_image=None, size: int = None):
        if blender_image is not None:
            self.width = blender_image.size[0]
            self.height = blender_image.size[1]
            self.pixels = list(blender_image.pixels[:])
            assert (
                len(self.pixels) == self.width * self.height * 4
            ), "Pixels array is not the right size"
        elif size is not None:
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
                        col = [0.8, 0, 0, 1]  # RED
                    else:
                        col = [0.4, 0.4, 1, 1]  # BLUE
                else:
                    if top:
                        col = [0, 0.8, 0, 1]  # GREEN
                    else:
                        col = [1, 0.6, 0, 1]  # YELLOW

                if light:
                    pixels.extend(col)
                else:
                    pixels.extend((c * 0.7 for c in col))

            a = self.PINK + self.PINK_ALT
            b = self.PINK_ALT + self.PINK
            row_a = list(islice(cycle(a), size * 4))
            row_b = list(islice(cycle(b), size * 4))
            self.pixels = pixels  # list(islice(cycle(row_a + row_b), size * size * 4))

    def get_pixel(self, pos: Vector2Int):
        # MODE = WRAP
        x = pos.x % self.width
        y = pos.y % self.height
        idx = (y * self.width + x) * 4
        # RETURN R G B A
        return tuple(self.pixels[idx : idx + 4])

    def set_pixel(self, pos: Vector2Int, r, g, b, a):
        x = pos.x % self.width
        y = pos.y % self.height
        idx = (y * self.width + x) * 4
        self.pixels[idx] = r
        self.pixels[idx + 1] = g
        self.pixels[idx + 2] = b
        self.pixels[idx + 3] = a

    def copy_region(
        self,
        source: "PixelArray",
        src_pos: Vector2Int,
        size: Vector2Int,
        dst_pos: Vector2Int,
        rotate_90_degrees=False,
    ):
        # print(
        #     f"""
        #     COPY REGION {src_x, src_y, region_width, region_height} from {source_image.width}x{source_image.height} img
        #     to {dst_x, dst_y} in {self.width}x{self.height} img
        #     """
        # )
        original_pixels_len = len(self.pixels)

        for y in range(size.y):
            for x in range(size.x):
                read_pos = src_pos.offset(x, y)
                if rotate_90_degrees:
                    write_pos = dst_pos.offset(size.y - 1 - y, x)
                else:
                    write_pos = dst_pos.offset(x, y)
                self.set_pixel(write_pos, *source.get_pixel(read_pos))

        # # Crop the region to the maximum viable area
        # out_of_bounds_x = min(0, src_x, dst_x)
        # out_of_bounds_y = min(0, src_y, dst_y)
        # src_x -= out_of_bounds_x
        # src_y -= out_of_bounds_y
        # dst_x -= out_of_bounds_x
        # dst_y -= out_of_bounds_y
        # region_width += out_of_bounds_x
        # region_height += out_of_bounds_y

        # out_of_bounds_x = max(
        #     0,
        #     src_x + region_width - source.width,
        #     dst_x + region_width - self.width,
        # )
        # out_of_bounds_y = max(
        #     0,
        #     src_y + region_height - source.height,
        #     dst_y + region_height - self.height,
        # )

        # region_width -= out_of_bounds_x
        # region_height -= out_of_bounds_y

        # for y in range(region_height):
        #     src_line_y = y + src_y
        #     src_idx_start = (src_line_y * source.width + src_x) * 4
        #     src_idx_end = (src_line_y * source.width + src_x + region_width) * 4
        #     dst_line_y = y + dst_y
        #     dst_idx_start = (dst_line_y * self.width + dst_x) * 4
        #     dst_idx_end = (dst_line_y * self.width + dst_x + region_width) * 4

        #     # print(
        #     #     f"COPY LINE: {src_x, src_line_y} to {dst_x, dst_line_y} W: {region_width} IDX: {src_idx_start, src_idx_end} to {dst_idx_start, dst_idx_end}"
        #     # )
        #     assert dst_idx_end - dst_idx_start == src_idx_end - src_idx_start

        #     srcpix = source.pixels[src_idx_start:src_idx_end]
        #     self.pixels[dst_idx_start:dst_idx_end] = srcpix

        assert (
            len(self.pixels) == original_pixels_len
        ), f"Pixel Array was resized (from {original_pixels_len} to {len(self.pixels)}). That's a NOPE"
