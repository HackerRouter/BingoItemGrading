"""结构内容：模板与实测两种口径的方块、实体、容器产出。"""

from __future__ import annotations


from .model import Sourced, _structure_maps, _with_wall_variants

class ContentMixin:
    def loot_aliases(self) -> dict[str, tuple[str, ...]]:
        """挂墙变体 → 本体的别名表（上游的 `dropsLike` 关系）。"""
        from bingo_grading.loot_alias import load as load_aliases

        return load_aliases(self.pack_version())

    def _templated_subjects(self) -> frozenset:
        """有模板解析的结构变体：它们的实测行不能用作方块来源。"""
        cached = self._templated_cache
        if cached is None:
            cached = frozenset(
                row.subject
                for row in self.store.of_type("structure_content")
                if row.value.get("source") == "template"
            )
            self._templated_cache = cached
        return cached


    def structure_block_sources(
        self, block: str, *, dimension: str | None = None
    ) -> list[tuple[str, float, str]]:
        """哪些结构会放置这个方块，每处几个：`[(结构集合, 每处个数, 变体)]`。

        读 `structure_content.blocks_per_start`。**这个字段有两个口径**，
        `value["source"]` 区分：

        - `template`：模板 SNBT 静态解析，按 `piece_counts`（每实例各模板出现
          几次）加权到每实例 —— **结构专有方块**；
        - `measured`：采集侧逐结构扫包围盒 —— **含包围盒内的自然地形**。

        口径必须挑，不能混：`village_taiga` 的实测行有 17 个 `coal_ore`、
        1597 块 `stone`（都是地形），模板行则一个都没有（村庄用的是
        `cobblestone` 与 `dirt_path`）。当「每处几个」用会得出「跑一趟村庄
        拿 17 个煤矿石」。

        规则：**只要该结构变体有模板行，就不用它的实测行**。模板行才是
        「结构放置了什么」的答案；实测行是包围盒内的世界快照。整份数据里
        只有实测行的结构（矿井、要塞、试炼大厅这些没有可解析模板的硬编码部件）
        才退回实测，并在 label 里标出「含地形」。

        同一集合有多个变体时按变体取平均（等权，与箱数同口径）。

        **挂墙变体也认**：龙头 / 头颅在结构里通常以 `*_wall_head`、`*_wall_skull`
        的形态生成（末地船船头挂的是 `dragon_wall_head`），而物品来自破掉它。
        只按 `dragon_head` 查会一个也找不到，于是「末地船有龙头」这件事实被漏掉。
        """
        maps = _structure_maps()
        variant_to_set: dict[str, str] = {}
        for set_id, variants in maps.members:
            for variant in variants:
                variant_to_set[variant] = set_id
        names = _with_wall_variants(block, self.loot_aliases())
        # `None` 表示不按维度筛。方块在哪生成就是哪——镶金黑石只在下界，
        # 而调用方默认在主世界，按默认维度筛会把它判成「没有来源」。
        scope = dimension
        # 有模板解析的变体：它们的实测行不可用作方块来源。
        templated = self._templated_subjects()
        # `{集合: {变体: (每处个数, 口径)}}`
        values: dict[str, dict[str, tuple[float, str]]] = {}
        for row in self.store.of_type("structure_content"):
            if scope is not None and row.dimension not in ("", scope):
                continue
            source = str(row.value.get("source") or "")
            if source != "template" and row.subject in templated:
                continue
            blocks = row.value.get("blocks_per_start") or {}
            amount = sum(
                float(blocks[name])
                for name in names
                if isinstance(blocks.get(name), (int, float)) and blocks[name] > 0
            )
            if amount <= 0:
                continue
            set_id = variant_to_set.get(row.subject)
            if set_id is None:
                continue
            bucket = values.setdefault(set_id, {})
            previous = bucket.get(row.subject)
            # 同一变体两条行都在时，模板口径胜出。
            if previous is not None and previous[1] == "template":
                continue
            bucket[row.subject] = (amount, source)
        out: list[tuple[str, float, str]] = []
        for set_id, per_variant in sorted(values.items()):
            template_variants = {
                name: item for name, item in per_variant.items() if item[1] == "template"
            }
            chosen = template_variants or per_variant
            suffix = "" if template_variants else "（实测口径，含地形）"
            average = sum(amount for amount, _ in chosen.values()) / len(chosen)
            label = (
                "、".join(
                    f"{name.split(':')[-1]}={amount:g}"
                    for name, (amount, _) in sorted(chosen.items())
                )
                if len(chosen) > 1
                else next(iter(chosen))
            )
            out.append((set_id, average, label + suffix))
        return out


    def structure_mob_sources(
        self, mob: str
    ) -> list[tuple[str, float, str, str]]:
        """哪些结构里有这个生物：`[(结构集合, 每处几只, 变体, 来源种类)]`。

        两种来源分开算，成本模型不同：

        - `spawners_per_start`：刷怪笼（键形如 `mob_spawner|blaze`）——**无限刷**，
          在那儿等着就行，单价按「等一只」的周期摊。两种笼子的周期不是一个量级：
          `mob_spawner` 是 200–800 tick，`trial_spawner` 是 20–160 tick 补一批；
        - `entities_per_start`：结构自带、已生成好的（末地城每处 21 只潜影贝）——
          **一趟打完就没了**，单价按「一趟打完全部」摊。

        这是敌对生物唯一可信的静态来源：自然界密度依赖玩家活动与光照，
        扫描量不出来（C17 已撤回），但「这个结构里有几只」是结构事实。
        """
        maps = _structure_maps()
        variant_to_set: dict[str, str] = {}
        for set_id, variants in maps.members:
            for variant in variants:
                variant_to_set[variant] = set_id
        mob_name = mob.split(":", 1)[-1]
        values: dict[str, dict[str, float]] = {}
        for row in self.store.rows.values():
            if row.stat_type != "structure_content":
                continue
            set_id = variant_to_set.get(row.subject)
            if set_id is None:
                continue
            for key, amount in (row.value.get("spawners_per_start") or {}).items():
                kind, _, name = key.partition("|")
                if not name or name != mob_name:
                    continue
                if not isinstance(amount, (int, float)) or amount <= 0:
                    continue
                values.setdefault(f"{set_id}|{kind}", {})[row.subject] = float(amount)
            for key, amount in (row.value.get("entities_per_start") or {}).items():
                if key.split(":", 1)[-1] != mob_name:
                    continue
                if not isinstance(amount, (int, float)) or amount <= 0:
                    continue
                values.setdefault(f"{set_id}|entities", {})[row.subject] = float(amount)
            # 结构定义里写死的生成量（`STRUCTURE_SPAWNED`）：海底神殿每处 3 只
            # 远古守卫者。实扫的 `entities` 对它是空的——玩家到达时守卫者
            # 已经死完或被卸载——所以这一路不能省。
            for key, amount in (row.value.get("spawned_per_start") or {}).items():
                if key.split(":", 1)[-1] != mob_name:
                    continue
                if not isinstance(amount, (int, float)) or amount <= 0:
                    continue
                values.setdefault(f"{set_id}|spawned", {})[row.subject] = float(amount)
        out: list[tuple[str, float, str, str]] = []
        for compound, per_variant in sorted(values.items()):
            set_id, _, kind = compound.partition("|")
            average = sum(per_variant.values()) / len(per_variant)
            out.append((set_id, average, next(iter(per_variant)), kind))
        return out


    def structure_entity_per_site(
        self, structure_set: str, entity: str, *, dimension: str | None = None
    ) -> Sourced | None:
        """每处结构里有几个该实体（已生成好的，不是刷怪笼）。

        末地城的鞘翅挂在**末地船**的物品展示框里，而「有没有船」这件事数据里
        只体现为 `entities_per_start["minecraft:item_frame"] = 0.44`——
        即约 44% 的末地城带船。要拿一个鞘翅平均得跑 1/0.44 处。
        """
        members = _structure_maps().members_of(structure_set)
        if not members:
            return None
        dimension = dimension or self.dimension
        values: dict[str, float] = {}
        for row in self.store.rows.values():
            if row.stat_type != "structure_content":
                continue
            if row.subject not in members:
                continue
            if row.dimension not in ("", dimension):
                continue
            amount = (row.value.get("entities_per_start") or {}).get(entity)
            if not isinstance(amount, (int, float)) or amount <= 0:
                amount = (row.value.get("spawned_per_start") or {}).get(entity)
            if isinstance(amount, (int, float)) and amount > 0:
                values[row.subject] = max(values.get(row.subject, 0.0), float(amount))
        if not values:
            return None
        average = sum(values.values()) / len(values)
        return Sourced(
            average,
            "structure_content:entities_per_start",
            f"{structure_set} 每处 {entity.split(':')[-1]} "
            + "、".join(f"{n.split(':')[-1]}={v:g}" for n, v in sorted(values.items())),
        )


    def structure_block_yield(
        self,
        block: str,
        structure_set: str,
        *,
        dimension: str | None = None,
    ) -> Sourced | None:
        """每处结构里有多少个该方块。

        用途：干草块这类**只在结构内生成**的方块。直接读 `block_density` 的
        每区块平均会算出「挖几百个区块才遇到一个」，那是错的——干草块不是散落
        在地里的，它长在村庄的马厩和动物栏里，进村就能拿到一堆。

        算法：`全图该方块总量 ÷ 扫描范围内的结构数量`。结构数量由
        `structure_density` 的 `spacing` 推出（间距为 s 区块的网格，密度 1/s²）。

        这把「只在结构内」这个约束编码进去了，比全图平均高一个数量级，
        也更接近实际「进一个村庄能拿到多少」。

        局限：假设该方块**全部**来自该结构。若它还有别的来源（野外散布、
        其他结构），结果会偏高。调用方应在 `assumptions` 中标明这一点。
        """
        dimension = dimension or self.dimension
        density_row = None
        for row in self.store.rows.values():
            if (
                row.stat_type == "block_density"
                and row.subject == block
                and row.dimension == dimension
            ):
                density_row = row
                break
        if density_row is None:
            return None

        structure_row = None
        for row in self.store.rows.values():
            if (
                row.stat_type == "structure_density"
                and row.subject == structure_set
                and row.dimension == dimension
            ):
                structure_row = row
                break
        if structure_row is None:
            return None

        spacing = structure_row.value.get("spacing")
        chunks = density_row.value.get("chunks")
        total = density_row.value.get("total_blocks")
        if not spacing or not chunks or total is None:
            return None

        structures = chunks / (spacing * spacing)
        if structures <= 0:
            return None
        per_structure = total / structures
        return Sourced(
            per_structure,
            "block_density÷structure_density",
            f"{block} 全图 {total} 个 ÷ {structures:.1f} 处 {structure_set}"
            f"（{chunks} 区块 / spacing {spacing}²）",
        )


    # ---------------------------------------------------------------- 结构与交易

    def structure_content(
        self,
        subject: str,
        *,
        source: str = "auto",
        dimension: str | None = None,
    ) -> tuple[dict, str] | None:
        """某结构的内容：`(value, 出处)`。

        `source="auto"` 时按优先级取：先 `template`（结构模板的静态真值），
        没有再取 `measured`（采集侧实测）。

        **两者分母不同，不能混用**：
        - `template`：`containers` = 每**模板**平均，用来判「有哪些表 / 哪些方块」；
        - `measured`：`containers` = 每**起点（实例）**平均，用来算「跑一趟拿多少」。

        算代价应当显式取 `source="measured"`；取白名单或结构专有方块用 `template`。
        """
        dimension = dimension or self.dimension
        order = ("template", "measured") if source == "auto" else (source,)
        for wanted in order:
            for row in self.store.rows.values():
                if row.stat_type != "structure_content" or row.subject != subject:
                    continue
                if (row.value.get("source") or "") != wanted:
                    continue
                if wanted == "measured" and row.dimension != dimension:
                    continue
                return dict(row.value), f"structure_content:{subject}[{wanted}]"
        return None
