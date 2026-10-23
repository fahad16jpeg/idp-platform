"""Tests for the platform CLI and static checks on the project it generates.

Runs with the standard library alone (python -m unittest discover -s tests);
PyYAML and Starlette are used when available.
"""

import ast
import asyncio
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from idp_platform import cli

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def generate(tmp: Path, name: str = "orders-api", **kwargs) -> Path:
    return cli.create_project(name, tmp, **kwargs)


class NameValidationTests(unittest.TestCase):
    def test_accepts_valid_names(self):
        for name in ("abc", "orders-api", "my-api-2", "a" * 20):
            self.assertEqual(cli.validate_name(name), name)

    def test_rejects_invalid_names(self):
        for name in ("", "ab", "My-Api", "1api", "api-", "-api", "my_api", "a--b", "a" * 21, "my api"):
            with self.assertRaises(cli.PlatformError, msg=name):
                cli.validate_name(name)

    def test_rejects_bad_region(self):
        with self.assertRaises(cli.PlatformError):
            cli.validate_region("UK South")


class CreateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_generates_expected_layout(self):
        root = generate(self.tmp)
        for rel in (
            "app/main.py",
            "app/routers/health.py",
            "tests/test_items.py",
            "Dockerfile",
            "docker-compose.yml",
            "requirements.txt",
            "README.md",
            ".gitignore",
            ".gitattributes",
            ".dockerignore",
            ".env.example",
            ".github/workflows/pipeline.yml",
            ".github/workflows/test.yml",
            ".github/workflows/build.yml",
            ".github/workflows/deploy.yml",
            ".github/actions/terraform-setup/action.yml",
            "terraform/container_app.tf",
            "scripts/bootstrap-azure.sh",
        ):
            self.assertTrue((root / rel).is_file(), rel)
        self.assertFalse(list(root.rglob("dot-*")), "dot- prefixes must be renamed")
        self.assertFalse(list(root.rglob("__pycache__")))

    def test_placeholders_substituted(self):
        root = generate(self.tmp, region="westeurope", python_version="3.13", acr_sku="Standard")
        for path in root.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(cli.PLACEHOLDER_RE.search(text), path)
        self.assertIn('default     = "westeurope"', (root / "terraform/variables.tf").read_text())
        self.assertIn("PYTHON_VERSION=3.13", (root / "Dockerfile").read_text())
        self.assertIn('default     = "Standard"', (root / "terraform/variables.tf").read_text())

    def test_files_are_utf8_with_lf_endings(self):
        root = generate(self.tmp)
        for path in root.rglob("*"):
            if path.is_file():
                data = path.read_bytes()
                self.assertNotIn(b"\r\n", data, path)
                data.decode("utf-8")

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_shell_scripts_are_executable(self):
        root = generate(self.tmp)
        self.assertTrue(os.access(root / "scripts/bootstrap-azure.sh", os.X_OK))

    def test_refuses_existing_directory_and_leaves_nothing_behind(self):
        (self.tmp / "orders-api").mkdir()
        with self.assertRaises(cli.PlatformError):
            generate(self.tmp)
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["orders-api"])

    def test_failed_render_removes_staging_directory(self):
        original = cli.render

        def broken(text, context, source):
            if source == "Dockerfile":
                raise cli.PlatformError("boom")
            return original(text, context, source)

        cli.render = broken
        try:
            with self.assertRaises(cli.PlatformError):
                generate(self.tmp)
        finally:
            cli.render = original
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_main_reports_errors_without_traceback(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = cli.main(["create", "Bad_Name", "--output-dir", str(self.tmp)])
        self.assertEqual(code, 1)
        self.assertIn("invalid service name", err.getvalue())

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_main_creates_project_and_git_repo(self):
        out = io.StringIO()
        env = {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        with unittest.mock.patch.dict(os.environ, env), redirect_stdout(out):
            code = cli.main(["create", "orders-api", "--output-dir", str(self.tmp)])
        self.assertEqual(code, 0)
        root = self.tmp / "orders-api"
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.split()
        self.assertIn(".github/workflows/pipeline.yml", tracked)
        self.assertIn("Next steps", out.getvalue())

    def test_tree_falls_back_to_ascii(self):
        root = generate(self.tmp)
        fake = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with unittest.mock.patch.object(sys, "stdout", fake):
            tree = cli.format_tree(root)
        tree.encode("cp1252")  # must not raise on a Windows console
        self.assertIn("|-- ", tree)


class GeneratedPythonTests(unittest.TestCase):
    """Approximates `ruff check` (E, F, W rules) for the generated code."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.root = generate(cls.tmp)
        cls.py_files = sorted(cls.root.rglob("*.py"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_compiles(self):
        for path in self.py_files:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_style(self):
        for path in self.py_files:
            text = path.read_text(encoding="utf-8")
            if text:
                self.assertTrue(text.endswith("\n") and not text.endswith("\n\n"), path)
            for n, line in enumerate(text.splitlines(), 1):
                self.assertLessEqual(len(line), 100, f"{path}:{n}")
                self.assertEqual(line, line.rstrip(), f"{path}:{n} trailing whitespace")

    def test_no_unused_imports(self):
        for path in self.py_files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = {}
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        name = (alias.asname or alias.name).split(".")[0]
                        imported[name] = node.lineno
            used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            used |= {
                n.value.id
                for n in ast.walk(tree)
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            }
            for name, line in imported.items():
                self.assertIn(name, used, f"{path}:{line} unused import {name}")

    def test_json_formatter(self):
        module = load_module(self.root / "app/logging_config.py", "gen_logging_config")
        import json
        import logging

        record = logging.LogRecord("x", logging.WARNING, __file__, 1, "hi %s", ("there",), None)
        record.status_code = 503
        payload = json.loads(module.JsonFormatter().format(record))
        self.assertEqual(payload["message"], "hi there")
        self.assertEqual(payload["status_code"], 503)
        self.assertNotIn("args", payload)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Metric:
    def __init__(self, *args, **kwargs):
        self.values = {}

    def labels(self, *labels):
        metric = self

        class Child:
            def inc(self, amount=1):
                metric.values[labels] = metric.values.get(labels, 0) + amount

            def dec(self, amount=1):
                metric.values[labels] = metric.values.get(labels, 0) - amount

            def observe(self, value):
                metric.values.setdefault(labels, []).append(value)

            def set(self, value):
                metric.values[labels] = value

        return Child()


@unittest.skipUnless(importlib.util.find_spec("starlette"), "starlette not installed")
class MetricsMiddlewareTests(unittest.TestCase):
    """Exercises the generated middleware with prometheus_client replaced by a stub."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        root = generate(cls.tmp)
        stub = types.ModuleType("prometheus_client")
        stub.Counter = stub.Gauge = stub.Histogram = _Metric
        with unittest.mock.patch.dict(sys.modules, {"prometheus_client": stub}):
            cls.metrics = load_module(root / "app/metrics.py", "gen_metrics")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, app, route=None):
        scope = {"type": "http", "method": "GET", "path": "/api/v1/items/123"}
        sent = []

        async def receive():
            return {"type": "http.request"}

        async def send(message):
            sent.append(message)

        async def wrapped(scope, receive, send):
            if route is not None:
                scope["route"] = types.SimpleNamespace(path=route)  # what FastAPI's router does
            await app(scope, receive, send)

        middleware = self.metrics.MetricsMiddleware(wrapped)
        asyncio.run(middleware(scope, receive, send))
        return sent

    def test_labels_by_route_template(self):
        async def ok(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        self.call(ok, route="/api/v1/items/{item_id}")
        counts = self.metrics.REQUEST_COUNT.values
        self.assertIn(("GET", "/api/v1/items/{item_id}", "200"), counts)
        self.assertFalse(any("123" in key[1] for key in counts))

    def test_unmatched_and_errors(self):
        async def boom(scope, receive, send):
            raise RuntimeError("bug")

        with self.assertRaises(RuntimeError):
            self.call(boom)
        self.assertIn(("GET", "unmatched", "500"), self.metrics.REQUEST_COUNT.values)
        self.assertEqual(self.metrics.REQUESTS_IN_PROGRESS.values[("GET",)], 0)


class GeneratedConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.root = generate(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def yaml_files(self):
        return sorted(self.root.glob(".github/**/*.yml")) + [self.root / "docker-compose.yml"]

    @unittest.skipIf(yaml is None, "PyYAML not installed")
    def test_yaml_parses_and_local_references_exist(self):
        for path in self.yaml_files():
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertIsInstance(doc, dict, path)
        for path in self.root.glob(".github/workflows/*.yml"):
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            jobs = doc["jobs"]
            for job in jobs.values():
                for need in [job["needs"]] if isinstance(job.get("needs"), str) else job.get(
                    "needs", []
                ):
                    self.assertIn(need, jobs, f"{path.name}: unknown job {need}")
                uses = [job.get("uses")] + [s.get("uses") for s in job.get("steps", [])]
                for ref in filter(None, uses):
                    if ref.startswith("./"):
                        target = self.root / ref[2:]
                        self.assertTrue(
                            target.is_file() or (target / "action.yml").is_file(), ref
                        )

    @unittest.skipIf(yaml is None, "PyYAML not installed")
    def test_reusable_workflows_declare_workflow_call(self):
        pipeline = yaml.safe_load((self.root / ".github/workflows/pipeline.yml").read_text())
        for job in pipeline["jobs"].values():
            called = yaml.safe_load((self.root / job["uses"][2:]).read_text())
            # PyYAML parses the bare key `on` as True
            triggers = called.get("on", called.get(True))
            self.assertIn("workflow_call", triggers, job["uses"])

    @unittest.skipIf(yaml is None or not shutil.which("bash"), "needs PyYAML and bash")
    def test_shell_snippets_have_valid_syntax(self):
        scripts = [(p.name, p.read_text()) for p in self.root.glob("scripts/*.sh")]
        for path in self.root.glob(".github/**/*.yml"):
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            steps = [s for job in doc.get("jobs", {}).values() for s in job.get("steps", [])]
            steps += doc.get("runs", {}).get("steps", [])
            for step in steps:
                if "run" in step:
                    body = re.sub(r"\$\{\{.*?\}\}", "X", step["run"])
                    scripts.append((f"{path.name}: {step.get('name', '?')}", body))
        self.assertGreater(len(scripts), 8)
        for label, body in scripts:
            result = subprocess.run(["bash", "-n"], input=body, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{label}: {result.stderr}")

    def test_dockerfile(self):
        text = (self.root / "Dockerfile").read_text()
        self.assertEqual(len(re.findall(r"^FROM ", text, re.M)), 2, "multi-stage")
        user = re.findall(r"^USER (\S+)", text, re.M)
        self.assertTrue(user and not user[-1].startswith(("root", "0")), "non-root user")
        self.assertIn("HEALTHCHECK", text)
        instructions = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
        self.assertFalse([ln for ln in instructions if "curl" in ln], "no curl in the image")

    def test_dockerignore_allows_what_the_dockerfile_copies(self):
        ignore = (self.root / ".dockerignore").read_text()
        for path in re.findall(r"^COPY (?:--\S+ )*(\S+) ", (self.root / "Dockerfile").read_text(), re.M):
            if not path.startswith("/"):
                self.assertIn(f"!{path.rstrip('/')}", ignore.replace("/\n", "\n"), path)


class TerraformStaticTests(unittest.TestCase):
    """Without a terraform binary: references resolve and formatting matches `terraform fmt`."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        root = generate(cls.tmp)
        cls.files = {p.name: p.read_text() for p in sorted((root / "terraform").glob("*.tf"))}
        cls.all = "\n".join(cls.files.values())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_braces_balance(self):
        for name, text in self.files.items():
            stripped = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
            stripped = re.sub(r"#.*", "", stripped)
            self.assertEqual(stripped.count("{"), stripped.count("}"), name)
            self.assertEqual(stripped.count("["), stripped.count("]"), name)

    def test_references_resolve(self):
        declared_vars = set(re.findall(r'^variable "(\w+)"', self.all, re.M))
        declared_res = {
            f"{t}.{n}" for t, n in re.findall(r'^resource "(\w+)" "(\w+)"', self.all, re.M)
        }
        declared_locals = set(re.findall(r"^  (\w+)\s*=", "\n".join(
            block for block in re.findall(r"^locals \{\n(.*?)^\}", self.all, re.M | re.S)
        ), re.M))
        for ref in set(re.findall(r"\bvar\.(\w+)", self.all)):
            self.assertIn(ref, declared_vars, f"var.{ref}")
        for ref in set(re.findall(r"\blocal\.(\w+)", self.all)):
            self.assertIn(ref, declared_locals, f"local.{ref}")
        for ref in set(re.findall(r"\b((?:azurerm|random|time)_\w+\.\w+)", self.all)):
            self.assertIn(ref, declared_res, ref)
        unused = declared_vars - set(re.findall(r"\bvar\.(\w+)", self.all))
        self.assertEqual(unused, set(), "declared but unused variables")

    def test_fmt_alignment(self):
        """terraform fmt aligns `=` across consecutive single-line attributes."""
        attr = re.compile(r"^(\s*)([\w\"-]+)(\s*)= ")
        for name, text in self.files.items():
            group = []
            for line in text.splitlines() + [""]:
                m = attr.match(line)
                single = m and not line.rstrip().endswith(("{", "[", "("))
                if single and (not group or group[0][1] == m.group(1)):
                    group.append((line, m.group(1), m.group(2), m.group(3)))
                    continue
                if group:
                    width = max(len(g[2]) for g in group)
                    for g_line, _, key, space in group:
                        self.assertEqual(len(key) + len(space), width + 1, f"{name}: {g_line}")
                group = []
                if single:
                    group.append((line, m.group(1), m.group(2), m.group(3)))

    def test_two_space_indent(self):
        for name, text in self.files.items():
            for line in text.splitlines():
                indent = len(line) - len(line.lstrip(" "))
                self.assertEqual(indent % 2, 0, f"{name}: {line}")
                self.assertNotIn("\t", line)


if __name__ == "__main__":
    unittest.main()
