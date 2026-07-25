import pytest
from src.utils.filters import should_include_file, detect_language
from src.utils.github_api import parse_github_url


class TestParseGithubUrl:

    def test_standard_url(self):
        owner, repo = parse_github_url("https://github.com/tiangolo/fastapi")
        assert owner == "tiangolo"
        assert repo == "fastapi"

    def test_trailing_slash(self):
        owner, repo = parse_github_url("https://github.com/tiangolo/fastapi/")
        assert owner == "tiangolo"
        assert repo == "fastapi"

    def test_git_extension(self):
        owner, repo = parse_github_url("https://github.com/tiangolo/fastapi.git")
        assert owner == "tiangolo"
        assert repo == "fastapi"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError):
            parse_github_url("https://github.com/onlyone")


class TestShouldIncludeFile:

    def test_includes_python(self):
        assert should_include_file("src/main.py", 1000) is True

    def test_includes_typescript(self):
        assert should_include_file("src/index.ts", 2000) is True

    def test_excludes_node_modules(self):
        assert should_include_file("node_modules/lodash/index.js", 100) is False

    def test_excludes_pycache(self):
        assert should_include_file("src/__pycache__/utils.cpython-311.pyc", 500) is False

    def test_excludes_lock_file_by_name(self):
        assert should_include_file("package-lock.json", 50000) is False

    def test_excludes_large_file(self):
        assert should_include_file("src/big_generated.py", 200_000) is False

    def test_excludes_unknown_extension(self):
        assert should_include_file("Makefile", 500) is False

    def test_excludes_nested_venv(self):
        assert should_include_file("backend/venv/lib/requests/api.py", 3000) is False

    def test_includes_go_file(self):
        assert should_include_file("cmd/server/main.go", 1500) is True

    def test_includes_yaml(self):
        assert should_include_file(".github/workflows/ci.yml", 800) is True


class TestDetectLanguage:

    def test_python(self):
        assert detect_language("src/utils.py") == "Python"

    def test_typescript(self):
        assert detect_language("components/Button.tsx") == "TypeScript"

    def test_javascript(self):
        assert detect_language("scripts/build.mjs") == "JavaScript"

    def test_go(self):
        assert detect_language("internal/server.go") == "Go"

    def test_markdown(self):
        assert detect_language("docs/README.md") == "Markdown"

    def test_unknown_extension(self):
        assert detect_language("Dockerfile") == "Unknown"

    def test_case_insensitive(self):
        assert detect_language("src/Main.PY") == "Python"