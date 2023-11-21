import os, sys, unicodedata

from math import fabs, sqrt, radians

from dataclasses import dataclass

import bmesh
from bmesh.types import BMFace, BMEdge, BMesh
from mathutils import Vector, Matrix


@dataclass(frozen=True)
class Vector2Int:
    x: int
    y: int

    def offset(self, x, y):
        return Vector2Int(self.x + x, self.y + y)

    def copy(self):
        return Vector2Int(self.x, self.y)

    def __getitem__(self, key):
        if key == 0:
            return self.x
        if key == 1:
            return self.y
        raise IndexError(f"{key} is not a valid subscript for Vector2Int")

    def __add__(self, other):
        if isinstance(other, int):
            return Vector2Int(self.x + other, self.y + other)
        return Vector2Int(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        if isinstance(other, int):
            return Vector2Int(self.x - other, self.y - other)
        return Vector2Int(self.x - other.x, self.y - other.y)

    def __neg__(self):
        return Vector2Int(-self.x, -self.y)

    def __truediv__(self, other):
        return Vector((self.x / other, self.y / other))

    def __mul__(self, other):
        return Vector((self.x * other, self.y * other))

    def __rmul__(self, other):
        return Vector((other * self.x, other * self.y))

    def __str__(self) -> str:
        return f"({self.x}, {self.y})"

    def __hash__(self):
        return hash((self.x, self.y))

    def __eq__(self, other):
        return self.x == other.x and self.y == other.y


@dataclass
class RectInt:
    min: Vector2Int
    max: Vector2Int

    @property
    def size(self):
        return self.max - self.min

    def overlaps(self, other_min, other_size):
        other_max = other_min + other_size
        return not (
            other_min.x >= self.max.x
            or self.min.x >= other_max.x
            or other_min.y >= self.max.y
            or self.min.y >= other_max.y
        )

    def contains(self, other_min, other_size):
        other_max = other_min + other_size
        return (
            other_min.x >= self.min.x
            and other_max.x <= self.max.x
            and other_min.y >= self.min.y
            and other_max.y <= self.max.y
        )

    def encapsulate(self, other: "RectInt"):
        self.min = Vector2Int(
            min(self.min.x, other.min.x), min(self.min.y, other.min.y)
        )
        self.max = Vector2Int(
            max(self.max.x, other.max.x), max(self.max.y, other.max.y)
        )


def elem_min(a, b):
    elems = [min(pair) for pair in zip(a, b)]
    return Vector(elems)


def elem_max(a, b):
    elems = [max(pair) for pair in zip(a, b)]
    return Vector(elems)


def flatten(t):
    return [item for sublist in t for item in sublist]


def measure_all_faces_uv_area(bm, uv_layer):
    """From MagicUV"""
    triangle_loops = bm.calc_loop_triangles()

    areas = {face: 0.0 for face in bm.faces}

    for loops in triangle_loops:
        face = loops[0].face
        area = areas[face]
        area += calc_tris_2d_area([l[uv_layer].uv for l in loops])
        areas[face] = area

    return areas


def calc_tris_2d_area(points):
    """From MagicUV"""
    area = 0.0
    for i, p1 in enumerate(points):
        p2 = points[(i + 1) % len(points)]
        v1 = p1 - points[0]
        v2 = p2 - points[0]
        a = v1.x * v2.y - v1.y * v2.x
        area = area + a

    return fabs(0.5 * area)


def vert_between_edges(edge_a, edge_b):
    if edge_a.verts[0] in edge_b.verts:
        return edge_a.verts[0]
    elif edge_a.verts[1] in edge_b.verts:
        return edge_a.verts[1]

def get_uv_space_matrix(matrix: Matrix, texture_size):
    scale_up = Matrix.Scale(texture_size, 3)
    scale_up[2][2] = 1
    scale_down = Matrix.Scale(1.0/texture_size, 3)
    scale_down[2][2] = 1
    return scale_down @ matrix @ scale_up

def matrix_pin_pivot(matrix: Matrix, pivot: Vector):
    pivot = pivot.to_3d()
    pivot.z = 1  # Make Homogeneous Vector
    transformed_pivot = matrix @ pivot
    pivot_offset = pivot - transformed_pivot

    matrix[0][2] += pivot_offset[0]
    matrix[1][2] += pivot_offset[1]


def uv_vert_between_edges(face: BMFace, edge_a, edge_b):
    for loop in face.loops:
        if edge_b in loop.vert.link_edges and edge_a in loop.vert.link_edges:
            return loop


def get_loops_for_edge(face: BMFace, edge: BMEdge):
    vert_idx_a = edge.verts[0]
    vert_idx_b = edge.verts[1]
    for loop in face.loops:
        if loop.vert == vert_idx_a or loop.vert == vert_idx_b:
            yield loop


def uvs_rotate_90_degrees(faces, uv_layer, pivot: Vector):
    transformed_pivot = Vector((-pivot.y, pivot.x))
    offset = pivot - transformed_pivot
    uvs_translate_rotate_scale(faces, uv_layer, offset, radians(90))


def uvs_translate_rotate_scale(
    faces,
    uv_layer,
    translate=Vector((0, 0)),
    rotate: float = 0,
    scale: float = 1,
):
    """
    Translate, rotate, and scale all UVs in the given faces.
    Translation is performed LAST.
    Rotation is in RADIANS.
    """
    matrix = (Matrix.Rotation(rotate, 2) * scale).to_3x3()
    matrix[0][2] = translate.x
    matrix[1][2] = translate.y
    uvs_transform(faces, uv_layer, matrix)


def uvs_transform(
    faces,
    uv_layer,
    transformation=Matrix
):
    """
    Transform all UV coordsin the given faces using the given matrix
    """
    for face in faces:
        for loop_uv in face.loops:
            uv = loop_uv[uv_layer].uv
            uv = uv.to_3d()
            uv.z = 1
            transformed = (transformation @ uv)
            transformed /= transformed.z
            loop_uv[uv_layer].uv = transformed.xy

def uvs_scale(
    faces,
    uv_layer,
    scale: Vector
    ):
    for face in faces:
        for loop_uv in face.loops:
            uv = loop_uv[uv_layer].uv
            loop_uv[uv_layer].uv = scale * uv


def uvs_snap_to_texel_corner(faces, uv_layer, texture_size, skip_pinned=False):
    for face in faces:
        for loop_uv in face.loops:
            if not (skip_pinned and loop_uv[uv_layer].pin_uv):
                uv = loop_uv[uv_layer].uv
                uv.x = round(uv.x * texture_size) / texture_size
                uv.y = round(uv.y * texture_size) / texture_size


def uvs_scale_texel_density(bm, faces, uv_layer, texture_size, target_density):
    mesh_face_area = sum(face.calc_area() for face in faces)

    uv_face_areas = measure_all_faces_uv_area(bm, uv_layer)
    uv_face_area = sum(uv_face_areas[face] for face in faces)
    uv_face_area *= texture_size * texture_size

    current_density = sqrt(uv_face_area) / sqrt(mesh_face_area)
    scale = target_density / current_density
    uvs_translate_rotate_scale(faces, uv_layer, scale=scale)
    return (current_density, scale)


def uvs_pin(faces, uv_layer, pin=True):
    for face in faces:
        for loop_uv in face.loops:
            loop_uv[uv_layer].pin_uv = pin


def any_pinned(faces, uv_layer):
    for face in faces:
        for loop_uv in face.loops:
            if loop_uv[uv_layer].pin_uv:
                return True
    return False

def lock_orientation(mesh, face_indices, is_locked):
    lock_layer = mesh.faces.layers.int.get('orientation_locked')
    if (lock_layer is None):
        lock_layer = mesh.faces.layers.int.new('orientation_locked')
        
    # THIS IS BAD BECAUSE IT LOCKS ALL FACES IN WHOLE MESH NOT JUST IN ISLAND
    for face_index in face_indices:
        face = mesh.faces[face_index]
        face[lock_layer] = 1 if is_locked else 0
    # print([face[lock_layer] for face in self.mesh.faces])

def is_outer_edge_of_selection(edge):
    return (
        len(list(edge_face for edge_face in edge.link_faces if edge_face.select)) <= 1
    )

def get_bmesh(obj) -> "BMesh":
    """
    Get a BMesh from the given object, will use either
    `bmesh.from_edit_mesh` or `from_mesh`, depending on 
    whether object is in Edit mode
    """
    if obj.data.is_editmode:
        bm = bmesh.from_edit_mesh(obj.data)
    else:
        bm = bmesh.new()
        bm.from_mesh(obj.data)
    return bm

def update_and_free_bmesh(obj, bm:"BMesh"):
    """
    updates mesh data on the given object. 
    """
    if obj.data.is_editmode:
        bmesh.update_edit_mesh(obj.data)
    else:
        bm.to_mesh(obj.data)
        bm.free()


def find_texture(obj, face=None, tex_layer=None):
    """From MagicUV"""
    images = find_all_textures(obj, face, tex_layer)
    images = list(set(images))

    # if len(images) >= 2:
        # raise RuntimeError(f"{obj} uses two or more materials.")
    if not images:
        return None

    return images[0]


def find_all_textures(obj, face=None, tex_layer=None):
    """From MagicUV"""

    # Try to find from texture_layer
    if tex_layer and face:
        if face[tex_layer].image is not None:
            # Return list with one element
            return [face[tex_layer].image]

    # Not found, search through Shader nodes:
    images = []

    for slot in obj.material_slots:
        if slot.material:
            for node in slot.material.node_tree.nodes:
                if node.type in ["TEX_ENVIRONMENT", "TEX_IMAGE"]:
                    if node.image:
                        images.append(node.image)

    return images


def dump(obj):
    for attr in dir(obj):
        if hasattr(obj, attr):
            print("obj.%s = %r" % (attr, getattr(obj, attr)))


def get_path_true_case(path):  # IMPORTANT: <path> must be a Unicode string
    """from: https://stackoverflow.com/questions/14515073/in-python-on-osx-with-hfs-how-can-i-get-the-correct-case-of-an-existing-filenam"""
    if not os.path.lexists(path):  # use lexists to also find broken symlinks
        raise OSError(2, "No such file or directory", path)
    isosx = sys.platform == "darwin"
    if isosx:  # convert to NFD for comparison with os.listdir() results
        path = unicodedata.normalize("NFD", path)
    parentpath, leaf = os.path.split(path)
    # find true case of leaf component
    if leaf not in [".", ".."]:  # skip . and .. components
        leaf_lower = leaf.lower()  # if you use Py3.3+: change .lower() to .casefold()
        found = False
        for leaf in os.listdir("." if parentpath == "" else parentpath):
            if leaf_lower == leaf.lower():  # see .casefold() comment above
                found = True
                if isosx:
                    leaf = unicodedata.normalize(
                        "NFC", leaf
                    )  # convert to NFC for return value
                break
        if not found:
            # should only happen if the path was just deleted
            raise OSError(2, "Unexpectedly not found in " + parentpath, leaf_lower)
    # recurse on parent path
    if parentpath not in ["", ".", "..", "/", "\\"] and not (
        sys.platform == "win32" and os.path.splitdrive(parentpath)[1] in ["\\", "/"]
    ):
        parentpath = get_path_true_case(parentpath)  # recurse
    return os.path.join(parentpath, leaf)


def is_path_true_case(path):  # IMPORTANT: <path> must be a Unicode string
    return get_path_true_case(path) == unicodedata.normalize("NFC", path)

def get_texture_name(obj):
    is_title_case = " " in obj.name or any(letter.isupper() for letter in obj.name)
    return f"{obj.name} Texture" if is_title_case else f"{obj.name}_tex"

def get_material_name(obj):
    is_title_case = " " in obj.name or any(letter.isupper() for letter in obj.name)
    return f"{obj.name} Material" if is_title_case else f"{obj.name}_mat"
