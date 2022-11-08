from dataclasses import dataclass, field
from itertools import accumulate
from statistics import mean
from typing import Any, Sequence
from enum import Enum
from math import ceil


from mathutils import Vector, Matrix


from .common import (
    Vector2Int,
    get_loops_for_edge,
    uv_vert_between_edges,
    vert_between_edges,
)

GridSnapModes = [
    ("ALL", "All Vertices", "", 1),
    ("BOUNDS", "Bounds Only", "", 2),
    ("NONE", "None", "", 3),
]


class Direction(Enum):
    EAST = 0
    NORTH = 1
    WEST = 2
    SOUTH = 3

    def opposite(self):
        if self == Direction.NORTH:
            return Direction.SOUTH
        elif self == Direction.SOUTH:
            return Direction.NORTH
        elif self == Direction.EAST:
            return Direction.WEST
        elif self == Direction.WEST:
            return Direction.EAST

    def vector(self):
        """
        Return the direction as a unit vector
        pointing in that direction
        """
        return [
            Vector2Int(1, 0),  # EAST
            Vector2Int(0, 1),  # NORTH
            Vector2Int(-1, 0),  # WEST
            Vector2Int(0, -1),  # SOUTH
        ][self.value]

    def transform(self, matrix):
        """
        Transform this direction by the given matrix.
        A matrix with 1's and 0's can be used to
        flip (NORTH becomes SOUTH)
        or transpose (NORTH becomes EAST)
        this direction.
        """
        v = self.vector() * 1.0
        v = matrix.to_2x2() @ v
        if abs(v.x) > abs(v.y):
            if v.x > 0:
                return Direction.EAST
            else:
                return Direction.WEST
        else:
            if v.y > 0:
                return Direction.NORTH
            else:
                return Direction.SOUTH


@dataclass()
class GridFace:
    face: Any
    coord: Vector2Int
    edges: list = field(default_factory=list)

    def edge(self, dir: Direction):
        return self.edges[dir.value]

    def get_loops(self, dir: Direction):
        return get_loops_for_edge(self.face, self.edge(dir))

    def transform_coords(self, matrix):
        transformed = matrix @ Vector((self.coord.x, self.coord.y, 1))
        self.coord = Vector2Int(round(transformed.x), round(transformed.y))
        self.edges = [
            self.edge(Direction.EAST.transform(matrix)),
            self.edge(Direction.NORTH.transform(matrix)),
            self.edge(Direction.WEST.transform(matrix)),
            self.edge(Direction.SOUTH.transform(matrix)),
        ]

    def overlay_on(self, other: "GridFace", uv_layer, flip_x, flip_y):
        for loop_self, loop_other in zip(
            self.get_loops(Direction.WEST),
            other.get_loops(Direction.EAST if flip_x else Direction.WEST),
        ):
            loop_self[uv_layer].uv.x = loop_other[uv_layer].uv.x

        for loop_self, loop_other in zip(
            self.get_loops(Direction.EAST),
            other.get_loops(Direction.WEST if flip_x else Direction.EAST),
        ):
            loop_self[uv_layer].uv.x = loop_other[uv_layer].uv.x

        for loop_self, loop_other in zip(
            self.get_loops(Direction.SOUTH),
            other.get_loops(Direction.NORTH if flip_y else Direction.SOUTH),
        ):
            loop_self[uv_layer].uv.y = loop_other[uv_layer].uv.y

        for loop_self, loop_other in zip(
            self.get_loops(Direction.NORTH),
            other.get_loops(Direction.SOUTH if flip_y else Direction.NORTH),
        ):
            loop_self[uv_layer].uv.y = loop_other[uv_layer].uv.y

    def average_edge_dir(self, uv_layer):
        """
        The direction of the vector spanning the diagonal
        of this face (from south-west to north-east)
        This is useful to determine how the face is oriented
        on the UV map
        """
        ne = uv_vert_between_edges(
            self.face, self.edge(Direction.NORTH), self.edge(Direction.EAST)
        )
        sw = uv_vert_between_edges(
            self.face, self.edge(Direction.SOUTH), self.edge(Direction.WEST)
        )
        nw = uv_vert_between_edges(
            self.face, self.edge(Direction.NORTH), self.edge(Direction.WEST)
        )
        east_dir = ne[uv_layer].uv - nw[uv_layer].uv
        north_dir = nw[uv_layer].uv - sw[uv_layer].uv
        return north_dir, east_dir

    def __str__(self):
        n_ = self.edge(Direction.NORTH)
        e_ = self.edge(Direction.EAST)
        s_ = self.edge(Direction.SOUTH)
        w_ = self.edge(Direction.WEST)
        n = n_.index
        e = e_.index
        s = s_.index
        w = w_.index
        nw = vert_between_edges(n_, w_).index
        ne = vert_between_edges(n_, e_).index
        sw = vert_between_edges(s_, w_).index
        se = vert_between_edges(s_, e_).index
        f = self.face.index
        return f"""
{nw:3} -- {n:3} -- {ne:3}
  |             |
{w:3}    {f:3}    {e:3}
  |             |
{sw:3} -- {s:3} -- {se:3}
        """


class GridBuildException(Exception):
    ...


class Grid:
    """
    Represents a grid of quads, given a mesh with selection of quads,
    will index them according to their position on the grid, and
    compute some useful additional data
    """

    def __init__(self, bm, faces):
        """
        For a selection of faces in bm,
        see if they are quads laid out on a grid,
        and find the 'grid coordinates' for each face.
        This is helpful for later shaping UVs as a grid as well
        """

        # A dictionary of faces, indexed by their bface object
        self._faces = {face.index: None for face in faces}

        # Make sure all faces are quads
        if not all(len(face.edges) == 4 for face in faces):
            raise Exception("Selection contains non-quads")

        # For each quad, opposing edges must be on a single grid line
        # starting with active face, map each neighbor.
        # Put the active face on grid coord (0,0), but we can
        # normalize the grid later.
        # First edge of the active face, and call that "NORTH"
        startface = bm.faces.active
        if startface is None or startface not in faces:
            startface = next(face for face in faces)
        self._walk(startface, Vector2Int(0, 0), startface.edges[0], Direction.NORTH)

        # All selected faces should have been walked, otherwise it's a
        # non-contiguous selection
        if not all(gf is not None for gf in self._faces.values()):
            unreached_faces = [
                index for (index, face) in self._faces.items() if face is None
            ]
            raise GridBuildException(
                f"Grid should contain a connected set of quad faces. Faces {unreached_faces} couldn't be reached from Face {startface.index}"
            )

        min_coord = None
        max_coord = None
        for gridface in self._faces.values():
            if min_coord is None:
                min_coord = gridface.coord
            else:
                min_coord = Vector2Int(
                    min(min_coord.x, gridface.coord.x),
                    min(min_coord.y, gridface.coord.y),
                )
            if max_coord is None:
                max_coord = gridface.coord
            else:
                max_coord = Vector2Int(
                    max(max_coord.x, gridface.coord.x),
                    max(max_coord.y, gridface.coord.y),
                )

        for gridface in self._faces.values():
            gridface.coord -= min_coord

        self.size = max_coord - min_coord + 1

    def _walk(self, face, coord, incoming_edge, edge_dir: Direction):
        """
        Add the face to the grid, and walk the neighbors.
        Given which edge was used to get to this face, and which direction
        that was assumed to be in, we can walk the other edges
        and follow the same assumption (that the edges are N, E, S, W)
        """

        # All target faces have been initialized as keys with None values
        # So the dict MUST contain the face (as key) to indicate it should be included
        # and it MUST be None to indicate it has not yet been walked
        if face.index in self._faces and self._faces[face.index] is None:

            gridface = GridFace(face, coord)
            self._faces[face.index] = gridface

            idx = list(face.edges).index(incoming_edge)
            north_edge_idx = (idx - edge_dir.value) % 4
            for dir_idx in range(4):
                edge_idx = (north_edge_idx + dir_idx) % 4
                edge = face.edges[edge_idx]
                gridface.edges.append(edge)
                if not edge.seam:
                    for other_face in self.other_faces_on_edge(edge, face):
                        if other_face:
                            # print(f"f{other_face.index} {Direction(dir_idx)} of {face.index}")
                            # If we walk from the SOUTH edge, that's the NORTH edge
                            # of the face we're walking to. So use opposite()
                            self._walk(
                                other_face,
                                coord + Direction(dir_idx).vector(),
                                edge,
                                Direction(dir_idx).opposite(),
                            )

    def compute_row_column_sizes(self):
        # We call things horizontal and vertical edges here, but actually
        # we don't really know if they are that. The grid might be
        # arbitrarily flipped at this point, but it's just easier to pretend
        # they are horizontal and vertical.
        # Same goes for Rows/Columns

        column_sizes = [[] for _ in range(self.size.x)]
        row_sizes = [[] for _ in range(self.size.y)]

        # A bunch of ifs because the grid is sparse.
        # E.g. we can't just add all the 'left' edges of the faces at X = 0
        # because some rows might not have a face at X = 0
        for gridface in self.get_faces():
            e = gridface.edge(Direction.WEST)
            row_sizes[gridface.coord.y].append(e.calc_length())

            e = gridface.edge(Direction.EAST)
            row_sizes[gridface.coord.y].append(e.calc_length())

            e = gridface.edge(Direction.SOUTH)
            column_sizes[gridface.coord.x].append(e.calc_length())

            e = gridface.edge(Direction.NORTH)
            column_sizes[gridface.coord.x].append(e.calc_length())

        column_sizes = [mean(lengths) for lengths in column_sizes]
        row_sizes = [mean(lengths) for lengths in row_sizes]

        return column_sizes, row_sizes

    def straighten_uv(
        self, uv_layer, grid_snap_mode, texture_size=None, target_density=None
    ):

        column_sizes, row_sizes = self.compute_row_column_sizes()

        # If target density is passed, make sure each row/column
        # consists of a round number of texture pixels
        # Also make sure that each row/column gets AT LEAST one pixel
        if texture_size is not None and target_density is not None:
            if grid_snap_mode == "ALL":
                column_sizes = [
                    max(1, round(s * target_density)) / texture_size
                    for s in column_sizes
                ]
                row_sizes = [
                    max(1, round(s * target_density)) / texture_size for s in row_sizes
                ]
            else:
                width = sum(column_sizes)
                height = sum(row_sizes)
                if grid_snap_mode == "BOUNDS":
                    new_width = max(1, round(width * target_density)) / texture_size
                    new_height = max(1, round(height * target_density)) / texture_size
                else:
                    # GRID SNAP MODE 'NONE'
                    new_width = max(1, (width * target_density)) / texture_size
                    new_height = max(1, (height * target_density)) / texture_size

                column_sizes = [s * new_width / width for s in column_sizes]
                row_sizes = [s * new_height / height for s in row_sizes]
                print(f"w:{width} h{height} ROUNDED w:{new_width} h{new_height}")

        x_pos = [0] + list(accumulate(column_sizes))
        y_pos = [0] + list(accumulate(row_sizes))

        for gridface in self.get_faces():
            for loop in get_loops_for_edge(
                gridface.face, gridface.edge(Direction.WEST)
            ):
                loop[uv_layer].uv.x = x_pos[gridface.coord.x]

            for loop in get_loops_for_edge(
                gridface.face, gridface.edge(Direction.EAST)
            ):
                loop[uv_layer].uv.x = x_pos[gridface.coord.x + 1]

            for loop in get_loops_for_edge(
                gridface.face, gridface.edge(Direction.SOUTH)
            ):
                loop[uv_layer].uv.y = y_pos[gridface.coord.y]

            for loop in get_loops_for_edge(
                gridface.face, gridface.edge(Direction.NORTH)
            ):
                loop[uv_layer].uv.y = y_pos[gridface.coord.y + 1]

    def realign_to_uv_map(self, uv_layer):
        """
        Ensure that the directions (NORTH/EAST/SOUTH/WEST)
        ACTUALLY refer to those directions on the UV map.
        When initially creating a grid, it's just created from
        the mesh faces, so it doesn't really have an inherent
        direction.
        """
        north_avg = Vector((0, 0))
        east_avg = Vector((0, 0))
        for gridface in self.get_faces():
            north, east = gridface.average_edge_dir(uv_layer)
            north_avg += north
            east_avg += east

        matrix = Matrix.Identity(3)
        do_transform = False

        # TRANSPOSE
        if abs(north_avg.x) > abs(north_avg.y):
            print(f"TRANSPOSING: NORTH {north_avg} EAST {east_avg}")
            matrix @= Matrix([[0, 1, 0], [1, 0, 0], [0, 0, 1]])
            self.size = Vector2Int(self.size.y, self.size.x)
            north_avg = north_avg.yx
            east_avg = east_avg.yx
            do_transform = True

        # FLIP HORIZONTAL
        if east_avg.x < 0:
            print(f"FLIP HORIZONTAL: {east_avg}")
            matrix = Matrix([[-1, 0, self.size.x - 1], [0, 1, 0], [0, 0, 1]]) @ matrix
            do_transform = True

        # FLIP VERTICAL
        if north_avg.y < 0:
            print(f"FLIP VERTICAL: {north_avg}")
            matrix = Matrix([[1, 0, 0], [0, -1, self.size.y - 1], [0, 0, 1]]) @ matrix
            do_transform = True

        if do_transform:
            for face in self.get_faces():
                face.transform_coords(matrix)

    def fold(self, uv_layer, x_sections=2, y_sections=1, alternate=True):
        """
        Fold the grid's UV coordinates in a number of sections. Like folding a
        sheet of paper in half, or in three, etc.
        "Alternate" determines whether each section is folded "back" or
        whether the sections are simply overlaid on each other.

        Example, imagine folding the following UV grid into 3 sections along the
        X-Axis. The vertices X-coords are numbered here

        1   2   3   4   5   6   7
        ┌───┬───┬───┬───┬───┬───┐
        │   │   │   │   │   │   │
        └───┴───┴───┴───┴───┴───┘

        Alternate OFF: like cutting the strip in pieces
                       and stacking them on top of each other

        1───┬───3      1 ──► 3
        │   │   │─5    3 ──► 5
        └───┴───┘ │─7  5 ──► 7
          └───┴───┘ │
            └───┴───┘


        Alternate ON: like folding a sheet of paper

        1───┬───3      1 ──► 3
        │   │   │─3    5 ◄── 3   (this section is reversed)
        └───┴───┘ │─7  5 ──► 7
          └───┴───┘ │
            └───┴───┘
        """
        by_coord = {gridface.coord: gridface for (gridface) in self._faces.values()}

        section_width = ceil(self.size.x / x_sections)
        section_height = ceil(self.size.y / y_sections)
        for gridface in self._faces.values():

            x = gridface.coord.x
            col, tx = divmod(x, section_width)
            odd_col = col % 2 != 0
            if odd_col and alternate:
                tx = section_width - tx - 1

            y = gridface.coord.y
            row, ty = divmod(y, section_height)
            odd_row = row % 2 != 0
            if odd_row and alternate:
                ty = section_height - ty - 1

            target_coord = Vector2Int(tx, ty)
            if target_coord != gridface.coord:
                target_face = by_coord.get(target_coord)
                if target_face != None:
                    # print(gridface)
                    # print(f"Overlaying {gridface.coord} on {target_coord}")
                    gridface.overlay_on(
                        target_face,
                        uv_layer,
                        odd_col and alternate,
                        odd_row and alternate,
                    )

    def get_faces(self) -> "Sequence[GridFace]":
        return self._faces.values()

    @classmethod
    def other_faces_on_edge(cls, edge, face):
        """Return the other face that an edge is linked to"""
        return (f for f in edge.link_faces if f is not face)

    def __str__(self):
        cw = 6
        ch = 2
        ascii = ASCIICanvas(self.size.x * cw + 1, self.size.y * ch + 1)
        for face in self.get_faces():
            x = face.coord.x * cw
            y = (self.size.y - 1 - face.coord.y) * ch
            ascii.box(x, y, cw + 1, ch + 1)
            ascii.text(x + 2, y + 1, f"{face.face.index:3}")

        output = f"\n{self.size.x} x {self.size.y} GRID\n\n{ascii}"

        return output


class ASCIICanvas:
    """
    Draw ASCII art boxes for diagnosing purposes

    ┌ ┍ ┎ ┏ ┐ ┑ ┒ ┓ └ ┕ ┖ ┗ ┘ ┙ ┚ ┛
    ├ ┝ ┞ ┟ ┠ ┡ ┢ ┣ ┤ ┥ ┦ ┧ ┨ ┩ ┪ ┫ ┬ ┭ ┮ ┯ ┰ ┱ ┲ ┳ ┴ ┵ ┶ ┷ ┸ ┹ ┺ ┻ ┼ ┽ ┾ ┿ ╀ ╁ ╂ ╃ ╄ ╅ ╆ ╇ ╈ ╉ ╊ ╋

    ┌┐
    └┘
    │─
    ├┤┬┴
    ┼
    """

    # A 1-bit means the character has a line point that way
    #     S W E N
    # 0 b 1 0 0 1  = north and south line => │
    line_to_bits = {
        " ": 0b0000,
        "└": 0b0011,
        "┘": 0b0110,
        "┐": 0b1100,
        "┌": 0b1001,
        "│": 0b1010,
        "─": 0b0101,
        "├": 0b1011,
        "┤": 0b1110,
        "┬": 0b1101,
        "┴": 0b0111,
        "┼": 0b1111,
    }

    def __init__(self, width, height):
        self.table = [[" " for j in range(width)] for i in range(height)]
        self.bits_to_line = {b: l for l, b in self.line_to_bits.items()}

    @property
    def width(self):
        return len(self.table[0])

    @property
    def height(self):
        return len(self.table)

    def set(self, x, y, char):
        if x < 0 or y < 0:
            return
        self.ensure_size(x - 1, y - 1)
        char = char[0]
        self.table[y][x] = char

    def ensure_size(self, w, h):
        if w > self.width or h > self.height:
            self.resize(max(w, self.width), max(h, self.height))

    def resize(self, new_width, new_height):
        if new_height < self.height:
            self.table = self.table[new_height]
        elif new_height > self.height:
            for _ in range(new_height - self.height):
                self.table.append([" "] * self.width)

        if new_width < self.width:
            self.table = [row[:new_width] for row in self.table]
        elif new_width > self.width:
            add_width = new_width - self.width
            for row in self.table:
                row.extend([" "] * add_width)

    def text(self, x, y, text):
        for i, char in enumerate(text):
            self.set(x + i, y, char)

    def box(self, x, y, width, height):
        """
        Draw a box on the canvas
        """
        if width == 1 or height == 1:
            return
        self.add_border(x, y, "┌")
        self.add_border(x + width - 1, y, "┐")
        self.add_border(x, y + height - 1, "└")
        self.add_border(x + width - 1, y + height - 1, "┘")
        for y_ in [y, y + height - 1]:
            for x_ in range(x + 1, x + width - 1):
                self.add_border(x_, y_, "─")
        for x_ in [x, x + width - 1]:
            for y_ in range(y + 1, y + height - 1):
                self.add_border(x_, y_, "│")

    def add_border(self, x, y, to_add):
        """
        Add a border on top of an existing border,
        this will create characters like ├ ┤ ┬ ┴
        """
        self.ensure_size(x + 1, y + 1)
        to_add = to_add[0]
        cur = self.table[y][x]
        # If these are not addable lines, just overwrite
        if cur not in self.line_to_bits or to_add not in self.line_to_bits:
            self.set(x, y, to_add)

        bits = self.line_to_bits[cur] | self.line_to_bits[to_add]
        self.set(x, y, self.bits_to_line[bits])

    def __str__(self):
        return "\n".join("".join(row) for row in self.table)
