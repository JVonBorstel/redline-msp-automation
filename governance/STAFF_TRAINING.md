# Staff training: working with AI safely

Status: **document-only** (a training page for technicians and account managers; the ten-minute exercise is built on fixtures and replayed by a test; no one has taken this training)

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only. Not legal advice.

For technicians, leads and account managers. No AI background is needed. It takes about an hour to read and ten minutes for the exercise. Words in code font, such as `user.reset-mfa`, are the names of levers. A lever is one pre-built, tested action, such as "reset a person's sign-in check".

How to read this page: each line about the program ends with a tag in round brackets. A proof tag names the test that checks the line on made-up data. A policy tag names the file that states a rule for people. A line that starts "Your part:" is what you do. The checker is `uv run --frozen python -m workflows.training check`; it fails if a named file or test does not exist. This page replaces the outline in `docs/planned/STAFF_TRAINING.md`, which stays in place for now (see `specs/B-96.md`).

## 1. What this is and is not

- The program reads a help request and suggests one pre-built action, with the reasons. It does not act on its own. (proof: `tests/phase1/test_triage.py::test_explanation_names_the_lever_the_data_and_the_dry_run`)
- A change to a client cannot run without a lead's approval. (proof: `tests/phase1/test_levers.py::test_p1_5_execute_without_lead_approval_denied`)
- Only registered levers act. Anything else is refused and written to the record. (proof: `tests/phase1/test_levers.py::test_p1_4_unregistered_lever_denied_and_logged`)
- The model does not choose the lever. A fixed rule does, from the category of the request. (proof: `tests/phase1/test_triage.py::test_sa2_model_output_cannot_choose_the_lever`)
- A list of jobs is kept for people only, such as checking who is on the phone. The program refuses to load a lever for them. (proof: `tests/py/levers/test_b14_fragments.py::test_b14_3_every_pattern_in_the_list_blocks_a_lever`)
- Your part: treat every suggestion as a draft from a helper who has not met the client.

## 2. What may and may not go into a prompt

- Every piece of text has a data class, DC-0 (public) to DC-6 (passwords and keys). The table is in `governance/ACCEPTABLE_USE.md` and the full mapping is in `governance/DLP_MAPPING.md`. (policy: `governance/DLP_MAPPING.md`)
- A password or key in a request stops the call. No model is used. (proof: `tests/py/guard/test_b55_redaction.py::test_b55_2_dc6_canaries_block_the_call_before_any_provider`)
- Health and account data is refused on any route to an outside service. (proof: `tests/py/guard/test_b55_redaction.py::test_b55_3_hosted_routes_refuse_dc4_and_dc5_text`)
- No outside AI service is turned on in the shipped settings. (proof: `tests/phase1/test_gateway.py::test_shipped_config_keeps_hosted_providers_off`)
- The program's data-shape checks are a tripwire. They can miss a name with no cue word. (policy: `governance/DLP_MAPPING.md`)
- Outside AI tools, such as a public chatbot, may only get public material (DC-0). (policy: `governance/ACCEPTABLE_USE.md`)
- Your part: if you are not sure of the class, treat it as health data (DC-4) at a dental client and as account data (DC-5) everywhere else.
- Your part: never paste a password, key or recovery code anywhere. Secrets stay in the vault.

## 3. How to read a suggestion

- A suggestion lists why it chose this action, which data it used and which lever it would pull. (proof: `tests/phase1/test_triage.py::test_explanation_names_the_lever_the_data_and_the_dry_run`)
- It shows who the change affects and what a lead must check before approving. (proof: `tests/py/triage/test_b05_trace.py::test_b05_1_t3101_shows_who_this_affects_with_the_levers_l1_to_l4_lines`)
- For a sign-in reset it says to call back on the number already on file. (proof: `tests/py/triage/test_b05_trace.py::test_b05_1_t3101_says_call_back_on_the_number_on_file_before_approval`)
- The text of a request is treated as data. A request that tries to give orders is flagged, goes to the security queue and gets no lever. (proof: `tests/phase1/test_triage.py::test_sa2_every_injection_ticket_is_flagged_reported_and_gets_no_lever`)
- The flag is a rule of thumb. It can miss a trick, so the approval step is the real safeguard. (policy: `governance/AI_POLICY.md`)
- Your part: check that the person named in the suggestion is the person in the request. A right action on the wrong person is the risk we rehearsed. (policy: `docs/TABLETOP_2026.md`)

## 4. Accept, correct or reject

- Accepting a suggestion sends it to a lead for approval. It does not run it. (proof: `tests/phase1/test_triage.py::test_enqueue_puts_the_triage_proposal_in_the_approval_queue`)
- A technician or lead can record the right category, priority, queue or lever. A program account cannot correct its own work. (proof: `tests/phase1/test_triage.py::test_invalid_corrections_are_refused_and_nothing_is_written`)
- A correction is saved as test data for later measurement. It does not change the program or train a model by itself. (proof: `tests/phase1/test_triage.py::test_sa4_a_correction_round_trips_into_the_eval_file`)
- A lead can reject a proposal without any callback or check. (proof: `tests/py/queue/test_b03_approval_page.py::test_b03_2_reject_needs_no_verification`)
- Your part: correct the small things too. A wrong category today is a wrong test label tomorrow.

## 5. Approvals: what you are signing off on

- Only a lead can open the approval page, and a lead sees only their own clients. (proof: `tests/py/queue/test_b03_approval_page.py::test_b03_1_list_filters_to_the_viewers_clients_and_an_unknown_viewer_sees_nothing`) (proof: `tests/py/queue/test_b03_approval_page.py::test_b03_1_only_a_lead_can_be_the_viewer`)
- Each proposal shows the exact change, the undo, the person affected and the effect on them. (proof: `tests/py/queue/test_b03_approval_page.py::test_b03_3_each_pending_proposal_shows_diff_undo_upn_and_l1_impact`)
- The person who asked for a change cannot approve it. (proof: `tests/py/storage/test_b82_sqlite.py::test_b82_1_a_requester_cannot_decide_their_own_proposal`)
- For a sign-in reset the lead must record a callback and where the number came from. Without it, the change is refused and stays pending. (proof: `tests/py/queue/test_b03_approval_page.py::test_b03_2_approve_without_an_allowed_verification_is_refused_audited_and_stays_pending`)
- The phone number itself is never typed in or stored. (proof: `tests/py/queue/test_b03_approval_page.py::test_b03_2_the_number_itself_is_never_accepted_or_recorded`)
- A "knowledge check" question is not accepted in place of a callback. (proof: `tests/py/levers/test_b28_runner3.py::test_b28_8_a_knowledge_check_style_method_is_not_a_callback`)
- Your name goes on the record next to the change. (proof: `tests/phase1/test_levers.py::test_p1_5_execute_with_lead_approval_allowed_and_approver_recorded`)
- Your part: read the diff before you approve. If you cannot say what it changes in one sentence, reject it.

## 6. When the AI is wrong or odd

- Tell the on-call lead at once about a secret in a request, data in the wrong tool, a strange instruction inside a ticket or a wrong automated change. (policy: `governance/ACCEPTABLE_USE.md`)
- A lead can pause a lever for one client or all clients. A paused lever refuses every call. (proof: `tests/py/levers/test_b02_runner_gates.py::test_b02_1_only_a_lead_may_pause_or_resume`)
- A wrong change is undone through a normal proposal. It needs approval, and the one who asked cannot approve it. (proof: `tests/py/rollback/test_b41_rollback.py::test_b41_1_the_proposal_needs_normal_approval_a_requester_cannot_approve_it`)
- The runbook (`docs/runbooks/ai-incident-response.md`) has nine steps, IR-1 to IR-9. Its commands are run in a test on made-up data. (proof: `tests/py/governance/test_b94_incident_response.py::test_b94_1_runbook_commands_run_end_to_end_on_a_synthetic_wrong_disable`)
- The runbook was rehearsed once, by a script, on made-up tenants. People have not rehearsed it. (policy: `docs/TABLETOP_2026.md`)
- Whether a breach happened, and who must be told, is decided by people with the client and counsel. The program does not decide it. (policy: `governance/never-automate.json`)
- Your part: report early and say what you saw.

## 7. Ten-minute exercise on synthetic tickets

You need a terminal in the project folder and ten minutes. Work with a partner. The three tickets are synthetic (made up). They are in `fixtures/tickets/contoso-dental.json` for a made-up dental practice. Read each ticket first, then run its command, then answer the questions before you open the answer key.

### The tickets

- Your part: read `T-3101`, subject "Phone in the lake, Authenticator gone". A hygienist lost her phone and wants her sign-in check reset.
- Your part: read `T-3127`, subject "Printer offline again". The body also holds an odd instruction.
- Your part: read `T-3128`, subject "MFA is slowing the front desk down". The body asks for a change for the whole practice.

### Run them (about two minutes each)

```
uv run --frozen python -m workflows.triage T-3101 --state .tmp/training
uv run --frozen python -m workflows.triage T-3127 --state .tmp/training
uv run --frozen python -m workflows.triage T-3128 --state .tmp/training
```

- Your part: for each ticket, say what the program suggested, which data it used, who would be affected, and whether you would approve it.

### Answer key

- `T-3101`: category mfa, queue identity. It suggests `user.reset-mfa` for the hygienist's own account. The dry run is ok, one change is shown, nothing is applied, and the proposal is pending a lead. (proof: `tests/py/governance/test_b96_training_docs.py::test_b96_1_the_exercise_answer_key_matches_what_the_commands_print`)
- `T-3127`: flagged as `instruction-override`. It goes to the security queue. No lever is proposed and no dry run happens. (proof: `tests/py/governance/test_b96_training_docs.py::test_b96_1_the_exercise_answer_key_matches_what_the_commands_print`)
- `T-3128`: flagged as `safety-bypass`. It goes to the security queue with no lever. A line that says approval is not required changes nothing. (proof: `tests/phase1/test_triage.py::test_sa2_every_injection_ticket_is_flagged_reported_and_gets_no_lever`)
- Your part: talk it through. Why would you still call the hygienist back on the number on file for `T-3101`? Which of the three needs a person to read it first?

## Limits

- The exercise runs on the built-in test model and on fixture tickets (made up). Real requests are messier and the program's suggestions on them have not been measured here. (policy: `README.md`)
- No one has taken this training. Training completion records are planned, not built. (policy: `map/controls.json`)
- A listed test shows that a rule is checked on made-up data (fixtures). It does not show the rule holds in every case, and the checker proves a test is defined, not that it passes. (policy: `CONTRIBUTING.md`)
- Nothing here is a certification, a legal opinion or a measured result. (policy: `governance/SOC2_CONTROL_MAPPING.md`)
