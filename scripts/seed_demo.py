#!/usr/bin/env python3
"""Populate an empty library with optional, offline sample photos. Never overwrite."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import Settings  # noqa: E402

ASSETS = Path(__file__).resolve().parent / "demo_assets"


def seed_demo(base: Path) -> bool:
    base = base.expanduser().resolve()
    marker = base / ".folio-demo.json"
    if marker.is_file():
        print(f"Demo-Bibliothek bereits vorhanden; nichts wird zurückgesetzt: {base}")
        return False
    if base.exists() and (
        not base.is_dir() or any(path.is_file() or path.is_symlink() for path in base.rglob("*"))
    ):
        raise ValueError(
            "Demo wird nur in einem leeren Datenordner angelegt. Vorhandene Daten bleiben unberührt. Bitte einen neuen Basis-Pfad wählen."
        )
    manifest = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
    base.mkdir(parents=True, exist_ok=True)
    for i, item in enumerate(manifest):
        target = base / item["path"]
        if not target.resolve().is_relative_to(base):
            raise ValueError("Ungültiger Demo-Pfad.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with (ASSETS / item["asset"]).open("rb") as source, target.open("xb") as destination:
            shutil.copyfileobj(source, destination)
        # Deliberately varied dates make the date sort useful in the demo.
        timestamp = 1754006400 + i * 86400
        os.utime(target, (timestamp, timestamp))
    for source, destination in [
        ("zur_sortieren/02_lissabon_im_licht.jpg", "alben/Architektur/lissabon.jpg"),
        ("zur_sortieren/Unterwegs/07_waldspaziergang.jpg", "alben/Natur & Draußen/waldspaziergang.jpg"),
    ]:
        target = base / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        with (base / source).open("rb") as original, target.open("xb") as copy:
            shutil.copyfileobj(original, copy)
        shutil.copystat(base / source, target)
    for folder in ("duplikate", "trash", "temp/duplikat", "temp/trash"):
        (base / folder).mkdir(parents=True, exist_ok=True)
    with marker.open("x", encoding="utf-8") as handle:
        json.dump(
            {
                "description": "Optionale Folio-Demo, keine persönlichen Bilder",
                "source_images": 18,
                "exact_duplicates": 2,
                "credits": "scripts/demo_assets/CREDITS.md",
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
    print(f"Demo bereit: 18 Eingangsbilder, 5 Alben, 2 exakte Duplikate.\n{base}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-path", type=Path, help="Optionaler, leerer Demo-Basis-Pfad; sonst config.yaml"
    )
    args = parser.parse_args()
    try:
        seed_demo(args.base_path if args.base_path else Settings.load().base_path)
    except (ValueError, OSError) as exc:
        print(f"Demo nicht angelegt: {exc}", file=sys.stderr)
        raise SystemExit(1)
