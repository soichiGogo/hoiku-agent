"""LLM 利用枠の決定論テスト（実モデル・ネットワーク不要）。"""

from __future__ import annotations

from datetime import datetime

import pytest

from hoiku_agent.config import settings
from hoiku_agent.harness import db, llm_budget


@pytest.fixture()
def budget_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/budget.db")
    db.reset_engine_cache()
    db.Base.metadata.create_all(db.engine())
    yield
    db.reset_engine_cache()


def test_reserve_applies_per_user_hourly_limit_without_consuming_global_on_rejection(
    budget_db, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "llm_user_hourly_limit_yen", 50)
    monkeypatch.setattr(settings, "llm_global_daily_limit_yen", 100)
    at = datetime(2026, 7, 11, 10, 15)

    first = llm_budget.reserve("user-a", "/run_sse", now=at)
    second = llm_budget.reserve("user-a", "/run_sse", now=at)

    assert first.allowed is True and first.remaining_yen == 15
    assert second.allowed is False and second.code == "user_hourly_limit"
    # 個人枠の失敗が、全体日次枠の予約を残さない。
    other = llm_budget.reserve("user-b", "/run_sse", now=at)
    assert other.allowed is True


def test_reserve_applies_global_daily_limit(budget_db, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_user_hourly_limit_yen", 100)
    monkeypatch.setattr(settings, "llm_global_daily_limit_yen", 35)
    at = datetime(2026, 7, 11, 10, 15)

    assert llm_budget.reserve("user-a", "/run_sse", now=at).allowed is True
    denied = llm_budget.reserve("user-b", "/run_sse", now=at)
    assert denied.allowed is False and denied.code == "global_daily_limit"


def test_status_reports_remaining_hourly_budget(budget_db, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_user_hourly_limit_yen", 100)
    at = datetime(2026, 7, 11, 10, 15)

    llm_budget.reserve("user-a", "/api/proofread", now=at)
    status = llm_budget.status("user-a", now=at)

    assert status["available"] is True
    assert status["used_yen"] == 5
    assert status["remaining_yen"] == 95
    assert status["resets_at"] == "2026-07-11T11:00:00"
