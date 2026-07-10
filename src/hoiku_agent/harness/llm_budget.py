"""Google Sign-In user ごとの LLM 利用枠（呼び出し前に予約する決定的ストア）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from ..config import settings
from . import db

Base = db.Base
MICROYEN = 1_000_000
_GLOBAL = "__all__"

# 実測（2026-07-11、gemini-3.5-flash、クラス月案・仮名日誌6件）:
# author 3回 + reviewer 1回 = 入力15,109 / 出力2,237 token = $0.0428 = 約6.85円（$1=160円）。
# レビュー差戻し時の最大3巡と約70%の余裕を取り、作成実行は35円を予約する。
_RESERVE_YEN = {"authoring": 35, "improve": 35, "upload": 50, "proofread": 5}


class LlmBudgetWindow(Base):
    __tablename__ = "llm_budget_windows"
    __table_args__ = (sa.UniqueConstraint("scope", "subject", "window_start"),)

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(sa.String(20), index=True)
    subject: Mapped[str] = mapped_column(sa.String(255), index=True)  # Google sub / __all__
    window_start: Mapped[datetime] = mapped_column(sa.DateTime, index=True)
    reserved_micro_yen: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime)


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    code: str
    reserved_yen: int
    remaining_yen: int = 0


def kind_for_path(path: str) -> str | None:
    if path in ("/run", "/run_sse"):
        return "authoring"
    if path.startswith("/api/improve"):
        return "improve"
    if path.startswith("/api/parse-upload"):
        return "upload"
    if path.startswith("/api/proofread"):
        return "proofread"
    return None


def _start(now: datetime, scope: str) -> datetime:
    return (
        now.replace(minute=0, second=0, microsecond=0)
        if scope == "user_hourly"
        else now.replace(hour=0, minute=0, second=0, microsecond=0)
    )


def _reserve(
    session: Session, scope: str, subject: str, at: datetime, amount: int, limit: int
) -> int | None:
    insert = (
        pg_insert if session.bind and session.bind.dialect.name == "postgresql" else sqlite_insert
    )
    stmt = (
        insert(LlmBudgetWindow)
        .values(
            scope=scope, subject=subject, window_start=at, reserved_micro_yen=amount, updated_at=at
        )
        .on_conflict_do_update(
            index_elements=("scope", "subject", "window_start"),
            set_={
                "reserved_micro_yen": LlmBudgetWindow.reserved_micro_yen + amount,
                "updated_at": at,
            },
            where=LlmBudgetWindow.reserved_micro_yen + amount <= limit,
        )
        .returning(LlmBudgetWindow.reserved_micro_yen)
    )
    return session.execute(stmt).scalar_one_or_none()


def reserve(google_subject: str, path: str, *, now: datetime | None = None) -> BudgetDecision:
    kind = kind_for_path(path)
    if not google_subject or kind is None:
        return BudgetDecision(False, "invalid_request", 0)
    eng = db.engine()
    if eng is None:
        return BudgetDecision(False, "budget_store_unavailable", _RESERVE_YEN[kind])
    at = now or datetime.now()
    amount = _RESERVE_YEN[kind] * MICROYEN
    user_limit = settings.llm_user_hourly_limit_yen * MICROYEN
    global_limit = settings.llm_global_daily_limit_yen * MICROYEN
    try:
        with Session(eng) as session:
            with session.begin():
                if (
                    _reserve(
                        session,
                        "global_daily",
                        _GLOBAL,
                        _start(at, "global_daily"),
                        amount,
                        global_limit,
                    )
                    is None
                ):
                    return BudgetDecision(False, "global_daily_limit", _RESERVE_YEN[kind])
                used = _reserve(
                    session,
                    "user_hourly",
                    google_subject,
                    _start(at, "user_hourly"),
                    amount,
                    user_limit,
                )
                if used is None:
                    # 全体枠を先に予約した場合でも、個人枠で弾いたリクエストは消費させない。
                    # `with session.begin()` の外へ出る前に rollback し、増分をまとめて取り消す。
                    session.rollback()
                    return BudgetDecision(False, "user_hourly_limit", _RESERVE_YEN[kind])
            return BudgetDecision(
                True, "reserved", _RESERVE_YEN[kind], max(0, (user_limit - used) // MICROYEN)
            )
    except Exception:  # noqa: BLE001
        return BudgetDecision(False, "budget_store_unavailable", _RESERVE_YEN[kind])


def status(google_subject: str, *, now: datetime | None = None) -> dict:
    eng = db.engine()
    at = now or datetime.now()
    limit = settings.llm_user_hourly_limit_yen * MICROYEN
    if eng is None or not google_subject:
        return {
            "available": False,
            "limit_yen": settings.llm_user_hourly_limit_yen,
            "used_yen": 0,
            "remaining_yen": 0,
        }
    try:
        with Session(eng) as session:
            used = (
                session.scalar(
                    sa.select(LlmBudgetWindow.reserved_micro_yen).where(
                        LlmBudgetWindow.scope == "user_hourly",
                        LlmBudgetWindow.subject == google_subject,
                        LlmBudgetWindow.window_start == _start(at, "user_hourly"),
                    )
                )
                or 0
            )
        return {
            "available": True,
            "limit_yen": settings.llm_user_hourly_limit_yen,
            "used_yen": (used + MICROYEN - 1) // MICROYEN,
            "remaining_yen": max(0, (limit - used) // MICROYEN),
            "resets_at": (_start(at, "user_hourly") + timedelta(hours=1)).isoformat(),
        }
    except Exception:  # noqa: BLE001
        return {
            "available": False,
            "limit_yen": settings.llm_user_hourly_limit_yen,
            "used_yen": 0,
            "remaining_yen": 0,
        }
