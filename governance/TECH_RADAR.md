# Tech radar

Status: **built as a document** (rings assigned from this repo's own evals and tests or from files it cites; the checker `workflows/assurance/briefs.py` fails on a missing citation). Everything numeric is **fixture-based**. This page is the finished version of the skeleton `docs/planned/TECH_RADAR.md`, which stays in place because the Phase 0 test requires it.

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.

## How to read it

A ring says what this prototype should do next about a technology, given only what this repo can show. It is not a market view, not a vendor review and not advice on what any real organisation should buy.

**adopt**: this repo built it and a test or an eval report here backs the claim in the row. It is adopted for this prototype's design, at fixture scale.

**trial**: built or wired, with tests, but the evidence is thin or has a named gap; keep using it and close the gap before relying on it.

**assess**: worth looking at; this repo holds no eval of it, so nothing is claimed beyond "candidate".

**hold**: do not enable until the named approval and evidence exist.


Every row names its evidence in the fourth column. An `adopt` row must name an eval report or a test of this repo. The last column says what the evidence does not show. Hand edits are checked by `uv run --frozen python -m workflows.assurance briefs check`.

## Radar

| Area | Candidate | Ring | Evidence | Not shown |
|---|---|---|---|---|
| Model routing | Rules-first cascade (rules, then small tier, then strong tier) | adopt | `evals/routing/report.md`, `evals/gates.json`, `tests/py/evals/test_b78_routing.py::test_b78_2_cascade_accepts_only_at_or_above_threshold_and_strong_is_final` | All three tiers are mocks written by the author of the 60 gold tickets; thresholds were fitted on the same tickets (the report calls the in-sample figure the flattering one); no latency, no real model, cost in relative units only |
| Agent safety | Permissions on the lever, enforced by the runner, not the model | adopt | `tests/py/mcp/test_b87_mcp.py::test_b87_2_fooled_client_unregistered_lever_is_refused_and_audited`, `tests/py/levers/test_b02_runner_gates.py::test_b02_1_global_pause_wins_over_a_client_pause`, `docs/DECISIONS.md` | Tested against mock adapters and a mock identity provider; no real tenant and no outside red team |
| Audit | Hash-chained, append-only lever audit log | adopt | `tests/py/audit/test_b17_audit_v2.py::test_b17_2_p1_2_rehashed_edit_breaks_the_next_record`, `docs/DECISIONS.md` | Proves edits inside the file are detectable; the immutable evidence store in the decision record is a target, not built (`docs/map/06-decisions.md`) |
| Job store | SQLite queue with leases, retries and dead letters | adopt | `tests/py/storage/test_b82_sqlite.py::test_b82_1_failures_retry_with_backoff_then_dead_letter`, `tests/py/load/test_b84_load.py::test_b84_3_worker_crash_after_the_effect_never_double_applies_on_retry`, `evals/load/bench_report.md` | One machine, one run, synthetic harness; the benchmark file itself says it is not a capacity claim |
| Release gate | Eval gate with fixed thresholds | adopt | `tools/eval_gate.py`, `evals/gates.json`, `tests/py/tools/test_b84_eval_gate.py::test_b84_1_committed_gates_pass_on_the_committed_evals` | Gates are regression alarms for these fixtures, not quality targets; the CI step is a proposal that has never run on a runner (`docs/changes/B-84.ci-eval-gate.yml`) |
| Injection defence | Rule-based injection detector, used as a tripwire only | trial | `evals/gates.json`, `tests/py/evals/test_b79_injection_v2.py`, `docs/DECISIONS.md` | The corpus is hand-written by the author of the rules; known misses are look-alike letters, paraphrase and other languages; the permission check is the control, not the detector |
| Logging | Structured log lines through the standard library with a field sanitizer | trial | `tests/py/obs/test_b83_obs.py::test_b83_1_hostile_text_in_any_channel_never_reaches_the_line`, `tests/py/obs/test_b83_obs.py::test_b83_1_residual_a_one_token_lowercase_identifier_is_accepted_in_an_identifier_field` | A residual leak path is recorded in the second test; no log store, no alerting, no volume figure |
| Observability | OpenTelemetry | assess | `docs/map/03-architecture-target.md`, `pyproject.toml` | No OpenTelemetry code and no dependency exist in this repo (the only runtime dependency is pydantic); no exporter, collector or overhead measurement |
| Agent protocol | MCP (Model Context Protocol) server over approved levers | trial | `mcp/README.md`, `tests/py/mcp/test_b87_mcp.py::test_b87_1_no_call_ever_reaches_the_runner_in_execute_mode_or_with_an_approval` | Written from memory of the protocol and never run against a real MCP client or the specification (UNVERIFIED in `mcp/README.md`); standard library only, no MCP library |
| Local model runners | Ollama | trial | `core/gateway/ollama.py`, `tests/phase1/test_gateway.py::test_routing_to_ollama_sends_the_configured_model`, `config/models.json` | The adapter is tested without a model; the routing report row for a local model reads skipped, so there is no accuracy or latency number (`evals/routing/report.md`) |
| Local model runners | vLLM | assess | `core/gateway/loopback.py`, `docs/ENVIRONMENT.md` | The loopback guard names vLLM as the same OpenAI-compatible shape; it was never run here and the environment audit does not list it as installed |
| Local model runners | LM Studio | assess | `docs/ENVIRONMENT.md` | Listed as installed on the build machine in the 2026-10-09 audit; no adapter, no test, no eval |
| Local open-weight models | Models named in the gateway config | assess | `config/models.json`, `evals/routing/report.md` | The model names are examples and nothing is downloaded by this repo; no local model has been scored on the gold tickets |
| Hosted model adapters | Azure OpenAI | hold | `core/gateway/hosted.py`, `tests/phase1/test_gateway.py::test_shipped_config_keeps_hosted_providers_off`, `map/controls.json`, `docs/UNVERIFIED.md` | The adapter is a disabled stub with no client; the approval gate and vendor register (C-28, C-43) are planned; data-handling terms are UNVERIFIED (U-08); cost, latency and accuracy against local were never measured |
| Hosted model adapters | Anthropic API | hold | `core/gateway/hosted.py`, `tests/phase1/test_gateway.py::test_shipped_config_keeps_hosted_providers_off`, `map/controls.json`, `docs/UNVERIFIED.md` | Same as the Azure OpenAI row: stub only, approval gate planned, terms UNVERIFIED (U-08), nothing measured |
| Vector store | pgvector | assess | `docs/BLUEPRINT.md`, `docs/DECISIONS.md` | No retrieval or embedding code exists; reply drafts are quotations from the client's own knowledge base, not a vector search; the isolation and retrieval evals this ring needs are planned |
| Vector store | Qdrant | assess | `docs/BLUEPRINT.md`, `docs/DECISIONS.md` | Same as the pgvector row: a candidate on paper, no code, no eval |

## What would move a ring

- A local model scored on the gold tickets by `evals/routing/run.py` would let the local runner rows move on a number instead of an adapter test (`evals/routing/report.md`).
- Written retention and training terms plus an approval record would be the first step off `hold` for a hosted adapter; this repo records them as required but does not hold them (`map/controls.json`).
- A retrieval isolation eval would be the first evidence for a vector store row; the plan for it is in the roadmap (`docs/ROADMAP.md`).
- A recorded run of the proposed CI gate on a runner would remove the main caveat on the release gate row (`docs/changes/B-84.ci-eval-gate.yml`).

## Not shown

- Nothing here compares products on price, support, licence or market share; the repo holds no source for any of those (`docs/UNVERIFIED.md`).
- Every accuracy figure comes from author-written gold labels and mock tiers; none is a measurement on real tickets (`evals/routing/report.md`).
- The rings say nothing about which technology a real organisation already runs; those facts are open questions (`docs/map/05-governance.md`).
- No technology is rated against a real user's acceptance, because no technician has used any of it (`governance/ROI_TRACKER.md`).

## Unverified

- UNVERIFIED: the MCP protocol subset was written from memory and never checked against the specification or a real client (`mcp/README.md`).
- UNVERIFIED: hosted-provider data terms (BAA, retention, abuse monitoring) are listed as unsettled in the claims register (`docs/UNVERIFIED.md`).
- UNVERIFIED: the installed tools and models on the build machine are as of the 2026-10-09 audit and were not re-run for this page (`docs/ENVIRONMENT.md`).
