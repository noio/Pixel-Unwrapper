from math import ceil, floor
from collections import defaultdict
from typing import Any

import bmesh
from bmesh.types import BMesh, BMFace

from mathutils import Vector

from .common import Vector2Int, RectInt, any_pinned, elem_max, elem_min


class UVFace:
    face: any
    min: Vector = Vector((0, 0))
    max: Vector = Vector((0, 0))
    center: Vector = Vector((0, 0))
    uv_layer: any

    def __init__(self, face: BMFace, uv_layer):
        self.face = face
        self.uv_layer = uv_layer

    def calc_info(self):
        ma = Vector((-10000000.0, -10000000.0))
        mi = Vector((10000000.0, 10000000.0))
        center = Vector((0, 0))

        for l in self.face.loops:
            uv = l[self.uv_layer].uv
            ma.x = max(uv.x, ma.x)
            ma.y = max(uv.y, ma.y)
            mi.x = min(uv.x, mi.x)
            mi.y = min(uv.y, mi.y)
            center += uv

        center /= len(self.face.loops)
        self.min = mi
        self.max = ma


class UVIsland:
    """Set of UV faces, usually an Island"""

    mesh: "BMesh"
    uv_faces: "list[UVFace]"
    num_uv: int
    group: int = -1
    max: Vector
    min: Vector
    average_uv: Vector
    # pixel_bounds: RectInt = None
    uv_layer: any

    def __init__(self, bmfaces: "list[BMFace]", mesh: "BMesh", uv_layer):
        self.mesh = mesh
        self.uv_faces = [UVFace(f, uv_layer) for f in bmfaces]
        self.uv_layer = uv_layer
        self.update_min_max()

    def update_min_max(self):
        """
        Update the min/max values of this island
        based on the faces it contains
        """
        self.max = Vector((-10000000.0, -10000000.0))
        self.min = Vector((10000000.0, 10000000.0))
        self.average_uv = Vector((0.0, 0.0))
        self.num_uv = 0
        for face in self.uv_faces:
            face.calc_info()

            self.average_uv += sum(
                (l[self.uv_layer].uv for l in face.face.loops), Vector((0, 0))
            )
            self.num_uv += len(face.face.loops)

            self.max.x = max(face.max.x, self.max.x)
            self.max.y = max(face.max.y, self.max.y)
            self.min.x = min(face.min.x, self.min.x)
            self.min.y = min(face.min.y, self.min.y)

        self.average_uv /= self.num_uv

    def calc_pixel_bounds(self, texture_size, min_padding=0.3):
        """
        Add integer pixel positions to this UV island,
        depending on the passed-in texture size.
        Useful when manipulating the texture based on islands,
        or when finding free space
        """
        xmin = floor(self.min.x * texture_size - min_padding)
        ymin = floor(self.min.y * texture_size - min_padding)
        xmax = ceil(self.max.x * texture_size + min_padding)
        ymax = ceil(self.max.y * texture_size + min_padding)

        mi = Vector2Int(xmin, ymin)
        ma = Vector2Int(xmax, ymax)

        return RectInt(mi, ma)

    def merge(self, other: "UVIsland"):
        self.max = elem_max(self.max, other.max)
        self.min = elem_min(self.min, other.min)

        # Weight the center by UV counts (as the center is the average vert uv coord)
        self.average_uv = (
            (self.average_uv * self.num_uv) + (other.average_uv * other.num_uv)
        ) / (self.num_uv + other.num_uv)

        self.uv_faces.extend(other.uv_faces)
        self.num_uv += other.num_uv

        # if self.pixel_bounds is not None and other.pixel_bounds is not None:
        #     self.pixel_bounds.encapsulate(other.pixel_bounds)

    def get_faces(self):
        return (uv_face.face for uv_face in self.uv_faces)

    def is_any_pinned(self):
        return any_pinned(self.get_faces(), self.mesh.loops.layers.uv.verify())

    def is_any_orientation_locked(self):
        # try:
        lock_layer = self.mesh.faces.layers.int.get("orientation_locked")
        if lock_layer is None:
            return False
        # print(f"{lock_layer=}")
        # except AttributeError:
        #     #if the layer doesn't exist, no faces are locked
        #     return False
        # print([face[lock_layer] for face in self.get_faces()])
        return any(face[lock_layer] == 1 for face in self.get_faces())


def get_islands_from_obj(obj, only_selected=True) -> "list[UVIsland]":
    if obj.data.is_editmode:
        mesh = bmesh.from_edit_mesh(obj.data)
    else:
        mesh = bmesh.new()
        mesh.from_mesh(obj.data)

    mesh.faces.ensure_lookup_table()

    return get_islands_from_mesh(mesh, only_selected)


def get_islands_from_mesh(mesh: "BMesh", only_selected=True) -> "list[UVIsland]":
    if not mesh.loops.layers.uv:
        return None
    uv_layer = mesh.loops.layers.uv.verify()

    if only_selected:
        selected_faces = [f for f in mesh.faces if f.select]
    else:
        selected_faces = [f for f in mesh.faces]

    return get_islands_for_faces(mesh, selected_faces, uv_layer)


def get_islands_for_faces(mesh: "BMesh", faces, uv_layer) -> "list[UVIsland]":
    # Build two lookups for
    # all verts that makes up a face
    # all faces using a vert
    # Lookups are by INDEX'
    mesh.faces.ensure_lookup_table()
    face_to_verts = defaultdict(set)
    vert_to_faces = defaultdict(set)
    for f in faces:
        for l in f.loops:
            id_ = l[uv_layer].uv.to_tuple(5), l.vert.index
            face_to_verts[f.index].add(id_)
            vert_to_faces[id_].add(f.index)

    all_face_indices = face_to_verts.keys()

    def connected_faces(face_idx):
        for vid in face_to_verts[face_idx]:
            for conn_face_idx in vert_to_faces[vid]:
                yield conn_face_idx

    face_idx_islands = get_connected_components(all_face_indices, connected_faces)
    islands = []
    for face_idx_island in face_idx_islands:
        islands.append(
            UVIsland(
                [mesh.faces[face_idx] for face_idx in face_idx_island],
                mesh,
                uv_layer,
            )
        )

    return islands


def merge_overlapping_islands(islands: "list[UVIsland]") -> "list[UVIsland]":
    """
    Check each pair of islands to see if their (pixel) bounding boxes overlap
    Merges them if they do
    """
    i = 0
    while i < len(islands):
        island_i = islands[i]
        j = i + 1
        while j < len(islands):
            island_j = islands[j]
            # See if the islands's bounds overlap eachother
            if not (
                island_j.min.x > island_i.max.x
                or island_i.min.x > island_j.max.x
                or island_j.min.y > island_i.max.y
                or island_i.min.y > island_j.max.y
            ):
                island_i.merge(island_j)
                del islands[j]
                # start over because we want to know if the merged
                # island now overlaps something else
                j = i + 1
            else:
                # either the list gets shorter, or we move
                # up one index
                j += 1
        i += 1

    return islands


def get_connected_components(nodes, get_connections_for_node):
    """
    Method to get "connected components" in an abstract graph
    Can be used for contiguous faces on a model, or for UV-islands
    """
    remaining = set(nodes)

    if len(remaining) != len(nodes):
        raise Exception("Nodes should be a list of unique objects")

    connected_components = []
    while remaining:
        node = next(iter(remaining))
        current_component = []
        nodes_to_add = [node]
        while nodes_to_add:
            node_to_add = nodes_to_add.pop()
            if node_to_add in remaining:
                remaining.remove(node_to_add)
                current_component.append(node_to_add)
                nodes_to_add.extend(get_connections_for_node(node_to_add))

        connected_components.append(current_component)
    return connected_components


def find_quad_groups(faces):
    "Finds connected (contiguous) groups of quads"
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
        if not edge.seam:
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
