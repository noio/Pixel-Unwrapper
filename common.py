import os, sys, unicodedata

from math import fabs, sqrt, radians

from dataclasses import dataclass

import bpy
import bmesh
from bmesh.types import BMFace, BMEdge, BMesh
from mathutils import Vector, Matrix

ERROR_MULTIPLE_MATERIALS = "Faces have different materials"
ERROR_TEXTURE_DIRTY = f"Please save texture first, because undo doesn't work for textures."
ERROR_NO_TEXTURE_SPACE = f'Not enough space to preserve texture data. Resize texture or turn off "Modify Texture"'
ERROR_SELECT_ALL_FACES_USING_MATERIAL = "Please select ALL faces using the material with the texture you want to resize"
ERROR_NO_MATERIAL_OR_NO_TEXTURE = "Selected faces have no material or no texture was found on the material"


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
        self.min = Vector2Int(min(self.min.x, other.min.x), min(self.min.y, other.min.y))
        self.max = Vector2Int(max(self.max.x, other.max.x), max(self.max.y, other.max.y))


def elem_min(a, b):
    elems = [min(pair) for pair in zip(a, b)]
    return Vector(elems)


def elem_max(a, b):
    elems = [max(pair) for pair in zip(a, b)]
    return Vector(elems)


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


def get_nearest_point_on_rectangle(point: Vector, rect_min: Vector, rect_max: Vector) -> Vector:
    """
    Returns the nearest point on a rectangle to the given point.
    Rectangle is defined by its min/max corners.
    """
    # First handle if point is closest to a corner
    if point.x <= rect_min.x and point.y <= rect_min.y:
        return Vector((rect_min.x, rect_min.y))  # bottom left
    if point.x >= rect_max.x and point.y <= rect_min.y:
        return Vector((rect_max.x, rect_min.y))  # bottom right
    if point.x >= rect_max.x and point.y >= rect_max.y:
        return Vector((rect_max.x, rect_max.y))  # top right
    if point.x <= rect_min.x and point.y >= rect_max.y:
        return Vector((rect_min.x, rect_max.y))  # top left

    # Otherwise project to nearest edge
    x = point.x
    y = point.y

    # Clamp to rectangle bounds
    x = max(rect_min.x, min(rect_max.x, x))
    y = max(rect_min.y, min(rect_max.y, y))

    # Find which edge is closest
    dist_left = abs(point.x - rect_min.x)
    dist_right = abs(point.x - rect_max.x)
    dist_bottom = abs(point.y - rect_min.y)
    dist_top = abs(point.y - rect_max.y)

    min_dist = min(dist_left, dist_right, dist_bottom, dist_top)

    if min_dist == dist_left:
        return Vector((rect_min.x, y))
    if min_dist == dist_right:
        return Vector((rect_max.x, y))
    if min_dist == dist_bottom:
        return Vector((x, rect_min.y))
    return Vector((x, rect_max.y))


def vert_between_edges(edge_a, edge_b):
    if edge_a.verts[0] in edge_b.verts:
        return edge_a.verts[0]
    elif edge_a.verts[1] in edge_b.verts:
        return edge_a.verts[1]

def pv(v, precision=3):
    """Format a vector with specified precision for all components."""
    if hasattr(v, "__iter__"):
        components = [f"{x:.{precision}f}" for x in v]
        return f"({', '.join(components)})"
    else:
        # Handle case where input might not be a vector
        return str(v)

def get_uv_space_matrix(matrix: Matrix, texture_size):
    scale_up = Matrix.Scale(texture_size, 3)
    scale_up[2][2] = 1
    scale_down = Matrix.Scale(1.0 / texture_size, 3)
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


def uvs_transform(faces, uv_layer, transformation=Matrix):
    """
    Transform all UV coordsin the given faces using the given matrix
    """
    for face in faces:
        for loop_uv in face.loops:
            uv = loop_uv[uv_layer].uv
            uv = uv.to_3d()
            uv.z = 1
            transformed = transformation @ uv
            transformed /= transformed.z
            loop_uv[uv_layer].uv = transformed.xy


def uvs_scale(faces, uv_layer, scale: Vector):
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
    return current_density, scale


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


LOCK_ORIENTATION_ATTRIBUTE = "pixunwrap_lock_orientation"


def lock_orientation(mesh, face_indices, is_locked):
    lock_layer = mesh.faces.layers.int.get(LOCK_ORIENTATION_ATTRIBUTE)
    if lock_layer is None:
        lock_layer = mesh.faces.layers.int.new(LOCK_ORIENTATION_ATTRIBUTE)

    # THIS IS BAD BECAUSE IT LOCKS ALL FACES IN WHOLE MESH NOT JUST IN ISLAND
    for face_index in face_indices:
        face = mesh.faces[face_index]
        face[lock_layer] = 1 if is_locked else 0
    # print([face[lock_layer] for face in self.mesh.faces])


def is_outer_edge_of_selection(edge):
    return len(list(edge_face for edge_face in edge.link_faces if edge_face.select)) <= 1


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


def update_and_free_bmesh(obj, bm: "BMesh"):
    """
    updates mesh data on the given object.
    """
    if obj.data.is_editmode:
        bmesh.update_edit_mesh(obj.data)
    else:
        bm.to_mesh(obj.data)
        bm.free()


def get_first_texture_on_object(obj):
    """
    Returns first texture on any material on given object
    """
    for slot in obj.material_slots:
        if slot.material:
            for node in slot.material.node_tree.nodes:
                if node.type in ["TEX_ENVIRONMENT", "TEX_IMAGE"]:
                    if node.image:
                        return node.image
    return None


def get_all_textures_on_object(obj):
    textures = []

    for slot in obj.material_slots:
        if slot.material:
            for node in slot.material.node_tree.nodes:
                if node.type in ["TEX_ENVIRONMENT", "TEX_IMAGE"]:
                    if node.image:
                        textures.append(node.image)

    textures = list(set(textures))
    return textures


class MultipleMaterialsError(Exception):
    ...


def get_material_index_from_faces(faces: "list[BMFace]"):
    """
    Checks if same material index is used for all faces,
    if yes: returns it,
    if no: do what?!
    """
    first_material_index = None
    for face in faces:
        if first_material_index is None:
            first_material_index = face.material_index
        else:
            if first_material_index != face.material_index:
                return None

    return first_material_index


def get_texture_for_faces(obj, faces):
    """
    Get appropriate texture size for faces.
    Raises MultipleMaterialsError if faces have different materials.
    """
    material_index = get_material_index_from_faces(faces)
    if material_index is None:
        raise MultipleMaterialsError(ERROR_MULTIPLE_MATERIALS)

    return get_texture_from_material_index(obj, material_index)

def get_texture_from_material_index(obj, material_index):
    # Early returns if no valid material
    if len(obj.material_slots) < material_index - 1:
        return None

    mat = obj.material_slots[material_index].material
    if not mat:
        return None

    # Return first found texture
    for node in mat.node_tree.nodes:
        if node.type in ["TEX_ENVIRONMENT", "TEX_IMAGE"]:
            if node.image:
                return node.image

    return None


def get_all_objects_with_texture(context, texture) -> "list[bpy.types.Object]":
    objects = []
    for obj in context.view_layer.objects:
        if obj.type == "MESH":
            obj_textures = get_all_textures_on_object(obj)
            if texture in obj_textures:
                objects.append(obj)
    return objects


def is_out_of_bounds(texture_size, pos: "Vector2Int", size: "Vector2Int"):
    max_coord = pos + size
    if not (pos.x >= 0 and max_coord.x <= texture_size and pos.y >= 0 and max_coord.y <= texture_size):
        return True
    return False


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
                    leaf = unicodedata.normalize("NFC", leaf)  # convert to NFC for return value
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


def get_texture_name(object_name):
    is_title_case = " " in object_name or any(letter.isupper() for letter in object_name)
    return f"{object_name} Texture" if is_title_case else f"{object_name}_tex"


def get_material_name(object_name):
    is_title_case = " " in object_name or any(letter.isupper() for letter in object_name)
    return f"{object_name} Material" if is_title_case else f"{object_name}_mat"
