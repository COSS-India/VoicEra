#!/usr/bin/env python3
"""Print telephony configuration catalog.

Usage::

    python3 apps/telephony/scripts/print_schemas.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_VOICERA_ROOT = Path(__file__).resolve().parents[3]
if str(_VOICERA_ROOT) not in sys.path:
    sys.path.insert(0, str(_VOICERA_ROOT))

from apps.telephony import configuration_telephony


def main() -> None:
    print(json.dumps(configuration_telephony(), indent=2))


if __name__ == "__main__":
    main()
