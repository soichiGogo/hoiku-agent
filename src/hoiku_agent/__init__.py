"""hoiku-agent: 保育士の書類作成を支援するAIエージェント。

ADK の探索規約に合わせ、agent サブモジュールと root_agent を再エクスポートする
（`from . import agent` が ADK の root_agent 発見に必要）。
"""

from . import agent
from .agent import root_agent

__all__ = ["agent", "root_agent"]
