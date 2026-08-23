from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'app' / 'static' / 'index.html').read_text(encoding='utf-8')
ROUTES = (ROOT / 'app' / 'routes' / 'decisions.py').read_text(encoding='utf-8')


def test_supporting_intelligence_is_collapsible_and_internal_release_labels_are_not_exposed():
    assert 've-supporting-intelligence' in HTML
    for title in ('Numbers & commercial evidence', 'Negotiation strategy', 'Risks & decision safeguards', 'Execution', 'History & learning', 'Evidence trail & trust checks'):
        assert title in HTML
    # Internal R19-R25 architecture names belong in engineering artifacts, not the buyer decision flow.
    assert '>R19<' not in HTML
    assert '>R20<' not in HTML
    assert '>R21<' not in HTML
    assert '>R22<' not in HTML
    assert '>R23<' not in HTML
    assert '>R24<' not in HTML
    assert '>R25<' not in HTML


def test_premium_hero_is_decision_first_not_generic_chat():
    assert 'Bring the mess.' in HTML
    assert 'Leave with a decision.' in HTML
    assert 'Evidence-grounded' in HTML
    assert 'Deterministic economics' in HTML
    assert 'Decision traceable' in HTML


def test_invite_redemption_never_returns_workspace_not_found_or_org_probe_detail():
    # Unauthenticated redemption must expose only a generic invalid-invite outcome;
    # callers must not be able to distinguish an existing workspace from a made-up one
    # through application error text.
    marker = 'def accept_invite(request: Request, body: AcceptInviteRequest):'
    start = ROUTES.index(marker)
    body = ROUTES[start:start + 2500]
    assert 'Workspace not found' not in body
    assert 'This invitation is invalid, expired, or already used.' in body


def test_invite_redemption_is_rate_limited_before_database_lookup():
    marker = 'def accept_invite(request: Request, body: AcceptInviteRequest):'
    start = ROUTES.index(marker)
    body = ROUTES[start:start + 2500]
    assert '_check_invite_accept_rate_limit(client_ip)' in body
    assert body.index('_check_invite_accept_rate_limit(client_ip)') < body.index('get_org_scoped_connection(org_id)')
