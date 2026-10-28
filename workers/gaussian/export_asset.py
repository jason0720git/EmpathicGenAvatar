"""Export LAM canonical geometry into the official ARKit WebRender rig.

LAM's upstream exporter replaces only the template FBX mesh positions before
converting with Blender. The official sample GLB contains that same template:
we verify the complete topology and rigid translation, then replace the base
POSITION accessor directly. Morph deltas, skin weights, skeleton and animation
are preserved. No learned portrait appearance is copied from the example.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import struct
import zipfile

import numpy as np


def decode_glb(raw: bytes) -> tuple[dict, bytearray]:
    magic, version, length = struct.unpack_from("<III", raw)
    if magic != 0x46546C67 or version != 2 or length != len(raw):
        raise ValueError("Invalid GLB header")
    json_length, json_type = struct.unpack_from("<II", raw, 12)
    if json_type != 0x4E4F534A:
        raise ValueError("Missing GLB JSON chunk")
    document = json.loads(raw[20:20 + json_length])
    binary_length, binary_type = struct.unpack_from("<II", raw, 20 + json_length)
    if binary_type != 0x004E4942:
        raise ValueError("Missing GLB binary chunk")
    return document, bytearray(raw[28 + json_length:28 + json_length + binary_length])


def encode_glb(document: dict, binary: bytes) -> bytes:
    raw_json = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf8")
    raw_json += b" " * (-len(raw_json) % 4)
    binary += b"\0" * (-len(binary) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 28 + len(raw_json) + len(binary))
            + struct.pack("<II", len(raw_json), 0x4E4F534A) + raw_json
            + struct.pack("<II", len(binary), 0x004E4942) + binary)


def accessor_array(document: dict, binary: bytes, index: int) -> np.ndarray:
    accessor = document["accessors"][index]
    view = document["bufferViews"][accessor["bufferView"]]
    dimensions = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}
    dtypes = {5126: "<f4", 5123: "<u2", 5125: "<u4", 5121: "u1"}
    if "byteStride" in view or "sparse" in accessor:
        raise ValueError("Expected a contiguous, non-sparse template accessor")
    return np.frombuffer(binary, dtype=dtypes[accessor["componentType"]],
                         count=accessor["count"] * dimensions[accessor["type"]],
                         offset=view.get("byteOffset", 0) + accessor.get("byteOffset", 0))


def template_data(template_fbx: Path, sample_zip: Path) -> tuple[dict, bytearray, int, np.ndarray, np.ndarray, bytes]:
    text = template_fbx.read_text(encoding="utf8")
    vertices = re.search(r"Vertices: \*60054 \{\s*a: ([^}]+)", text)
    triangles = re.search(r"PolygonVertexIndex: \*119712 \{\s*a: ([^}]+)", text)
    if not vertices or not triangles:
        raise ValueError("Unexpected LAM ARKit FBX template topology")
    original = np.fromstring(vertices.group(1), sep=",").reshape(-1, 3)
    faces = np.fromstring(triangles.group(1), sep=",", dtype=np.int64)
    faces = np.where(faces < 0, -faces - 1, faces).reshape(-1, 3)
    with zipfile.ZipFile(sample_zip) as bundle:
        skin_name = next(n for n in bundle.namelist() if n.endswith("/skin.glb") and not n.startswith("__MACOSX"))
        root = skin_name.rsplit("/", 1)[0]
        document, binary = decode_glb(bundle.read(skin_name))
        animation = bundle.read(root + "/animation.glb")
    primitive = document["meshes"][0]["primitives"][0]
    actual_faces = accessor_array(document, binary, primitive["indices"]).reshape(-1, 3)
    if not np.array_equal(faces, actual_faces):
        raise ValueError("Template and GLB triangle order differ; refusing unverified rig mapping")
    position_index = primitive["attributes"]["POSITION"]
    positions = accessor_array(document, binary, position_index).reshape(-1, 3)
    delta = positions.astype(np.float64) - original
    translation = delta.mean(axis=0)
    if np.max(np.abs(delta - translation)) > 1e-6:
        raise ValueError("Template and sample GLB have different geometry; rebuild official template")
    return document, binary, position_index, translation, faces, animation


def export_avatar(vertices: np.ndarray, faces: np.ndarray, offset_ply: Path,
                  output_zip: Path, template_fbx: Path, sample_zip: Path) -> dict:
    document, binary, position_index, translation, template_faces, animation = template_data(template_fbx, sample_zip)
    if vertices.shape != (20018, 3) or not np.isfinite(vertices).all():
        raise ValueError("Expected 20,018 finite canonical LAM vertices")
    if not np.array_equal(faces, template_faces):
        raise ValueError("Generated canonical mesh topology differs from the verified ARKit template")
    positions = np.asarray(vertices + translation, dtype="<f4")
    accessor_array(document, binary, position_index)[:] = positions.reshape(-1)
    accessor = document["accessors"][position_index]
    accessor["min"] = positions.min(axis=0).tolist()
    accessor["max"] = positions.max(axis=0).tolist()
    # Retain a deterministic legacy index list for the ZIP schema. The pinned
    # SDK loads vertex_order.json but never applies it (replaceIndexes=false).
    # The actual PLY/morph/skin correspondence is DIRECT index equality,
    # verified above; never reorder those buffers using this auxiliary list.
    vertex_order = np.argsort(vertices[:, 1], kind="stable").tolist()
    root = "avatar"
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        # SDK discovers the root using JSZip's explicit directory entries.
        bundle.writestr(root + "/", b"")
        bundle.writestr(root + "/skin.glb", encode_glb(document, binary))
        bundle.writestr(root + "/animation.glb", animation)
        bundle.writestr(root + "/vertex_order.json", json.dumps(vertex_order))
        bundle.write(offset_ply, root + "/offset.ply")
    return {
        "vertex_count": len(vertices),
        "blendshapes": document["meshes"][0]["extras"]["targetNames"],
        "template_translation": translation.tolist(),
        "export_method": "verified_template_glb_position_replacement",
    }
