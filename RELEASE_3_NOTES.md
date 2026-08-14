# VendorEdge Release 3 Notes

This release is part of the internal CTO release train.

Key hardening:
- bounded classifier decomposition after genuine 2K/4K/8K truncation;
- explicit retry telemetry;
- signed-session identity enforcement across protected pilot endpoints;
- validation endpoint authentication and rate limiting;
- frontend authentication compatibility for protected file/signal endpoints.

Do not deploy until the complete regression suite passes in the target runtime and the real browser checklist is completed.
