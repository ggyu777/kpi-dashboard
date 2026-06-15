"""
PostgreSQL 저장소 (Railway / Render).
DATABASE_URL 미설정 시 로컬 JSON 폴백 (개발용).
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

from sqlalchemy import (
    Column,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATA_FILE = Path(__file__).parent / "data" / "kpi-store.json"

_DEFAULT_AD_REVENUES = {"top": 0, "center": 0, "bottom": 0, "popular_slot": 0, "popup": 0}


def default_ad_revenues() -> dict[str, int]:
    return dict(_DEFAULT_AD_REVENUES)


def _database_url() -> Optional[str]:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return None
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


class Base(DeclarativeBase):
    pass


class KpiTarget(Base):
    __tablename__ = "kpi_targets"
    week = Column(String(16), primary_key=True)
    kpi_id = Column(String(64), primary_key=True)
    target = Column(Float, nullable=False)


class KpiManualData(Base):
    __tablename__ = "kpi_manual_data"
    week = Column(String(16), primary_key=True)
    kpi_id = Column(String(64), primary_key=True)
    value = Column(Float, nullable=False)


class AdConversion(Base):
    __tablename__ = "ad_conversions"
    week = Column(String(16), primary_key=True)
    placement = Column(String(32), primary_key=True)
    conversion_rate = Column(Float, nullable=False)


class AdPlacementMeta(Base):
    __tablename__ = "ad_placement_meta"
    week = Column(String(16), primary_key=True)
    placement = Column(String(32), primary_key=True)
    revenue = Column(Integer, nullable=True)
    note = Column(Text, nullable=False, default="")


class WeeklyNote(Base):
    __tablename__ = "weekly_notes"
    week = Column(String(16), primary_key=True)
    kpi_summary = Column(Text, nullable=False, default="")
    project_progress = Column(Text, nullable=False, default="")
    next_week_strategy = Column(Text, nullable=False, default="")


class WeeklyTask(Base):
    __tablename__ = "weekly_tasks"
    week = Column(String(16), primary_key=True)
    tasks = Column(JSONB, nullable=False, default=list)


class WeeklyPlan(Base):
    __tablename__ = "weekly_plans"
    week = Column(String(16), primary_key=True)
    author = Column(String(128), nullable=False, default="")
    north_star = Column(Text, nullable=False, default="")
    goals = Column(JSONB, nullable=False, default=list)
    actions = Column(JSONB, nullable=False, default=list)
    ad_revenues = Column(JSONB, nullable=False, default=dict)


class MonthlyPlan(Base):
    __tablename__ = "monthly_plans"
    month = Column(String(16), primary_key=True)
    author = Column(String(128), nullable=False, default="")
    north_star = Column(Text, nullable=False, default="")
    mau_target = Column(Integer, nullable=False, default=0)
    goals = Column(JSONB, nullable=False, default=list)
    kpt_keep = Column(Text, nullable=False, default="")
    kpt_problem = Column(Text, nullable=False, default="")
    kpt_try = Column(Text, nullable=False, default="")
    next_actions = Column(JSONB, nullable=False, default=list)
    ad_revenues = Column(JSONB, nullable=False, default=dict)


class MonthlyFeedback(Base):
    __tablename__ = "monthly_feedback"
    month = Column(String(16), primary_key=True)
    feedback = Column(Text, nullable=False, default="")


_engine = None
_SessionLocal: Optional[sessionmaker] = None
_use_postgres: Optional[bool] = None


def using_postgres() -> bool:
    global _use_postgres
    if _use_postgres is None:
        _use_postgres = _database_url() is not None
    return _use_postgres


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = _database_url()
        if not url:
            raise RuntimeError("DATABASE_URL is not set")
        _engine = create_engine(url, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


@contextmanager
def db_session() -> Generator[Session, None, None]:
    if _SessionLocal is None:
        get_engine()
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    if not using_postgres():
        return
    Base.metadata.create_all(get_engine())


# ── JSON 폴백 (로컬 개발) ──────────────────────────────────────────────

def _empty_store() -> dict:
    return {
        "targets": [],
        "manual_data": [],
        "ad_conversions": [],
        "ad_placement_meta": [],
        "weekly_notes": [],
        "weekly_tasks": [],
        "weekly_plans": [],
        "monthly_plans": [],
        "monthly_feedback": [],
    }


def _read_json_store() -> dict:
    DATA_FILE.parent.mkdir(exist_ok=True)
    if not DATA_FILE.exists():
        return _empty_store()
    try:
        store = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        for key in _empty_store():
            store.setdefault(key, [])
        return store
    except Exception as e:
        print(f"[store] JSON 파싱 실패 — 백업 후 빈 저장소 사용: {e}")
        if DATA_FILE.exists():
            backup = DATA_FILE.with_suffix(".json.bak")
            try:
                backup.write_text(DATA_FILE.read_text(encoding="utf-8"), encoding="utf-8")
                print(f"[store] 백업 저장: {backup}")
            except Exception:
                pass
        return _empty_store()


def _write_json_store(store: dict) -> None:
    DATA_FILE.parent.mkdir(exist_ok=True)
    tmp = DATA_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA_FILE)


# ── 공개 API (main.py와 동일 시그니처) ─────────────────────────────────

def get_targets(week: str) -> dict[str, float]:
    if not using_postgres():
        store = _read_json_store()
        return {t["kpi_id"]: t["target"] for t in store["targets"] if t["week"] == week}
    with db_session() as s:
        rows = s.query(KpiTarget).filter(KpiTarget.week == week).all()
        return {r.kpi_id: r.target for r in rows}


def save_targets(week: str, targets: dict[str, float]) -> None:
    if not using_postgres():
        store = _read_json_store()
        store["targets"] = [t for t in store["targets"] if t["week"] != week]
        for kpi_id, target in targets.items():
            store["targets"].append({"week": week, "kpi_id": kpi_id, "target": target})
        _write_json_store(store)
        return
    with db_session() as s:
        s.query(KpiTarget).filter(KpiTarget.week == week).delete()
        for kpi_id, target in targets.items():
            s.add(KpiTarget(week=week, kpi_id=kpi_id, target=target))


def get_manual_data(week: str) -> dict[str, float]:
    if not using_postgres():
        store = _read_json_store()
        return {d["kpi_id"]: d["value"] for d in store["manual_data"] if d["week"] == week}
    with db_session() as s:
        rows = s.query(KpiManualData).filter(KpiManualData.week == week).all()
        return {r.kpi_id: r.value for r in rows}


def save_manual_data(week: str, data: dict[str, float]) -> None:
    if not using_postgres():
        store = _read_json_store()
        store["manual_data"] = [d for d in store["manual_data"] if d["week"] != week]
        for kpi_id, value in data.items():
            store["manual_data"].append({"week": week, "kpi_id": kpi_id, "value": value})
        _write_json_store(store)
        return
    with db_session() as s:
        s.query(KpiManualData).filter(KpiManualData.week == week).delete()
        for kpi_id, value in data.items():
            s.add(KpiManualData(week=week, kpi_id=kpi_id, value=value))


def get_ad_conversions(week: str) -> dict[str, float | None]:
    if not using_postgres():
        store = _read_json_store()
        return {
            r["placement"]: r["conversion_rate"]
            for r in store["ad_conversions"]
            if r["week"] == week
        }
    with db_session() as s:
        rows = s.query(AdConversion).filter(AdConversion.week == week).all()
        return {r.placement: r.conversion_rate for r in rows}


def save_ad_conversions(week: str, rates: dict[str, float]) -> None:
    if not using_postgres():
        store = _read_json_store()
        store["ad_conversions"] = [r for r in store["ad_conversions"] if r["week"] != week]
        for placement, rate in rates.items():
            store["ad_conversions"].append({"week": week, "placement": placement, "conversion_rate": rate})
        _write_json_store(store)
        return
    with db_session() as s:
        s.query(AdConversion).filter(AdConversion.week == week).delete()
        for placement, rate in rates.items():
            s.add(AdConversion(week=week, placement=placement, conversion_rate=rate))


def get_ad_placement_meta(week: str) -> dict[str, dict]:
    if not using_postgres():
        store = _read_json_store()
        out: dict[str, dict] = {}
        for r in store.get("ad_placement_meta", []):
            if r.get("week") == week:
                out[r["placement"]] = {"revenue": r.get("revenue"), "note": r.get("note") or ""}
        return out
    with db_session() as s:
        rows = s.query(AdPlacementMeta).filter(AdPlacementMeta.week == week).all()
        return {r.placement: {"revenue": r.revenue, "note": r.note or ""} for r in rows}


def save_ad_placement_meta_field(week: str, placement: str, field: str, value) -> None:
    if not using_postgres():
        store = _read_json_store()
        store.setdefault("ad_placement_meta", [])
        existing = next(
            (r for r in store["ad_placement_meta"] if r.get("week") == week and r.get("placement") == placement),
            {"week": week, "placement": placement, "revenue": None, "note": ""},
        )
        rows = [r for r in store["ad_placement_meta"] if not (r.get("week") == week and r.get("placement") == placement)]
        if field == "revenue":
            existing["revenue"] = int(value) if value not in (None, "") else None
        elif field == "note":
            existing["note"] = str(value or "")
        rows.append(existing)
        store["ad_placement_meta"] = rows
        _write_json_store(store)
        return
    with db_session() as s:
        row = s.get(AdPlacementMeta, {"week": week, "placement": placement})
        if row is None:
            row = AdPlacementMeta(week=week, placement=placement, revenue=None, note="")
            s.add(row)
        if field == "revenue":
            row.revenue = int(value) if value not in (None, "") else None
        elif field == "note":
            row.note = str(value or "")


def get_weekly_notes(week: str) -> dict:
    if not using_postgres():
        store = _read_json_store()
        note = next((n for n in store["weekly_notes"] if n["week"] == week), None)
        if note:
            return note
        return {"week": week, "kpi_summary": "", "project_progress": "", "next_week_strategy": ""}
    with db_session() as s:
        row = s.get(WeeklyNote, week)
        if row:
            return {
                "week": week,
                "kpi_summary": row.kpi_summary or "",
                "project_progress": row.project_progress or "",
                "next_week_strategy": row.next_week_strategy or "",
            }
        return {"week": week, "kpi_summary": "", "project_progress": "", "next_week_strategy": ""}


def save_weekly_notes(week: str, kpi_summary: str, project_progress: str, next_week_strategy: str) -> None:
    if not using_postgres():
        store = _read_json_store()
        store["weekly_notes"] = [n for n in store["weekly_notes"] if n["week"] != week]
        store["weekly_notes"].append({
            "week": week,
            "kpi_summary": kpi_summary,
            "project_progress": project_progress,
            "next_week_strategy": next_week_strategy,
        })
        _write_json_store(store)
        return
    with db_session() as s:
        row = s.get(WeeklyNote, week)
        if row is None:
            row = WeeklyNote(week=week)
            s.add(row)
        row.kpi_summary = kpi_summary
        row.project_progress = project_progress
        row.next_week_strategy = next_week_strategy


def get_weekly_tasks(week: str) -> list[dict]:
    if not using_postgres():
        store = _read_json_store()
        entry = next((t for t in store["weekly_tasks"] if t["week"] == week), None)
        return entry.get("tasks", []) if entry else []
    with db_session() as s:
        row = s.get(WeeklyTask, week)
        return list(row.tasks) if row and row.tasks else []


def save_weekly_tasks(week: str, tasks: list[dict]) -> None:
    if not using_postgres():
        store = _read_json_store()
        store["weekly_tasks"] = [t for t in store["weekly_tasks"] if t["week"] != week]
        store["weekly_tasks"].append({"week": week, "tasks": tasks})
        _write_json_store(store)
        return
    with db_session() as s:
        row = s.get(WeeklyTask, week)
        if row is None:
            row = WeeklyTask(week=week, tasks=tasks)
            s.add(row)
        else:
            row.tasks = tasks


def get_monthly_feedback(month: str) -> str:
    if not using_postgres():
        store = _read_json_store()
        entry = next((f for f in store["monthly_feedback"] if f["month"] == month), None)
        return entry.get("feedback", "") if entry else ""
    with db_session() as s:
        row = s.get(MonthlyFeedback, month)
        return row.feedback if row else ""


def save_monthly_feedback(month: str, feedback: str) -> None:
    if not using_postgres():
        store = _read_json_store()
        store["monthly_feedback"] = [f for f in store["monthly_feedback"] if f["month"] != month]
        store["monthly_feedback"].append({"month": month, "feedback": feedback})
        _write_json_store(store)
        return
    with db_session() as s:
        row = s.get(MonthlyFeedback, month)
        if row is None:
            row = MonthlyFeedback(month=month, feedback=feedback)
            s.add(row)
        else:
            row.feedback = feedback


def get_monthly_plan(month: str) -> dict:
    if not using_postgres():
        store = _read_json_store()
        plan = next((p for p in store["monthly_plans"] if p["month"] == month), None)
        if plan:
            return plan
        return {
            "month": month,
            "author": "",
            "north_star": "",
            "mau_target": 0,
            "goals": [],
            "kpt_keep": "",
            "kpt_problem": "",
            "kpt_try": "",
            "next_actions": [],
            "ad_revenues": default_ad_revenues(),
        }
    with db_session() as s:
        row = s.get(MonthlyPlan, month)
        if row:
            return {
                "month": month,
                "author": row.author or "",
                "north_star": row.north_star or "",
                "mau_target": row.mau_target or 0,
                "goals": row.goals or [],
                "kpt_keep": row.kpt_keep or "",
                "kpt_problem": row.kpt_problem or "",
                "kpt_try": row.kpt_try or "",
                "next_actions": row.next_actions or [],
                "ad_revenues": {**default_ad_revenues(), **(row.ad_revenues or {})},
            }
        return {
            "month": month,
            "author": "",
            "north_star": "",
            "mau_target": 0,
            "goals": [],
            "kpt_keep": "",
            "kpt_problem": "",
            "kpt_try": "",
            "next_actions": [],
            "ad_revenues": default_ad_revenues(),
        }


def save_monthly_plan(month: str, data: dict) -> None:
    if not using_postgres():
        store = _read_json_store()
        store["monthly_plans"] = [p for p in store["monthly_plans"] if p["month"] != month]
        data["month"] = month
        store["monthly_plans"].append(data)
        _write_json_store(store)
        return
    with db_session() as s:
        row = s.get(MonthlyPlan, month)
        if row is None:
            row = MonthlyPlan(month=month)
            s.add(row)
        row.author = data.get("author", "")
        row.north_star = data.get("north_star", "")
        row.mau_target = int(data.get("mau_target") or 0)
        row.goals = data.get("goals", [])
        row.kpt_keep = data.get("kpt_keep", "")
        row.kpt_problem = data.get("kpt_problem", "")
        row.kpt_try = data.get("kpt_try", "")
        row.next_actions = data.get("next_actions", [])
        row.ad_revenues = data.get("ad_revenues", {})


def get_weekly_plan(week: str) -> dict:
    if not using_postgres():
        store = _read_json_store()
        plan = next((p for p in store["weekly_plans"] if p["week"] == week), None)
        if plan:
            return plan
        return {
            "week": week,
            "author": "",
            "north_star": "",
            "goals": [],
            "actions": [],
            "ad_revenues": default_ad_revenues(),
        }
    with db_session() as s:
        row = s.get(WeeklyPlan, week)
        if row:
            return {
                "week": week,
                "author": row.author or "",
                "north_star": row.north_star or "",
                "goals": row.goals or [],
                "actions": row.actions or [],
                "ad_revenues": {**default_ad_revenues(), **(row.ad_revenues or {})},
            }
        return {
            "week": week,
            "author": "",
            "north_star": "",
            "goals": [],
            "actions": [],
            "ad_revenues": default_ad_revenues(),
        }


def save_weekly_plan(week: str, data: dict) -> None:
    if not using_postgres():
        store = _read_json_store()
        store["weekly_plans"] = [p for p in store["weekly_plans"] if p["week"] != week]
        data["week"] = week
        store["weekly_plans"].append(data)
        _write_json_store(store)
        return
    with db_session() as s:
        row = s.get(WeeklyPlan, week)
        if row is None:
            row = WeeklyPlan(week=week)
            s.add(row)
        row.author = data.get("author", "")
        row.north_star = data.get("north_star", "")
        row.goals = data.get("goals", [])
        row.actions = data.get("actions", [])
        row.ad_revenues = data.get("ad_revenues", {})


def import_json_store(store: dict) -> dict[str, int]:
    """JSON 저장소 전체를 Postgres로 이관. 반환: 테이블별 row 수."""
    if not using_postgres():
        raise RuntimeError("DATABASE_URL required for import")
    counts: dict[str, int] = {}
    init_db()

    with db_session() as s:
        s.execute(text("TRUNCATE kpi_targets, kpi_manual_data, ad_conversions, ad_placement_meta, "
                       "weekly_notes, weekly_tasks, weekly_plans, monthly_plans, monthly_feedback CASCADE"))

    with db_session() as s:
        for t in store.get("targets", []):
            s.merge(KpiTarget(week=t["week"], kpi_id=t["kpi_id"], target=t["target"]))
        counts["kpi_targets"] = len(store.get("targets", []))

        for d in store.get("manual_data", []):
            s.merge(KpiManualData(week=d["week"], kpi_id=d["kpi_id"], value=d["value"]))
        counts["kpi_manual_data"] = len(store.get("manual_data", []))

        for r in store.get("ad_conversions", []):
            s.merge(AdConversion(week=r["week"], placement=r["placement"], conversion_rate=r["conversion_rate"]))
        counts["ad_conversions"] = len(store.get("ad_conversions", []))

        for r in store.get("ad_placement_meta", []):
            s.merge(AdPlacementMeta(
                week=r["week"], placement=r["placement"],
                revenue=r.get("revenue"), note=r.get("note") or "",
            ))
        counts["ad_placement_meta"] = len(store.get("ad_placement_meta", []))

        notes_by_week: dict[str, dict] = {}
        for n in store.get("weekly_notes", []):
            wk = n["week"]
            prev = notes_by_week.get(wk)
            if prev is None or len(str(n.get("project_progress", ""))) > len(str(prev.get("project_progress", ""))):
                notes_by_week[wk] = n
        for wk, n in notes_by_week.items():
            s.merge(WeeklyNote(
                week=wk,
                kpi_summary=n.get("kpi_summary", ""),
                project_progress=n.get("project_progress", ""),
                next_week_strategy=n.get("next_week_strategy", ""),
            ))
        counts["weekly_notes"] = len(notes_by_week)

        for t in store.get("weekly_tasks", []):
            s.merge(WeeklyTask(week=t["week"], tasks=t.get("tasks", [])))
        counts["weekly_tasks"] = len(store.get("weekly_tasks", []))

        for p in store.get("weekly_plans", []):
            s.merge(WeeklyPlan(
                week=p["week"],
                author=p.get("author", ""),
                north_star=p.get("north_star", ""),
                goals=p.get("goals", []),
                actions=p.get("actions", []),
                ad_revenues=p.get("ad_revenues", {}),
            ))
        counts["weekly_plans"] = len(store.get("weekly_plans", []))

        for p in store.get("monthly_plans", []):
            s.merge(MonthlyPlan(
                month=p["month"],
                author=p.get("author", ""),
                north_star=p.get("north_star", ""),
                mau_target=int(p.get("mau_target") or 0),
                goals=p.get("goals", []),
                kpt_keep=p.get("kpt_keep", ""),
                kpt_problem=p.get("kpt_problem", ""),
                kpt_try=p.get("kpt_try", ""),
                next_actions=p.get("next_actions", []),
                ad_revenues=p.get("ad_revenues", {}),
            ))
        counts["monthly_plans"] = len(store.get("monthly_plans", []))

        for f in store.get("monthly_feedback", []):
            s.merge(MonthlyFeedback(month=f["month"], feedback=f.get("feedback", "")))
        counts["monthly_feedback"] = len(store.get("monthly_feedback", []))

    return counts


def _extract_json_array(raw: str, key: str, use_last: bool = True) -> Any:
    """raw 텍스트에서 `"key": [...]` 배열 추출 (손상 파일 tail 복구용)."""
    marker = f'"{key}":'
    idx = raw.rfind(marker) if use_last else raw.find(marker)
    if idx < 0:
        return None
    arr_start = raw.find("[", idx + len(marker))
    if arr_start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(arr_start, len(raw)):
        ch = raw[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[arr_start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def load_json_store_from_file(path: Path) -> dict:
    """손상된 JSON 복구 시도 포함."""
    raw = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    merged = _empty_store()

    # 첫 번째 완전한 JSON 객체 (앞부분)
    depth = 0
    start = raw.find("{")
    if start >= 0:
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        partial = json.loads(raw[start : i + 1])
                        merged.update(partial)
                        print(f"[migrate] 앞부분 JSON 복구 ({i + 1} bytes)")
                    except json.JSONDecodeError:
                        pass
                    break

    # tail에서 배열 재추출 (깨진 파일 뒤쪽에 실데이터가 있는 경우)
    for key in ("weekly_notes", "weekly_tasks", "weekly_plans", "monthly_plans", "monthly_feedback",
                "targets", "manual_data", "ad_conversions", "ad_placement_meta"):
        arr = _extract_json_array(raw, key, use_last=True)
        if arr is not None and len(arr) > len(merged.get(key, [])):
            merged[key] = arr
            print(f"[migrate] {key} {len(arr)}건 tail 복구")

    return merged
