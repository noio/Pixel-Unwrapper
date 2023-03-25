from dataclasses import dataclass


from .common import (
    RectInt,
    Vector2Int,
)
from .islands import (
    UVIsland,
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
    target_island: UVIsland, 
    all_islands: "list[UVIsland]", 
    texture_size: int,
    prefer_current_position: bool
):

    candidate_positions = [Vector2Int(0, 0)]
    current_rect = target_island.calc_pixel_bounds(texture_size)

    rects = []
    for uv_island in all_islands:
        if uv_island != target_island:
            island_rect = uv_island.calc_pixel_bounds(texture_size)
            rects.append(island_rect)
            candidate_positions.append(
                Vector2Int(island_rect.max.x, island_rect.min.y)
            )
            candidate_positions.append(
                Vector2Int(island_rect.min.x, island_rect.max.y)
            )

    candidate_positions.sort(key=lambda p: (p.y, p.x))

    if prefer_current_position:
        # Try at the existing position first! No need to move islands if space is free
        candidate_positions.insert(0, current_rect.min)
    else:
        candidate_positions.append(current_rect.min)

    tex_min = Vector2Int(0, 0)
    tex_max = Vector2Int(texture_size, texture_size)
    tex_rect = RectInt(tex_min, tex_max)

    size = current_rect.size
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
