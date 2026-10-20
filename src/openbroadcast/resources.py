"""Documentation paths for both installed wheels and editable source checkouts."""
from pathlib import Path


def documentation_path(relative: str) -> Path:
    package = Path(__file__).resolve().parent
    installed = package / relative
    if installed.is_file():
        return installed
    # Editable installs read the same canonical documentation that builds copy.
    if package.parent.name == "src":
        checkout = package.parent.parent
        if (checkout / "pyproject.toml").is_file():
            return checkout / relative
    return installed
