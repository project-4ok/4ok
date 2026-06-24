from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from http.client import RemoteDisconnected
from urllib.error import URLError
from urllib.request import urlopen

from gcb.governance.policy import CerbosRevealPolicy, PrincipalContext

POSTGRES_URL = "postgresql+psycopg://gcb:gcb_dev_password@localhost:5432/gcb"
CERBOS_URL = "http://localhost:3592"


def main() -> int:
    try:
        run(["docker", "compose", "up", "-d", "postgres", "cerbos"])
    except FileNotFoundError:
        print("docker is not installed", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as error:
        print(error.stderr or error.stdout, file=sys.stderr)
        return error.returncode

    if not wait_for_cerbos():
        print("cerbos did not become ready at http://localhost:3592", file=sys.stderr)
        return 1

    cerbos_policy = CerbosRevealPolicy(endpoint=CERBOS_URL)
    principal = PrincipalContext.local_default()
    allowed = cerbos_policy.check_reveal(
        token_type="iban", purpose="payment_processing", principal=principal
    )
    denied = cerbos_policy.check_reveal(
        token_type="iban", purpose="customer_support", principal=principal
    )
    if not allowed.allowed or denied.allowed:
        print(
            json.dumps(
                {
                    "allowed": allowed.__dict__,
                    "denied": denied.__dict__,
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1

    env = {**os.environ, "GCB_TEST_DATABASE_URL": POSTGRES_URL}
    run(["uv", "run", "pytest", "tests/test_postgres_integration.py"], env=env)
    print("runtime smoke passed")
    return 0


def wait_for_cerbos() -> bool:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{CERBOS_URL}/_cerbos/health", timeout=2) as response:
                if response.status == 200:
                    return True
        except (RemoteDisconnected, TimeoutError, URLError):
            pass
        time.sleep(1)
    return False


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, check=True, env=env, text=True, capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())
