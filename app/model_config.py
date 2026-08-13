"""
Single source of truth for which Claude model version this deployment
uses. Previously hardcoded as the literal string "claude-sonnet-5" in
three separate files (classifier.py, reasoner.py, market_verification.py)
-- a real duplication risk (an upgrade could easily miss one of the
three) and, more immediately, a blocker for accurately logging which
model version was actually in use when a fallback fired. Change the
model version here, once, and every call site and every logged event
stays correct automatically.
"""

CLASSIFIER_MODEL = "claude-sonnet-5"
