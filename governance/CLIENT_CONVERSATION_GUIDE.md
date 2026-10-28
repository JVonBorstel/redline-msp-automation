# Client conversation guide

Status: **document-only** (a guide for account managers talking to small, regulated clients about AI; no one has used it with a real client)

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only. Not legal advice.

For account managers. The aim is to say true things, simply, and to stop where the facts stop. Each line about the program ends with a tag in round brackets. A proof tag names the test that checks it on made-up data. A policy tag names the file that states a rule or a gap. A line that starts "Your part:" is advice for you. The checker is `uv run --frozen python -m workflows.training check`. This page replaces the outline in `docs/planned/CLIENT_CONVERSATION_GUIDE.md`, which stays in place for now (see `specs/B-96.md`). Give the client `docs/AI_EXPLAINER.md` and `docs/CLIENT_DATA_HANDLING.md`, one page each.

## 1. Plain-language summary

- We use AI to read a help request and suggest a fix, with reasons. A person decides. (proof: `tests/phase1/test_triage.py::test_explanation_names_the_lever_the_data_and_the_dry_run`)
- The program shows what a change would do before anything changes. (proof: `tests/phase1/test_levers.py::test_p1_3_dry_run_changes_nothing`)
- A named lead approves each change to your accounts. The program cannot approve its own work. (proof: `tests/phase1/test_levers.py::test_p1_4_agent_cannot_execute_a_write_lever_even_with_approval`)
- Some jobs stay with people, such as checking who is on the phone. (proof: `tests/py/levers/test_b14_fragments.py::test_b14_3_the_named_examples_are_refused_with_inventory_id_and_reason`)
- Your part: say "a helper that suggests, and a person who decides". Do not say "automatic".

## 2. Data handling

- No outside AI service is turned on in what we ship. (proof: `tests/phase1/test_gateway.py::test_shipped_config_keeps_hosted_providers_off`)
- Health and account data is refused on any route to an outside service. (proof: `tests/py/guard/test_b55_redaction.py::test_b55_3_hosted_routes_refuse_dc4_and_dc5_text`)
- Passwords and keys stop a call before any model sees them. (proof: `tests/py/guard/test_b55_redaction.py::test_b55_2_dc6_canaries_block_the_call_before_any_provider`)
- Each request and change belongs to one client. A call for another client is refused. (proof: `tests/phase1/test_levers.py::test_p1_1_cross_client_refused`)
- The record we hand a client holds that client's entries only. (proof: `tests/py/levers/test_b42_caps.py::test_b42_2_exported_client_chain_reveals_no_other_client`)
- Which rule applies to which data class is in the policy pages. (policy: `governance/DLP_MAPPING.md`)
- Your part: use the one-page data summary and do not add to it from memory.

## 3. Honest limits

- This is a prototype. It has not been used for any real client. (policy: `README.md`)
- Every number we have comes from made-up test requests. Do not quote one as a result. (policy: `governance/ROI_TRACKER.md`)
- The check for tricky requests is a rule of thumb. It can miss one, so the approval step is the real safeguard. (policy: `governance/AI_POLICY.md`)
- The checks that find private data can miss a name. (policy: `governance/DLP_MAPPING.md`)
- No auditor has reviewed this prototype, and we do not claim certification or compliance. (policy: `governance/SOC2_CONTROL_MAPPING.md`)
- Which rules apply to a given client, such as health or financial rules, is for counsel to confirm. (policy: `governance/AI_POLICY.md`)
- Your part: when you do not know, say "I will find out and tell you". Write down the question.

## 4. Common questions

| Question | Careful answer |
|---|---|
| Will you train on my data? | We have not built any training. A correction from our staff is saved as a test label to check results. It does not retrain anything. (proof: `tests/phase1/test_triage.py::test_sa4_a_correction_round_trips_into_the_eval_file`) No outside AI service is on, so no vendor receives your data today. (proof: `tests/phase1/test_gateway.py::test_shipped_config_keeps_hosted_providers_off`) |
| Who can see it? | Our staff who serve you. A lead sees only the clients they are assigned to. (proof: `tests/py/queue/test_b03_approval_page.py::test_b03_1_list_filters_to_the_viewers_clients_and_an_unknown_viewer_sees_nothing`) Another client cannot see your requests. (proof: `tests/phase1/test_levers.py::test_p1_1_cross_client_refused`) |
| What if it is wrong? | A lead sees the exact change first and can reject it. (proof: `tests/py/queue/test_b03_approval_page.py::test_b03_3_each_pending_proposal_shows_diff_undo_upn_and_l1_impact`) A wrong change can be undone through a second approved change. (proof: `tests/py/rollback/test_b41_rollback.py::test_b41_3_disable_then_rollback_proposal_approval_execute_restores_the_fixture_byte_for_byte`) A lead can pause the action for every client. (proof: `tests/py/levers/test_b02_runner_gates.py::test_b02_1_global_pause_denies_dry_run_and_execute_with_the_reason`) The risk we rehearsed is the right action on the wrong person. (policy: `docs/TABLETOP_2026.md`) |
| How do I opt out? | There is no working opt-out switch. A client setting for it exists, but nothing reads it yet. Tell us, and a person will decide. Do not promise one. (policy: `governance/AI_POLICY.md`) |
| Can I see what you did with my account? | We can export the record of changes for your account only, and a check shows if it was edited. (proof: `tests/py/levers/test_b42_caps.py::test_b42_2_cli_verify_and_export`) |
| Do you use ChatGPT or similar? | No outside AI service is on in this program. Staff may use outside tools only with public material. (policy: `governance/ACCEPTABLE_USE.md`) |
| What if there is a data leak? | We follow a written runbook and draft plain notices, and people send them. People and counsel decide who must be told. (policy: `docs/runbooks/ai-incident-response.md`) Notice drafts come from a fixed template with no model. (proof: `tests/py/notify/test_b04_notify.py::test_b04_2_no_model_import`) |
| Is this approved for HIPAA or SOC 2? | We do not say that. We can show what we built and what checks it. Counsel confirms what applies to you. (policy: `docs/map/05-governance.md`) |

## 5. What we will and will not commit to in writing

- Your part: do put in writing what the program does, using the one-page summaries, and only the lines that carry a test.
- Your part: do put in writing that a person approves each change and that no outside AI service is on.
- Your part: do not put in writing a saving, a speed, an accuracy rate, an uptime, an opt-out or a compliance claim.
- Your part: do not put in writing how long data is kept. No retention period is set here. (policy: `governance/SOC2_CONTROL_MAPPING.md`)
- Your part: ask the compliance owner and counsel before you sign anything that names a law or a standard.

## Limits

- The answers above are limited to what this prototype does on made-up data (fixtures). Real clients, real data and real volumes have not been tested here. (policy: `README.md`)
- A listed test shows that a rule is checked on made-up data (fixtures). It does not show the rule holds in every case, and the checker proves a test is defined, not that it passes. (policy: `CONTRIBUTING.md`)
- Nothing here is legal advice, a certification or a promise about results. (policy: `governance/SOC2_CONTROL_MAPPING.md`)
