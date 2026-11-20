"""盘点采集侧产物的元数据完整性与契约缺口。

关心的点：版本、种子、范围、单位、维度、可复算所需的标识是否都落盘。
只读。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

run = Path(sys.argv[1])
print(f"运行目录 {run.name}")
print()

summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
print("summary 全部字段：")
print(json.dumps(summary, ensure_ascii=False, indent=1)[:1200])
print()

print("各分析器顶层字段是否有版本/种子/配置：")
for path in sorted(run.glob("*.json")):
    doc = json.loads(path.read_text(encoding="utf-8"))
    keys = sorted(doc)
    has = {name: (name in doc) for name in ("version", "minecraftVersion", "seed", "pack", "config", "jarSha256", "range", "areaSpec")}
    print(f"  {path.name:<34} {keys}")

print()
print("area 字符串：")
for path in sorted(run.glob("*.json")):
    doc = json.loads(path.read_text(encoding="utf-8"))
    print(f"  {path.name:<34} area={doc.get('area')!r}")
    print(f"  {'':<34} dimensions={doc.get('dimensions')}")

print()
print("entity-census 的 note 与聚类口径：")
doc = json.loads((run / "entity-census.json").read_text(encoding="utf-8"))
print(f"  note={doc['result'].get('note')!r}")
print(f"  clustering={doc['result'].get('clustering')}")

print()
print("ore-exposure 的 note：")
doc = json.loads((run / "ore-exposure.json").read_text(encoding="utf-8"))
print(f"  note={doc['result'].get('note')!r}")
print(f"  matrix.families={doc['result']['matrix'].get('families')}")
print(f"  byFamily 键={sorted(doc['result']['byFamily'])}")

print()
print("structure-spacing 的 note：")
doc = json.loads((run / "structure-spacing.json").read_text(encoding="utf-8"))
print(f"  note={doc['result'].get('note')!r}")
print(f"  单个 group 字段={sorted(doc['result']['groups'][0])}")

print()
print("lava-lakes 的 note 与字段：")
doc = json.loads((run / "lava-lakes.json").read_text(encoding="utf-8"))
print(f"  note={doc['result'].get('note')!r}")
print(f"  yThreshold={doc['result'].get('yThreshold')} minLakeSize={doc['result'].get('minLakeSize')}")
