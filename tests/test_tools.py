"""一階ツールの決定的な振る舞い（ローカル記録検索・降格）の単体テスト（LLM 非依存）。

設計コンテキスト §6/§9：GCP 未接続でも降格して落ちないこと、ローカル記録ストアの検索を検証。
"""

from __future__ import annotations

import json

from hoiku_agent import config
from hoiku_agent.tools import search_guideline, search_past_documents


def _write_record(directory, name, record):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


def test_search_past_documents_filters_by_child_and_query(tmp_path, monkeypatch):
    records_dir = tmp_path / "records"
    _write_record(
        records_dir,
        "d1.json",
        {
            "date": "2026-06-24",
            "practice_record": "園庭で砂遊び",
            "individual_notes": [{"child_id": "架空児A", "observed_state": "砂をすくった"}],
        },
    )
    _write_record(
        records_dir,
        "d2.json",
        {
            "date": "2026-06-23",
            "practice_record": "室内で絵本",
            "individual_notes": [{"child_id": "架空児B", "observed_state": "指さしをした"}],
        },
    )
    monkeypatch.setattr(config.settings, "records_dir", str(records_dir))

    hits = search_past_documents("砂遊び", child_id="架空児A")
    assert len(hits) == 1
    assert "架空児A" in hits[0]["text"]
    assert "砂" in hits[0]["text"]


def test_search_past_documents_empty_store_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "records_dir", str(tmp_path / "missing"))
    assert search_past_documents("何か") == []


def test_search_guideline_degrades_without_corpus(monkeypatch):
    monkeypatch.setattr(config.settings, "rag_corpus", "")
    out = search_guideline("3歳 言葉 ねらい")
    assert len(out) == 1
    assert "RAG未接続" in out[0]["source"]


_VALID_DRAFT_JSON = """\
```json
{
  "date": "2026-06-25",
  "age_band": "0-2",
  "weather": "晴れ",
  "attendance": [{"child_id": "架空児A", "present": true}],
  "practice_record": "砂遊び",
  "individual_notes": [
    {"child_id": "架空児A", "observed_state": "砂の感触を確かめた", "tags": ["身近なものと関わり感性が育つ"]}
  ],
  "evaluation": {"child_focus": "集中していた", "self_review": "道具が適切"}
}
```"""


def test_validate_fields_tool_accepts_draft_json_string():
    from hoiku_agent.tools import validate_fields

    assert validate_fields(_VALID_DRAFT_JSON) == []


def test_validate_fields_tool_reports_unparseable_json():
    from hoiku_agent.tools import validate_fields

    problems = validate_fields("これは JSON ではありません")
    assert problems and "解釈できませんでした" in problems[0]


# ──────────────────── recall_child_history（Memory Bank 読み・§9） ────────────────────


class _StubMemoryResponse:
    """tool_context.search_memory の戻り（SearchMemoryResponse）を模す。"""

    def __init__(self, texts):
        from google.genai import types

        self.memories = [
            type(
                "MemoryEntry",
                (),
                {"content": types.Content(role="model", parts=[types.Part(text=t)])},
            )()
            for t in texts
        ]


class _StubToolContext:
    """MemoryService 配線済みの ToolContext を模す（search_memory を提供）。"""

    def __init__(self, texts):
        self._texts = texts
        self.queries: list[str] = []

    async def search_memory(self, query: str):
        self.queries.append(query)
        return _StubMemoryResponse(self._texts)


def test_recall_child_history_returns_memories_when_connected():
    """MemoryService 配線時は search_memory の結果（その子の像）を本文として返す（非降格）。"""
    import asyncio

    from hoiku_agent.tools import recall_child_history

    ctx = _StubToolContext(["前回は砂場で感触を確かめ、繰り返し楽しんでいた"])
    out = asyncio.run(recall_child_history("架空児A", query="砂", tool_context=ctx))

    assert any("感触" in m["text"] for m in out)
    # child_id とクエリが検索キーに反映される
    assert ctx.queries and "架空児A" in ctx.queries[0] and "砂" in ctx.queries[0]


def test_recall_child_history_degrades_without_tool_context():
    """tool_context 未注入（ローカル/未接続）では降格メッセージ1件で落ちない。"""
    import asyncio

    from hoiku_agent.tools import recall_child_history

    out = asyncio.run(recall_child_history("架空児A"))
    assert len(out) == 1 and "memory未接続" in out[0]["text"]


def test_recall_child_history_degrades_when_memory_service_unwired():
    """tool_context はあるが MemoryService 未配線（search_memory が ValueError）でも降格1件で落ちない。"""
    import asyncio

    from hoiku_agent.tools import recall_child_history

    class _NoMemoryCtx:
        async def search_memory(self, query: str):
            raise ValueError("memory service not configured")

    out = asyncio.run(recall_child_history("架空児A", tool_context=_NoMemoryCtx()))
    assert len(out) == 1 and "Memory Bank 未設定" in out[0]["text"]
