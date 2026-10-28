# What our AI helper does, and what it does not

Status: **document-only** (a one-page explanation; each line names the test or file that backs it, on made-up test data)

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.

This page is for a business owner. You do not need to know anything about AI to read it.

## What it does

- It reads a help request and suggests a fix, with its reasons. It does not act on its own. (proof: `tests/phase1/test_triage.py::test_explanation_names_the_lever_the_data_and_the_dry_run`)
- It shows what a change would do before anything changes. The preview changes nothing. (proof: `tests/phase1/test_levers.py::test_p1_3_dry_run_changes_nothing`)
- A named lead at our company must approve a change. The software cannot approve its own work. (proof: `tests/phase1/test_levers.py::test_p1_4_agent_cannot_execute_a_write_lever_even_with_approval`)
- The person who asked for a change cannot approve it. (proof: `tests/py/storage/test_b82_sqlite.py::test_b82_1_a_requester_cannot_decide_their_own_proposal`)
- Text inside a help request is treated as data, not as orders. A request that says "ignore your rules" is flagged, and it gets no action. (proof: `tests/phase1/test_triage.py::test_sa2_every_injection_ticket_is_flagged_reported_and_gets_no_lever`)
- Some jobs stay with people, such as checking who is on the phone. The software refuses to load a tool for them. (proof: `tests/py/levers/test_b14_fragments.py::test_b14_3_the_named_examples_are_refused_with_inventory_id_and_reason`)
- Each step goes into a record. If someone edits the record later, a check shows it. (proof: `tests/phase1/test_audit.py::test_p1_2_one_byte_changed_in_a_middle_record_names_its_seq`)
- A lead can pause a tool. While it is paused, it refuses every call. (proof: `tests/py/levers/test_b02_runner_gates.py::test_b02_1_global_pause_denies_dry_run_and_execute_with_the_reason`)

## What it can get wrong

- It can be wrong. The check for tricky requests is a rule of thumb. It can miss one. The approval step is the real safeguard. (policy: `governance/AI_POLICY.md`)
- Our test numbers come from made-up requests. They say nothing about real results. (policy: `governance/ROI_TRACKER.md`)
- Messages to your staff are drafted from a fixed template. A person reads each one and sends it. (proof: `tests/py/notify/test_b04_notify.py::test_b04_2_no_model_import`)

## Limits

- This is a prototype. It has not been used for any real client. (policy: `README.md`)
- A test named here shows a rule is checked on made-up data (fixtures). It does not show the rule holds in every case. (policy: `CONTRIBUTING.md`)
- Nothing here is a certification, an audit result or a promise about results. (policy: `governance/SOC2_CONTROL_MAPPING.md`)
