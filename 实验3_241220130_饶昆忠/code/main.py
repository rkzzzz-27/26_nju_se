"""Command line entry point for the local campus market prototype."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

from campus_market.errors import MarketError
from campus_market.http_api import serve
from campus_market.service import MarketService


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="校园二手交易系统实验三后端")
    result.add_argument(
        "--db", default=os.environ.get("MARKET_DB", "data/market.db"),
        help="SQLite 数据库文件",
    )
    result.add_argument(
        "--school-domain",
        default=os.environ.get("MARKET_SCHOOL_DOMAIN", "example.edu.cn"),
        help="允许注册的学校邮箱域名",
    )
    commands = result.add_subparsers(dest="command", required=True)
    server = commands.add_parser("serve", help="启动本机 JSON API")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8765)
    admin = commands.add_parser("bootstrap-admin", help="线下开通管理员")
    admin.add_argument("--email", required=True)
    admin.add_argument("--password", help="省略时从终端安全输入")
    jobs = commands.add_parser("run-jobs", help="执行一次提醒与到期任务")
    jobs.add_argument("--now", help="仅测试使用的当前 UTC 时间")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    service = MarketService(args.db, args.school_domain)
    try:
        if args.command == "serve":
            if args.host not in ("127.0.0.1", "::1", "localhost"):
                raise MarketError(
                    "local_only",
                    "实验原型仅允许监听本机地址；正式部署请通过 HTTPS 反向代理接入",
                )
            serve(service, args.host, args.port)
            return 0
        if args.command == "bootstrap-admin":
            password = args.password or getpass.getpass("管理员密码：")
            result = service.bootstrap_admin(args.email, password)
        elif args.command == "run-jobs":
            result = service.run_due_jobs(args.now)
        else:
            raise AssertionError("unreachable")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except MarketError as error:
        print(json.dumps(error.as_dict(), ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
