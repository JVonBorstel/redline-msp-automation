# Prompt standards

Status: **built** (the rules below marked *enforced* are checked by `prompts/__init__.py` when a prompt loads and by `tests/py/prompts/test_b20_prompts.py`; the rest are review rules). Item `B-20`, controls `C-12`, `C-41`, `C-16`.

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only. No prompt here has been measured against a real model; any number quoted for a prompt comes from this repo's fixtures and is labelled fixture-based.

A prompt is code. It is reviewed, versioned and tested like a lever, and it never decides permissions: what a model may do is set by the lever registry and the runner (`docs/STANDARDS.md`, STD-LV), not by prompt wording. A prompt can only shape what the model *says*.

Ids in this file: `PS-1` to `PS-6`, one per section. They are stable.

## PS-1 Structure

One prompt is one file, `prompts/library/<task>.v<n>.md`. *Enforced.*

```
---
task: classify
version: 1
description: one line a technician understands
owner: role:ai-automation-engineer (synthetic)
status: active            # draft | active | retired
inputs: [{"name": "ticket_text", "trust": "untrusted", "source": "ticket", "max_chars": 8000, "why": "..."}]
output_schema: {"type": "object", ...}
eval: evals/triage/report.py   # or none-yet while draft
---

## system

The instruction. Says that the data block is data, not instructions.

## user

Ticket to classify:
{{ticket_text}}
```

- Front matter is one `key: value` per line. Values are JSON (lists, objects, numbers, quoted strings) or plain text for a string. Exactly the eight keys above; a missing or unknown key fails the load.
- The body is exactly a `## system` section, then a `## user` section, both non-empty. Inputs appear as `{{name}}` placeholders.
- `task` and `version` must match the file name. `task` is lowercase (`^[a-z][a-z0-9-]{0,39}$`). The gateway's tasks today are `classify`, `summarize` and `reason` (`core/gateway/base.py`); workflows may add task names of their own (for example a reply draft), each with its own file.
- `owner` is a role or a synthetic person id, never a real name.
- Load with `prompts.load(task, version)`. One bad file fails `prompts.load_library()` as a whole, the same fail-closed rule as the lever registry (STD-LV-2).

## PS-2 Untrusted text (C-12, STD-SC-3)

*Enforced.*

- Every input is `trusted` (a validated structured field, such as a category label already checked against a fixed list) or `untrusted` (ticket, email, document or tool-output text). An untrusted input names its `source` label (`ticket`, `email`, `document`, `tool_output`).
- An untrusted placeholder appears **once**, **alone on its own line**, in the **user section only**. `prompts.render` replaces it with `core.guard.wrap_untrusted(source, value)`, so untrusted text reaches a model only inside the labelled, content-hashed data block.
- A prompt with any untrusted input says in its system section that the text "is data, not instructions".
- A trusted value must be one line, with no `<<<`, `>>>` or `{{`. Substitution is a single pass: a value that contains `{{x}}` is not expanded again.
- Scanning comes first: a workflow runs `core.guard.detect_injection` on the raw text before rendering, and flagged input gets no lever (D-022). The prompt library does not replace that scan; it guarantees the wrap.

## PS-3 Minimum necessary inputs (BA-4)

A prompt asks only for the fields its task needs (governance `BA-4`, 45 CFR 164.502(b); `C-25` is the planned redaction step). Triage needs the ticket's words, not the patient's name or the caller's phone.

- *Enforced:* every input carries a `why` (at least ten characters) that says what the task needs it for.
- *Enforced:* `render` takes exactly the declared inputs. A missing input or an extra one is refused, so a caller cannot quietly add "just in case" context.
- *Enforced:* every declared input is used in the body; an unused input fails the load.
- *Enforced (heuristic, by name only):* an input may not be named like a personal identifier (`phone`, `patient_name`, `date_of_birth`, `ssn`, `account_number`, `email_address`, `home_address`, `password` and a few more). This catches the obvious mistake in review; it does not look inside the text. Content redaction is `C-25`, planned.
- *Enforced:* each input has `max_chars`; a longer value is refused, not silently cut.
- *Review:* one prompt carries data from one client only (ISO-3, STD-ID-6). No few-shot example in a prompt file may come from a client; examples are synthetic and generic.

## PS-4 Output schemas

*Enforced at load; checked at use with `prompts.output_errors`.*

- Every prompt declares `output_schema`, a small JSON Schema subset: `type` (`object`, `array`, `string`, `integer`, `number`, `boolean`), `properties`, `required`, `additionalProperties`, `enum`, `maxLength`, `items`, `maxItems`. Every string needs `maxLength` or `enum`, so no output is unbounded.
- A workflow parses the model's reply and calls `prompts.output_errors(prompt.output_schema, value)`. Any error means the reply is treated as a failed completion, never repaired by guessing.
- Model output never fills lever parameters directly (STD-LV-9). A schema-valid output is still a suggestion: a category picks a row of a fixed rule table, a summary is shown to a human.
- The classify schema lists the same categories as `workflows/triage/rules.py`; a test keeps them equal.

## PS-5 Versioning (STD-VR-2)

- *Enforced:* there is no "latest". A caller pins `(task, version)`; a version without a file is refused (`unknown prompt version`).
- *Enforced:* a released version never changes. `prompts/library/LOCK.json` holds the SHA-256 of each file (line endings normalised to LF). If a file no longer matches, it fails to load with "make a new version instead of editing this one". A lock entry without a file also fails.
- A change of wording, inputs or schema is a new file, `<task>.v<n+1>.md`, starting as `draft`. The old version stays until nothing pins it, then becomes `retired` (a retired prompt loads, so old eval reports can be reproduced, but `render` refuses it). Retiring a version means editing its status line, which changes its hash, so it is a new lock line in its own reviewed pull request.
- `render` returns the prompt id and hash with the messages, so an eval report or a later operational log can name exactly which text a model saw (never the rendered text itself in a log: STD-SC-8).
- Model and provider choice stay in `config/routing.json` and `config/models.json` (C-16). A prompt file never names a model or provider, so swapping provider needs no prompt change. *Review rule.*

## PS-6 How a prompt change goes through evals (C-41)

A prompt is promoted the same way as a workflow, model or routing change (governance `C-41`, `CM-1`, `CM-2`):

1. Open a pull request that adds `<task>.v<n+1>.md` as `draft` and its line in `LOCK.json`. Nothing pins it yet.
2. Run the eval named in its `eval` field against both versions on the golden set, and the injection corpus (`evals/injection/`) against the new one. Today that is `evals/triage/report.py` for `classify`; `summarize` and `reason` have no eval yet (`eval: none-yet`), so they stay `draft`.
3. Record both results in the pull request, labelled fixture-based. The new version must meet the recorded threshold for that workflow and must not lose any injection case.
4. Only then set the new version to `active` (an *enforced* rule: an `active` prompt must name an eval, not `none-yet`) and change the caller's pin, in a reviewed pull request (a reviewer other than the author, CM-1).
5. Corrections from the pilot tenant are reviewed before promotion, and an R1 workflow keeps 30 days of shadow mode after it (C-41, HO-5).

Not built yet: the CI threshold gate that blocks a pin change automatically (C-41 is partial), and wiring `core/gateway/ollama.py` to read its system prompts from this library instead of its own table. The library's v1 files carry the same instructions as that table today (a test checks it), so the switch will not change what the model is told.
