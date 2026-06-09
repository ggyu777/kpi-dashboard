#!/usr/bin/env python3
"""로컬 kpi-store.json → PostgreSQL 이관 (손상 파일 복구 포함)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from db import DATA_FILE, import_json_store, init_db, load_json_store_from_file, using_postgres


def main() -> int:
    parser = argparse.ArgumentParser(description="kpi-store.json → Postgres 마이그레이션")
    parser.add_argument(
        "--file",
        type=Path,
        default=DATA_FILE,
        help=f"JSON 경로 (기본: {DATA_FILE})",
    )
    parser.add_argument("--dry-run", action="store_true", help="파싱만 하고 DB에 쓰지 않음")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"파일 없음: {args.file}")
        return 1

    store = load_json_store_from_file(args.file)
    summary = {k: len(store.get(k, [])) for k in (
        "targets", "manual_data", "ad_conversions", "ad_placement_meta",
        "weekly_notes", "weekly_tasks", "weekly_plans", "monthly_plans", "monthly_feedback",
    )}
    print("복구/로드 결과:")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    if args.dry_run:
        print("(dry-run — DB 미기록)")
        return 0

    if not using_postgres():
        print("DATABASE_URL 환경변수가 필요합니다.")
        return 1

    init_db()
    counts = import_json_store(store)
    print("Postgres 이관 완료:")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
