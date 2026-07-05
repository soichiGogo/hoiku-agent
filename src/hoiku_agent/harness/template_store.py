"""harness：様式テンプレート（本文レイアウトのデータ）ストア。

設計コンテキスト §5/§18。書類の本文レイアウト（章立て＝セクションの順序・見出しラベル・種別・
出し分け）を **コードでなくデータ**（`knowledge/様式テンプレート.json`）で持ち、`harness/draft.py`
（と後続で帳票PDF・編集フォーム）が `load_template(doc_type)` で読んで描く。特定園の様式差（§18）を
コード改修でなくテンプレ編集で吸収できるようにするのが狙い。

責務境界（notation_store / policy_store と同じ哲学）:
- レイアウトのデータのみを扱う（validation は持たない＝型の保証は schema_check・§5）。
- 純関数（find_template）と IO（load/save）を分ける。clock は持たない（テンプレは日時を持たない）。
- 置き場は IO 節で解決＝**明示 path ＞ `DATABASE_URL`（Cloud SQL＝アーカイブ/policy/notation と同じ DB・
  `template_books` 1行に book 丸ごと JSONB・version 楽観ロック） ＞ ローカル `knowledge/様式テンプレート.json`
  （git はシード）**。純関数は置き場を知らない。カードを行へ射影しない（book 丸ごと JSON が SSOT）。

編集は現状スコープ外（園差の実需が来たら web CRUD を後続で足す）。本モジュールは読み取り（load_template）と
書き込み経路（save_book＝DB 統合の存在）を持ち、CRUD は notation_store の add/update/remove に倣って拡張できる。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column

from ..schemas.template import DocTemplate, TemplateBook
from . import db

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATE_PATH = _REPO_ROOT / "knowledge" / "様式テンプレート.json"


# ──────────────────────────── 純関数（検索） ────────────────────────────


def find_template(book: TemplateBook, doc_type: str) -> DocTemplate | None:
    """doc_type のテンプレを引く（無ければ None）。"""
    return next((t for t in book.templates if t.doc_type == doc_type), None)


# ──────────────────────────── IO（降格 / fail-loud） ────────────────────────────
# 置き場の解決順序は notation_store / policy_store と同一（明示 path ＞ DATABASE_URL ＞ ローカルシード）。

_BOOK_ROW_ID = "default"
_CONFLICT_MESSAGE = "様式テンプレートが他の場所で先に更新されています（競合）。最新を読み直してからやり直してください。"


class TemplateBookRecord(db.Base):
    """様式テンプレートブックの DB 行（book 丸ごと JSON が SSOT・1行・version は楽観ロック用）。"""

    __tablename__ = "template_books"

    id: Mapped[str] = mapped_column(sa.String(20), primary_key=True)
    book: Mapped[dict] = mapped_column(db.JSON_VARIANT)
    version: Mapped[int] = mapped_column(sa.Integer)


def _db_active(path: Path | None) -> bool:
    return path is None and bool(db.database_url())


def _load_local(path: Path) -> TemplateBook:
    if not path.exists():
        return TemplateBook()
    data = json.loads(path.read_text(encoding="utf-8"))
    return TemplateBook.model_validate(data)


def load_book_meta(path: Path | None = None) -> tuple[TemplateBook, int | None]:
    """テンプレストアと書き込み前提条件（version）を読む（notation_store.load_book_meta と対称）。

    DB（DATABASE_URL 設定・path 未指定）で行不在なら 0＝create-only＋ローカルシードを返す。
    ローカルは None（precondition なし）。壊れ JSON は例外（読み手が降格して握る）。

    **DB 到達不能／テーブル未整備（migration 0005 未適用）等の DB 障害は、常に同梱の
    ローカルシード（git＋Docker COPY で必ず存在）へ降格して読む**（version=None＝precondition 不明）。
    テンプレは全書類種別の write_*／帳票PDF／編集フォームが確定処理で必ず読むため、ここで送出すると
    書類生成そのものが落ちる（本番で observed＝template_books 未作成で全 doc_type がクラッシュ）。
    レイアウトのデータは常にシードで代替可能なので、DB 障害は fail-loud でなく降格が正しい
    （notation_store.load_rules_or_empty と同じ「降格safe」哲学＝§5）。書込側は _db_active を独立に
    見て DB へ書くため、この降格で偽の書込は起きない。
    """
    if _db_active(path):
        try:
            eng = db.engine()
            with Session(eng) as session:
                row = session.get(TemplateBookRecord, _BOOK_ROW_ID)
        except SQLAlchemyError:
            # DB 到達不能／テーブル未整備（migration 未適用）＝同梱シードへ降格し生成を止めない。
            return _load_local(_TEMPLATE_PATH), None
        if row is None:
            return _load_local(_TEMPLATE_PATH), 0
        return TemplateBook.model_validate(row.book), row.version
    return _load_local(path or _TEMPLATE_PATH), None


def load_book(path: Path | None = None) -> TemplateBook:
    """テンプレストアを読む（読み手用。書き手は load_book_meta で version も取る）。"""
    return load_book_meta(path)[0]


def load_template(doc_type: str, path: Path | None = None) -> DocTemplate:
    """doc_type の様式テンプレを読む（draft.py 等の描画が使う）。

    テンプレは git 同梱シード＋Docker COPY で常に存在する前提。見つからなければ**同梱シードが欠けている
    パッケージング不具合**なので fail-loud（握りつぶすと本文が空になり静かに壊れる）。
    """
    tmpl = find_template(load_book(path), doc_type)
    if tmpl is None:
        raise ValueError(f"様式テンプレートに doc_type={doc_type!r} がありません（seed を確認）")
    return tmpl


def save_book(
    book: TemplateBook, path: Path | None = None, *, if_version: int | None = None
) -> None:
    """テンプレストアを書き出す（DB は if_version の compare-and-swap で楽観ロック＝notation と同一）。"""
    payload = book.model_dump(mode="json")
    if _db_active(path):
        eng = db.engine()
        try:
            with Session(eng) as session, session.begin():
                if if_version is None:
                    row = session.get(TemplateBookRecord, _BOOK_ROW_ID)
                    if row is None:
                        session.add(TemplateBookRecord(id=_BOOK_ROW_ID, book=payload, version=1))
                    else:
                        row.book = payload
                        row.version += 1
                elif if_version == 0:
                    session.add(TemplateBookRecord(id=_BOOK_ROW_ID, book=payload, version=1))
                else:
                    updated = session.execute(
                        sa.update(TemplateBookRecord)
                        .where(
                            TemplateBookRecord.id == _BOOK_ROW_ID,
                            TemplateBookRecord.version == if_version,
                        )
                        .values(book=payload, version=if_version + 1)
                    )
                    if updated.rowcount != 1:
                        raise ValueError(_CONFLICT_MESSAGE)
        except IntegrityError as e:
            raise ValueError(_CONFLICT_MESSAGE) from e
        return

    path = path or _TEMPLATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ──────────────────────────── view（API/UI 用の決定的マッピング） ────────────────────────────


def book_view(book: TemplateBook) -> dict:
    """テンプレ全体を `/api/doc-template` 契約へ変換する（フロントの編集フォームが本文順序/ラベルに使う）。

    doc_type → セクション列（key/label/kind/item_field）。フロントは kind/key で widget を選び、
    順序と label をここから取る（レイアウトの SSOT を1つに＝§18）。
    """
    return {
        "templates": {
            t.doc_type: [
                {
                    "key": s.key,
                    "label": s.label,
                    "kind": s.kind.value,
                    "item_field": s.item_field,
                }
                for s in t.sections
            ]
            for t in book.templates
        }
    }


def store_status(path: Path | None = None) -> str:
    """ストアの永続性を正直に表す（notation_store と対称）。

    DB 設定時は **DB を直接叩いて** 到達性を測る（`load_book` はシード降格するため偽の
    "persistent" を出さない＝§5「偽の緑を出さない」）。テーブル未整備／到達不能は "unavailable"。
    """
    if _db_active(path):
        try:
            eng = db.engine()
            with Session(eng) as session:
                session.get(TemplateBookRecord, _BOOK_ROW_ID)
        except Exception:  # noqa: BLE001  到達不能/テーブル未整備＝シード降格で読めても永続ではない
            return "unavailable"
        return "persistent"
    path = path or _TEMPLATE_PATH
    if not path.exists():
        return "unavailable"
    try:
        load_book(path)
    except (OSError, ValueError):
        return "unavailable"
    return "ephemeral" if os.environ.get("K_SERVICE") else "persistent"
