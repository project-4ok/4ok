from __future__ import annotations

import json
import sys

from gcb.runtime.connector_contracts import connector_contract_report


def main() -> int:
    report = connector_contract_report()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
