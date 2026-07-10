"""游戏规则接口与默认实现。"""

from .interface import RuleSet, Resonance
from .ymjh_default import YMJHDefaultRuleSet

__all__ = ["RuleSet", "Resonance", "YMJHDefaultRuleSet"]
