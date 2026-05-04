"""Config layer: pydantic schemas + YAML loaders.

Every value crossing the YAML boundary is parsed here before entering the
typed core (see ARCHITECTURE.md "Boundary parsing").
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config"
