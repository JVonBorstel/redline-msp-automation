# mcp/: MCP server over approved levers (B-87)

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.

A Model Context Protocol server on **stdio** (JSON-RPC 2.0, newline-delimited, Python standard library only; no MCP library is in `uv.lock`). It lets another agent, or Claude, press the buttons the lever registry allows and no others. It is a door, not a gatekeeper: every call becomes one `LeverRunner.invoke(..., mode="dry-run")` as the caller's identity, and the runner decides (role, client scope, lever scope, pauses, parameter schema, audit). Spec: `specs/B-87.md`.

## Run

```powershell
uv run --frozen python -m mcp --as triage-bot                    # read levers only
uv run --frozen python -m mcp --as triage-bot --include-writes   # plus write levers, as proposals only
$env:B87_MCP_TOKEN = '<id token>'; uv run --frozen python -m mcp --auth-config config/mcp-auth.json
```

Exactly one of `--as` and `--auth-config` is required (exit 2 otherwise). State (tenant copy and audit chains) lives under `--state` (default `.tmp/demo`, the folder the lever CLI uses). Protocol goes to stdout, diagnostics to stderr.

## What is exposed

- Default: every registered **read** lever (R0). With `--include-writes`: also every registered write lever, **as a proposal only**.
- A tool is `client` plus `params`; its `params` schema is built from the lever's own schema (types, enums, patterns, lengths, bounds, `additionalProperties: false`). There is no argument for mode, approval, identity or token.
- Tool name = lever name with `.` as `_` (`user.reset-mfa` is `user_reset-mfa`).
- A read returns the runner's data inside a labelled untrusted-data block (`core.guard.wrap_untrusted`) and a list of injection rules that fired (flagged, never followed).
- A write returns the runner's dry-run diff (masked as in the audit) in an untrusted-data block, and a **pending-approval proposal** (`id` = the approval queue's `P-<12 hex>` contract, `executes: false`). Nothing is applied and nothing is queued; a lead decides in the approval queue.
- Never-automate levers cannot be registered (`core/levers/registry.py`), and the server filters the same list again.

## Security checks and their tests

All tests are in `tests/py/mcp/test_b87_mcp.py`.

| Check | Test |
|---|---|
| Only registered read levers are listed by default | `test_b87_1_default_listing_is_exactly_the_registered_read_levers` |
| No write lever is listed by default; writes are listed only when asked, marked proposal-only | `test_b87_1_no_write_lever_is_listed_by_default`, `test_b87_1_writes_are_listed_only_when_asked_and_are_marked_proposal_only` |
| Tool schema has no mode, approval, identity or token argument | `test_b87_1_tool_schema_has_no_way_to_ask_for_execute_approval_or_identity` |
| Tool schema comes from the lever schema | `test_b87_1_tool_schema_is_built_from_the_lever_schema` |
| Every call is one runner call, in dry-run, as the caller | `test_b87_1_read_call_goes_through_the_runner_as_the_callers_identity_in_dry_run` |
| Lever output is untrusted data; injection is flagged, not followed | `test_b87_1_tool_output_is_untrusted_data_and_injection_is_flagged_not_followed` |
| A write returns a dry-run diff and a pending proposal and changes nothing | `test_b87_1_write_call_returns_a_dry_run_diff_and_a_pending_proposal_and_changes_nothing` |
| Proposal id is the approval queue's contract | `test_b87_1_proposal_id_is_the_queue_contract` |
| No call reaches the runner in execute mode or with an approval | `test_b87_1_no_call_ever_reaches_the_runner_in_execute_mode_or_with_an_approval` |
| Role is enforced by the runner, not the server | `test_b87_1_role_is_enforced_by_the_runner_not_the_server` |
| Identity client scope is enforced by the runner | `test_b87_1_client_scope_of_the_identity_is_enforced_by_the_runner` |
| A lever not enabled for a client is denied and audited | `test_b87_2_out_of_scope_lever_for_a_client_is_denied_and_audited` |
| Fooled client: an unregistered lever is refused and audited | `test_b87_2_fooled_client_unregistered_lever_is_refused_and_audited` |
| A registered but unexposed lever is refused and audited | `test_b87_2_registered_write_lever_that_is_not_exposed_is_refused_and_audited` |
| A dotted lever name is not a tool name | `test_b87_2_dotted_lever_name_is_not_a_tool_name` |
| A never-automate lever is never listed or callable | `test_b87_2_never_automate_lever_is_never_listed_or_callable` |
| Malformed arguments are refused before the runner, and audited | `test_b87_1_malformed_arguments_are_refused_before_the_runner_and_audited` |
| Param values are validated by the lever schema | `test_b87_1_param_values_are_validated_by_the_lever_schema` |
| A hostile client value cannot choose an audit file | `test_b87_1_a_hostile_client_value_cannot_choose_an_audit_file` |
| Token identity reaches the runner | `test_b87_2_valid_token_sets_the_identity_the_runner_sees` |
| Wrong audience, unmapped person or expired token: denied and audited | `test_b87_2_token_for_another_audience_or_person_or_time_is_denied_and_audited` |
| Missing or garbage token: denied, empty listing | `test_b87_2_missing_or_garbage_token_is_denied_and_listing_is_empty` |
| Token re-checked on every call | `test_b87_2_token_is_checked_again_on_every_call` |
| Token never reaches the runner, the audit, the results or any file | `test_b87_2_token_is_never_passed_to_the_runner_the_audit_or_the_client` |
| Fixed identity and token mode are exclusive | `test_b87_2_identity_and_token_are_exclusive_and_one_is_required` |
| Protocol: negotiation, init gate, errors, parse errors, batches, oversize lines | `test_b87_protocol_initialize_negotiates_and_declares_tools_only`, `test_b87_protocol_nothing_works_before_initialize`, `test_b87_protocol_errors_and_notifications`, `test_b87_protocol_stdio_loop_handles_parse_errors_batches_and_oversize_lines` |
| stdout carries only JSON-RPC (real subprocess) | `test_b87_protocol_stdout_carries_only_json_rpc_lines` |
| The CLI will not start without exactly one way to know the caller | `test_b87_protocol_cli_refuses_to_start_without_exactly_one_way_to_know_the_caller` |
| stdio only: no network or process module is imported | `test_b87_3_the_server_imports_no_network_or_process_module` |
| No shell and no dynamic code | `test_b87_3_the_server_runs_no_shell_and_no_dynamic_code` |
| This table cites only tests that exist | `test_b87_3_readme_lists_every_security_check_with_a_test_that_exists` |

## Limits

- The protocol subset is written from memory of the MCP specification; not checked against it or a real MCP client (UNVERIFIED).
- `--as` trusts the person who starts the process to name the identity (the OS user is the boundary). Token mode reuses the B-89 validator and its approver map (`oid` to identity), so an agent identity needs an entry there; Entra app registrations, scopes and a real token flow are not exercised.
- Listing is the same for every identity; the runner refuses what the identity may not do.
- The proposal is returned, not queued: `core.queue.store.Source` has no value for this server and `core/` is outside B-87's files.
