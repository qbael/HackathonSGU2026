"""CPU checks of the actual notebook cells; never import/download a model."""

import ast
import hashlib
import io
import json
import math
import unittest
import warnings
from pathlib import Path

import nbformat
import numpy as np
from PIL import Image, ImageDraw, ImageOps


ROOT = Path(__file__).parent


def notebook(name):
    return nbformat.read(ROOT / name, as_version=4)


def tagged_source(document, tag):
    return next(cell.source for cell in document.cells if tag in cell.metadata.get("tags", []))


def namespace():
    return {
        "hashlib": hashlib, "io": io, "json": json, "math": math,
        "warnings": warnings, "Path": Path, "np": np,
        "Image": Image, "ImageDraw": ImageDraw, "ImageOps": ImageOps,
    }


class NotebookTests(unittest.TestCase):
    def test_schema_and_python_cells(self):
        for path in ROOT.glob("*.ipynb"):
            document = notebook(path.name)
            nbformat.validate(document)
            for index, cell in enumerate(document.cells):
                if cell.cell_type == "code":
                    self.assertEqual(cell.outputs, [])
                    self.assertIsNone(cell.execution_count)
                    compile(cell.source, f"{path.name}:cell{index}", "exec")

    def test_image_validation_and_orientation(self):
        for name in ("01_qwen_embedding.ipynb", "02_qwen_redaction.ipynb"):
            scope = namespace()
            exec(tagged_source(notebook(name), "image-validation"), scope)
            exif = Image.Exif()
            exif[274] = 6
            exif[270] = "Synthetic metadata"
            exif[34853] = {1: "N", 2: (1.0, 2.0, 3.0), 3: "E", 4: (4.0, 5.0, 6.0)}
            jpeg = io.BytesIO()
            Image.new("RGB", (30, 20), "white").save(jpeg, format="JPEG", exif=exif)
            oriented = scope["decode_image"](jpeg.getvalue())
            self.assertEqual(oriented.size, (20, 30))
            self.assertFalse(oriented.info)
            self.assertFalse(oriented.getexif())
            animated = io.BytesIO()
            Image.new("RGB", (16, 16), "red").save(
                animated, format="PNG", save_all=True,
                append_images=[Image.new("RGB", (16, 16), "blue")], duration=100,
            )
            with self.assertRaisesRegex(ValueError, "một frame"):
                scope["decode_image"](animated.getvalue())
            original = Image.new("RGB", (32, 32))
            raw = io.BytesIO()
            original.save(raw, format="PNG")
            scope["MAX_SOURCE_PIXELS"] = 100
            with self.assertRaisesRegex(ValueError, "20 megapixel"):
                scope["decode_image"](raw.getvalue())

    def test_embedding_vector_validation(self):
        source = tagged_source(notebook("01_qwen_embedding.ipynb"), "embedding-validation")
        tree = ast.parse(source)
        validate = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "validate_vector")
        scope = namespace()
        exec(compile(ast.Module(body=[validate], type_ignores=[]), "notebook-vector", "exec"), scope)
        vector = scope["validate_vector"](np.ones(2048))
        np.testing.assert_allclose(np.linalg.norm(vector), 1, atol=1e-5)
        for invalid in (np.zeros(2048), np.ones(5), np.full(2048, np.nan), np.full(2048, np.inf)):
            with self.assertRaises(ValueError):
                scope["validate_vector"](invalid)

    def test_regions_and_redaction(self):
        scope = namespace()
        exec(tagged_source(notebook("02_qwen_redaction.ipynb"), "redaction-validation"), scope)
        for invalid in (None, [{"label": {}, "bbox_2d": [0, 0, 1, 1]}],
                        [{"label": "face", "bbox_2d": [0, 0, float("inf"), 1]}]):
            with self.assertRaises(ValueError):
                scope["validate_regions"](invalid)
        pixels = np.random.default_rng(42).integers(0, 256, (80, 100, 3), dtype=np.uint8)
        picture = Image.fromarray(pixels)
        blurred = scope["redact_image"](
            picture, [{"label": "face", "bbox_2d": [200, 200, 800, 800]}], blur_faces=True,
        )
        self.assertFalse(np.array_equal(np.asarray(blurred), pixels))
        np.testing.assert_array_equal(np.asarray(blurred)[:10], pixels[:10])
        overlap = scope["redact_image"](picture, [
            {"label": "document_number", "bbox_2d": [200, 200, 800, 800]},
            {"label": "face", "bbox_2d": [100, 100, 900, 900]},
        ], blur_faces=True)
        self.assertEqual(int(np.asarray(overlap)[30:50, 30:70].sum()), 0)
        np.testing.assert_array_equal(np.asarray(picture), pixels)


if __name__ == "__main__":
    unittest.main()
