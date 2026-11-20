"""强连通分量：一次算完，之后 O(1) 查「两点是否同属一环」。

从 `ra/solve/scc.py` 提升上来的纯算法（无第三方依赖），两个 Minecraft
数据项目共用同一份实现，避免各写一遍、各踩一遍坑。

## 为什么不靠「找一条回路」

用 DFS 找环有两个问题：

1. **会误判**：两个节点互相引用不等于「没有入口」。比如
   `block:furnace → item:furnace` 有回路，但另有配方入口，
   不构成「无入口的环」。按「缺项最少的规则」查回去会把可达物品报成死锁。
2. **很慢**：回溯时移除外层 `seen`，同一节点被反复访问。

所以改用一次 Kosaraju：判据是分量性质——「该节点所在分量没有成员可达，
且分量大小 > 1」，与「从某个起点走回起点」无关。
"""

from __future__ import annotations


def strongly_connected(graph: dict[str, set[str]]) -> dict[str, int]:
    """Kosaraju（迭代版），返回 `节点 → 分量编号`。

    `graph` 是 `节点 → 后继`。未在 `graph` 里出现的节点也会被分配分量
    （只要它作为后继出现过）。
    """
    vertices = set(graph)
    for targets in graph.values():
        vertices |= targets

    # 第一遍：DFS 求完成序
    order: list[str] = []
    visited: set[str] = set()
    for root in sorted(vertices):
        if root in visited:
            continue
        stack: list[tuple[str, bool]] = [(root, False)]
        while stack:
            node, expanded = stack.pop()
            if expanded:
                order.append(node)
                continue
            if node in visited:
                continue
            visited.add(node)
            stack.append((node, True))
            for nxt in sorted(graph.get(node, ())):
                if nxt not in visited:
                    stack.append((nxt, False))

    # 反向图
    reverse: dict[str, set[str]] = {}
    for node, targets in graph.items():
        for target in targets:
            reverse.setdefault(target, set()).add(node)

    # 第二遍：按完成序的逆序在反向图上 DFS
    component: dict[str, int] = {}
    index = 0
    for node in reversed(order):
        if node in component:
            continue
        stack = [node]
        component[node] = index
        while stack:
            current = stack.pop()
            for prev in sorted(reverse.get(current, ())):
                if prev not in component:
                    component[prev] = index
                    stack.append(prev)
        index += 1

    return component


def component_members(component: dict[str, int]) -> dict[int, list[str]]:
    """分量编号 → 成员（已排序）。"""
    members: dict[int, list[str]] = {}
    for node, cid in component.items():
        members.setdefault(cid, []).append(node)
    return {cid: sorted(values) for cid, values in members.items()}


def cycles_of(graph: dict[str, set[str]]) -> tuple[tuple[str, ...], ...]:
    """图里所有「真正的环」：分量大小 > 1 的那些，成员按字典序。

    自环（`a → a`）也算：单个节点自己指向自己，分量大小是 1，
    所以要单独看有没有自边。
    """
    component = strongly_connected(graph)
    out: list[tuple[str, ...]] = []
    for cid, nodes in component_members(component).items():
        if len(nodes) > 1:
            out.append(tuple(nodes))
            continue
        node = nodes[0]
        if node in graph.get(node, ()):
            out.append(tuple(nodes))
    return tuple(sorted(out))
