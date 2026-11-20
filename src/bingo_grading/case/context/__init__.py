"""DAG 案例的数据来源。

案例不该自己编数字。这个模块把「从统计层取哪个数」收敛成几个方法，
每个方法都返回数值的来源说明，好让诊断输出能区分真实数据与假设值。

实现按取数族拆成 mixin，`base.CaseContext` 组合它们；本文件只做门面。
"""

from __future__ import annotations

from .base import CaseContext
from .model import BlockExposure, CaseError, PatchSource, Sourced

__all__ = ["BlockExposure", "CaseContext", "CaseError", "PatchSource", "Sourced"]
