"""Agent Engine（Memory Bank）の作成・設定スクリプト（手動運用・要 GCP 資格情報）。

設計コンテキスト §9/§13：子ども別長期メモリ＝Agent Engine Memory Bank。本スクリプトは「来園のたびに
像が育つ」記憶を**保育ドメイン向けにチューニングして**用意する、再現可能な provisioning エントリ。
（root_agent からは呼ばない。`recall_child_history` とWeb承認時の
`memory_writeback.persist_approved_facts` が使う接続先を整える運用ツール。）

何をするか:
- Agent Engine を作成（または既存 `AGENT_ENGINE_ID` を更新）し、Memory Bank に
  ① 生成モデル（`generation_config.model`・完全修飾パス。未設定だと記憶が生成されない＝実機で判明）と
  ② 生成カスタマイズ（日本語・**子の姿に焦点**・三人称＝子について。書類作成のメタ情報は記録しない）
  を設定する。最後に `.env` に入れる `AGENT_ENGINE_ID` を表示する。

使い方（要 ADC＝`gcloud auth application-default login` 済み・`.env` に PROJECT/LOCATION）:
    uv run python scripts/provision_memory_bank.py --create        # 新規作成して設定
    uv run python scripts/provision_memory_bank.py                 # .env の AGENT_ENGINE_ID を再設定（冪等）
    uv run python scripts/provision_memory_bank.py --model gemini-2.5-flash

設定後は `docs/ライブ実行手順.md` の手順2以降（`.env` 設定 → `uvicorn server:app`）へ。
"""

from __future__ import annotations

import argparse

import vertexai

from hoiku_agent.config import settings

# 生成カスタマイズ（§13 ドメイン作り込み）：保育日誌の観察→「子の姿」を日本語・三人称で抽出する。
# managed topic（USER_* 等）は保育者(user)中心の要約になり「下書きを依頼・承認した」等のメタを拾うため、
# custom topic で上書きし、few-shot で日本語・子の姿の文体を教える。
CHILD_OBSERVATION_CUSTOMIZATION: dict = {
    "enable_third_person_memories": True,  # 記憶は「その子について」（三人称）＝保育者(user)ではない
    "memory_topics": [
        {
            "custom_memory_topic": {
                "label": "child_observation",
                "description": (
                    "保育日誌の観察記録から、その子（架空児）の発達・遊び・興味・人との関わり・育ちの"
                    "『姿』を日本語で簡潔に1〜2文で抽出する。実名は使わず架空児の仮名で表す。"
                    "書類作成の依頼・下書き生成や承認の有無などのメタ情報、フォーマットの話、"
                    "保育者自身の振り返りは記録しない。"
                ),
            }
        }
    ],
    "generate_memories_examples": [
        {
            "conversation_source": {
                "events": [
                    {
                        "content": {
                            "role": "user",
                            "parts": [
                                {
                                    "text": "観察メモ：架空児ハナ（1歳）は絵本を指さして声を出し、保育者と顔を見合わせて笑った。0–2個別の保育日誌の下書きを作成してください。"
                                }
                            ],
                        }
                    },
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "text": '下書きを作成しました。```json {"individual_notes":[{"child_id":"架空児ハナ"}]} ```'
                                }
                            ],
                        }
                    },
                ]
            },
            "generated_memories": [
                {
                    "fact": "架空児ハナは絵本を指さして声を出し、保育者と視線を交わして笑うなど、身近な人と気持ちを通わせるやりとりを楽しむ姿が見られる。",
                    "topics": [{"custom_memory_topic_label": "child_observation"}],
                }
            ],
        }
    ],
}


def _full_model(project: str, location: str, model: str) -> str:
    """生成モデルは完全修飾の resource path で渡す（短縮名は Invalid model name で弾かれる＝実機で判明）。"""
    if model.startswith("projects/"):
        return model
    return f"projects/{project}/locations/{location}/publishers/google/models/{model}"


def provision(create: bool, model: str) -> str:
    """Memory Bank を作成/更新し、ENGINE_ID を返す。"""
    project = settings.google_cloud_project
    location = settings.google_cloud_location
    if not project:
        raise SystemExit("GOOGLE_CLOUD_PROJECT が未設定です（.env を確認）。")

    client = vertexai.Client(project=project, location=location)
    memory_bank_config = {
        "generation_config": {"model": _full_model(project, location, model)},
        "customization_configs": [CHILD_OBSERVATION_CUSTOMIZATION],
    }

    if create or not settings.agent_engine_id:
        engine = client.agent_engines.create(config={"display_name": "hoiku-memory-bank"})
        name = engine.api_resource.name  # projects/.../reasoningEngines/<id>
        print(f"作成: {name}")
    else:
        name = (
            f"projects/{project}/locations/{location}/reasoningEngines/{settings.agent_engine_id}"
        )
        print(f"更新: {name}")

    client.agent_engines.update(
        name=name, config={"context_spec": {"memory_bank_config": memory_bank_config}}
    )
    engine_id = name.rstrip("/").split("/")[-1]
    print(
        f"設定完了（生成モデル＋日本語/子の姿カスタマイズ）。\n.env に設定: AGENT_ENGINE_ID={engine_id}"
    )
    return engine_id


def main() -> None:
    ap = argparse.ArgumentParser(description="Memory Bank（Agent Engine）の作成・設定")
    ap.add_argument("--create", action="store_true", help="新規に Agent Engine を作成する")
    ap.add_argument(
        "--model", default="gemini-2.5-flash", help="記憶生成モデル（既定 gemini-2.5-flash）"
    )
    args = ap.parse_args()
    provision(create=args.create, model=args.model)


if __name__ == "__main__":
    main()
