# VendorEdge Benchmark Harness

**Honest note**: this cannot be run without a real Anthropic API key and a real running instance of VendorEdge. It was built tonight but never executed against a live system — that's the one thing only you can do next.

## Setup (one-time)

```bash
pip install requests --break-system-packages
```

## Running it

Against your local Docker setup:
```bash
export ANTHROPIC_API_KEY=your-real-key
export VENDOREDGE_BASE_URL=http://localhost:8000
python3 benchmark/run_benchmark.py
```

Against your deployed Render instance:
```bash
export ANTHROPIC_API_KEY=your-real-key
export VENDOREDGE_BASE_URL=https://vendoredge.onrender.com
python3 benchmark/run_benchmark.py
```

## What it checks

Structural correctness only — did a guaranteed field show up when it should, stay correctly absent when it shouldn't. It does **not** judge whether the reasoning is good; that's still your call, the same one you've made reading every real response tonight.

## When to run it

Before any future prompt change to `reasoner.py` — this is what actually catches a new Hard Rule silently breaking an older one, the real risk as the schema keeps growing.

## Growing this suite

`cases.py` currently has 4 cases, covering both content types and a deliberately underspecified case. As real pilot questions come in, add the good or revealing ones here — that's better test data than more synthetic examples.
