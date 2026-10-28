# 07 Reference MSP profile: assumptions and how the prototype fits them

Status: **document-only** (assumption pass). No code. This page states what the prototype assumes about the managed service provider (MSP) it is built for, and which adapters that makes worth building first. It is a reference profile: **a composite of common MSP practice, not a description of any real company**. Nothing here comes from inside any organisation, and nothing in the prototype uses real data: all fixtures stay synthetic.

> Independently built prototype. Synthetic data only. Every row below carries an honest label. **ASSUMED** = a deliberate planning assumption for the reference MSP, common in the industry but not checked against any real organisation. **UNKNOWN** = no basis at all; the prototype takes the stricter safe default and says so. Vendor names are generic examples of a product category, never a claim that a real MSP runs them. Decisions that rest on an assumption are in `06-decisions.md` with what would change them.

Ids in this file: profile rows `MP-nn` and adapter priorities `AP-nn`. They are stable, and other documents cite them.

---

## 1. The short version

The reference MSP is a small or mid-sized managed service provider whose clients are regulated small businesses: **financial services** (banks, credit unions, title companies, investment advisers), **legal** and **accounting and tax** firms, with some **healthcare** (the Contoso Dental demo client). Its tooling is the common PSA, RMM, documentation and backup stack, a client portal, an outsourced 24/7 SOC/MDR, an email-security product and a SIEM. It is a Microsoft cloud partner (Microsoft 365 and Azure), and builds its own automation on Azure services, PowerShell, Microsoft Graph and an MCP-capable model gateway.

Two consequences follow for the maps. The demo client (Contoso Dental, HIPAA framing) is one vertical of several, so the personas also lean to financial and legal clients (D6-13). And the compliance packs cover the regimes those clients live under: GLBA, SEC, Regulation S-P, FDIC, OCC, NCUA, FINRA and, for the dental client, HIPAA (D6-12).

## 2. Company facts

| Id | Assumption | Basis | Label |
|---|---|---|---|
| MP-01 | Domains and offices are synthetic: every address in the repo is on a reserved test domain (`.example`) | fixtures policy | ASSUMED |
| MP-02 | Concentrated on financial services; a Microsoft cloud solution partner for Microsoft 365 and Azure | planning assumption | ASSUMED |
| MP-03 | Holds a Microsoft partner designation for modern work | planning assumption | ASSUMED |
| MP-04 | A small team (tens of staff); the planning scale used for volumes is in `01-work-inventory.md` | planning assumption | ASSUMED |
| MP-05 | Audited under SOC 2 Type II | planning assumption; claimed by nothing in this repo (U-01) | UNKNOWN |
| MP-06 | Supports clients through regulator exams and evidence requests | planning assumption | ASSUMED |

## 3. Tool stack

| Id | Category | Assumption | Basis | Label |
|---|---|---|---|---|
| MP-10 | PSA | A PSA in the Autotask class (generic vendor example) | common in the segment | ASSUMED |
| MP-11 | Client portal | A client portal that fronts tickets, monitoring and subscription management | common in the segment | ASSUMED |
| MP-12 | RMM | An RMM in the Datto RMM class (generic vendor example) | common in the segment | ASSUMED |
| MP-13 | Remote support | A remote-support tool in the Splashtop class | common in the segment | ASSUMED |
| MP-14 | Documentation | A documentation platform in the IT Glue class | common in the segment | ASSUMED |
| MP-15 | Backup and DR | Appliance-based backup and DR (image-based, with boot checks) | common in the segment; service assumed, vendor UNKNOWN | ASSUMED |
| MP-16 | Microsoft 365 backup | A managed Microsoft 365 backup service | service assumed, vendor UNKNOWN | ASSUMED |
| MP-17 | EDR, SOC, MDR | Endpoint detection with an outsourced 24/7 SOC | common in the segment; vendor UNKNOWN | ASSUMED |
| MP-18 | M365 identity threat detection | A third-party identity threat detection service with a 24/7 SOC | common in the segment | ASSUMED |
| MP-19 | SIEM | A SIEM, licensed per user | common in the segment | ASSUMED |
| MP-20 | SaaS monitoring | A SaaS-application monitoring service; vendor UNKNOWN | common in the segment | UNKNOWN |
| MP-21 | Email security | An email security product that offers a user "report phish" button | common in the segment | ASSUMED |
| MP-22 | DMARC service | A DMARC aggregate-report collector (generic vendor example: EasyDMARC class) | common in the segment | ASSUMED |
| MP-23 | Password vault | A managed password vault with enforced MFA and a security audit score; vendor UNKNOWN | service assumed | UNKNOWN |
| MP-24 | Phishing simulation | A phishing-simulation programme with a few campaigns a year; vendor UNKNOWN | service assumed | UNKNOWN |
| MP-25 | Penetration testing | A recurring internal and external penetration-test service (findings report) | common in the segment | ASSUMED |
| MP-26 | Vulnerability scanning | A vulnerability scanner in the Tenable Nessus class (generic vendor example) | common in the segment | ASSUMED |
| MP-27 | Firewall and network | A Fortinet-class firewall estate | common in the segment | ASSUMED |
| MP-28 | SASE | A private gateway fronting Microsoft 365 access; vendor UNKNOWN | service assumed | UNKNOWN |
| MP-29 | CSAT | A customer-satisfaction survey tool tied to tickets | common in the segment | ASSUMED |
| MP-30 | Identity | Entra ID, as part of Microsoft 365 | the Microsoft cloud stack | ASSUMED |
| MP-31 | Internal build and AI stack | Azure DevOps or GitHub Actions, Azure Functions, Logic Apps, Key Vault, Azure OpenAI, hosted-model providers, MCP, PowerShell, Graph, Power Platform; integrations between PSA, RMM, Microsoft 365, Azure and security platforms | the stack this prototype targets | ASSUMED |

## 4. Clients and the rules they live under

| Id | Assumption | Basis | Label |
|---|---|---|---|
| MP-40 | Specialisations: financial institutions (commercial banks, credit unions, title, private equity, investment banks), investment advisers and wealth managers, legal, accounting and tax | planning assumption | ASSUMED |
| MP-41 | Regimes in play: Regulation S-P, SEC cybersecurity rules, GLBA, SEC, FDIC, OCC, NCUA, FINRA; frameworks CIS, NIST, CMMC; cyber-insurance questionnaires | industry knowledge | ASSUMED |
| MP-42 | Also likely: FFIEC expectations for banks and credit unions; SEC books-and-records rules for advisers; ABA Model Rule 1.6 confidentiality for law firms; IRS Publication 4557, a WISP and the FTC Safeguards Rule for tax preparers | general practice | ASSUMED |
| MP-43 | Healthcare and dental clients exist (the demo client) | the demo narrative | ASSUMED |

## 5. How the prototype maps onto this stack

The prototype's seams already match: every external system sits behind a per-client adapter (`B-18`), real implementations fail closed until configured (`B-91`), levers run through one permission-checking runner, and hosted models stay off until approved (D-018). What changes with a real MSP is the order and the shape of the mocks.

### 5.1 Adapters to build first

| Id | Adapter | Mock shaped after | Why first | Roadmap |
|---|---|---|---|---|
| AP-01 | PSA tickets, companies, contacts | An Autotask-style REST API (MP-10) | every workflow starts from a ticket; client ids come from the PSA company (D6-15) | `B-18` (W2), B18-4 |
| AP-02 | Microsoft 365 / Entra via Graph under GDAP | Graph v1.0 (already mocked); access by GDAP and the Secure Application Model (D6-09) | identity is where the highest stakes are | `B-19` (W2), `B-91` |
| AP-03 | Backup job review | Appliance and Microsoft 365 backup job shapes (MP-15, MP-16) | rank 1 leverage; read-only first | `B-68` (moved to W3), B68-4 |
| AP-04 | RMM devices, alerts, components | A Datto RMM-style API (MP-12) | device reconciliation, patching, scripted tier 1 fixes | `B-61` (W6), B61-4 |
| AP-05 | Documentation and KB | A documentation-platform API (MP-14); passwords never ingested | retrieval over documentation and knowledge bases | `B-56` (W5) |
| AP-06 | Security alert intake | alert types: EDR/MDR (MP-17), M365 ITDR (MP-18), SIEM (MP-19); the SOC stays the responder | grouping and enrichment for on-call engineers | `B-43` (W4), B43-4 |
| AP-07 | Client portal intake | a client portal (MP-11) as an intake source beside email and phone | the client-facing channel for tickets | not a separate item: a source type inside `B-18` |
| AP-08 | CSAT export | a CSAT tool (MP-29) | the per-person metric (D6-21) | `B-74` (W7), B74-4 |
| AP-09 | Delivery | A pipeline, Functions, Key Vault, an Azure OpenAI adapter (mocked) | matches MP-31 | `B-85`, `B-86`, `B-90` (W9) |

Every mock records its source fields as Verified or UNVERIFIED (STD-FX-2) and uses no real organisation's data. Product names appear only in specs and adapter docs as generic vendor examples, never in fixtures as if they were real records.

### 5.3 Every tool in the stack, and where it lands (stack coverage)

Checked row by row against `map/roadmap.json` (no tool type is left without a roadmap home). "Shape" is what the item's fixture or mock follows; it is an acceptance line in that item, so the item cannot ship without it.

| Stack row | Tool | Work it serves (inventory) | Roadmap home | Shape required by |
|---|---|---|---|---|
| MP-10 | PSA | every ticket workflow (W-SD-*) | `B-18` (W2, shipped) | AP-01, B18-4 |
| MP-11 | Client portal | ticket intake (W-SD-01) | a source type inside `B-18` | AP-07 |
| MP-12 | RMM | devices, patching (W-EP-*, W-PAT-*) | `B-61` (W6) | AP-04, B61-4 |
| MP-13 | Remote support | remote sessions (W-EP-07) | `B-62` (W6) | B62 session-record line |
| MP-14 | Documentation | documentation and KB (W-KB-*) | `B-56` (W5), vault excluded | AP-05 |
| MP-15, MP-16 | Backup, M365 SaaS backup | backup review (W-BDR-01, W-BDR-02, W-BDR-05, W-BDR-08) | `B-68` (W3), `B-70` (W6) | AP-03, B68-4 |
| MP-17 | EDR / MDR, SOC | security alert intake (W-SEC-01) | `B-43` (W4) | AP-06, B43-4 |
| MP-18 | M365 ITDR | identity alerts (W-SEC-01, W-SEC-04) | `B-43`, `B-46` (W4) | AP-06, B43-4 |
| MP-19 | SIEM | alert source (W-SEC-01) | `B-43` (W4) | AP-06, B43-4 |
| MP-20 | SaaS monitoring | alert source (W-SEC-01) | `B-43` (W4) | B43-5 |
| MP-21 | Email security | user-reported phishing (W-SEC-03) | `B-45` (W4) | B45-4 |
| MP-22 | DMARC service | DMARC, SPF, DKIM monitoring (W-M365-10) | `B-54` (W4) | B54-4 |
| MP-23 | Password vault | vault audit score (W-KB-07 stays excluded from RAG) | `B-71` (W7) report line | B71-4 |
| MP-24 | Phishing simulation | awareness results (W-SEC-10) | `B-71` (W7) | B71-4 |
| MP-25 | Penetration testing | findings review (W-SEC-06) | `B-47` (W4) | B47-4 |
| MP-26 | Vulnerability scanning | vulnerability scan review (W-SEC-06) | `B-47` (W4) | B47-4 |
| MP-27, MP-28 | Firewall, SASE | incident timelines; rule changes stay human (W-SEC-09, NN-05) | `B-48` (W4), firmware report `B-67` (W6) | B48-4 |
| MP-29 | CSAT | CSAT (W-SD-14) | `B-74` (W7) | AP-08, B74-4 |
| MP-30 | Entra ID | identity levers (W-IDM-*) | `B-19`, `B-89` (W2, shipped), W3 identity items | AP-02 |
| MP-31 | Pipelines, Functions, Key Vault, Azure OpenAI | delivery | `B-85`, `B-86`, `B-90` (W9) | AP-09 |

What stays out on purpose: any real connection to these products (NN-07), and changes the program must never make (firewall and SASE rules, Conditional Access, licences; NN-05).

### 5.2 What the stack means for controls

- **Social engineering of the help desk** is the top identity risk for any MSP with financial clients; the runner requires callback-on-file plus the client's authorized contact for MFA reset and TAP (D6-06, `B28-8`).
- **Regulation S-P service-provider duties.** If an MSP's adviser clients must oversee their service providers and be told quickly of a breach (hedged, D6-12), the program's per-client audit chain (`B-42`) and incident fact packs (`B-48`) are evidence those clients can use.
- **A 24/7 SOC may already exist** (MP-17, MP-18), so the program adds grouping, enrichment and pre-authorized containment (D6-08), not a second responder.
- **Hosted model providers may already be in the MSP's own stack** (MP-31), but which client data may reach them is a contract question per client (D6-11); the register starts with both `pending`.

## 6. What to ask a real MSP (each question closes an assumption)

1. Which PSA and RMM are in use, and may an automation identity hold API access to each? (D6-01)
2. Which backup products run for servers and for Microsoft 365, and does the AI role own backup review? (D6-24)
3. How do technicians verify a caller for an MFA reset today? (D6-06)
4. Who approves changes, and what may on-call do alone at night? (D6-05, D6-08)
5. Which clients' contracts allow ticket text to reach a hosted model, and under which terms? (D6-11)
6. Which regime applies to which client, and who sets it? (D6-12)
