import argparse
import sys
import tomllib
from pathlib import Path

from .translator import poetry_to_uv, uv_to_poetry, dump_toml


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="toml-translator",
        description="Translate pyproject.toml between Poetry and uv formats",
    )

    parser.add_argument(
        "mode",
        choices=("poetry2uv", "uv2poetry"),
        help="Translation direction",
    )

    parser.add_argument(
        "path",
        type=Path,
        help="Path to pyproject.toml",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.path.exists():
        parser.error(f"File not found: {args.path}")

    if not args.path.is_file():
        parser.error(f"Not a file: {args.path}")

    with args.path.open("rb") as f:
        data = tomllib.load(f)

    if args.mode == "poetry2uv":
        result = poetry_to_uv(data)
    else:
        result = uv_to_poetry(data)

    sys.stdout.write(dump_toml(result))


if __name__ == "__main__":  # pragma: no cover
    main()
