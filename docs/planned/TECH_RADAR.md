# Tech radar

Status: skeleton. Rings (adopt, trial, assess, hold) are assigned in Phases 7 and 10 from this repo's own eval results and documented sources. Nothing below is a recommendation yet and nothing here is a claim of fact beyond "candidate to evaluate".

| Area | Candidates to evaluate | Ring | Evidence needed |
|------|------------------------|------|-----------------|
| Local model runners | Ollama, vLLM, LM Studio | unassessed | latency and accuracy on golden sets (Phase 7) |
| Local open-weight models | those installed (see docs/ENVIRONMENT.md) | unassessed | routing report (Phase 7) |
| Hosted model adapters | Azure OpenAI, Anthropic | unassessed | cost, latency, accuracy vs local; data-handling terms (verify, do not assume) |
| Vector store | pgvector, Qdrant | unassessed | isolation and retrieval evals (Phase 5) |
| Agent protocol | MCP | unassessed | security checks in Phase 9 |
| Observability | OpenTelemetry | unassessed | Phase 8 |
