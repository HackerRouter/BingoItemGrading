"""刷怪与交易：权重、袭击、村民报价。"""

from __future__ import annotations


from .model import _structure_maps

class MobsMixin:
    def mob_spawn_weights(self, holder: str) -> tuple[dict[str, dict], str] | None:
        """某个 holder 的刷怪规则：`({entity: value}, 出处)`。

        `holder` 是 RA 刷怪表里的原始键，形如 `structure:minecraft:fortress`
        或 `biome:minecraft:badlands`（列表见 `spawn_tables.jsonl`）。

        返回的是**静态规则**（`weight` / `count_min` / `count_max` / `wave`），
        不是实测密度。要算「一趟遇到几只」，得再乘现场停留时间；
        密度口径请用 `mob_density`，两者不要混。

        raid 类没有 `weight`，只有 `wave` 与 `count_*`，此处按整场聚合返回。
        """
        rows = self._mob_spawn_index().get(holder)
        if not rows:
            return None
        return dict(rows), f"mob_spawn:{holder}"


    def _mob_spawn_index(self) -> dict[str, dict[str, dict]]:
        """`{holder: {entity: value}}`，懒构建（全表 850 行，只扫一次）。"""
        cached = self._mob_spawn_cache.get("index")
        if cached is not None:
            return cached
        index: dict[str, dict[str, dict]] = {}
        for row in self.store.rows.values():
            if row.stat_type != "mob_spawn":
                continue
            condition = (row.condition or "").strip()
            if not condition.startswith("holder="):
                continue
            index.setdefault(condition[len("holder=") :], {})[row.subject] = dict(row.value)
        self._mob_spawn_cache["index"] = index
        return index


    def structure_spawn_weights(
        self, mob: str
    ) -> list[tuple[str, float, float, str]]:
        """结构刷怪表里出现在哪些结构：`[(结构集合, 权重, 同类别权重和, 类别)]`。

        只算 `structure:` / `structure_template:` 两类 holder。权重是**结构内部**
        刷怪规则的相对值：在同类刷怪尝试里，刷到目标生物的机率是
        `weight / 同类别权重和`，所以想拿一只平均要打死倒数这么多只。

        同类别才求和是有原因的：`monster` 与 `creature` 走不同的刷怪上限，
        不共用一个名额池，混着算会把机率押低。
        """
        mob_name = mob.split(":", 1)[-1]
        # 刷怪表用**变体名**（`structure:minecraft:monument`），
        # 而行程/水下判定用**结构集合名**（`minecraft:ocean_monuments`）。
        variant_to_set: dict[str, str] = {}
        for set_id, variants in _structure_maps().members:
            for variant in variants:
                variant_to_set[variant] = set_id
        out: list[tuple[str, float, float, str]] = []
        for holder, rows in sorted(self._mob_spawn_index().items()):
            kind, _, name = holder.partition(":")
            if kind not in ("structure", "structure_template") or not name:
                continue
            set_id = variant_to_set.get(name, name)
            target = None
            for entity, value in rows.items():
                if entity.split(":", 1)[-1] == mob_name:
                    target = value
                    break
            if target is None:
                continue
            weight = target.get("weight")
            if not isinstance(weight, (int, float)) or weight <= 0:
                continue
            category = str(target.get("category") or "")
            total = 0.0
            for value in rows.values():
                if str(value.get("category") or "") != category:
                    continue
                other = value.get("weight")
                if isinstance(other, (int, float)) and other > 0:
                    total += float(other)
            if total <= 0:
                continue
            out.append((set_id, float(weight), total, category))
        return out


    def raid_spawns(
        self, mob: str
    ) -> list[tuple[str, dict, list[tuple[int, float]], list[tuple[int, float]]]]:
        """袭击里的这个生物：`[(holder, 规则, 每波总数, 每波目标数)]`。

        袭击是**事件**不是随机刷怪：不祥之瓶 + 村庄触发，按波次成批出怪。
        波次是**有顺序的**，想拿到第 7 波的东西就得把前 6 波也打完，
        所以这里返回逐波明细而不是整场合计——下游按「打到目标出现为止」累加。

        两个列表都是 `[(波号, 数量)]`，只含非零波，按波号升序。
        """
        mob_name = mob.split(":", 1)[-1]
        out: list[tuple[str, dict, list[tuple[int, float]], list[tuple[int, float]]]] = []
        for holder, rows in sorted(self._mob_spawn_index().items()):
            if not holder.startswith("raid:"):
                continue
            target = None
            for entity, value in rows.items():
                if entity.split(":", 1)[-1] == mob_name:
                    target = value
                    break
            if target is None:
                continue
            per_wave_target: list[tuple[int, float]] = []
            raw = target.get("wave_counts") or {}
            for key, amount in raw.items():
                if isinstance(amount, (int, float)) and amount > 0:
                    per_wave_target.append((int(key), float(amount)))
            per_wave_target.sort()
            if not per_wave_target:
                continue
            totals: dict[int, float] = {}
            for value in rows.values():
                for key, amount in (value.get("wave_counts") or {}).items():
                    if not isinstance(amount, (int, float)) or amount <= 0:
                        continue
                    wave = int(key)
                    totals[wave] = totals.get(wave, 0.0) + float(amount)
            per_wave_total = sorted(totals.items())
            out.append((holder, target, per_wave_total, per_wave_target))
        return out


    def trade_offers(
        self, profession: str, level: int | str
    ) -> tuple[list[dict], str] | None:
        """某职业某等级的全部报价：`(offers, 出处)`。

        同一等级可能有多条等价交易（农民 1 级有小麦/甜菜根/胡萝卜/马铃薯），
        这里原样返回，选哪条由调用方按代价决定。
        """
        subject = f"minecraft:{profession}/{level}"
        for row in self.store.rows.values():
            if row.stat_type != "trade_offer" or row.subject != subject:
                continue
            return list(row.value.get("offers") or []), f"trade_offer:{subject}"
        return None
