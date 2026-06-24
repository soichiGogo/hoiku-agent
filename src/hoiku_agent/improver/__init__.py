"""improver：二階「回す」自走ループの公開 API（設計コンテキスト §8）。

root_agent（一階）とは別エントリ。ここを agent.py から import しない（自動起動しない）。
"""

from .improver_agent import build_improver_agent

__all__ = ["build_improver_agent"]
