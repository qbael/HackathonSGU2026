import json
from pathlib import Path
import unittest


COLAB = Path(__file__).resolve().parents[1] / "notebooks/colab"


class NotebookTest(unittest.TestCase):
    def test_standalone_notebooks_have_valid_python_and_no_saved_outputs(self):
        for name in ("01_qwen_embedding.ipynb", "02_qwen_redaction.ipynb"):
            with self.subTest(notebook=name):
                notebook = json.loads((COLAB / name).read_text(encoding="utf-8"))
                self.assertEqual(notebook["nbformat"], 4)
                self.assertEqual(notebook["metadata"]["kernelspec"]["name"], "python3")
                self.assertGreater(len(notebook["cells"]), 5)
                for index, cell in enumerate(notebook["cells"]):
                    self.assertIn(cell["cell_type"], ("code", "markdown"))
                    if cell["cell_type"] == "code":
                        self.assertEqual(cell["outputs"], [])
                        self.assertIsNone(cell["execution_count"])
                        compile("".join(cell["source"]), f"{name}:cell{index}", "exec")


if __name__ == "__main__":
    unittest.main()
