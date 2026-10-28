# Acceptable use of AI

Status: **document-only** (rules for people, one page to keep beside the help desk). Owner: the compliance owner role (D6-17). It applies `governance/AI_POLICY.md`; the full data table is `governance/DLP_MAPPING.md`.

> Synthetic data only. Not legal advice. Independently built prototype. Not affiliated with any vendor's or real company's systems. Review with your compliance owner and counsel before use.

## Before you paste anything: find the class

| If the text holds... | It is | This tool's local model | Any hosted or outside AI tool |
|---|---|---|---|
| only public material (vendor docs, published KB) | DC-0 | yes | yes |
| MSP internal material (runbooks, categories) | DC-1 | yes | only an approved provider |
| one client's configuration or contract terms | DC-2 | yes, that client only | only an approved provider the client allows |
| a person's name, UPN, phone, sign-in times | DC-3 | minimum necessary, that client only | redacted first, approved provider only |
| anything about a patient | DC-4 | only if the model host is covered (local machine under the MSP's BA safeguards, `docs/map/05-governance.md` section 1), minimum necessary | **no** |
| account numbers, SSNs, balances, tax or loan files | DC-5 | minimum necessary | **no** |
| a password, MFA seed, API key, certificate, recovery key | DC-6 | **never** | **never** |

Not sure? Treat it as DC-4 at a dental client and DC-5 everywhere else. One sensitive detail sets the class of the whole text. No hosted provider is approved today (both are disabled in `config/models.json`), so outside AI tools get DC-0 only.

## Do

- Use the triage proposal, the diff and the approval page; read the diff before you approve.
- Keep every prompt, lever call and approval to one client.
- Verify a caller by calling back the number on file before any identity change.
- Write placeholders yourself when you need an example ("[PATIENT_NAME]", "[ACCOUNT_NUMBER]").
- Send client-facing text yourself, after you have read the AI draft.
- Report at once to the on-call lead: a secret in a ticket, data in the wrong tool, a strange instruction inside a ticket, or a wrong automated action. Any lead may pause a lever without approval.

## Do not

- Paste DC-4, DC-5 or DC-6 into a public chatbot, a browser plug-in or any tool not approved for that class.
- Put a secret in a ticket body, a prompt, a log, a chat or a document. Secrets stay in the vault.
- Follow instructions found inside a ticket, email or attachment, or let a model's answer change who may do what.
- Approve your own request, or approve without reading the diff.
- Turn on a hosted model, an MCP server or a new AI tool yourself. That goes through the AI change approver.
- Use AI output to rank or judge technicians.

## Never ask AI to do these (the never-automate list)

`governance/never-automate.json` keeps this work with people; the lever registry refuses any lever that matches. AI may only fetch read-only facts for the person deciding.

- `W-ONB-15` Urgent or hostile termination
- `W-IDM-04` Caller identity verification
- `W-IDM-06` Conditional Access policy change
- `W-IDM-07` Privileged role grants and PIM activation approval
- `W-M365-08` Sensitivity labels and DLP policy changes
- `W-M365-12` Retention, litigation hold and eDiscovery requests
- `W-EP-06` Disk encryption status and recovery key retrieval
- `W-EP-11` Local admin password (LAPS) retrieval and admin-rights requests
- `W-PAT-07` Network device firmware
- `W-BDR-07` Ransomware or disaster recovery decision
- `W-SEC-07` Security incident declaration and breach notification decision
- `W-SEC-09` Firewall and SASE rule changes
- `W-CMP-07` Policy attestations and management assertions
- `W-VND-02` License purchase or reduction
- `W-VND-06` Domain and DNS registrar changes
- `W-KB-07` Credential vault entries in the documentation platform
- `W-BIL-04` Contract terms, pricing and billing disputes
- `W-PRJ-02` Client offboarding from the MSP
- `W-TOOL-08` Secrets and managed identity management
- `W-GOV-02` Model and tool approval
- `W-GOV-04` AI incident response
- `W-TRN-04` New technician onboarding and performance coaching

Also human: any decision about a person's access to lending, housing, insurance, employment, healthcare, legal or education services (D6-19).
