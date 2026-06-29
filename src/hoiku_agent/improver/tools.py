"""改善エージェント（二階）固有のツール。

設計コンテキスト §8。育つ指針の正(SSOT)は構造化カードストア（`knowledge/文書作成指針.json`）。
改善エージェントは次を回す（番人＝意味的競合精査＋保育士の決定）:
- read_policy_cards … 既存 active カードを読む（意味的競合を精査する材料）。
- propose_policy_card … 修正差分から追加/改訂案を作り、**意味的に競合する既存カードを自分で申告**する。
  決定的な完全重複は安全網（policy_store.find_exact_duplicate）が併せて検出する。
- ask_caregiver … 競合があれば該当カードと新案を**比較相談**、無くても反映可否を確認（人に訊く口は一階と共用）。
- commit_policy_card … 保育士の決定で**即反映**（add／supersede→save_book）。任意で git に証拠 commit。

決定的ロジックの実体は harness（policy_store / git_ops）に1つ（§5）。ここは harness を呼ぶ薄いラッパ＋
runtime 境界（`datetime.now()` の注入）だけ。意味的競合の判定は LLM（このエージェント）の責務で、
harness は完全重複の安全網のみを持つ（決定的）。run_eval/評価ゲートは取り込みフローから外す（eval は
CI の品質回帰として別系統で温存＝decouple・§12）。
"""

from __future__ import annotations

from datetime import datetime

from ..harness import policy_store
from ..harness.git_ops import commit_policy_book
from ..schemas.policy import PolicyCard, PolicyScope
from ..tools import ask_caregiver as ask_caregiver  # noqa: PLC0414  人に訊く口は一階と共用

_SCOPES = {s.value: s for s in PolicyScope}  # "共通"/"保育日誌"/"月案" → PolicyScope


def _parse_scope(scope: str) -> PolicyScope | None:
    return _SCOPES.get((scope or "").strip())


def read_policy_cards(scope: str = "") -> dict:
    """既存の active 指針カードを返す（意味的競合を精査する材料）。

    Args:
        scope: "共通"/"保育日誌"/"月案" で絞る（空/不正は全件＝降格・落とさない）。

    Returns:
        {"cards": [{id, scope, body, rationale, source}], "count": n}
    """
    book = policy_store.load_book()
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
) -> dict:
    """修正差分から導いた指針カード案を申告し、競合（意味的＋完全重複）を返す（§8）。

    LLM が `read_policy_cards` で既存を読み、意味的に矛盾する既存カードの id を `conflicts_with`
    （カンマ区切り）で申告する。ツールは完全重複（決定的・安全網）も併せて検出し、競合があれば op を
    supersede（置換）に寄せて返す（最終決定は保育士）。

    Returns:
        {status, proposal:{scope,body,rationale,source,op,supersede_id,note},
         exact_duplicate:{id,body}|None, declared_conflicts:[{id,body,scope}],
         has_conflict:bool, guidance:str}
    """
    sc = _parse_scope(scope)
    if sc is None:
        return {"status": "error", "detail": f"scope は 共通/保育日誌/月案 のいずれか: {scope!r}"}
    if not body.strip():
        return {"status": "error", "detail": "body（カード本文）が空です"}

    book = policy_store.load_book()
    dup = policy_store.find_exact_duplicate(book, sc, body)
    declared = []
    for cid in (c.strip() for c in conflicts_with.split(",")):
        card = policy_store.find_card(book, cid) if cid else None
        if card is not None:
            declared.append(card)

    op = "supersede" if declared else "add"
    supersede_id = declared[0].id if declared else ""
    has_conflict = bool(declared) or dup is not None

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
    commit: bool = False,
) -> dict:
    """保育士の決定で指針カードを**即反映**する（add／supersede→save_book・§8）。

    runtime 境界として `datetime.now()` を注入し PolicyCard を生成 → harness の policy_store で
    add/supersede → save_book（即反映）。`commit=True` で git_ops.commit_policy_book による証拠 commit。
    完全重複・対象不在・不正 scope は status="rejected"/"error" を返し、改善エージェントを落とさない。

    Returns:
        {status, card:{…card_view…}, history_entry:{at,by,summary,card_id}, store, committed}
    """
    sc = _parse_scope(scope)
    if sc is None:
        return {"status": "error", "detail": f"scope は 共通/保育日誌/月案 のいずれか: {scope!r}"}
    if not body.strip():
        return {"status": "error", "detail": "body（カード本文）が空です"}

    now = datetime.now()  # runtime 境界でのみ now を注入（harness/schemas は純関数を保つ＝§5）
    book = policy_store.load_book()
    card = PolicyCard(
        id=policy_store.next_card_id(book),
        scope=sc,
        body=body.strip(),
        rationale=rationale,
        source=source or "保育士の修正メモ",
        created_at=now,
        updated_at=now,
    )
    try:
        if op == "supersede" and supersede_id.strip():
            new_book = policy_store.supersede_card(book, old_id=supersede_id.strip(), new_card=card)
        else:
            new_book = policy_store.add_card(book, card)
    except ValueError as e:
        return {"status": "rejected", "detail": str(e)}

    policy_store.save_book(new_book)  # 即反映

    committed = None
    if commit:
        committed = commit_policy_book(
            title=f"policy: {sc.value} を更新（{card.id}・{decided_by}）", dry_run=False
        )

    change = new_book.history[-1]
    return {
        "status": "committed",
        "card": policy_store.card_view(card),
        "history_entry": policy_store.history_view(change),
        "store": policy_store.store_status(),
        "committed": committed,
    }
