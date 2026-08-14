from app.pipeline.pilot_metrics import build_pilot_metrics

def test_small_sample_never_declares_readiness():
    r=build_pilot_metrics([{"would_use_again":True,"trust_level":"high","ease_of_use":"easy"}], [{"validation_verdict":"reasoning_held"}])
    assert r["readiness"]=="INSUFFICIENT_REAL_DATA" and r["would_use_again_rate"]==100

def test_promising_requires_real_outcomes_and_reuse():
    exp=[{"would_use_again":True,"trust_level":"high","ease_of_use":"easy"} for _ in range(5)]
    out=[{"validation_verdict":"reasoning_held"} for _ in range(4)]+[{"validation_verdict":"needs_revision"}]
    r=build_pilot_metrics(exp,out)
    assert r["readiness"]=="PROMISING" and r["reasoning_held_rate"]==80

def test_bad_outcomes_do_not_hide_behind_reuse():
    exp=[{"would_use_again":True,"trust_level":"high","ease_of_use":"easy"} for _ in range(5)]
    out=[{"validation_verdict":"needs_revision"} for _ in range(5)]
    assert build_pilot_metrics(exp,out)["readiness"]=="LEARN_BEFORE_SCALING"
