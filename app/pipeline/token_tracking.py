"""
Minimal token-usage tracking for real-cost measurement. Deliberately a
simple module-level accumulator, not a database table or a new service --
this exists purely so the real-LLM validation harness can report actual
tokens and actual cost per case, which nothing in the codebase captured
before. Additive only: does not change the signature or behavior of
classify() or generate_commercial_position() in any way.
"""

_usage_log: list[dict] = []


def record_usage(call_type: str, model: str, input_tokens: int, output_tokens: int):
    _usage_log.append({
        "call_type": call_type, "model": model,
        "input_tokens": input_tokens, "output_tokens": output_tokens,
    })


def get_usage() -> list[dict]:
    return list(_usage_log)


def reset_usage():
    _usage_log.clear()
