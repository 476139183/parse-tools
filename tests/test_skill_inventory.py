import importlib.util
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops/skills/ljt-repo-architect/scripts/inventory.py"
spec = importlib.util.spec_from_file_location("ljt_inventory", SCRIPT)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)

classify_path = inventory.classify_path


def test_classify_entrypoints():
    assert classify_path(PurePosixPath("main.py")) == "entrypoints"
    assert classify_path(PurePosixPath("app_mp.py")) == "entrypoints"


def test_classify_backend_package():
    assert classify_path(PurePosixPath("parse_tools/platforms/douyin/douyin.py")) == "backend"


def test_classify_frontend():
    assert classify_path(PurePosixPath("parse_tools/frontend/js/api.js")) == "frontend"


def test_classify_injection():
    assert classify_path(PurePosixPath("ops/injection/src/feed.js")) == "injection"


def test_classify_vendored_subtitle_remover():
    assert classify_path(PurePosixPath("ops/vendor/subtitle_remover/x.py")) == "vendored"


def test_classify_vendored_injection_lib():
    assert classify_path(PurePosixPath("ops/injection/lib/x.js")) == "vendored"


def test_classify_vendored_graphify_out():
    assert classify_path(PurePosixPath("graphify-out/graph.json")) == "vendored"


def test_classify_docs():
    assert classify_path(PurePosixPath("ops/docs/design.md")) == "docs"


def test_classify_build():
    assert classify_path(PurePosixPath(".github/workflows/build.yml")) == "build"
    assert classify_path(PurePosixPath("ops/packaging/parse_tools.spec")) == "build"


def test_classify_other():
    assert classify_path(PurePosixPath("LICENSE")) == "other"
    assert classify_path(PurePosixPath("README.md")) == "other"


def test_classify_none_for_ignored():
    assert classify_path(PurePosixPath("__pycache__/x.py")) is None
    assert classify_path(PurePosixPath("data/secret.json")) is None
    assert classify_path(PurePosixPath("build/output.exe")) is None


def test_cli_json_output():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(ROOT), "--json"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert data["root"].startswith("/"), "root must be absolute"
    assert len(data["tracked_files"]) > 50, f"expected >50 files, got {len(data['tracked_files'])}"
    groups = data["groups"]
    assert any(f.startswith("parse_tools/") for f in groups["backend"])
    assert "vendored" in groups
    assert any(f.startswith("ops/vendor/subtitle_remover/") for f in groups["vendored"])
    assert any(f.startswith("ops/injection/lib/") for f in groups["vendored"])
    for group_name, files in groups.items():
        for f in files:
            assert not f.startswith("graphify-out/"), f"graphify-out found in {group_name}: {f}"
