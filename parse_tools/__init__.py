"""Parse Tools — multi-platform content parse & download toolbox."""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

APP_NAME = "Parse Tools"
APP_SLUG = "parse-tools"
APP_VERSION = "3.0.0"

__all__ = [
    "APP_NAME",
    "APP_SLUG",
    "APP_VERSION",
    "PACKAGE_DIR",
    "PROJECT_ROOT",
]
