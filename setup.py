"""Copy the canonical user documentation into wheels; metadata is in pyproject.toml."""
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPy(build_py):
    def run(self):
        super().run()
        root = Path(__file__).parent
        destination = Path(self.build_lib) / "openbroadcast"
        sources = [root / "README.md", root / "README.zh-CN.md", *sorted((root / "docs").glob("*.md"))]
        for source in sources:
            target = destination / source.relative_to(root)
            self.mkpath(str(target.parent))
            self.copy_file(str(source), str(target))


setup(cmdclass={"build_py": BuildPy})
