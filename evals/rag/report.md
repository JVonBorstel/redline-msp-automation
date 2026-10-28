# Cited retrieval, refusal and leakage eval (B-57)

Label: **fixture-based**. No model is called and nothing leaves this machine. The corpus is the synthetic one of
B-56 (`fixtures/kb`) plus eval-only documents (`evals/rag/adversarial.json`); both were written by one author,
so these numbers check the pipeline, not a language model, not a real documentation platform and not real tickets.

**What the numbers do and do not show.** Retrieval uses `HashEmbedder`, a word-overlap stand-in: it is lexical,
not semantic, so a question that shares no words with its article scores near zero. Recall, answer rate and the
threshold below describe this stand-in and these 50 questions only; a real embedder will score differently and
the threshold must be re-chosen with the same eval. The leakage and citation results are structural (namespace
filter in the store, quoted-only answers) and hold whatever the embedder; the zero was also checked at
threshold 0.0, where every caller gets an answer whenever it has any passage.

## Gates

- Answer threshold (chosen from the dev half only): **0.38** (`rag.retrieve.ANSWER_THRESHOLD`).
- Leaks: **0** over 150 question x caller runs (50 questions x 3 callers); at threshold 0.0: **0** over 150 runs.
- Citations to a chunk outside the caller's client and msp-internal namespaces: **0** (at 0.0: 0).
- Answered sentences (all 150 runs): 56; uncited: 0; not quoted from the cited chunk: 0. Groundedness **100.0%**. This is 100% by construction (answers are quoted sentences); the check proves the code keeps it so, it is not a measure of answer quality.
- Should-refuse questions answered (false answers): dev **0** (gated: the threshold is the smallest step above the best dev score), holdout **2** of 15 (reported, not gated). Refusal rate dev 100.0%, holdout 86.7%.
- Store errors (search failed closed): 0.
- Result: **PASS**.

Planted and checked on every run, in every answer, citation and returned passage: the other clients' canaries,
prompt-injection markers, vault canaries and secret shapes (built at run time).

## Refusal and answer rates at the chosen threshold

| Question kind | Asked | Refused | Answered |
|---|---|---|---|
| answerable | 18 | 4 | 14 |
| unanswerable | 8 | 8 | 0 |
| cross_client | 8 | 8 | 0 |
| canary_probe | 6 | 2 | 4 |
| injection_probe | 6 | 6 | 0 |
| vault_probe | 4 | 4 | 0 |

Question mix: answerable 18, unanswerable 8, cross_client 8, canary_probe 6, injection_probe 6, vault_probe 4. A question is should-answer only if it has an expected article (answerable questions, and the canary probes that ask for a caller's own or the shared one).

- Answerable questions answered: dev 90.0%, holdout 70.0%.
- Answered and cited the expected article: dev 90.0%, holdout 70.0%.
- Answered without citing the expected article: none.
- Holdout should-refuse questions that got an answer: q36 (canary_probe, top score 0.41, cited KB-CD-004), q38 (canary_probe, top score 0.39, cited KB-FC-003, KB-FC-001). Each such answer quotes the caller's own or the shared MSP articles (never another client's, see Leaks): the question shares generic words such as `reference phrase` with them, which word overlap cannot tell from a match.
- Answerable but refused (`no source found`): q02 (top score 0.30), q08 (top score 0.35), q17 (top score 0.22), q18 (top score 0.00). These are the cost of the word-overlap stand-in and of a threshold set to refuse every should-refuse dev question; paraphrases with no shared words are the typical miss.
- Sentences dropped by the second injection scan at answer time: 0.

## Threshold sweep (all 50 questions, stated client)

| Threshold | Answerable answered | Answered citing the expected article | Should-refuse answered | Leaks |
|---|---|---|---|---|
| 0.05 | 95.0% | 95.0% | 27 | 0 |
| 0.10 | 95.0% | 95.0% | 19 | 0 |
| 0.15 | 95.0% | 95.0% | 8 | 0 |
| 0.20 | 95.0% | 95.0% | 6 | 0 |
| 0.25 | 90.0% | 90.0% | 3 | 0 |
| 0.30 | 90.0% | 90.0% | 3 | 0 |
| 0.35 | 80.0% | 80.0% | 3 | 0 |
| 0.40 | 70.0% | 70.0% | 1 | 0 |
| 0.45 | 65.0% | 65.0% | 0 | 0 |
| 0.50 | 65.0% | 65.0% | 0 | 0 |
| 0.55 | 60.0% | 60.0% | 0 | 0 |
| 0.60 | 50.0% | 50.0% | 0 | 0 |
| 0.65 | 35.0% | 35.0% | 0 | 0 |
| 0.70 | 25.0% | 25.0% | 0 | 0 |

Leaks stay 0 at every threshold: isolation does not depend on it. False answers fall to 0 at the chosen value
by construction on dev; the holdout column of the gates above is the check that it was not just tuned to dev.

## Ingestion refusals in the eval corpus

- client:contoso-dental: 4 indexed, cd-vault-router refused (vault-source)
- client:fabrikam-capital: 2 indexed, fc-portal-logins refused (vault-source)
- client:contoso-dental: 2 indexed, cd-secrets-sheet refused (vault-source)
- client:fabrikam-capital: 3 indexed, fc-secret-note refused (secret-shape)
- msp-internal: 2 indexed, msp-vault-notes refused (vault-source)

## Honest limits

- `HashEmbedder` is not semantic. Recall and the threshold are properties of this stand-in. Nothing here was run
  against a real embedding model or a real documentation export (UNVERIFIED).
- 50 questions written by the same author as the articles; the threshold was set on the 25 dev questions and
  checked on 25 holdout questions, which is a small and friendly sample, not a guarantee.
- The injection tripwire and the redaction rules are heuristics (B-55, B-79). A planted document they miss would be
  indexed and could be quoted; the planted ones here are caught by design, so a zero here does not prove the
  tripwire catches real attacks. The lever registry's permission checks remain the control for that.
- Answers are quoted sentences, not generated text; no model produces or checks them. Whether a quoted sentence
  answers the question is not measured beyond the expected-article check.
- Leak detection is by exact planted string (case-insensitive). A paraphrase of another client's text would not be
  seen, but the store never returns another client's chunk, which the namespace check counts separately.
- Cross-client probes ask about topics only the other client documents; the msp-internal namespace is shared by
  design and its canary is not counted as a leak.
