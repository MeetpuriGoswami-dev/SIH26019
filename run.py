#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bhumi-Niti (भूमि-नीति) — Universal Startup Runner
National Digital Platform for Evidence-Based Land Governance
DoLR, Ministry of Rural Development | SIH Problem Statement 26019
─────────────────────────────────────────────────────────────────
Usage:  python run.py
"""

import sys
import os

# Ensure UTF-8 output on Windows (Python 3.7+ reconfigure)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass  # Python < 3.7 fallback
import subprocess
import importlib
import time
import threading
import webbrowser

# ─── ANSI colour helpers ───────────────────────────────────────────────────────
def _c(code: str, text: str) -> str:
    """Wrap text in ANSI colour code (auto-stripped on Windows without ANSI support)."""
    return f"\033[{code}m{text}\033[0m"

CYAN   = lambda t: _c("96", t)
GREEN  = lambda t: _c("92", t)
YELLOW = lambda t: _c("93", t)
RED    = lambda t: _c("91", t)
BOLD   = lambda t: _c("1",  t)
DIM    = lambda t: _c("2",  t)


# ─── ASCII Banner ──────────────────────────────────────────────────────────────
BANNER = r"""
  ██████╗ ██╗  ██╗██╗   ██╗███╗   ███╗██╗      ███╗   ██╗██╗████████╗██╗
  ██╔══██╗██║  ██║██║   ██║████╗ ████║██║      ████╗  ██║██║╚══██╔══╝██║
  ██████╔╝███████║██║   ██║██╔████╔██║██║█████╗██╔██╗ ██║██║   ██║   ██║
  ██╔══██╗██╔══██║██║   ██║██║╚██╔╝██║██║╚════╝██║╚██╗██║██║   ██║   ██║
  ██████╔╝██║  ██║╚██████╔╝██║ ╚═╝ ██║██║      ██║ ╚████║██║   ██║   ██║
  ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝╚═╝      ╚═╝  ╚═══╝╚═╝   ╚═╝   ╚═╝
"""

def print_banner() -> None:
    # Enable ANSI on Windows 10+
    if sys.platform == "win32":
        os.system("")

    print(CYAN(BANNER))
    print(BOLD("  भूमि-नीति  |  National Digital Platform for Evidence-Based Land Governance"))
    print(DIM("  Ministry of Rural Development (DoLR)  |  SIH Problem Statement 26019"))
    print()
    print("  " + "─" * 66)
    print(f"  {BOLD('Service URL')}        →  {GREEN('http://localhost:8000')}")
    print(f"  {BOLD('Swagger API Docs')}   →  {CYAN('http://localhost:8000/docs')}")
    print(f"  {BOLD('Knowledge Base')}     →  {CYAN('http://localhost:8000/knowledge-base')}")
    print("  " + "─" * 66)
    print()


# ─── Pre-flight: Python version ────────────────────────────────────────────────
def check_python_version() -> None:
    major, minor = sys.version_info[:2]
    version_str = f"Python {major}.{minor}.{sys.version_info[2]}"
    if (major, minor) < (3, 10):
        print(RED(f"✗  {version_str} detected — Bhumi-Niti requires Python 3.10 or newer."))
        print(YELLOW("   Please upgrade: https://www.python.org/downloads/"))
        sys.exit(1)
    print(GREEN(f"✔  {version_str}"))


# ─── Pre-flight: virtual environment ───────────────────────────────────────────
def check_venv() -> None:
    in_venv = (
        os.environ.get("VIRTUAL_ENV")
        or os.environ.get("CONDA_DEFAULT_ENV")
        or hasattr(sys, "real_prefix")
        or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)
    )
    if in_venv:
        label = os.environ.get("VIRTUAL_ENV") or os.environ.get("CONDA_DEFAULT_ENV") or "active"
        print(GREEN(f"✔  Virtual environment active  ({label})"))
    else:
        print(YELLOW("⚠  No virtual environment detected."))
        print(YELLOW("   It is strongly recommended to run inside a venv:"))
        print(YELLOW("     python -m venv venv"))
        if sys.platform == "win32":
            print(YELLOW(r"     venv\Scripts\activate"))
        else:
            print(YELLOW("     source venv/bin/activate"))
        print()
        # Non-fatal: allow continuation
        print(DIM("   Continuing in global Python environment …"))


# ─── Pre-flight: required packages ────────────────────────────────────────────
REQUIRED_PACKAGES = {
    "fastapi":    "fastapi",
    "uvicorn":    "uvicorn",
    "requests":   "requests",
    "pydantic":   "pydantic",
    "shapely":    "shapely",
    "httpx":      "httpx",
}

def check_packages() -> None:
    missing = []
    for import_name, pip_name in REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(import_name)
            print(GREEN(f"✔  {pip_name}"))
        except ImportError:
            print(RED(f"✗  {pip_name}  (missing)"))
            missing.append(pip_name)

    if missing:
        print()
        print(RED("  ✗  Missing dependencies detected:  " + ", ".join(missing)))
        print(YELLOW("  ▶  Run the following command to install all requirements:"))
        print()
        print(BOLD("       pip install -r requirements.txt"))
        print()
        sys.exit(1)


# ─── Pre-flight: project structure ────────────────────────────────────────────
def check_project_structure() -> None:
    required_files = ["main.py", "requirements.txt", "engine/pipeline.py"]
    root = os.path.dirname(os.path.abspath(__file__))
    all_ok = True
    for f in required_files:
        path = os.path.join(root, f)
        if not os.path.exists(path):
            print(RED(f"✗  Required file not found: {f}"))
            all_ok = False
    if not all_ok:
        print(RED("  Project structure check failed. Are you in the correct directory?"))
        sys.exit(1)
    print(GREEN("✔  Project structure OK"))


# ─── Auto-browser launch (deferred) ───────────────────────────────────────────
def _open_browser_after_delay(url: str, delay: float = 1.5) -> None:
    time.sleep(delay)
    try:
        webbrowser.open_new_tab(url)
    except Exception:
        pass  # Non-critical

def schedule_browser_open(url: str = "http://localhost:8000", delay: float = 1.5) -> None:
    t = threading.Thread(target=_open_browser_after_delay, args=(url, delay), daemon=True)
    t.start()


# ─── Main entry point ─────────────────────────────────────────────────────────
def main() -> None:
    # Step 0: Banner
    print_banner()

    # Step 1: Pre-flight checks
    print(BOLD("  ▶  Running pre-flight checks …"))
    print()
    check_python_version()
    check_venv()
    check_packages()
    check_project_structure()

    print()
    print(GREEN("  ✔  All checks passed. Starting Bhumi-Niti server …"))
    print()
    print("  " + "─" * 66)
    print(f"  {BOLD('Press Ctrl+C to stop the server')}")
    print("  " + "─" * 66)
    print()

    # Step 2: Schedule browser open after 1.5 s
    schedule_browser_open("http://localhost:8000", delay=1.5)

    # Step 3: Launch Uvicorn (replaces current process — clean signal handling)
    # Change cwd to project root so relative imports work
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)

    try:
        import uvicorn
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            reload_dirs=[root],
            log_level="info",
        )
    except KeyboardInterrupt:
        print()
        print(YELLOW("  ⏹  Bhumi-Niti server stopped."))
        sys.exit(0)


if __name__ == "__main__":
    main()
