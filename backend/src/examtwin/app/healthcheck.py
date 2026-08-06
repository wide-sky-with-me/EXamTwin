from __future__ import annotations

import json
from typing import Any
from urllib.request import urlopen

from examtwin.contracts.system import API_CAPABILITIES, API_CONTRACT_VERSION

DEFAULT_HEALTH_URL = "http://127.0.0.1:8000/api/v1/health"


def health_payload_is_valid(payload: dict[str, Any]) -> bool:
    return (
        payload.get("status") == "ok"
        and payload.get("api_contract_version") == API_CONTRACT_VERSION
        and set(payload.get("capabilities", [])) == set(API_CAPABILITIES)
    )


def main() -> int:
    try:
        with urlopen(DEFAULT_HEALTH_URL, timeout=3) as response:  # noqa: S310 - fixed loopback URL
            payload = json.load(response)
        if not health_payload_is_valid(payload):
            raise ValueError("contract or infrastructure is degraded")
    except Exception as error:
        print(f"API healthcheck failed: {type(error).__name__}")
        return 1
    print(f"API healthy ({API_CONTRACT_VERSION})")
    return 0
