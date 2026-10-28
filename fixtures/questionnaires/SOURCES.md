# Synthetic questionnaire fixtures (B-60)

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.

Everything here was written for this repo. No real questionnaire, insurer form, client, policy or project was used.

- `kb/`: a small knowledge base in the B-56 manifest format. `msp-internal` holds invented MSP policy sentences; `contoso-dental` and `fabrikam-capital` hold invented client records. One policy source contains planted instruction text on purpose (tests check it is never quoted). The `*-canary-*` strings are planted to prove no client text reaches another client's draft.
- `projects.json`: invented past projects with invented actual hours. `namespace` says who may see a project: `msp-internal` (anonymous reference work) or a single client id. One note contains planted instruction text on purpose.
- `crosswalk.json`: which repo control ids may back a question, by keyword. A reviewer's mapping, not a measurement.
- `security_questionnaire.json`, `cyber_insurance.json`, `proposal.json`: synthetic questionnaires and a synthetic proposal outline. Some items are made to be refused.

The policy sentences are invented wording. They are not statements about any real organisation, and no answer built from them is evidence that anything operates.
