from math import ceil, floor, fabs
from collections import defaultdict
from typing import Any, Optional, Generator

import bmesh
from bmesh.types import BMesh, BMFace

from mathutils import Vector

from .common import LOCK_ORIENTATION_ATTRIBUTE, Vector2Int, RectInt, any_pinned, elem_max, elem_min


class BoundaryNotFoundError(Exception):
    ...


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

            self.average_uv += sum((l[self.uv_layer].uv for l in face.face.loops), Vector((0, 0)))
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
        self.average_uv = ((self.average_uv * self.num_uv) + (other.average_uv * other.num_uv)) / (
            self.num_uv + other.num_uv
        )

        self.uv_faces.extend(other.uv_faces)
        self.num_uv += other.num_uv

        # if self.pixel_bounds is not None and other.pixel_bounds is not None:
        #     self.pixel_bounds.encapsulate(other.pixel_bounds)

    def get_faces(self):
        return (uv_face.face for uv_face in self.uv_faces)

    def get_loops_for_vert(self, vert):
        """Returns all UV loops for a given vertex in this island."""
        loops = []
        for face in self.uv_faces:
            for loop in face.face.loops:
                if loop.vert == vert:
                    loops.append(loop)
        return loops

    def get_boundary_loops(self):
        """Returns list of ordered vertex loops that form UV island boundaries."""
        # Get boundary edges as before
        edge_face_count = {}
        for face in self.uv_faces:
            for edge in face.face.edges:
                edge_face_count[edge] = edge_face_count.get(edge, 0) + 1

        boundary_edges = set(edge for edge, count in edge_face_count.items() if count == 1)

        # Build connectivity map
        # vert_connections is a dictionary of sets with all verts each vert is connected to
        vert_connections = {}
        for edge in boundary_edges:
            v1, v2 = edge.verts
            vert_connections.setdefault(v1, set()).add(v2)
            vert_connections.setdefault(v2, set()).add(v1)

        # Find all loops
        loops = []
        remaining_edges = boundary_edges.copy()

        while remaining_edges:
            # Start new loop from any remaining edge
            start_edge = next(iter(remaining_edges))
            start_vert = start_edge.verts[0]
            current_loop = [start_vert]
            current = start_vert

            # Walk until we close the loop
            while True:
                # We really just follow ANY connection?
                connected_to_current = vert_connections[current]
                next_vert = next(v for v in connected_to_current if len(current_loop) < 2 or v != current_loop[-2])

                try:
                    # Remove edges as we use them
                    edge_to_remove = next(e for e in remaining_edges if current in e.verts and next_vert in e.verts)
                    remaining_edges.remove(edge_to_remove)

                    # print(f"e{edge_to_remove.index} = (v{current.index} => v{next_vert.index}) ({len(remaining_edges)} remaining)")

                    current_loop.append(next_vert)
                    current = next_vert
                except StopIteration:
                    break

            if current_loop[0] != current_loop[-1]:
                raise ValueError("Boundary edges do not form loop")
            del current_loop[-1]
            loops.append(current_loop)

        # Convert loops to (vert, uv) pairs
        uv_layer = self.mesh.loops.layers.uv.verify()
        loops_with_uvs = []

        for loop in loops:
            loop_with_uvs = []
            for vert in loop:
                # Find UV for this vert
                for face in self.uv_faces:
                    for l in face.face.loops:
                        if l.vert == vert:
                            uv = l[uv_layer].uv.copy()
                            loop_with_uvs.append((vert, uv))
                            break
                    if len(loop_with_uvs) > 0 and loop_with_uvs[-1][0] == vert:
                        break
            loops_with_uvs.append(loop_with_uvs)

        return loops_with_uvs

    def is_any_pinned(self):
        return any_pinned(self.get_faces(), self.mesh.loops.layers.uv.verify())

    def is_any_orientation_locked(self):
        # try:
        lock_layer = self.mesh.faces.layers.int.get(LOCK_ORIENTATION_ATTRIBUTE)
        if lock_layer is None:
            return False
        # print(f"{lock_layer=}")
        # except AttributeError:
        #     #if the layer doesn't exist, no faces are locked
        #     return False
        # print([face[lock_layer] for face in self.get_faces()])
        return any(face[lock_layer] == 1 for face in self.get_faces())


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


def get_islands_from_obj(obj, only_selected=True) -> Optional[list[UVIsland]]:
    if obj.data.is_editmode:
        mesh = bmesh.from_edit_mesh(obj.data)
    else:
        mesh = bmesh.new()
        mesh.from_mesh(obj.data)

    mesh.faces.ensure_lookup_table()

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
    # Lookups are by INDEX
    mesh.faces.ensure_lookup_table()
    face_to_verts = defaultdict(set)
    vert_to_faces = defaultdict(set)
    for f in faces:
        for l in f.loops:
            id_ = l[uv_layer].uv.to_tuple(5), l.vert.index
            face_to_verts[f.index].add(id_)
            vert_to_faces[id_].add(f.index)

    all_face_indices = face_to_verts.keys()

    def get_connected_faces(face_idx):
        for vid in face_to_verts[face_idx]:
            for conn_face_idx in vert_to_faces[vid]:
                yield conn_face_idx

    face_idx_islands = get_connected_components(all_face_indices, get_connected_faces)
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
            # See if the islands' bounds overlap each other
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

    return quad_groups, connected_non_quads


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
                dist = (face.calc_center_bounds() - group_face.calc_center_bounds()).length_squared
                print(f"distance to {i}/{group_face.index} is {dist}")
                if dist < closest_dist:
                    closest_dist = dist
                    closest = i

        print(f"Closest distance was {closest_dist} for group {closest}")
        output[closest].append(face)
    return output


def calculate_loop_length(loop):
    """Calculate total UV-space length of a loop of (vert, uv) pairs"""
    total_length = 0
    for i in range(len(loop)):
        _, uv1 = loop[i]
        _, uv2 = loop[(i + 1) % len(loop)]
        total_length += (uv1 - uv2).length
    return total_length


def find_corner_points(loop, corners):
    """
    Find 4 points in the loop closest to any corner of the bounding rectangle.
    Returns (corner_points, corner_indices) where both lists are in boundary-walking order.
    Validates that corners aren't twisted (indices should be monotonic in the loop).
    """


    # Find all point-to-corner distances
    distances = []  # [(loop_idx, corner_idx, distance), ...]
    for loop_idx, (vert, uv) in enumerate(loop):
        for corner_idx, corner in enumerate(corners):
            dist = (uv - corner).length
            distances.append((loop_idx, corner_idx, dist))

    # Sort by distance to find best matches
    distances.sort(key=lambda x: x[2])

    used_loop_indices = set()
    used_corner_indices = set()
    corner_matches = []  # [(loop_idx, corner_idx), ...]

    # Take closest matches, but don't reuse points or corners
    for loop_idx, corner_idx, dist in distances:
        if len(corner_matches) >= 4:
            break
        if loop_idx not in used_loop_indices and corner_idx not in used_corner_indices:
            corner_matches.append((loop_idx, corner_idx))
            used_loop_indices.add(loop_idx)
            used_corner_indices.add(corner_idx)

        # Instead of sorting by loop order, sort by corner order
    corner_matches.sort(key=lambda x: x[1])  # Sort by corner_idx

    # Get points in corner order
    ordered_indices = [match[0] for match in corner_matches]
    corner_points = [loop[i] for i in ordered_indices]

    # Validate that corners aren't twisted (using original loop-order indices)
    loop_order_indices = sorted(ordered_indices)

    # Rotate to get sequential loop indices for validation
    start_idx = loop_order_indices.index(min(ordered_indices))
    loop_order_indices = (
            loop_order_indices[start_idx:] +
            loop_order_indices[:start_idx]
    )

    # Do the relative indices validation
    relative_indices = []
    first_idx = loop_order_indices[0]
    for idx in loop_order_indices:
        rel_idx = idx - first_idx
        if rel_idx < 0:
            rel_idx += len(loop)
        relative_indices.append(rel_idx)

    # Check if indices are monotonically increasing or decreasing
    diffs = [relative_indices[i + 1] - relative_indices[i] for i in range(len(relative_indices) - 1)]
    if not (all(d > 0 for d in diffs) or all(d < 0 for d in diffs)):
        raise ValueError("Corner points are twisted in the boundary loop")

    return corner_points, ordered_indices
