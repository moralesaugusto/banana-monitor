#!/usr/bin/env python3
"""Single command to start Banana after a `git pull`.

Rebuilds the frontend if its source changed since the last build, then hands
off to the backend (`uv run banana`), which syncs its own virtualenv from the
lockfile and applies every pending database migration on startup by itself -
neither needs a manual `make build`/`make migrate` step first.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend"


def newest_mtime(*paths: Path) -> float:
    newest = 0.0
    for path in paths:
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
        elif path.is_dir():
            for file in path.rglob("*"):
                if file.is_file():
                    newest = max(newest, file.stat().st_mtime)
    return newest


def run(cmd: list[str], cwd: Path) -> None:
    print(f"+ {' '.join(cmd)}  (in {cwd.relative_to(ROOT)})", flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def build_frontend_if_needed() -> None:
    lockfile = FRONTEND / "package-lock.json"
    install_marker = FRONTEND / "node_modules" / ".package-lock.json"
    if not install_marker.is_file() or lockfile.stat().st_mtime > install_marker.stat().st_mtime:
        run(["npm", "install"], cwd=FRONTEND)

    dist_index = FRONTEND / "dist" / "index.html"
    source_mtime = newest_mtime(
        FRONTEND / "src",
        FRONTEND / "public",
        FRONTEND / "index.html",
        FRONTEND / "package.json",
        lockfile,
        FRONTEND / "vite.config.ts",
        FRONTEND / "tsconfig.json",
        FRONTEND / "tsconfig.app.json",
        FRONTEND / "tsconfig.node.json",
    )
    if not dist_index.is_file() or source_mtime > dist_index.stat().st_mtime:
        run(["npm", "run", "build"], cwd=FRONTEND)
    else:
        print("Frontend is up to date, skipping build.")


def main() -> None:
    build_frontend_if_needed()
    print("+ uv run banana  (in backend)", flush=True)
    os.chdir(BACKEND)
    os.execvp("uv", ["uv", "run", "banana"])


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
