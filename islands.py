from math import ceil, floor
from collections import defaultdict
from typing import Any

import bmesh
from bmesh.types import BMesh, BMFace

from mathutils import Vector

from .common import Vector2Int, RectInt, elem_max, elem_min


class UVFace:
    face: any
    min: Vector = Vector((0, 0))
    max: Vector = Vector((0, 0))
    center: Vector = Vector((0, 0))
    uv_layer: any

    def __init__(self, face: BMFace, uv_layer):
        self.face = face
        self.uv_layer = uv_layer
        self.calc_info()

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


class UVFaceSet:
    faces: "list[UVFace]"
    num_uv: int
    group: int = -1
    max: Vector
    min: Vector
    average_uv: Vector
    pixel_pos: RectInt = None
    uv_layer: any

    def __init__(self, bmfaces: "list[BMFace]", uv_layer):
        self.faces = [UVFace(f, uv_layer) for f in bmfaces]
        self.uv_layer = uv_layer
        self.calc_info()

    def calc_info(self):
        self.max = Vector((-10000000.0, -10000000.0))
        self.min = Vector((10000000.0, 10000000.0))
        self.average_uv = Vector((0.0, 0.0))
        self.num_uv = 0
        for face in self.faces:

            self.average_uv += sum(
                (l[self.uv_layer].uv for l in face.face.loops), Vector((0, 0))
            )
            self.num_uv += len(face.face.loops)

            self.max.x = max(face.max.x, self.max.x)
            self.max.y = max(face.max.y, self.max.y)
            self.min.x = min(face.min.x, self.min.x)
            self.min.y = min(face.min.y, self.min.y)

        self.average_uv /= self.num_uv

    def calc_pixel_pos(self, texture_size, min_padding=0.02):
        if self.pixel_pos is None:
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

            self.pixel_pos = RectInt(mi, ma)

    def merge(self, other: "UVFaceSet"):
        self.max = elem_max(self.max, other.max)
        self.min = elem_min(self.min, other.min)

        # Weight the center by UV counts (as the center is the average vert uv coord)
        self.average_uv = (
            (self.average_uv * self.num_uv) + (other.average_uv * other.num_uv)
        ) / (self.num_uv + other.num_uv)

        self.faces.extend(other.faces)
        self.num_uv += other.num_uv

        if self.pixel_pos is not None and other.pixel_pos is not None:
            self.pixel_pos.encapsulate(other.pixel_pos)


def get_island_info(obj, only_selected=True) -> "list[UVFaceSet]":
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()

    return get_island_info_from_bmesh(bm, only_selected)


def get_island_info_from_bmesh(bm, only_selected=True) -> "list[UVFaceSet]":
    if not bm.loops.layers.uv:
        return None
    uv_layer = bm.loops.layers.uv.verify()

    if only_selected:
        selected_faces = [f for f in bm.faces if f.select]
    else:
        selected_faces = [f for f in bm.faces]

    return get_island_info_from_faces(bm, selected_faces, uv_layer)


def get_island_info_from_faces(bm, faces, uv_layer) -> "list[UVFaceSet]":
    ftv, vtf = __create_vert_face_mapping(faces, uv_layer)

    uv_island_lists = []
    all_face_indices = ftv.keys()

    def connected_faces(face_idx):
        for vid in ftv[face_idx]:
            for conn_face_idx in vtf[vid]:
                yield conn_face_idx

    face_idx_islands = get_connected_components(all_face_indices, connected_faces)
    islands = []
    for face_idx_island in face_idx_islands:
        islands.append(
            UVFaceSet(
                [bm.faces[face_idx] for face_idx in face_idx_island],
                uv_layer,
            )
        )

    return islands


def merge_overlapping_islands(islands: "list[UVFaceSet]") -> "list[UVFaceSet]":
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


def __create_vert_face_mapping(faces, uv_layer):
    # create mesh database for all faces
    face_to_verts = defaultdict(set)
    vert_to_faces = defaultdict(set)
    for f in faces:
        for l in f.loops:
            id_ = l[uv_layer].uv.to_tuple(5), l.vert.index
            face_to_verts[f.index].add(id_)
            vert_to_faces[id_].add(f.index)

    return (face_to_verts, vert_to_faces)


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
