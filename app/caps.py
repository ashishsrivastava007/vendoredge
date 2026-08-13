"""
The single source of truth for every size limit in a CommercialPosition
response. Real, repeated bugs tonight were caused by the same number being
typed in five different places (the Pydantic schema, the prompt's Hard
Rule text, the prompt's JSON schema example) and drifting out of sync when
only some of them got updated. Every one of those places now imports its
number from here -- nowhere else defines a cap number directly.

If a limit ever needs to change, change it here, once. The automated test
in tests/test_caps_consistency.py fails loudly if any other file drifts
out of sync with these values, catching this exact class of bug
permanently, not just today's instance of it.
"""

MAX_COMMERCIAL_INSIGHTS = 3
MIN_COMMERCIAL_INSIGHTS = 1

MAX_COST_DRIVERS = 5

MIN_KEY_FIGURES = 2
MAX_KEY_FIGURES = 5

MAX_SUPPLIERS = 4

MAX_NEGOTIATION_DIMENSIONS = 6

MIN_TALK_TRACK_MOVES = 2
MAX_TALK_TRACK_MOVES = 3

MAX_FINANCIAL_SCENARIOS = 4

MIN_ASSUMPTIONS = 1
MAX_ASSUMPTIONS = 5

MAX_METHODOLOGY_CHARS = 300
MAX_HYPOTHESIS_CHARS = 350
