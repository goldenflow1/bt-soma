"""Development harness for the SOMA miner.

The harness decides whether a candidate satisfies its spec. It never trusts a
candidate's own report: it runs checks itself, records receipts, and refuses
missing artifacts.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
