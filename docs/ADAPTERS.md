# Adapters: what the real ones need

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.

Status: **document-only plus closed stubs** (B-91). No real vendor API was called while writing this page, no vendor page was opened for it, and no network was used. Everything below that is not tied to a repo source is written from memory and is **UNVERIFIED**; each row says what would verify it. Nothing here is a claim about the MSP's products (see `docs/UNVERIFIED.md` U-03).

## In plain words

An adapter is the seam between the program and an outside system. Today every system has a **mock** (fixtures) and a **real stub** that refuses every call with `real adapter not configured`. A real implementation replaces the stub in `adapters/real.py` (`REAL_STUBS`) only after it passes the shared contract suite `tests/py/contract/test_b91_adapters.py`; that suite runs on every registered implementation, so a new one gets the same checks the mocks get (B91-1). The rules every adapter must pass:

1. **One client.** Built for one client from that client's binding; another client's binding is refused at construction (TEN-04).
2. **No existence oracle.** Another client's object answers with the same result as one that does not exist.
3. **Fail closed.** Unconfigured or real-but-not-wired means `ok=False`, reason `real adapter not configured`, no data.
4. **No secret anywhere.** A binding holds a secret NAME (`client-<id>-<purpose>`); a value is refused. Names and values never reach a repr, a result, an error or a log.
5. **Deterministic.** Same call, same result; errors carry no address, path, traceback or timestamp; a crash is `<Class> crashed: <ExceptionType>` and never the message.

## Systems

| System | Interface (`adapters/`) | Mock | Real stub | Real API (UNVERIFIED unless noted) |
|---|---|---|---|---|
| PSA | `psa/base.py` | `PsaMock` | `RealPsa` | Autotask PSA REST API (D6-01). Entity field names were read on 2026-10-21 by B-18 (`fixtures/psa/SOURCES.md`); nothing else on this row was. |
| RMM | `rmm/base.py` | `RmmMock` | `RealRmm` | Datto RMM API v2 (sites, devices, audit, alerts, jobs, components). Shapes from memory (`fixtures/rmm/SOURCES.md`). |
| Intune | `intune/base.py` | `IntuneMock` | `RealIntune` | Microsoft Graph v1.0 `managedDevice` (`GET /deviceManagement/managedDevices`). |
| Microsoft 365 identity | `graph/base.py` | `GraphMock` | `RealGraph` | Microsoft Graph v1.0 users and authentication methods. |
| Backup | `backup/base.py` | `BackupMock` | `RealBackup` | Not chosen. Two job types (image appliance, Microsoft 365 SaaS); every field is a neutral stand-in (`fixtures/backup/SOURCES.md`). |
| Security alerts | `alerts/base.py` | `AlertsMock` | `RealAlerts` | Not chosen. Alert sources are types, not products (D6-04). |
| Documentation / KB | none yet | none | none | Out of scope for B-91 (no interface exists). |

Selection: builders exist for PSA, Graph, Intune and RMM (`build_adapter`, `build_graph_adapter`, `build_intune_adapter`, `build_rmm_adapter`); the suite proves each fails closed on a non-mock binding (B91-3). Backup and alerts have no builder yet, so their selection path is the stub class itself.

## Least privilege and throttling, per system

All scope names are UNVERIFIED (from memory) unless a source is given. Authentication details are the real adapter's job and are deliberately absent from the stubs.

| System | Least-privilege access to ask for | Throttling | Verify by |
|---|---|---|---|
| PSA (Autotask) | A dedicated API-only user with a security level limited to read on Companies, Contacts, Tickets, TicketNotes, Resources; no write until a PSA write lever is approved. Per-account setting (U-11). | Autotask documents request thresholds per integration; the numbers are not recorded here. The adapter must back off on any 429 or 5xx and cap concurrency per client. | Autotask REST API and security-level docs; the MSP's own API user |
| RMM (Datto RMM) | An API key and secret for a read-only role limited to the client's site; components listed, never run (D6-26). | Datto documents a request rate limit per account; the number is not recorded here. Back off on 429. | Datto RMM API docs |
| Intune | Delegated through GDAP with the least-privileged role that can read devices (Intune Administrator is the usual answer; a read-only role is preferable if one fits). Graph scope `DeviceManagementManagedDevices.Read.All`. | Graph rules below. | Graph permissions reference; a test tenant |
| Microsoft 365 identity | Per lever, see the next section. Reads: `User.Read.All`, `UserAuthenticationMethod.Read.All`. | Graph rules below. | Graph permissions reference; a test tenant |
| Backup | Read-only API user scoped to the client's organization; retry is the single write and stays a lever (`backup.retry-job`). | Unknown until a vendor is chosen. | The chosen vendor's docs |
| Alerts | Read-only per source; the adapter can never close or contain an alert. | Unknown until sources are chosen. | Each source's docs |

**Microsoft Graph throttling.** Graph answers HTTP 429 when limits are exceeded and sends a `Retry-After` header; one common cause is many requests from one app across all tenants. Source: <https://learn.microsoft.com/en-us/graph/throttling>, read 2026-10-20 by earlier work recorded in `docs/map/03-architecture-target.md` (SL-10); it was not re-opened for B-91. The adapter rule that follows (design, not yet code): wait the `Retry-After` seconds when present, otherwise exponential backoff with jitter and a cap; never retry a write without its idempotency key; the scheduler caps concurrency per client and per app registration; prefer delta queries over full scans for daily jobs. Per-endpoint limits and the exact `Retry-After` units are UNVERIFIED here.

## Microsoft 365 levers: GDAP role and delegated scope (B91-4)

Access model (D6-09): GDAP with least-privileged roles and the Secure Application Model (SAM, a partner-held app with delegated permissions exercised through GDAP). **No lever uses Global Administrator.** Every cell is UNVERIFIED: written from memory, checked against nothing, and the least-privileged role for each task must be confirmed in a test tenant before a relationship is requested. Scope names marked "(registry)" are the repo's own declarations in `levers/registry*.json`, also UNVERIFIED (`docs/UNVERIFIED.md` U-19).

| Lever | Least-privileged GDAP role (candidate) | SAM delegated scope (candidate) |
|---|---|---|
| `user.new`, `user.set-properties` | User Administrator | `User.ReadWrite.All` (registry) |
| `user.enable`, `user.disable` | User Administrator | `User.EnableDisableAccount.All` (registry for `user.enable`) |
| `user.revoke-sessions` | User Administrator or Helpdesk Administrator | `User.RevokeSessions.All` (registry) |
| `user.reset-password` | Helpdesk Administrator or Password Administrator (non-admin targets only; admin targets are refused, D6-06) | `User-PasswordProfile.ReadWrite.All` |
| `user.new-tap`, `user.reset-mfa` | Authentication Administrator | `UserAuthenticationMethod.ReadWrite.All` |
| `group.add-member`, `group.remove-member` | Groups Administrator | `GroupMember.ReadWrite.All` |
| `license.add`, `license.remove` | License Administrator | `LicenseAssignment.ReadWrite.All` |
| `mailbox.add-dl-member`, `mailbox.remove-dl-member`, `mailbox.grant-full-access`, `mailbox.revoke-full-access`, `mailbox.grant-send-as`, `mailbox.revoke-send-as`, `mailbox.convert-shared`, `mailbox.set-auto-reply`, `mailbox.clear-auto-reply`, `mailbox.enable-archive` | Exchange Administrator | Exchange Online delegated permission (`Exchange.Manage`); these run as Exchange cmdlets, not Graph (U-17) |
| `mailbox.grant-onedrive-manager`, `mailbox.revoke-onedrive-manager` | SharePoint Administrator | Not settled: the SharePoint Online or Graph delegated scope is unknown to this page |
| `message.trace` | Exchange Administrator (a read-only role may exist) | Exchange Online delegated permission |
| `quarantine.release` | Security Administrator or Exchange Administrator | Exchange Online delegated permission |
| `signins.list` | Reports Reader or Security Reader | `AuditLog.Read.All` |
| `risk.list-users`, `risk.user-facts` | Security Reader | `IdentityRiskyUser.Read.All` |
| `risk.device-facts` | Intune read-only role if one fits, else Intune Administrator | `DeviceManagementManagedDevices.Read.All` |
| `inboxrule.list`, `inboxrule.disable`, `inboxrule.enable` | Exchange Administrator | See app-only below: delegated `MailboxSettings.*` (registry) acts on the signed-in person's own mailbox |

Not Microsoft 365: `ticket.get`, `ticket.link`, `contact.check`, `kb.search` (PSA and knowledge base), `backup.retry-job` (backup vendor).

**App-only access** is listed only for documented per-client app registrations (D6-09). None is documented yet; B-54 tracks app registrations and their expiry. The one candidate is the `inboxrule.*` family: a delegated `MailboxSettings.ReadWrite` scope covers only the signed-in user's own mailbox, so reaching a client's users' mailboxes would need an application permission and therefore a documented per-client registration with the narrowest mailbox scope Exchange allows (application access policy or RBAC for applications, UNVERIFIED). Until that registration is documented and approved, the real `inboxrule.*` path stays closed.

## UNVERIFIED (this page and the stubs)

- No real vendor API was called. No vendor documentation page was opened for B-91. The only sourced items are the Graph throttling page (read 2026-10-20 by earlier work) and the Autotask field names (read 2026-10-21 by B-18).
- Every field name in the RMM, backup and alert mocks, every GDAP role and SAM scope above, every throttle number, and the claim that a given role is the **least** privileged one for its lever.
- Whether the MSP's PSA is Autotask, its RMM Datto RMM, or its backup and alert products are what the stubs' names suggest (U-03, U-04, U-13, U-14).
- That a real implementation can honour rule 2 (no existence oracle) when the vendor returns 403 for another tenant's object and 404 for a missing one; the real adapter must map both to the same result. The contract suite checks this only for the mocks until recorded vendor responses exist.
- `GraphMock` does not refuse another client's tenant id when the tenant fixture carries no `_meta.tenantId` (the committed ones carry none). The contract suite records this as an expected failure (`test_b91_one_client_a_mock_refuses_another_clients_external_id[graph]`, an imperative `xfail`); adding `tenantId` to the fixtures or checking it in the mock closes it.
- The mock-fixture poisoning test covers PSA, backup, alerts and RMM only; Intune and Graph rows carry no owner field, so their isolation rests on one file per client.
