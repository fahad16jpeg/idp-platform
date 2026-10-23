"""platform - Internal Developer Platform CLI.

Scaffolds a FastAPI service with Docker, Terraform (Azure Container Apps),
GitHub Actions CI/CD, tests and monitoring.

    platform create my-api
    platform create my-api --region westeurope --python-version 3.13
    platform doctor
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from idp_platform import __version__

TEMPLATE = "fastapi-service"

# Service names end up in Azure resource names. Container App names allow at most
# 32 characters ("ca-<name>-<env>"), lowercase letters, digits and single hyphens.
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,18}[a-z0-9]$")
REGION_RE = re.compile(r"^[a-z][a-z0-9]{2,30}$")
PLACEHOLDER_RE = re.compile(r"__[A-Z][A-Z0-9_]*__")

PYTHON_VERSIONS = ("3.11", "3.12", "3.13")
ACR_SKUS = ("Basic", "Standard", "Premium")

# Template files whose names start with "dot-" are written with a leading "."
# (packaging tools often drop real dotfiles such as .github or .gitignore).
DOT_PREFIX = "dot-"
EXECUTABLE_SUFFIXES = (".sh",)


class PlatformError(Exception):
    """A user-facing error: printed without a traceback."""


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #


def validate_name(name: str) -> str:
    if not NAME_RE.match(name) or "--" in name:
        raise PlatformError(
            f"invalid service name {name!r}: use 3-20 characters of lowercase letters, "
            "digits and single hyphens, starting with a letter (e.g. 'orders-api')"
        )
    return name


def validate_region(region: str) -> str:
    if not REGION_RE.match(region):
        raise PlatformError(
            f"invalid Azure region {region!r}: use the short name, e.g. 'uksouth' or 'westeurope'"
        )
    return region


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #


def template_root() -> Traversable:
    return resources.files("idp_platform") / "templates" / TEMPLATE


def target_name(name: str) -> str:
    return "." + name[len(DOT_PREFIX) :] if name.startswith(DOT_PREFIX) else name


def render(text: str, context: dict[str, str], source: str) -> str:
    for key, value in context.items():
        text = text.replace(key, value)
    leftover = sorted(set(PLACEHOLDER_RE.findall(text)))
    if leftover:
        raise PlatformError(f"template bug: unresolved placeholders {leftover} in {source}")
    return text


def render_tree(src: Traversable, dest: Path, context: dict[str, str]) -> list[Path]:
    written: list[Path] = []
    for item in sorted(src.iterdir(), key=lambda t: t.name):
        if item.name == "__pycache__" or item.name.endswith((".pyc", ".pyo")):
            continue
        out = dest / target_name(item.name)
        if item.is_dir():
            out.mkdir(parents=True, exist_ok=True)
            written += render_tree(item, out, context)
            continue
        content = render(item.read_text(encoding="utf-8"), context, item.name)
        # Always UTF-8 with LF endings, so files are identical on Windows and
        # shell scripts / Dockerfiles work inside Linux containers and CI.
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        if out.suffix in EXECUTABLE_SUFFIXES:
            out.chmod(0o755)
        written.append(out)
    return written


def build_context(name: str, region: str, python_version: str, acr_sku: str) -> dict[str, str]:
    return {
        "__PROJECT_NAME__": name,
        "__PYTHON_VERSION__": python_version,
        "__AZURE_REGION__": region,
        "__ACR_SKU__": acr_sku,
    }


def create_project(
    name: str,
    output_dir: Path,
    region: str = "uksouth",
    python_version: str = "3.12",
    acr_sku: str = "Basic",
) -> Path:
    """Render the template into output_dir/name. Nothing is left behind on failure."""
    validate_name(name)
    validate_region(region)
    if python_version not in PYTHON_VERSIONS:
        raise PlatformError(f"unsupported Python version {python_version!r}")
    if acr_sku not in ACR_SKUS:
        raise PlatformError(f"unsupported ACR SKU {acr_sku!r}")

    output_dir = output_dir.resolve()
    dest = output_dir / name
    if dest.exists():
        raise PlatformError(f"'{dest}' already exists; choose another name or remove it first")
    output_dir.mkdir(parents=True, exist_ok=True)

    context = build_context(name, region, python_version, acr_sku)
    staging = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=output_dir))
    try:
        render_tree(template_root(), staging, context)
        staging.rename(dest)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return dest


# --------------------------------------------------------------------------- #
# output helpers
# --------------------------------------------------------------------------- #


def _supports(text: str) -> bool:
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        text.encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def format_tree(root: Path, max_depth: int = 2) -> str:
    """Directory tree; falls back to ASCII on consoles that can't print box characters."""
    tee, last, pipe = ("├── ", "└── ", "│   ") if _supports("├└│") else ("|-- ", "`-- ", "|   ")
    lines = [f"{root.name}/"]

    def walk(directory: Path, prefix: str, depth: int) -> None:
        entries = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        for index, entry in enumerate(entries):
            is_last = index == len(entries) - 1
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{prefix}{last if is_last else tee}{entry.name}{suffix}")
            if entry.is_dir() and entry.name != ".git" and depth < max_depth:
                walk(entry, prefix + ("    " if is_last else pipe), depth + 1)

    walk(root, "", 1)
    return "\n".join(lines)


def init_git(path: Path) -> str:
    """Initialise a repo with one commit. Returns a status message; never raises."""
    if not shutil.which("git"):
        return "git not found - skipped repository initialisation"
    try:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
        subprocess.run(["git", "add", "-A"], cwd=path, check=True)
        commit = subprocess.run(
            ["git", "commit", "-q", "-m", "Initial scaffold from platform"],
            cwd=path,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"git initialisation failed ({exc}); run 'git init' yourself"
    if commit.returncode != 0:
        return (
            "git repository initialised, but the first commit failed - set your identity with "
            "'git config --global user.name ...' and 'git config --global user.email ...', "
            "then run 'git commit -m \"Initial scaffold\"'"
        )
    return "git repository initialised on branch 'main' with an initial commit"


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #


def cmd_create(args: argparse.Namespace) -> int:
    dest = create_project(
        args.name,
        Path(args.output_dir),
        region=args.region,
        python_version=args.python_version,
        acr_sku=args.acr_sku,
    )
    print(f"Created {dest}\n")
    print(format_tree(dest))
    if not args.no_git:
        print(f"\n{init_git(dest)}")

    activate = r".venv\Scripts\activate" if os.name == "nt" else "source .venv/bin/activate"
    print(
        f"""
Next steps
  cd {dest.name}
  python -m venv .venv && {activate}
  pip install -r requirements-dev.txt
  pytest                          # run the tests
  docker compose up --build       # run locally on http://localhost:8000

Deploy to Azure: follow "First-time deployment setup" in {dest.name}/README.md
"""
    )
    return 0


TOOLS = (
    ("python", "run the service and tests", [sys.executable, "--version"]),
    ("git", "version control", ["git", "--version"]),
    ("docker", "build and run containers", ["docker", "--version"]),
    ("terraform", "plan Azure infrastructure locally", ["terraform", "-version"]),
    ("az", "Azure CLI, needed once for bootstrap", ["az", "version", "-o", "tsv"]),
    ("gh", "GitHub CLI, optional: bootstrap sets repo variables with it", ["gh", "--version"]),
)


def cmd_doctor(_: argparse.Namespace) -> int:
    missing = 0
    for name, purpose, command in TOOLS:
        if name != "python" and not shutil.which(command[0]):
            print(f"  [missing] {name:<10} {purpose}")
            missing += 1
            continue
        try:
            out = subprocess.run(command, capture_output=True, text=True, timeout=20)
            version = (out.stdout or out.stderr).strip().splitlines()[0]
        except (OSError, subprocess.SubprocessError, IndexError):
            version = "installed (version unknown)"
        print(f"  [ok]      {name:<10} {version}")
    print("\nAll tools found." if not missing else f"\n{missing} tool(s) missing.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="platform", description="Internal Developer Platform CLI")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="scaffold a new FastAPI service")
    create.add_argument("name", help="service name, e.g. orders-api (also the folder name)")
    create.add_argument("--region", default="uksouth", help="Azure region (default: uksouth)")
    create.add_argument(
        "--python-version", default="3.12", choices=PYTHON_VERSIONS, help="default: 3.12"
    )
    create.add_argument("--acr-sku", default="Basic", choices=ACR_SKUS, help="default: Basic")
    create.add_argument("--output-dir", default=".", help="where to create the service folder")
    create.add_argument("--no-git", action="store_true", help="don't initialise a git repo")
    create.set_defaults(func=cmd_create)

    doctor = sub.add_parser("doctor", help="check that the required tools are installed")
    doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except PlatformError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
