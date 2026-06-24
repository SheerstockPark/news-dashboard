"""newsdash — shared modules for the oil-trading news dashboard.

Importable by both tools/ scripts and the Streamlit dashboard. Keeps deterministic
logic (config loading, DB access, relevance tagging) in one place so tools stay thin.
"""

from pathlib import Path

# Repo root = two levels up from this file (src/newsdash/__init__.py -> repo/).
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "db"
DB_PATH = DATA_DIR / "news.sqlite"
CONFIG_PATH = REPO_ROOT / "config" / "sources.yaml"
