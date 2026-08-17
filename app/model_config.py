"""Single source of truth for VendorEdge's model routing.

The extraction/classification path favors a current high-performance model for
speed and cost. The final commercial reasoning path favors the current frontier
Opus model because that output is the product's core value. Both are deployment
configurable; no business logic depends on a model-specific response style.
"""
import os

# Explicit per-stage overrides are preferred. VENDOREDGE_MODEL remains as a
# backwards-compatible single-model override for simple deployments/tests.
_single = os.environ.get("VENDOREDGE_MODEL")
CLASSIFIER_MODEL = os.environ.get("VENDOREDGE_CLASSIFIER_MODEL") or _single or "claude-sonnet-4-6"
REASONING_MODEL = os.environ.get("VENDOREDGE_REASONING_MODEL") or _single or "claude-opus-4-8"
MARKET_MODEL = os.environ.get("VENDOREDGE_MARKET_MODEL") or _single or "claude-sonnet-4-6"
