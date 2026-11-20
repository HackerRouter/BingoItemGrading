"""从 server.jar 的 version.json 读数据包格式号，并用 pack.mcmeta 的 overlays 判定启用层。"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bingo_grading import paths  # noqa: E402

LABEL = sys.argv[1] if len(sys.argv) > 1 else "26.3"

JAR = paths.REF_RECIPE_ANALYSIS / "inputs" / LABEL / "server.jar"

# 上游服务器存档里的地形包原件；`data/packs/` 里的本地副本没有上游 `.server/`，
# 所以这个脚本作为「上游探测」仍读上游位置，只是不再写死仓库内的 ref/。
_found = sorted((paths.REF_COLLECTOR / ".server").glob(f"*/world/datapacks/*"))
MCMETA = next(
    (path / "pack.mcmeta" for path in _found if (path / "pack.mcmeta").is_file()),
    paths.REF_COLLECTOR / ".server" / "missing" / "pack.mcmeta",
)

lines: list[str] = []


def say(text: str = "") -> None:
    lines.append(text)


say(f"地形包 = {MCMETA.parent.name}")


if not JAR.exists():
    say(f"server.jar 不存在：{JAR}")
else:
    with zipfile.ZipFile(JAR) as jar:
        names = [n for n in jar.namelist() if n.endswith("version.json") and n.count("/") <= 2]
        say(f"version.json 候选：{names}")
        for name in names:
            try:
                doc = json.loads(jar.read(name).decode("utf-8-sig"))
            except Exception as exc:  # noqa: BLE001
                say(f"  {name} 读取失败：{exc}")
                continue
            say(f"  {name}: {json.dumps(doc, ensure_ascii=False)}")

meta = json.loads(MCMETA.read_text(encoding="utf-8-sig"))
say("")
say(f"pack.mcmeta 主包 min_format={meta['pack'].get('min_format')} max_format={meta['pack'].get('max_format')}")
say("overlays:")
for entry in meta.get("overlays", {}).get("entries", []):
    say(f"  {entry['directory']:<20}{entry.get('min_format')} ~ {entry.get('max_format')}")

out = ROOT / "build" / "pack-format.txt"
out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(f"written {out}")
