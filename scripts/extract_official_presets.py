import argparse
import sys
from pathlib import Path

import nonebot

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
nonebot.init(driver="nonebot.drivers.none:Driver")

from nonebot_plugin_manosaba_memes.sprite_editor.presets import (
    PRESET_PATH,
    extract_official_presets,
    write_catalog,
    write_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract stable full-body sprite presets from official .nani scripts."
    )
    parser.add_argument("script_root", type=Path)
    parser.add_argument("--output", type=Path, default=PRESET_PATH)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--asset-root", type=Path)
    args = parser.parse_args()

    catalog, report = extract_official_presets(
        args.script_root, asset_root=args.asset_root
    )
    write_catalog(catalog, args.output)
    if args.report:
        write_report(report, args.report)

    print(f"scanned {report.scanned_files} scripts")
    print(f"parsed {report.parsed_char_commands} @char commands")
    print(f"accepted {sum(report.character_counts.values())} unique presets")
    for character, count in report.character_counts.items():
        print(f"  {character}: {count}")
    if report.invalid:
        print(f"quarantined {len(report.invalid)} invalid appearances")


if __name__ == "__main__":
    main()
