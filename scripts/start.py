"""Cross-platform, native bootstrap used by start.sh and start.bat."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    # npm is a .cmd launcher on Windows. Arguments here are fixed, not browser input.
    subprocess.run(
        command, cwd=cwd, env=env, check=True, shell=os.name == "nt" and command[0].endswith(".cmd")
    )


def main() -> int:
    if sys.version_info < (3, 11):  # noqa: UP036 - bootstrap can be invoked with an older interpreter
        raise SystemExit("Folio benötigt Python 3.11 oder neuer.")
    parser = argparse.ArgumentParser(description="Folio ohne Docker installieren, bauen und starten.")
    parser.add_argument(
        "--demo", action="store_true", help="Optionale Demobilder in einer leeren Bibliothek anlegen"
    )
    parser.add_argument(
        "--skip-install", action="store_true", help="Bereits installierte Abhängigkeiten verwenden"
    )
    parser.add_argument("--no-build", action="store_true", help="Vorhandenes Frontend-Build verwenden")
    parser.add_argument("--base-path", help="Basis-Pfad für die Bildbibliothek")
    parser.add_argument("--host", help="Server-Bind-Adresse (Standard: config.yaml)")
    parser.add_argument("--port", type=int, help="Server-Port (Standard: config.yaml)")
    args = parser.parse_args()
    os.chdir(ROOT)
    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        if args.skip_install:
            raise SystemExit("Keine .venv vorhanden. Bitte einmal ohne --skip-install starten.")
        print("[1/4] Python-Umgebung wird angelegt …", flush=True)
        venv.EnvBuilder(with_pip=True).create(ROOT / ".venv")
    run(
        [
            str(python),
            "-c",
            "import sys; assert sys.version_info >= (3,11), 'Die .venv benötigt Python 3.11+'",
        ]
    )
    if not args.skip_install:
        print("[1/4] Python-Abhängigkeiten installieren …", flush=True)
        run([str(python), "-m", "pip", "install", "-r", "requirements.txt"])
    frontend = ROOT / "frontend"
    if not args.no_build:
        npm = shutil.which("npm")
        node = shutil.which("node")
        if not npm or not node:
            raise SystemExit(
                "Bitte Node.js 22.12+ (oder 20.19+) mit npm installieren. Für ein vorhandenes Build: --no-build."
            )
        version = subprocess.check_output([node, "--version"], text=True).strip().lstrip("v")
        major, minor, *_ = (int(part) for part in version.split("."))
        if not ((major == 20 and minor >= 19) or (major == 22 and minor >= 12) or major > 22):
            raise SystemExit("Vite benötigt Node.js 20.19+ oder 22.12+. Empfohlen: aktuelles Node.js LTS.")
        if not args.skip_install:
            print("[2/4] Frontend-Abhängigkeiten installieren …", flush=True)
            run([npm, "ci"], cwd=frontend)
        print("[2/4] Vue-Frontend bauen …", flush=True)
        run([npm, "run", "build"], cwd=frontend)
    elif not (frontend / "dist/index.html").is_file():
        raise SystemExit("Kein Frontend-Build gefunden. Bitte einmal ohne --no-build starten.")
    environment = os.environ.copy()
    if args.base_path:
        environment["IMAGE_SORTER_BASE_PATH"] = str(Path(args.base_path).expanduser().resolve())
    if args.host:
        environment["HOST"] = args.host
    if args.port is not None:
        if not 1 <= args.port <= 65535:
            raise SystemExit("Ungültiger Port.")
        environment["PORT"] = str(args.port)
    if args.demo:
        print("[3/4] Demo-Bibliothek vorbereiten …", flush=True)
        run([str(python), "scripts/seed_demo.py"], env=environment)
    print("[4/4] Folio startet. Standardadresse: http://127.0.0.1:8000 · Beenden mit Strg+C", flush=True)
    command = [str(python), "-m", "backend"]
    if os.name != "nt":
        os.execvpe(command[0], command, environment)
    run(command, env=environment)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(
            f"Start abgebrochen (Exit-Code {exc.returncode}). Bitte die Fehlermeldung oben prüfen.",
            file=sys.stderr,
        )
        raise SystemExit(exc.returncode)
    except KeyboardInterrupt:
        raise SystemExit(130)
