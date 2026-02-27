#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync AI model zip files to NAS using rsync."
    )
    parser.add_argument(
        "--src",
        default="/home/greg/40k/ai/models/",
        help="Source models directory (default: %(default)s)",
    )
    parser.add_argument(
        "--dst",
        default="Wulfenson@192.168.1.100:/volume1/docker/40k/models/",
        help="Destination rsync target (default: %(default)s)",
    )
    args = parser.parse_args()

    src = Path(args.src)
    if not src.exists() or not src.is_dir():
        print(f"Source directory not found: {src}", file=sys.stderr)
        return 1

    cmd = [
        "rsync",
        "-av",
        "--progress",
        "--prune-empty-dirs",
        "--include=*/",
        "--include=model_*.zip",
        "--exclude=*",
        f"{src}/",
        args.dst,
    ]

    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
    