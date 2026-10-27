"""Command-line entry point ``rtl2d`` (argparse). Subcommands: run, check."""

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rtl2d", description="RTL -> diagram pipeline")
    parser.add_subparsers(dest="command")
    parser.parse_args(argv)
    parser.print_help()
    return 0
