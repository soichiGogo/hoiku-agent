"""agents の出力・抽出プロンプト契約を LLM 非依存で検査する。"""

from __future__ import annotations

from hoiku_agent.agents.prompts import (
    CLASS_MONTHLY_AUTHOR_INSTRUCTION,
    build_upload_extract_instruction,
)


def test_class_monthly_author_omits_class_name_from_json_contract():
    """クラス名は手書き相当なので、作成 AI に生成・転記させない。"""
    assert '"class_name":' not in CLASS_MONTHLY_AUTHOR_INSTRUCTION
    assert "クラス名（class_name）は書かず、JSON に含めない" in CLASS_MONTHLY_AUTHOR_INSTRUCTION
    assert "seed や名簿から推測・転記・創作しない" in CLASS_MONTHLY_AUTHOR_INSTRUCTION


def test_class_monthly_upload_still_extracts_class_name_from_source():
    """既存書類の取込は別経路なので、原本にあるクラス名を引き続き抽出する。"""
    instruction = build_upload_extract_instruction(
        "class_monthly", age_band="0-2", target="2026-07"
    )

    assert '"class_name": "クラス名（原本にあれば。例: ひよこ組。無ければ空文字）"' in instruction
