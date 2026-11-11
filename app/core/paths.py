from pathlib import Path


def find_project_root(start: Path | None = None) -> Path:
    """Find the project root using pyproject.toml."""
    current = (start or Path(__file__)).resolve()

    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate

    raise RuntimeError(
        "Could not locate the project root: pyproject.toml was not found."
    )


try:
    PROJECT_ROOT = find_project_root()
except RuntimeError:
    # Installed wheels need not have the repository's pyproject.toml beside
    # site-packages. Use the caller's working directory for optional .env/data.
    PROJECT_ROOT = Path.cwd().resolve()

DATA_DIR = PROJECT_ROOT / "data"
SAMPLE_DOCS_DIR = PROJECT_ROOT / "sample_docs"
FRONTEND_DIR = PROJECT_ROOT / "frontend"


def resolve_frontend_dir() -> Path:
    """Return the project-root frontend directory, or package web fallback."""
    if FRONTEND_DIR.is_dir():
        return FRONTEND_DIR
    return Path(__file__).resolve().parents[1] / "web"
