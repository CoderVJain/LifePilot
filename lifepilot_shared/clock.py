"""What day it is, in one place that a test can hold still.

Half of what LifePilot says depends on the date: "tomorrow", "next Thursday", which week the demo
covers, and the dates the model is told when it routes a request. Reading the system clock directly
in each of those made all of them untestable and made recorded model answers expire overnight.

`LIFEPILOT_TODAY=2026-10-01` pins it. Nothing else changes.
"""

import os
from datetime import date

TODAY_ENV = "LIFEPILOT_TODAY"


def today() -> date:
    """The day LifePilot thinks it is."""
    pinned = (os.environ.get(TODAY_ENV) or "").strip()
    if pinned:
        try:
            return date.fromisoformat(pinned)
        except ValueError:
            pass
    return date.today()
