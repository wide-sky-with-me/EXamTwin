from __future__ import annotations

import json
from typing import Any
from urllib.request import urlopen

from examtwin.contracts.system import API_CAPABILITIES, API_CONTRACT_VERSION, API_PREFIX
from examtwin.platform.config import get_settings


def health_payload_is_valid(payload: dict[str, Any]) -> bool:
    return (
        payload.get("status") == "ok"
        and payload.get("api_contract_version") == API_CONTRACT_VERSION
        and set(payload.get("capabilities", [])) == set(API_CAPABILITIES)
    )


def main() -> int:
    settings = get_settings()
    health_url = f"http://127.0.0.1:{settings.api_port}{API_PREFIX}/health"
    try:
        with urlopen(health_url, timeout=3) as response:  # noqa: S310 - fixed loopback URL
            payload = json.load(response)
        if not health_payload_is_valid(payload):
            raise ValueError("contract or infrastructure is degraded")
    except Exception as error:
        print(f"API healthcheck failed: {type(error).__name__}")
        return 1
    print(f"API healthy ({API_CONTRACT_VERSION})")
    return 0
