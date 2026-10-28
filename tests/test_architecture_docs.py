from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "ops" / "docs"
ARCHITECTURE = DOCS / "ARCHITECTURE.md"
LEARNING_PATH = DOCS / "CODE_LEARNING_PATH.md"
DIAGRAM_SOURCES = (
    "ops/docs/diagrams/software-architecture.mmd",
    "ops/docs/diagrams/application-flow.mmd",
    "ops/docs/diagrams/build-flow.mmd",
)
UNFINISHED_MARKERS = ("TODO", "FIXME", "待补", "待完成", "未完成")


def _read(path: Path) -> str:
    assert path.is_file(), f"missing document: {path}"
    return path.read_text(encoding="utf-8")


def test_architecture_guide_covers_required_modules_and_concepts():
    text = _read(ARCHITECTURE)

    required_topics = {
        "main.py": "桌面入口",
        "app.py": "Flask 应用",
        "parse_tools/core": "核心包",
        "TaskStore": "统一任务层",
        "frontend/": "前端",
        "ops/injection/src/": "视频号页面注入",
        "ops/packaging/parse_tools.spec": "桌面打包",
        "ops/vendor/subtitle_remover/": "vendored",
        "数据目录": "本地状态与文件",
        # historical aliases kept in doc for searchability
        "backend/config.py": "配置别名",
        "backend/runtime.py": "运行时别名",
        "backend/account_pool.py": "账号池别名",
        "backend/rss_scheduler.py": "RSS 别名",
        "backend/mitm_proxy.py": "mitm 别名",
        "backend/transcode.py": "转码别名",
        "蓝图": "API 分层",
    }
    for token, meaning in required_topics.items():
        assert token in text, f"architecture guide does not explain {meaning}: {token}"

    for heading in (
        "模块地图",
        "请求流",
        "启动流",
        "后台工作",
        "存储",
        "构建与自动化",
        "扩展路径",
        "Bug 路由",
    ):
        assert heading in text, f"architecture guide missing section: {heading}"


def test_architecture_guide_describes_runtime_and_build_flows():
    text = _read(ARCHITECTURE)
    for token, meaning in {
        "create_app": "应用工厂",
        "TaskStore": "任务层",
        "ops/packaging/parse_tools.spec": "PyInstaller",
        ".github/workflows/build.yml": "GitHub Actions",
        "macOS ARM64": "ARM64",
        "macOS x86_64": "x86_64",
    }.items():
        assert token in text, f"architecture guide does not explain {meaning}: {token}"


def test_both_documents_link_all_three_diagram_sources():
    for path in (ARCHITECTURE, LEARNING_PATH):
        text = _read(path)
        for diagram in DIAGRAM_SOURCES:
            assert f"]({diagram})" in text, f"{path.name} does not link {diagram}"


def test_learning_path_has_five_staged_exercises_with_commands_and_observations():
    text = _read(LEARNING_PATH)
    assert text.count("## 练习 1：") >= 1
    for number in range(2, 6):
        assert f"## 练习 {number}：" in text
    assert text.count("```bash") >= 5
    assert text.count("**预期观察**") >= 5


def test_learning_path_names_exact_entry_points_and_debug_destinations():
    text = _read(LEARNING_PATH)
    # Learning path may still mention legacy names; ensure key entry points exist
    for path in ("main.py", "app.py", "frontend/js/router.js", "frontend/js/api.js"):
        assert path in text, f"learning path does not reference {path}"


def test_documents_do_not_contain_unfinished_work_markers():
    for path in (ARCHITECTURE, LEARNING_PATH):
        text = _read(path)
        for marker in UNFINISHED_MARKERS:
            assert marker not in text, f"{path.name} contains unfinished marker: {marker}"
