"""
Register and serve the neoantigen flow deployment.

Run this after `prefect server start` to make the flow visible and
launchable from the Prefect dashboard.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from neoantigen_flow import neoantigen_flow

if __name__ == "__main__":
    neoantigen_flow.serve(
        name="neoantigen-prediction",
        tags=["neoantigen"],
    )
