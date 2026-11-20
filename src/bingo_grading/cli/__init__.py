"""命令行入口。

所有路径默认从仓库根推出，不依赖当前工作目录；显式参数覆盖默认值。

实现按命令族拆在同名子模块里；本文件只定义 `main` 并做门面。
"""

from __future__ import annotations

from .. import config as config_module
from .common import graph_path, index_path, print_json, stats_path
from .parser import build_parser


def main(argv: list[str] | None = None) -> int:
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        return args.handler(args)
    except config_module.ConfigError as exc:
        # 配置缺失或格式不对：直接报出来并退出，不退化成默认目录。
        print_json({"error": str(exc)})
        return 1


__all__ = ["build_parser", "graph_path", "index_path", "main", "print_json", "stats_path"]
