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
        "--host",
        default="192.168.1.100",
        help="SSH host/IP for NAS (default: %(default)s)",
    )
    parser.add_argument(
        "--user",
        default="Wulfenson",
        help="SSH user for NAS (default: %(default)s)",
    )
    parser.add_argument(
        "--identity-file",
        default="/home/greg/.ssh/id_ed25519_nas_40k",
        help="Private key path used by SSH (default: %(default)s)",
    )
    parser.add_argument(
        "--remote-path",
        default="/volume1/docker/40k/models/",
        help="Destination path on NAS (default: %(default)s)",
    )
    parser.add_argument(
        "--dst",
        default=None,
        help=(
            "Full rsync destination (overrides --host/--remote-path), "
            "example: user@192.168.1.100:/volume1/docker/40k/models/"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied without transferring files",
    )
    parser.add_argument(
        "--verbose-ssh",
        action="store_true",
        help="Enable SSH verbose logs (-vv) for troubleshooting",
    )
    parser.add_argument(
        "--rsync-path",
        default="/usr/bin/rsync",
        help="Remote rsync binary path on NAS (default: %(default)s)",
    )
    args = parser.parse_args()

    src = Path(args.src)
    if not src.exists() or not src.is_dir():
        print(f"Source directory not found: {src}", file=sys.stderr)
        return 1

    destination = args.dst
    if destination is None:
        destination = f"{args.user}@{args.host}:{args.remote_path}"

    identity_file = Path(args.identity_file).expanduser()
    if args.dst is None and not identity_file.exists():
        print(f"Identity file not found: {identity_file}", file=sys.stderr)
        return 1

    ssh_cmd = [
        "ssh",
        "-i",
        str(identity_file),
        "-o",
        "IdentitiesOnly=yes",
        "-T",
    ]
    if args.verbose_ssh:
        ssh_cmd.append("-vv")

    cmd = [
        "rsync",
        "-av",
        "--progress",
        "-e",
        " ".join(ssh_cmd),
        "--rsync-path",
        args.rsync_path,
        "--prune-empty-dirs",
        "--include=*/",
        "--include=model_*.zip",
        "--exclude=*",
        f"{src}/",
        destination,
    ]

    if args.dry_run:
        cmd.insert(3, "--dry-run")

    print("Running:", " ".join(cmd))
    try:
        result = subprocess.run(cmd)
    except FileNotFoundError:
        print("Error: rsync is not installed or not in PATH.", file=sys.stderr)
        return 127

    if result.returncode == 255:
        print(
            "\nSSH authentication failed.\n"
            "Verify your SSH alias/host and key setup (try: ssh nas40k).",
            file=sys.stderr,
        )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
    