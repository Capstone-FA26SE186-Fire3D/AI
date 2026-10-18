"""Per-storey preview GLB (metres, Y-up, no embedded textures)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh
from trimesh.exchange.gltf import export_glb
from trimesh.visual import TextureVisuals
from trimesh.visual.material import PBRMaterial

from worker.pipeline.extract import Storey
from worker.pipeline.geometry import UNASSIGNED, ElementMesh

_GREY = [200, 200, 200, 255]


def box_uv(vertices: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Unweld faces and project UV0 onto the plane of each face's dominant normal axis (metres)."""
    tri = vertices[faces]  # (m, 3, 3)
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    axis = np.argmax(np.abs(normals), axis=1)  # 0: x, 1: y (up), 2: z
    flat = tri.reshape(-1, 3)
    ax = np.repeat(axis, 3)
    uv = np.empty((len(flat), 2), dtype=float)
    uv[ax == 0] = flat[ax == 0][:, [2, 1]]
    uv[ax == 1] = flat[ax == 1][:, [0, 2]]
    uv[ax == 2] = flat[ax == 2][:, [0, 1]]
    new_faces = np.arange(len(flat), dtype=np.int64).reshape(-1, 3)
    return flat, new_faces, uv


def build_glb(meshes: list[ElementMesh], storeys: list[Storey], out: Path) -> dict[str, str]:
    """Write `out`; top-level nodes are storey ids (or "unassigned"), children are named by GlobalId.

    Returns {global_id: node_name}.
    """
    scene = trimesh.Scene()
    root = scene.graph.base_frame
    known = {s.id for s in storeys}
    groups = [s.id for s in storeys]
    if any((m.storey_id or UNASSIGNED) not in known for m in meshes) or not groups:
        groups.append(UNASSIGNED)
    for g in groups:
        scene.graph.update(frame_from=root, frame_to=g, matrix=np.eye(4))

    materials: dict[str, PBRMaterial] = {}
    node_map: dict[str, str] = {}
    for m in meshes:
        parent = m.storey_id if m.storey_id in known else UNASSIGNED
        lib = m.material_key or "default"
        mat = materials.setdefault(lib, PBRMaterial(name=lib, baseColorFactor=_GREY))
        verts, faces, uv = box_uv(m.vertices, m.faces)
        extras = {"ifcGlobalId": m.global_id, "ifcClass": m.ifc_class, "libraryKey": m.material_key}
        tm = trimesh.Trimesh(verts, faces, process=False, visual=TextureVisuals(uv=uv, material=mat))
        tm.metadata.update(extras)  # exported as mesh extras
        # node metadata is exported as glTF node extras
        scene.add_geometry(tm, geom_name=m.global_id, node_name=m.global_id, parent_node_name=parent,
                           metadata=dict(extras))
        node_map[m.global_id] = m.global_id

    out = Path(out)
    # export_glb directly: Scene.export refuses empty scenes, but a model whose products all lack
    # Body geometry must still yield a (node-only) GLB next to its QA issues.
    out.write_bytes(export_glb(scene))
    return node_map
