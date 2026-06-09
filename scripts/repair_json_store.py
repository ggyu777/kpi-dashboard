#!/usr/bin/env python3
"""손상된 kpi-store.json을 복구해 깨끗한 파일로 저장."""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import DATA_FILE, load_json_store_from_file

def main():
    store = load_json_store_from_file(DATA_FILE)
    backup = DATA_FILE.with_suffix(".json.bak")
    if DATA_FILE.exists():
        backup.write_text(DATA_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    DATA_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"복구 완료 → {DATA_FILE}")
    print(f"백업 → {backup}")

if __name__ == "__main__":
    main()
