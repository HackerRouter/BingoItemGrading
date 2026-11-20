"""从 section-block-histogram 读粘土、干草块等方块的每区块数量。"""

from __future__ import annotations

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
run = sorted((root / "ref" / "WorldGenStatsCollector" / "stats").iterdir())[-1]
data = json.loads((run / "section-block-histogram.json").read_text(encoding="utf-8-sig"))

print("run:", run.name)
print("range:", json.dumps(data.get("range"), ensure_ascii=False)[:200])

result = data.get("result") or {}
print("\nresult keys:", sorted(result)[:20])

for dimension, payload in result.items():
    print(f"\n===== {dimension} =====")
    if isinstance(payload, dict):
        print("  keys:", sorted(payload)[:15])
