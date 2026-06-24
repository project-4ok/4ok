from __future__ import annotations

from fourok.cli_parts.core_commands import dispatch_core
from fourok.cli_parts.parser import build_parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "onboarding":
        args.command = "onboard"
    if args.command == "admin":
        args.command = args.admin_command
    if dispatch_core(args):
        return


if __name__ == "__main__":
    main()
