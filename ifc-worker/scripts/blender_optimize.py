"""Run inside Blender: blender --background --factory-startup --python blender_optimize.py -- in.glb out.glb

Adds a second UV map "UVMap_Lightmap" (non-overlapping, 0..1) to every mesh; keeps node names and
custom properties (glTF extras).
"""
import sys

import bpy

LIGHTMAP_UV = "UVMap_Lightmap"


def main(src: str, dst: str) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=src)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    for obj in meshes:
        mesh = obj.data
        if LIGHTMAP_UV in mesh.uv_layers:
            continue
        if len(mesh.uv_layers) >= 8:
            continue
        layer = mesh.uv_layers.new(name=LIGHTMAP_UV)
        mesh.uv_layers.active = layer
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.lightmap_pack(PREF_CONTEXT="ALL_FACES", PREF_PACK_IN_ONE=False, PREF_MARGIN_DIV=0.1)
        bpy.ops.object.mode_set(mode="OBJECT")
        mesh.uv_layers.active = mesh.uv_layers[0]
    bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", export_extras=True, export_yup=True)


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:]
    main(args[0], args[1])
