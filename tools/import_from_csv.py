#!/usr/bin/env python3
"""
Generate minqlx !link commands from a legacy CSV export.

Expected headers:
  - steamid (required)
  - discordid (required)
  - discord_name (optional)

Example:
  steamid,discordid,discord_name
  76561198000000000,123456789012345678,SomeUser
"""

import argparse
import csv
import sys


def parse_args():
    parser = argparse.ArgumentParser(description="Generate !link commands from CSV mappings.")
    parser.add_argument("csv_file", help="Path to CSV file")
    parser.add_argument(
        "--prefix",
        default="!",
        help="Command prefix to emit (default: !)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        with open(args.csv_file, "r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            required = {"steamid", "discordid"}
            missing = required.difference(set(reader.fieldnames or []))
            if missing:
                print("Missing CSV column(s): {}".format(", ".join(sorted(missing))), file=sys.stderr)
                return 1

            for row in reader:
                steam_id = (row.get("steamid") or "").strip()
                discord_id = (row.get("discordid") or "").strip()
                discord_name = (row.get("discord_name") or "").strip()

                if not steam_id or not discord_id:
                    continue
                if not steam_id.isdigit() or not discord_id.isdigit():
                    continue

                if discord_name:
                    print("{}link {} {} {}".format(args.prefix, steam_id, discord_id, discord_name))
                else:
                    print("{}link {} {}".format(args.prefix, steam_id, discord_id))
    except OSError as exc:
        print("Failed to read CSV file: {}".format(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

