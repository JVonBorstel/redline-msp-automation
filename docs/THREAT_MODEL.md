# Threat model

Status: skeleton. Sections 1 and 2 are the plan for the product, completed in Phases 1 and 7; section 3 lists the build-time controls this public repository keeps. Nothing here claims a control is in place unless a test proves it.

## 1. Assets and trust boundaries (planned)
Assets: client data (per-client isolation), credentials and keys, audit log integrity, approval decisions, model prompts and outputs.
Untrusted: ticket text, emails, documents, tool and web output, model output. Trusted: lever code, schemas, policy config, the audit verifier.
Boundary rule: untrusted content may inform a suggestion; it can never change permissions, scope, or which levers exist.

## 2. Product threats and planned controls
| Threat | Planned control | Proof (phase) |
|--------|-----------------|---------------|
| Prompt injection in tickets, emails, docs, tool output | core/guard detectors; data never alters tool-selection rules; injection corpus with pass/fail report | 1, 7 |
| Model asks for an unregistered or out-of-scope lever | registry denies and logs | 1 |
| Cross-client data access (lever, retrieval, cache, error text) | scope enforced in code at tool and retrieval layers; leakage evals | 1, 5 |
| Tampered audit log | hash chain plus verifier CLI; external head pinning | 1 |
| Unreviewed state change | dry-run diff plus approval record for every write lever | 1, 3 |
| Secret leakage in logs, prompts, fixtures | redaction, secret scan, DLP mapping | 0, 1, 10 |
| Provider lock-in or data egress to hosted models | local default; hosted adapters off; config-only switching | 1 |
| Duplicate or replayed writes | idempotency keys, retry tests | 7 |
| Over-privileged MCP exposure | read-only default, token audience validation, no token passthrough, vetted servers | 9 |

## 3. Build-time controls
Threat: a change reaches the main line without review, or a secret is committed.

| Control | How | Test |
|---------|-----|------|
| Review before merge | pull requests only; `.github/CODEOWNERS` makes the owner the required reviewer for `scripts/`, `.github/`, `config/`, `governance/`, `core/levers/` and the audit and identity code | convention; branch protection is a repository setting |
| CI on clean runners | `.github/workflows/ci.yml`: lint, types and every suite, with a read-only token and no secrets | the workflow itself |
| Commit-time secret scan | `scripts/hooks/pre-commit`: case-insensitive, UTF-16 aware, many token shapes, filename rules | `tests/py` secret-scan checks |

### Known limits (not hidden)
1. **The commit secret scan is a heuristic** and is off until `scripts/install-hooks.ps1` runs. Its filter exempts values that look like placeholders or environment lookups. Base64-hidden or split tokens are not detected.
2. **The audit log is tamper-evident, not tamper-proof.** The hash chain, sequence numbers and head pin catch edits and truncation by accident or by a careless actor. A person who can rewrite both the log and its `.head` file can forge it. Pin the head hash somewhere the writer cannot write.
3. **Humans can override.** `--no-verify` and editing CI are intentional human powers.
4. **No third-party review.** Nothing in this repository has had an independent human or third-party security review.
