from __future__ import annotations

from gcb.cli_parts.core_commands import dispatch_core
from gcb.cli_parts.honcho_commands import dispatch_honcho
from gcb.cli_parts.parser import build_parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if dispatch_core(args):
        return
    if dispatch_honcho(args):
        return


if __name__ == "__main__":
    main()
