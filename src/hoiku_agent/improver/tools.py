"""改善エージェント（二階）固有のツール。

設計コンテキスト §8。育つ指針の正(SSOT)は構造化カードストア（置き場の解決は harness/policy_store＝
`DATABASE_URL` の Cloud SQL（書類アーカイブと同じ DB）またはローカル `knowledge/文書作成指針.json`。この層は置き場を知らない）。
改善エージェントは次を回す（番人＝意味的競合精査＋保育士の決定）:
- read_policy_cards … 既存 active カードを読む（意味的競合を精査する材料）。
- propose_policy_card … 修正差分から追加/改訂案を作り、**意味的に競合する既存カードを自分で申告**する。
  決定的な完全重複は安全網（policy_store.find_exact_duplicate）が併せて検出する。
- ask_caregiver … 競合があれば該当カードと新案を**比較相談**、無くても反映可否を確認（人に訊く口は一階と共用）。
- commit_policy_card … 保育士の決定で**即反映**（add／supersede→save_book。「回した証拠」＝カード内蔵の
  変更履歴）。
- read_reference_policy／propose_reference_update／commit_reference_update … 参照資料の現在値を読み、
  日本語ラベル付きの変更案を返し、保育士の確認後に policy_store.update_reference_policy で即反映する。

決定的ロジックの実体は harness（policy_store）に1つ（§5）。ここは harness を呼ぶ薄いラッパ＋
runtime 境界（`datetime.now()` の注入）だけ。意味的競合の判定は LLM（このエージェント）の責務で、
harness は完全重複の安全網のみを持つ（決定的）。run_eval/評価ゲートは取り込みフローから外す（eval は
CI の品質回帰として別系統で温存＝decouple・§12）。
"""

from __future__ import annotations

from datetime import datetime

from ..harness import policy_store
from ..schemas.policy import (
    REFERENCE_SOURCE_META,
    PolicyCard,
    PolicyScope,
    PolicyStatus,
    ReferenceRule,
    ReferenceSource,
)
from ..tools import ask_caregiver as ask_caregiver  # noqa: PLC0414  人に訊く口は一階と共用

_SCOPES = {
    s.value: s for s in PolicyScope
}  # 値→PolicyScope（共通/保育日誌/月案/保育経過記録/保育要録）
# エラー文言・docstring 用の scope 一覧は enum から導出する（scope 追加時に文言が古くならないように）。
_SCOPE_LABEL = "/".join(s.value for s in PolicyScope)


def _parse_scope(scope: str) -> PolicyScope | None:
    return _SCOPES.get((scope or "").strip())


def _reference_view(rule: ReferenceRule) -> dict:
    """参照規則を改善AI・UI向けの日本語メタデータ付き表示へ変換する。"""
    label, description = REFERENCE_SOURCE_META[rule.source]
    return {
        **rule.model_dump(mode="json"),
        "label": label,
        "description": description,
    }


def _parse_reference_sources(
    enable: str, disable: str
) -> tuple[set[ReferenceSource], set[ReferenceSource]] | dict:
    """FunctionTool から渡る素の文字列を閉じた ReferenceSource 語彙へ変換する。"""
    known = {source.value: source for source in ReferenceSource}

    def parse(raw: str) -> tuple[set[ReferenceSource], list[str]]:
        values = {value.strip() for value in (raw or "").split(",") if value.strip()}
        return {known[value] for value in values if value in known}, sorted(values - known.keys())

    enabled, unknown_enabled = parse(enable)
    disabled, unknown_disabled = parse(disable)
    unknown = sorted({*unknown_enabled, *unknown_disabled})
    if unknown:
        return {
            "status": "rejected",
            "detail": f"未知の reference source です: {', '.join(unknown)}",
            "valid_sources": [
                {
                    "source": source.value,
                    "label": REFERENCE_SOURCE_META[source][0],
                }
                for source in ReferenceSource
            ],
        }
    overlap = enabled & disabled
    if overlap:
        return {
            "status": "rejected",
            "detail": "同じ資料を有効化と無効化の両方には指定できません: "
            + ", ".join(source.value for source in ReferenceSource if source in overlap),
        }
    return enabled, disabled


def _reference_update_plan(
    scope: str, enable: str, disable: str, *, book=None, book_id: str | None = None
) -> tuple[PolicyScope, list[ReferenceRule], list[ReferenceRule]] | dict:
    """現在値と文字列引数から参照規則の変更前・変更後を決定的に組み立てる。"""
    sc = _parse_scope(scope)
    if sc is None:
        return {
            "status": "rejected",
            "detail": f"scope は {_SCOPE_LABEL} のいずれか: {scope!r}",
        }
    parsed = _parse_reference_sources(enable, disable)
    if isinstance(parsed, dict):
        return parsed
    enabled, disabled = parsed
    if book is None:
        book = policy_store.load_book(**({"book_id": book_id} if book_id is not None else {}))
    card = policy_store.reference_policy_card(book, sc)
    if card is None:
        return {
            "status": "rejected",
            "detail": f"{sc.value}には参照する資料の既定設定がありません",
        }

    before = list(card.references)
    current = {rule.source: rule for rule in before}
    after = []
    for rule in before:
        enabled_value = rule.source in enabled or rule.enabled
        if rule.source in disabled:
            enabled_value = False
        after.append(rule.model_copy(update={"enabled": enabled_value}))
    for source in ReferenceSource:
        if source in current or source not in enabled:
            continue
        enabled_value = True
        if source in disabled:
            enabled_value = False
        after.append(ReferenceRule(source=source, enabled=enabled_value))
    return sc, before, after


def read_reference_policy(scope: str, *, book_id: str | None = None) -> dict:
    """当該 scope の reference_policy を日本語ラベル付きで返す。"""
    sc = _parse_scope(scope)
    if sc is None:
        return {"references": [], "detail": f"scope は {_SCOPE_LABEL} のいずれか: {scope!r}"}
    book = policy_store.load_book(**({"book_id": book_id} if book_id is not None else {}))
    card = policy_store.reference_policy_card(book, sc)
    if card is None:
        return {
            "scope": sc.value,
            "references": [],
            "detail": f"{sc.value}には参照する資料の既定設定がありません",
        }
    return {
        "scope": sc.value,
        "references": [_reference_view(rule) for rule in card.references],
    }


def propose_reference_update(
    scope: str,
    enable: str,
    disable: str,
    reason: str = "",
    *,
    book_id: str | None = None,
) -> dict:
    """自然言語から抽出した参照資料の変更を、保存せず確認案として返す。"""
    plan = _reference_update_plan(scope, enable, disable, book_id=book_id)
    if isinstance(plan, dict):
        return plan
    sc, before, after = plan
    return {
        "status": "ok",
        "proposal": {
            "scope": sc.value,
            "before": [_reference_view(rule) for rule in before],
            "after": [_reference_view(rule) for rule in after],
            "reason": reason.strip(),
            "enable": enable,
            "disable": disable,
        },
        "guidance": "ask_caregiver で変更前と変更後を示し、保育士の同意後だけ反映してください。",
    }


def commit_reference_update(
    scope: str,
    enable: str,
    disable: str,
    decided_by: str = "保育士",
    *,
    book_id: str | None = None,
) -> dict:
    """保育士の決定後、参照資料の既定設定を楽観ロック付きで即反映する。"""
    try:
        storage = {"book_id": book_id} if book_id is not None else {}
        book, version = policy_store.load_book_meta(**storage)
        plan = _reference_update_plan(scope, enable, disable, book=book)
        if isinstance(plan, dict):
            return plan
        sc, _, after = plan
        updated = policy_store.update_reference_policy(
            book,
            scope=sc,
            references=after,
            when=datetime.now(),
            decided_by=decided_by,
            source="改善エージェント",
        )
        policy_store.save_book(updated, if_version=version, **storage)
    except ValueError as error:
        return {"status": "rejected", "detail": str(error)}

    card = policy_store.reference_policy_card(updated, sc)
    return {
        "status": "committed",
        "card": policy_store.card_view(card),
        "history_entry": policy_store.history_view(updated.history[-1]),
        "store": policy_store.store_status(),
    }


def read_policy_cards(scope: str = "", *, book_id: str | None = None) -> dict:
    """既存の active 指針カードを返す（意味的競合を精査する材料）。

    Args:
        scope: "共通"/"保育日誌"/"月案"/"保育経過記録" で絞る（空/不正は全件＝降格・落とさない）。

    Returns:
        {"cards": [{id, scope, body, rationale, source}], "count": n}
    """
    book = policy_store.load_book(**({"book_id": book_id} if book_id is not None else {}))
    cards = policy_store.active_cards(book, _parse_scope(scope))
    return {
        "cards": [
            {
                "id": c.id,
                "scope": c.scope.value,
                "body": c.body,
                "rationale": c.rationale,
                "source": c.source,
            }
            for c in cards
        ],
        "count": len(cards),
    }


def propose_policy_card(
    scope: str,
    body: str,
    rationale: str = "",
    source: str = "",
    conflicts_with: str = "",
    note: str = "",
    *,
    book_id: str | None = None,
) -> dict:
    """修正差分から導いた指針カード案を申告し、競合（意味的＋完全重複）を返す（§8）。

    LLM が `read_policy_cards` で既存を読み、意味的に矛盾する既存カードの id を `conflicts_with`
    （カンマ区切り）で申告する。ツールは完全重複（決定的・安全網）も併せて検出し、競合があれば op を
    supersede（置換）に寄せて返す（最終決定は保育士）。

    Returns:
        {status, proposal:{scope,body,rationale,source,op,supersede_id,note},
         exact_duplicate:{id,body}|None, declared_conflicts:[{id,body,scope}],
         inactive_conflict_ids:[id], unknown_conflict_ids:[id],
         has_conflict:bool, guidance:str}
    """
    sc = _parse_scope(scope)
    if sc is None:
        return {
            "status": "error",
            "detail": f"scope は {_SCOPE_LABEL} のいずれか: {scope!r}",
        }
    if not body.strip():
        return {"status": "error", "detail": "body（カード本文）が空です"}

    book = policy_store.load_book(**({"book_id": book_id} if book_id is not None else {}))
    dup = policy_store.find_exact_duplicate(book, sc, body)
    declared = []
    inactive_ids = []  # 置換済み・取り下げ済みカードを現行指針として再採用しない
    unknown_ids = []  # 申告されたが存在しない競合カード id（黙って捨てず素通りさせない）
    for cid in (c.strip() for c in conflicts_with.split(",")):
        if not cid:
            continue
        card = policy_store.find_card(book, cid)
        if card is not None and card.status == PolicyStatus.active:
            declared.append(card)
        elif card is not None:
            inactive_ids.append(cid)
        else:
            unknown_ids.append(cid)

    op = "supersede" if declared else "add"
    supersede_id = declared[0].id if declared else ""
    # 不明・非現行 id は競合参照の見直しが必要なので、競合ありとして扱い素通りを防ぐ。
    has_conflict = bool(declared) or dup is not None or bool(inactive_ids) or bool(unknown_ids)

    if dup is not None:
        guidance = (
            "完全重複あり：同じ内容のカードが既にあります。追加は不要か、置き換えるなら supersede を検討。"
            "ask_caregiver で保育士に確認してください。"
        )
    elif declared:
        guidance = (
            "意味的競合あり：ask_caregiver で既存カードと新案を比較相談し、保育士に "
            "『既存を残す／新しい案に置きかえる(supersede)／両方活かして統合』を選んでもらう。"
            "決定後に commit_policy_card で即反映。"
        )
    elif inactive_ids:
        guidance = (
            f"申告された競合カードは現行指針ではありません（{', '.join(inactive_ids)}）。"
            "置換済み・取り下げ済みカードを競合相手として扱わず、read_policy_cards が返す active カードだけで "
            "競合を確認し直してください。"
        )
    elif unknown_ids:
        guidance = (
            f"申告された競合カード id が見つかりません（{', '.join(unknown_ids)}）。read_policy_cards で "
            "id を確認し直して再提案するか、競合が無いなら conflicts_with を空にしてください"
            "（『競合なし』として素通りさせない）。"
        )
    else:
        guidance = (
            "競合なし：ask_caregiver で『この内容で指針に反映してよいか』を確認し、"
            "保育士の同意後に commit_policy_card（op=add）で即反映してください。"
        )

    return {
        "status": "ok",
        "proposal": {
            "scope": sc.value,
            "body": body.strip(),
            "rationale": rationale,
            "source": source,
            "op": op,
            "supersede_id": supersede_id,
            "note": note,
        },
        "exact_duplicate": ({"id": dup.id, "body": dup.body} if dup else None),
        "declared_conflicts": [
            {"id": c.id, "body": c.body, "scope": c.scope.value} for c in declared
        ],
        "inactive_conflict_ids": inactive_ids,
        "unknown_conflict_ids": unknown_ids,
        "has_conflict": has_conflict,
        "guidance": guidance,
    }


def commit_policy_card(
    scope: str,
    body: str,
    rationale: str = "",
    source: str = "",
    op: str = "add",
    supersede_id: str = "",
    decided_by: str = "保育士",
    *,
    book_id: str | None = None,
) -> dict:
    """保育士の決定で指針カードを**即反映**する（add／supersede→save_book・§8）。

    runtime 境界として `datetime.now()` を注入し PolicyCard を生成 → harness の policy_store で
    add/supersede → save_book（即反映）。「回した証拠」はカード内蔵の変更履歴（decided_by 含む）が担う。
    完全重複・対象不在・不正 scope は status="rejected"/"error" を返し、改善エージェントを落とさない。

    Returns:
        {status, card:{…card_view…}, history_entry:{at,by,summary,card_id}, store}
    """
    sc = _parse_scope(scope)
    if sc is None:
        return {
            "status": "error",
            "detail": f"scope は {_SCOPE_LABEL} のいずれか: {scope!r}",
        }
    if not body.strip():
        return {"status": "error", "detail": "body（カード本文）が空です"}

    now = datetime.now()  # runtime 境界でのみ now を注入（harness/schemas は純関数を保つ＝§5）
    # generation＝GCS 外部ストアの楽観ロック前提条件（ローカルは None＝従来動作）。
    storage = {"book_id": book_id} if book_id is not None else {}
    book, version = policy_store.load_book_meta(**storage)
    card = PolicyCard(
        id=policy_store.next_card_id(book),
        scope=sc,
        body=body.strip(),
        rationale=rationale,
        source=source or "保育士の修正メモ",
        created_at=now,
        updated_at=now,
    )
    if op == "supersede" and not supersede_id.strip():
        # 置き換え対象 id が無いのに黙って add に落とすと、旧カードが active のまま矛盾する新カードが
        # 併存し「置換した」ように見える＝意味的競合の解消というこのフローの目的が silent に破れる。
        # 不正 scope・本文空と同じく fail-loud にする。
        return {
            "status": "error",
            "detail": "supersede には置き換え対象カードの id（supersede_id）が必要です",
        }
    try:
        if op == "supersede":
            new_book = policy_store.supersede_card(
                book, old_id=supersede_id.strip(), new_card=card, decided_by=decided_by
            )
        else:
            new_book = policy_store.add_card(book, card, decided_by=decided_by)
    except ValueError as e:
        return {"status": "rejected", "detail": str(e)}

    try:
        policy_store.save_book(
            new_book, if_version=version, **storage
        )  # 即反映（DB は version 楽観ロック）
    except ValueError as e:
        # 読み込み後に他所で更新された（generation 競合）。黙って上書きせず再試行を促す。
        return {"status": "rejected", "detail": str(e)}

    change = new_book.history[-1]
    return {
        "status": "committed",
        "card": policy_store.card_view(card),
        "history_entry": policy_store.history_view(change),
        "store": policy_store.store_status(),
    }


_READ_POLICY_CARDS_IMPL = read_policy_cards
_PROPOSE_POLICY_CARD_IMPL = propose_policy_card
_COMMIT_POLICY_CARD_IMPL = commit_policy_card
_READ_REFERENCE_POLICY_IMPL = read_reference_policy
_PROPOSE_REFERENCE_UPDATE_IMPL = propose_reference_update
_COMMIT_REFERENCE_UPDATE_IMPL = commit_reference_update


def build_policy_tools(book_id: str | None = None) -> list:
    """認可済みの PolicyBook ID を閉じ込めた FunctionTool 用関数を構築する。

    book_id は LLM の引数へ公開しない。Web は workspace book を束縛し、CLI は None のまま
    従来の default book を使う。functools.partial は ADK のツール名導出を壊すため使わない。
    """

    def read_policy_cards(scope: str = "") -> dict:
        """認可済み領域にある既存の指針カードを読む。"""
        return _READ_POLICY_CARDS_IMPL(scope, book_id=book_id)

    read_policy_cards.__doc__ = _READ_POLICY_CARDS_IMPL.__doc__

    def propose_policy_card(
        scope: str,
        body: str,
        rationale: str = "",
        source: str = "",
        conflicts_with: str = "",
        note: str = "",
    ) -> dict:
        """認可済み領域の既存カードに対する指針カード案を作る。"""
        return _PROPOSE_POLICY_CARD_IMPL(
            scope,
            body,
            rationale,
            source,
            conflicts_with,
            note,
            book_id=book_id,
        )

    propose_policy_card.__doc__ = _PROPOSE_POLICY_CARD_IMPL.__doc__

    def read_reference_policy(scope: str) -> dict:
        """認可済み領域にある参照資料の現在設定を読む。"""
        return _READ_REFERENCE_POLICY_IMPL(scope, book_id=book_id)

    read_reference_policy.__doc__ = _READ_REFERENCE_POLICY_IMPL.__doc__

    def propose_reference_update(scope: str, enable: str, disable: str, reason: str = "") -> dict:
        """認可済み領域の参照資料について変更案を作る。"""
        return _PROPOSE_REFERENCE_UPDATE_IMPL(scope, enable, disable, reason, book_id=book_id)

    propose_reference_update.__doc__ = _PROPOSE_REFERENCE_UPDATE_IMPL.__doc__

    def commit_policy_card(
        scope: str,
        body: str,
        rationale: str = "",
        source: str = "",
        op: str = "add",
        supersede_id: str = "",
        decided_by: str = "保育士",
    ) -> dict:
        """保育士の決定後、認可済み領域へ指針カードを反映する。"""
        return _COMMIT_POLICY_CARD_IMPL(
            scope,
            body,
            rationale,
            source,
            op,
            supersede_id,
            decided_by,
            book_id=book_id,
        )

    commit_policy_card.__doc__ = _COMMIT_POLICY_CARD_IMPL.__doc__

    def commit_reference_update(
        scope: str,
        enable: str,
        disable: str,
        decided_by: str = "保育士",
    ) -> dict:
        """保育士の決定後、認可済み領域へ参照資料の変更を反映する。"""
        return _COMMIT_REFERENCE_UPDATE_IMPL(scope, enable, disable, decided_by, book_id=book_id)

    commit_reference_update.__doc__ = _COMMIT_REFERENCE_UPDATE_IMPL.__doc__

    return [
        read_policy_cards,
        propose_policy_card,
        read_reference_policy,
        propose_reference_update,
        commit_policy_card,
        commit_reference_update,
    ]
