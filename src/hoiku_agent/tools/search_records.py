"""ツール：過去の日誌/月案を検索（参照・連続性）。

設計コンテキスト §6 ツール表（search_records）。作成AIが前月連続性や過去の実践を参照するために
自分で取りに行く（Agentic RAG / tool-use ループ）。月⇄日の還流（L2）の入力にもなる。

配線（v0）：ローカルの過去記録ストア（JSON）を引く。保存先は config.records_dir、未設定なら repo の
`data/records/`（gitignore 済み・架空児のみ＝§14）。各 JSON は DiaryEntry 相当の dict、またはその配列。
child_id・キーワードで素朴にフィルタする（埋め込み検索は将来 RAG/Memory へ寄せる余地＝§9）。
ストアが無い/空なら空リストを返す（降格）。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import settings

_DEFAULT_RECORDS_DIR = Path(__file__).resolve().parents[3] / "data" / "records"


def _records_dir() -> Path:
    return Path(settings.records_dir) if settings.records_dir else _DEFAULT_RECORDS_DIR


def _load_records(directory: Path) -> list[dict]:
    records: list[dict] = []
    if not directory.exists():
        return records
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                item.setdefault("_source", path.name)
                records.append(item)
    return records


def _summarize(record: dict, child_id: str | None) -> str:
    date = record.get("date", "日付不明")
    practice = record.get("practice_record", "")
    notes = record.get("individual_notes", []) or []
    if child_id:
        notes = [n for n in notes if isinstance(n, dict) and n.get("child_id") == child_id] or notes
    note_texts = [
        f"[{n.get('child_id', '?')}] {n.get('observed_state', '')}"
        for n in notes
        if isinstance(n, dict)
    ]
    body = f"{date}：{practice}"
    if note_texts:
        body += " / " + " / ".join(note_texts)
    return body


def search_records(query: str, child_id: str | None = None, top_k: int = 4) -> list[dict]:
    """過去の日誌/月案を検索する。

    Args:
        query: 検索クエリ（空可。キーワード AND ではなく素朴な含有スコア）。
        child_id: 指定があればその子の記録に絞る（0–2 個別前提）。
        top_k: 取得件数。

    Returns:
        ヒットした記録（{"source", "text", "date"} のリスト）。ストア無し/該当無しは空リスト。
    """
    records = _load_records(_records_dir())
    tokens = [t for t in query.split() if t]
    scored: list[tuple[float, str, dict]] = []
    for record in records:
        blob = json.dumps(record, ensure_ascii=False)
        if child_id and child_id not in blob:
            continue
        score = sum(1 for t in tokens if t in blob)
        if tokens and score == 0:
            continue  # クエリ指定があり一致ゼロは除外
        scored.append((score, str(record.get("date", "")), record))
    # スコア降順 → 日付降順（新しい記録を優先）
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [
        {
            "source": record.get("_source", "record"),
            "date": record.get("date"),
            "text": _summarize(record, child_id),
        }
        for _, _, record in scored[:top_k]
    ]
