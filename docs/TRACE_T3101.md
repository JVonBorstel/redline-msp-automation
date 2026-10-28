# One ticket, traced from one person to the community

Status: **built** for every step below, on synthetic test data only. Nothing here has touched a real company's accounts.

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Every person, company and ticket is made up. Every number on this page is fixture-based (it comes from made-up test data, not real use).

**The case.** Priya Nair (synthetic), a dental hygienist at Contoso Dental (synthetic), dropped her phone in a lake. She cannot approve the extra sign-in check on her work account, called multi-factor authentication (MFA). The managed service provider (MSP) that runs the practice's information technology (IT), receives her request as ticket T-3101.

**Reading the ids.** Each row ends with the rules it rests on, so any claim can be checked. `W-` is a job in the work map, `C-` a safeguard (control), `EU-` a promise to the end user, `ISO-` a rule keeping clients apart, `HO-` a human oversight rule. They are defined in `map/inventory.json`, `map/controls.json` and `docs/map/05-governance.md`.

## What happens to this one ticket

| Step | What happens, in plain words | Rests on |
|---|---|---|
| The ticket | Priya's message is treated as untrusted data, never as instructions: a hidden "ignore the rules" line would be flagged, not obeyed. | W-SD-02, W-IDM-02, C-14 |
| The triage proposal | Software sorts the ticket (sign-in problem, high priority) and proposes one pre-approved action: reset Priya's MFA. It only rehearses it: nothing changes, and the planned change (remove her lost phone as a sign-in method) is shown, with who a wrong reset would hurt. | W-SD-02, C-05, C-03, HO-2 |
| The verification | Staff call Priya back on the phone number already on file, never a number written in the ticket. The lead records how she was checked and where the number came from. Without that record, the software refuses to make the change. | C-30, EU-4, HO-4 |
| The approval | A service desk lead (Lee) approves this exact change, for this person, at this one client. The technician who asked cannot approve it, and a lead for another client cannot either. | C-06, C-07, C-04, ISO-1, ISO-9, HO-3, EU-3 |
| The audit record | Every step writes a record: who asked, who approved, how Priya was checked, what changed. Each record is sealed to the one before, so changing one letter later shows as broken. Her phone details are masked out. Run on this one ticket alone, the checker reports 2 records (the rehearsal and the change), chain intact; that count is fixture-based. | C-08, EU-5 |
| The notice draft | Priya gets a short, plain message: what changed, that her password is the same, who approved it, how to set up her new phone, and a number that puts her first. Software fills a fixed template; a person reads it and sends it. | C-35, C-36, EU-1, EU-2, HO-8, HO-9 |

## What it means beyond Priya

| For whom | What it means | Rests on |
|---|---|---|
| Contoso Dental | One change, to one person, by staff who serve this practice, with a record the practice can ask for. No other client can see Priya's ticket. Patients are seen on time because the hygienist is back at work. | ISO-1, ISO-9, EU-5, EU-6, W-IDM-02 |
| The MSP | The same safeguards run for every client and every reset, not only when someone remembers them. That is evidence an auditor can check, and an honest story an account manager can tell a client about what the software does and does not do. | C-08, C-30, C-45, W-TRN-02 |
| The community | Attackers often phone a help desk posing as staff and ask for exactly this reset. When every reset at every client needs a callback and a named human, that trick stops working at scale. | C-30, EU-4, HO-4, W-IDM-02 |

## See it run

The same commands as the demo demo script (`docs/DEMO.md`), on a laptop with no internet:

```powershell
uv run --frozen python -m workflows.triage T-3101 --enqueue
uv run --frozen python -m ui --state .tmp/demo --demo
uv run --frozen python -m core.audit.verify .tmp/demo/audit/contoso-dental.jsonl
```

The first shows the proposal. The second opens the approval page, on this laptop only, where the lead records the callback and approves. The third checks the record chain. The notice tool lives in `workflows/notify`; its command joins the demo script with the demo update (item B-10).

## What this does not prove

- **No real company.** The accounts are a made-up copy shaped like Microsoft's data. Nothing has run against a real tenant (a company's Microsoft account space).
- **No real callback.** Nobody's phone rang. The software checks that the lead recorded a callback, by whom and when; it cannot know the call happened.
- **Nothing is sent.** The notice is a draft; a person sends it.
- **No real results.** The sorting uses a stand-in model on test data. Every number here is fixture-based, not a real-world measure.
