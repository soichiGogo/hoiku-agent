"""harness：ドラフトの様式整形（決定的）。

設計コンテキスト §5/§6。write_draft の "実体" はここに1つだけ置く。tools/write_draft.py は
FunctionTool としてこれを呼ぶ薄いラッパ。確定出力（整形済みドラフト）の決定的実行は harness が
パイプライン末尾で行う（tool ではなくステップ＝§6）。

pydantic スキーマ（DiaryEntry 等）→ 園の様式テキストへ整形する。LLM は呼ばない。
"""

from __future__ import annotations

from ..schemas import DiaryEntry


def write_draft(entry: DiaryEntry, template_ref: str | None = None) -> str:
    """日誌ドラフト（DiaryEntry）を様式テキストへ整形して返す。

    Args:
        entry: 整形対象の日誌ドラフト。
        template_ref: 雛形のパス等（あれば様式に従う）。越谷市様式は末尾「など」＝園差で拡張可。

    Returns:
        様式に整形した文字列。

    TODO(設計):
    - template_ref に基づく実様式整形（ヒアリングで実様式1枚を入手後＝§18）。
    - 10の姿/3つの視点タグの明示出力（§13 のドメイン作り込み）。
    """
    # TODO: 実様式整形に置き換える（下は最小の確認用整形）。
    return (
        f"【保育日誌 {entry.date} / {entry.age_band.value} / 天候:{entry.weather}】\n"
        f"実践記録: {entry.practice_record}\n"
        f"評価・反省(a 子ども): {entry.evaluation.child_focus}\n"
        f"評価・反省(b 自分): {entry.evaluation.self_review}\n"
    )
