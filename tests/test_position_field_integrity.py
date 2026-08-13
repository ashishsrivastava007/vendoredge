"""
Permanent regression guard for a real, live bug: `market_verification_scope`
was accidentally dropped from models.py during a later edit, while
decisions.py still tried to set it directly on every completed position --
a genuine production crash (500-style failure on every price_increase
case that triggered market verification).

The root cause this test targets: earlier tests for this field checked the
ATTACHMENT LOGIC using a mock/fake object standing in for a position, never
against the real Pydantic schema -- which is exactly why a schema
regression could slip through undetected. Pydantic raises immediately if
you try to set a field that doesn't exist on the model, so testing against
a REAL CommercialPosition instance is what actually catches this class of
bug, not a logic-level check alone.

Every field decisions.py sets directly on a position (`position.field = x`,
not something the model itself returns) is tested here, not just the one
that broke -- the same discipline as the caps-consistency test suite,
applied to a different kind of drift.
"""
from app.models import CommercialPosition, Confidence, ConfidenceFactor, FinancialImpact

_CONF = Confidence(
    level="medium",
    factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")],
    derivation_note="n",
)


def _real_position() -> CommercialPosition:
    return CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        reasoning="...", confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )


def test_market_verification_scope_exists_on_the_real_schema():
    """The exact field and exact assignment that crashed live, reproduced
    directly against a real position, not a mock."""
    position = _real_position()
    position.market_verification_scope = "Southeast Asia"
    assert position.market_verification_scope == "Southeast Asia"


def test_confidence_calibration_note_exists_on_the_real_schema():
    position = _real_position()
    position.confidence_calibration_note = "Across 5 recorded outcomes, reasoning held in 4 (80%) of them."
    assert position.confidence_calibration_note is not None


def test_financial_impact_exists_and_accepts_a_real_object():
    position = _real_position()
    position.financial_impact = FinancialImpact(
        annual_spend_usd=1000000, requested_change_percent=10,
        potential_annual_impact_usd=100000, note="...",
    )
    assert position.financial_impact.annual_spend_usd == 1000000


def test_informed_by_case_count_exists_on_the_real_schema():
    position = _real_position()
    position.informed_by_case_count = 3
    assert position.informed_by_case_count == 3
