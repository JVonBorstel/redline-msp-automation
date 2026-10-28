# How we handle your data when we use AI

Status: **document-only** (a one-page summary; each line names the test or file that backs it, on made-up test data)

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.

This page is for a business owner. It says where your data goes and where it does not.

## Where your data goes

- The program runs on one computer. It uses a built-in test model, or a model on that same computer. (proof: `tests/phase1/test_gateway.py::test_shipped_routing_uses_the_configured_provider_and_model`)
- No outside AI service is turned on. Both are off in the settings we ship. (proof: `tests/phase1/test_gateway.py::test_shipped_config_keeps_hosted_providers_off`)
- A model on that computer can only be reached from that computer. Other addresses are refused. (proof: `tests/phase1/test_gateway.py::test_non_loopback_or_tricky_urls_are_refused`)
- Text marked as health or account data is refused if a request tries to send it to an outside service. (proof: `tests/py/guard/test_b55_redaction.py::test_b55_3_hosted_routes_refuse_dc4_and_dc5_text`)
- Passwords and keys are blocked. No model is called when one is found. (proof: `tests/py/guard/test_b55_redaction.py::test_b55_2_dc6_canaries_block_the_call_before_any_provider`)
- Passwords and keys are hidden before anything is written to our record. (proof: `tests/phase1/test_audit.py::test_p1_9_secret_named_params_are_redacted`)

## Who can see it

- Each request and each change belongs to one client. A lever call for another client is refused. (proof: `tests/phase1/test_levers.py::test_p1_1_cross_client_refused`)
- If we hand you our record of what we did for you, it holds your entries only. (proof: `tests/py/levers/test_b42_caps.py::test_b42_2_exported_client_chain_reveals_no_other_client`)
- In our tests, a note for one client never showed another client's contact. (proof: `tests/py/notify/test_b04_notify.py::test_b04_3_isolation_contoso_draft_never_shows_fabrikam_contact`)

## What we cannot tell you yet

- How long data is kept is not set in this prototype. (policy: `governance/SOC2_CONTROL_MAPPING.md`)
- There is no working switch for you to opt out. A client setting for it exists, but nothing reads it yet. (policy: `governance/AI_POLICY.md`)
- The checks that find private data are rules of thumb, and they can miss a name. (policy: `governance/DLP_MAPPING.md`)

## Limits

- This is a prototype. It has not been used for any real client. (policy: `README.md`)
- A test named here shows a rule is checked on made-up data (fixtures). It does not show the rule holds in every case. (policy: `CONTRIBUTING.md`)
- Nothing here is legal advice, a certification or an audit result. (policy: `governance/SOC2_CONTROL_MAPPING.md`)
