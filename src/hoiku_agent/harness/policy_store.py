"""harness：育つ文書作成指針＝構造化カードストア（決定的）。

設計コンテキスト §5（決定的ロジックの唯一実装）/ §8（改善エージェント）/ §9（メモリ＝育つ指針）。
v1 で指針の正(SSOT)を markdown から **構造化カード JSON（`knowledge/文書作成指針.json`）** へ移す。
本モジュールはそのカードストアの **決定的な CRUD・competing 完全重複ガード・履歴・テキスト再生** を
1箇所に集約する（LLM を呼ばない・`tests/test_harness/` から純粋にテスト可能）。

責務境界（§5/§8）:
- 「意味的な競合」の判定は改善エージェント（LLM）の責務＝ここではやらない。ここが持つのは
  **完全重複（同 scope・body 完全一致）の安全網**だけ（決定的）。
- clock を持たない＝`created_at`/`updated_at`/`timestamp` は呼び出し側（improver の tool 境界）が
  注入する（純関数を保つ＝finalize.py / FinalizeAgent の日付解決と同じ流儀）。
- 純関数（add/supersede/remove/render/検索）と IO（load_book/save_book）を分ける。read 経路は降格
  （read_policy が握る）、write 経路は fail-loud（ValueError）で SSOT を黙って壊さない。

git への証拠 commit は `git_ops.commit_policy_book`（プロダクトが回す git 操作）が担う（本モジュールは
JSON の決定的編集まで・subprocess は叩かない）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..schemas.policy import (
    PolicyBook,
    PolicyCard,
    PolicyChange,
    PolicyChangeAction,
    PolicyScope,
    PolicyStatus,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_POLICY_PATH = _REPO_ROOT / "knowledge" / "文書作成指針.json"

# render_to_text の節見出し（旧 markdown 指針と同じ構成を再生＝read_policy / eval の連続性を保つ）。
_DOC_TITLE = "# 文書作成指針（育つ skill）"
_SCOPE_HEADINGS: dict[PolicyScope, str] = {
    PolicyScope.共通: "## 共通ルール（園・書類横断）",
    PolicyScope.保育日誌: "### 保育日誌",
    PolicyScope.月案: "### 月案 / 週案 / 日案",
}
_KANSHO_HEADING = "## 書類別の勘所"
_HISTORY_HEADING = "## 変更履歴（誰の指摘で・何を変えたか＝「回した証拠」）"


# ──────────────────────────── 検索・採番（純関数） ────────────────────────────


def next_card_id(book: PolicyBook) -> str:
    """既存 id（"card-NNNN"）の最大連番 +1 を決定的に採番する。空なら card-0001。"""
    max_n = 0
    for card in book.cards:
        if card.id.startswith("card-"):
            try:
                max_n = max(max_n, int(card.id[len("card-") :]))
            except ValueError:
                continue
    return f"card-{max_n + 1:04d}"


def find_card(book: PolicyBook, card_id: str) -> PolicyCard | None:
    """id でカードを引く（無ければ None）。"""
    return next((c for c in book.cards if c.id == card_id), None)


def active_cards(book: PolicyBook, scope: PolicyScope | None = None) -> list[PolicyCard]:
    """現行（active）カードを挿入順で返す。scope 指定でその対象書類のみに絞る。"""
    return [
        c
        for c in book.cards
        if c.status == PolicyStatus.active and (scope is None or c.scope == scope)
    ]


def find_exact_duplicate(book: PolicyBook, scope: PolicyScope, body: str) -> PolicyCard | None:
    """同 scope の active カードで body が**完全一致**するものを返す（決定的な安全網・§8）。

    意味的な矛盾はここでは見ない（それは改善エージェント＝LLM の責務）。完全重複（二重登録）だけを弾く。
    """
    target = body.strip()
    return next((c for c in active_cards(book, scope) if c.body.strip() == target), None)


# ──────────────────────────── 変更（純関数・新 PolicyBook を返す） ────────────────────────────


def _truncate(text: str, n: int = 30) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= n else text[:n] + "…"


def add_card(book: PolicyBook, card: PolicyCard, *, summary: str = "") -> PolicyBook:
    """カードを追加する（純関数・新 PolicyBook を返す）。

    id 重複・本文空・同 scope の完全重複は ValueError（fail-loud＝SSOT を黙って壊さない）。
    history に add を1件追記する（timestamp＝card.created_at）。
    """
    if not card.body.strip():
        raise ValueError("カード本文（body）が空です")
    if find_card(book, card.id) is not None:
        raise ValueError(f"カード id が重複しています: {card.id}")
    if find_exact_duplicate(book, card.scope, card.body) is not None:
        raise ValueError(
            f"同じ内容のカードが既にあります（{card.scope.value}）: {_truncate(card.body)}"
        )

    change = PolicyChange(
        timestamp=card.created_at,
        action=PolicyChangeAction.add,
        card_id=card.id,
        summary=summary or f"{card.scope.value}に「{_truncate(card.body)}」を追加",
        source=card.source,
    )
    return book.model_copy(
        update={"cards": [*book.cards, card], "history": [*book.history, change]}
    )


def supersede_card(
    book: PolicyBook, *, old_id: str, new_card: PolicyCard, summary: str = ""
) -> PolicyBook:
    """旧カードを新カードで置き換える（純関数・新 PolicyBook を返す）。

    旧カードは status=superseded で残し（superseded_by＝新 id）、新カード（supersedes＝旧 id）を
    active で足す＝版管理で「回した証拠」を保つ（§8）。旧が無い/active でない、本文空、id 重複は ValueError。
    """
    old = find_card(book, old_id)
    if old is None:
        raise ValueError(f"置き換え対象のカードが見つかりません: {old_id}")
    if old.status != PolicyStatus.active:
        raise ValueError(f"置き換え対象が active ではありません: {old_id}（{old.status.value}）")
    if not new_card.body.strip():
        raise ValueError("新カード本文（body）が空です")
    if find_card(book, new_card.id) is not None:
        raise ValueError(f"新カード id が重複しています: {new_card.id}")

    linked_new = new_card.model_copy(update={"supersedes": old_id})
    cards: list[PolicyCard] = []
    for c in book.cards:
        if c.id == old_id:
            cards.append(
                c.model_copy(
                    update={
                        "status": PolicyStatus.superseded,
                        "superseded_by": new_card.id,
                        "updated_at": new_card.created_at,
                    }
                )
            )
        else:
            cards.append(c)
    cards.append(linked_new)

    change = PolicyChange(
        timestamp=new_card.created_at,
        action=PolicyChangeAction.supersede,
        card_id=new_card.id,
        superseded_id=old_id,
        summary=summary
        or f"{new_card.scope.value}の指針を更新（「{_truncate(old.body)}」→「{_truncate(new_card.body)}」）",
        source=new_card.source,
    )
    return book.model_copy(update={"cards": cards, "history": [*book.history, change]})


def remove_card(
    book: PolicyBook, *, card_id: str, summary: str, when, decided_by: str = "保育士"
) -> PolicyBook:
    """カードをソフト削除する（status=retired）。純関数・新 PolicyBook を返す。`when`＝外部注入 datetime。"""
    target = find_card(book, card_id)
    if target is None or target.status != PolicyStatus.active:
        raise ValueError(f"削除対象の active カードが見つかりません: {card_id}")
    cards = [
        c.model_copy(update={"status": PolicyStatus.retired, "updated_at": when})
        if c.id == card_id
        else c
        for c in book.cards
    ]
    change = PolicyChange(
        timestamp=when,
        action=PolicyChangeAction.remove,
        card_id=card_id,
        summary=summary or f"{target.scope.value}の指針「{_truncate(target.body)}」を取り下げ",
        source=target.source,
        decided_by=decided_by,
    )
    return book.model_copy(update={"cards": cards, "history": [*book.history, change]})


# ──────────────────────────── テキスト再生（純関数） ────────────────────────────


def _render_bullets(book: PolicyBook, scope: PolicyScope) -> list[str]:
    cards = active_cards(book, scope)
    if not cards:
        return ["- （未登録）"]
    return [f"- {c.body.strip()}" for c in cards]


def render_to_text(book: PolicyBook, scope: PolicyScope | None = None) -> str:
    """active カードから指針テキストを決定的に再生する（read_policy / UI / prompt 用）。

    scope=None：旧 markdown と同じ節構成（共通ルール／書類別の勘所＞保育日誌・月案／変更履歴）を全再生。
    scope 指定：その対象書類の節（見出し＋箇条書き）だけを返す（可視化・部分提示用）。
    """
    if scope is not None:
        lines = [_SCOPE_HEADINGS[scope], "", *_render_bullets(book, scope)]
        return "\n".join(lines)

    lines: list[str] = [_DOC_TITLE, ""]
    lines += [_SCOPE_HEADINGS[PolicyScope.共通], "", *_render_bullets(book, PolicyScope.共通), ""]
    lines += [_KANSHO_HEADING, ""]
    lines += [
        _SCOPE_HEADINGS[PolicyScope.保育日誌],
        "",
        *_render_bullets(book, PolicyScope.保育日誌),
        "",
    ]
    lines += [_SCOPE_HEADINGS[PolicyScope.月案], "", *_render_bullets(book, PolicyScope.月案), ""]
    lines += [_HISTORY_HEADING, ""]
    if book.history:
        for ch in book.history:
            lines.append(f"- {ch.timestamp.date().isoformat()} {ch.summary}")
    else:
        lines.append("- （更新なし）")
    return "\n".join(lines)


# ──────────────────────────── IO（降格 / fail-loud） ────────────────────────────
#
# 置き場の解決順序: 明示 `path` 引数 ＞ `POLICY_STORE_URI`（gs://＝外部永続化・Cloud Run の
# コンテナFS 揮発を解消） ＞ モジュール既定 `_POLICY_PATH`（ローカル dev）。
# GCS の read-modify-write 競合は generation precondition（`load_book_meta`→`save_book(if_generation=…)`）
# で楽観ロックする（複数インスタンス同時書き込みで後勝ちの黙殺をしない＝fail-loud）。


def _store_uri() -> str:
    """外部ストア URI（未設定は空文字＝ローカル降格）。config が唯一の出所。"""
    from ..config import settings  # 遅延 import（テストの monkeypatch・循環回避）

    return settings.policy_store_uri.strip()


def _gcs_blob(uri: str):
    """`gs://<bucket>/<object>` から google-cloud-storage の Blob を返す（テストの注入点）。"""
    from google.cloud import storage  # 遅延 import（ローカル運用では GCS SDK に触れない）

    bucket_name, _, object_name = uri.removeprefix("gs://").partition("/")
    if not bucket_name or not object_name:
        raise ValueError(f"POLICY_STORE_URI が不正です（gs://<bucket>/<object> の形式）: {uri}")
    return storage.Client().bucket(bucket_name).blob(object_name)


def load_book_meta(path: Path | None = None) -> tuple[PolicyBook, int | None]:
    """カードストアと書き込み前提条件（GCS generation）を読む。

    戻り値の第2要素は `save_book(if_generation=…)` に渡す楽観ロック用 generation：
    - GCS（URI 設定・path 未指定）… オブジェクトの generation。**不在は 0**（＝「まだ存在しない」
      前提の初回作成。`if_generation_match=0` が create-only を意味する GCS 仕様に合わせる）。
    - ローカル … None（precondition なし＝従来動作）。
    不在なら空 PolicyBook（write 経路の初回 add を許す）。壊れ JSON / スキーマ不一致は
    ValueError（write 経路は fail-loud で SSOT を黙って壊さない）。read 経路（read_policy）は
    呼び出し側が例外を握って降格する。
    """
    uri = "" if path is not None else _store_uri()
    if uri:
        from google.api_core.exceptions import NotFound

        blob = _gcs_blob(uri)
        try:
            blob.reload()  # メタデータ（generation）を取得。不在は NotFound
        except NotFound:
            return PolicyBook(), 0
        data = json.loads(blob.download_as_bytes().decode("utf-8"))
        return PolicyBook.model_validate(data), blob.generation

    path = path or _POLICY_PATH
    if not path.exists():
        return PolicyBook(), None
    data = json.loads(path.read_text(encoding="utf-8"))  # 壊れは JSONDecodeError → 呼び出し側へ
    return PolicyBook.model_validate(data), None


def load_book(path: Path | None = None) -> PolicyBook:
    """カードストア JSON を読む（読み手用。書き手は `load_book_meta` で generation も取る）。

    path は呼び出し時に解決する（明示 path ＞ POLICY_STORE_URI ＞ `_POLICY_PATH`）＝テストは
    `_POLICY_PATH` を monkeypatch で差し替えられる。
    """
    return load_book_meta(path)[0]


def save_book(
    book: PolicyBook, path: Path | None = None, *, if_generation: int | None = None
) -> None:
    """カードストアを書き出す（末尾改行つき・人間可読＝write_baseline と同流儀）。

    GCS（URI 設定・path 未指定）では `if_generation`（`load_book_meta` の第2要素）を渡すと
    generation precondition で楽観ロックし、競合（他所で先に更新）は ValueError（fail-loud＝
    唯一の書き手 commit_policy_card が rejected へ変換して improver を落とさない）。
    ローカルでは if_generation は無視される（単一プロセス dev）。
    """
    payload = json.dumps(book.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"

    uri = "" if path is not None else _store_uri()
    if uri:
        from google.api_core.exceptions import PreconditionFailed

        blob = _gcs_blob(uri)
        kwargs = {} if if_generation is None else {"if_generation_match": if_generation}
        try:
            blob.upload_from_string(payload, content_type="application/json", **kwargs)
        except PreconditionFailed as e:
            raise ValueError(
                "指針ストアが他の場所で先に更新されています（競合）。"
                "最新の指針を読み直してからやり直してください。"
            ) from e
        return

    path = path or _POLICY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def store_status(path: Path | None = None) -> str:
    """ストアの永続性を正直に表す（UI が偽の永続を出さないため・§8）。

    - "unavailable" … ストア未配線/壊れ/GCS 到達不能（閲覧降格）。
    - "ephemeral"   … Cloud Run（K_SERVICE）で外部ストア未設定＝コンテナFS は scale-to-zero/
                      再起動で揮発（恒久は POLICY_STORE_URI の設定）。
    - "persistent"  … GCS 外部ストア（POLICY_STORE_URI）またはローカルディスク（dev）＝
                      書込みは再起動後も残る。
    """
    if path is None and _store_uri():
        try:
            load_book()  # GCS 読み取り（オブジェクト不在は空 book＝設定済みなら永続）
        except Exception:  # noqa: BLE001  到達不能/権限/壊れは降格（偽の永続を出さない）
            return "unavailable"
        return "persistent"

    path = path or _POLICY_PATH
    if not path.exists():
        return "unavailable"
    try:
        load_book(path)
    except (OSError, ValueError):
        return "unavailable"
    return "ephemeral" if os.environ.get("K_SERVICE") else "persistent"


# ──────────────────────────── view（API/UI 用の決定的マッピング） ────────────────────────────

# scope → フロントの対象書類タグ（左ライン色分け・ラベル）。presentation 契約の唯一の出所。
_SCOPE_DOC_TYPE: dict[PolicyScope, str] = {
    PolicyScope.共通: "common",
    PolicyScope.保育日誌: "diary",
    PolicyScope.月案: "monthly",
}
_SCOPE_DOC_LABEL: dict[PolicyScope, str] = {
    PolicyScope.共通: "共通",
    PolicyScope.保育日誌: "保育日誌",
    PolicyScope.月案: "個別月案",
}


def card_view(card: PolicyCard) -> dict:
    """カード1枚をフロント/API 用の JSON-serializable dict に変換する（決定的）。"""
    return {
        "id": card.id,
        "body": card.body,
        "scope": card.scope.value,
        "doc_type": _SCOPE_DOC_TYPE[card.scope],
        "doc_label": _SCOPE_DOC_LABEL[card.scope],
        "source": card.source,
        "date": card.created_at.date().isoformat(),
    }


def history_view(change: PolicyChange) -> dict:
    """変更履歴1件をフロント/API 用の dict に変換する（だれの気づきで何が増えたか）。"""
    return {
        "at": change.timestamp.date().isoformat(),
        "by": change.source or change.decided_by,
        "summary": change.summary,
        "card_id": change.card_id,
    }


def book_view(book: PolicyBook) -> dict:
    """ストア全体を /api/policy 契約の {cards, history} に変換する（履歴は newest first）。"""
    return {
        "cards": [card_view(c) for c in active_cards(book)],
        "history": [history_view(h) for h in reversed(book.history)],
    }
