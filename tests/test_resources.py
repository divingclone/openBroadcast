from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openbroadcast import resources


class ResourceTests(unittest.TestCase):
    def test_editable_install_uses_canonical_checkout_documentation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").touch()
            guide = root / "README.zh-CN.md"
            guide.write_text("使用说明", encoding="utf-8")
            with patch.object(resources, "__file__", str(root / "src/openbroadcast/resources.py")):
                self.assertEqual(resources.documentation_path(guide.name), guide)
                self.assertEqual(resources.documentation_path(guide.name).read_text(encoding="utf-8"), "使用说明")

    def test_wheel_uses_bundled_documentation(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "site-packages/openbroadcast"
            (package / "docs").mkdir(parents=True)
            guide = package / "docs/compatibility.md"
            guide.write_text("Installed guide", encoding="utf-8")
            with patch.object(resources, "__file__", str(package / "resources.py")):
                self.assertEqual(resources.documentation_path("docs/compatibility.md"), guide)

    def test_missing_installed_guide_does_not_read_unrelated_parent_readme(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("Unrelated", encoding="utf-8")
            package = root / "site-packages/openbroadcast"
            with patch.object(resources, "__file__", str(package / "resources.py")):
                self.assertEqual(resources.documentation_path("README.md"), package / "README.md")
