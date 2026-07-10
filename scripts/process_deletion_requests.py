"""期限を過ぎたアカウント削除依頼を処理する運営者向けコマンド。"""

from __future__ import annotations

from datetime import datetime

from hoiku_agent.harness import record_store


def main() -> None:
    result = record_store.process_due_deletion_requests(now=datetime.now())
    print(f"削除処理: {result.get('status')}（{result.get('processed', 0)}件）")


if __name__ == "__main__":
    main()
