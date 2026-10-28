# Security policy

> Independently built prototype. All tenants, people and tickets are synthetic.

## Data rules (apply to every file, issue, pull request, log and screenshot)
- **Synthetic data only.** This repo contains invented tenants (for example "Contoso Dental"), invented tickets and invented users. **No client data, ever**, and no real company data, names, tickets or documents. If you find something that looks real, treat it as a security report (below).
- **Secrets never go in code, docs, logs, commits, issues or pull request text.** Configuration shape lives in `.env.example` with placeholder values only; real values stay out of the repo. A pre-commit secret scan (`scripts/hooks/pre-commit`, enabled with `pwsh -File scripts/install-hooks.ps1`) and the tests check for secret-looking content. Both are heuristic, not a guarantee.
- If a real secret is ever committed: treat it as compromised, rotate it at the source first, then tell the owner. Removing it from git history does not make it safe again.

## Scope and honesty
This is a prototype with no production deployment and no real-world results. Its controls (lever permissions, approvals, audit chain, injection tripwire, secret scan) are tested on synthetic fixtures; their known limits are listed in `docs/THREAT_MODEL.md`. Nothing here has had a human or third-party security review.

## Reporting a vulnerability or a data leak
Please do not open a public issue for a security problem. Use GitHub's private vulnerability reporting on this repository (Security tab, "Report a vulnerability") if it is enabled, otherwise contact the owner, @JVonBorstel, through GitHub. Include what you found, where, and how to reproduce it, without pasting any real secret or real data. This is a one-person project: there is no SLA, but reports are read.

## Supported versions
Only the `main` branch.
