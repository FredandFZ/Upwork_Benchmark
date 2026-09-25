from __future__ import annotations

import argparse
import json

from runtime import build, check, feature_catalog, get_feature, simulate


def main():
    parser = argparse.ArgumentParser(description="Inspect and exercise the current project behavior.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list")
    show = sub.add_parser("show")
    show.add_argument("slug")
    run = sub.add_parser("simulate")
    run.add_argument("slug")
    sub.add_parser("build")
    sub.add_parser("check")
    args = parser.parse_args()
    if args.command in {None, "list"}:
        value = feature_catalog()
    elif args.command == "show":
        value = get_feature(args.slug)
    elif args.command == "simulate":
        value = simulate(args.slug)
    elif args.command == "build":
        value = {"output": str(build())}
    else:
        value = check()
    print(json.dumps(value, ensure_ascii=False, indent=2))
    if args.command == "simulate" and value.get("status") == "FAILED":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
