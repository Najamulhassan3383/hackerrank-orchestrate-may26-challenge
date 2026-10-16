# Potential improvements: a practical learning guide

Reviewed against the implementation on **2026-10-14**. This is a roadmap; proposed safeguards are not implemented by this documentation update. The challenge has ended. Use the project to learn how to build, measure, and operate a support system.

The most valuable next step is a repeatable evaluation harness and correctness fixes before adding more model calls. A fluent answer is not proof that retrieval, routing, or grounding worked.

## 1. Understand the system you built

```text
Offline indexing:
Markdown -> frontmatter/body -> chunks -> Titan embeddings -> Postgres/pgvector

Ticket processing:
CSV -> ticket embedding -> company-filtered top-5 chunks -> prompt
    -> Bedrock Converse -> raw text -> JSON parser -> output CSV
```

| Component | Implementation | Current responsibility |
| --- | --- | --- |
| Input/orchestration | `code/main.py` | Read tickets, call dependencies, save raw replies and the final CSV |
| Document preparation | `code/chunking.py` | Keep short articles whole, split longer ones, skip index files and release notes |
| Embeddings | `code/embed.py` | Normalized 1,024-dimensional vectors; retry selected service errors |
| Index build | `code/index_chunks.py` | Concurrent embedding, batch inserts, skip existing `(path, md5(body))` pairs |
| Database | `code/db.py`, `db/init.sql` | Connect to Postgres, check extension and row count |
| Retrieval | `code/retrieve.py` | Exact cosine-distance search with an optional company filter |
| Generation | `code/prompt.py`, `code/bedrock_client.py` | Build the prompt and request JSON with temperature zero |
| Parsing | `code/parse.py` | Extract a JSON object and convert five fields to strings |
| Existing checks | `code/test_retrieval.py` | Three basic chunk checks and seven question-to-article checks |

Small modules, parameterized SQL, environment-based cloud configuration, and saved raw outputs are useful foundations. Temperature zero reduces sampling variation; it does not guarantee identical outputs across runs or provider updates.

## 2. Verified findings and immediate priorities

An offline audit exercised real functions with synthetic inputs and mocked service boundaries. It made **no AWS or database calls**, did not reindex, and did not replace `support_tickets/output.csv`. CSV writing was mocked; printed messages saying “wrote” were not actual writes. Temporary raw responses contained synthetic text only.

**Three of twelve diagnostic checks passed.** These probes intentionally exercise missing safeguards. This fraction is not a support-answer accuracy score.

| Check | Observed result | Interpretation |
| --- | --- | --- |
| Existing offline chunk checks | Pass | Short article, long split, and release-note path checks pass |
| Valid JSON | Pass | A valid five-field object parses |
| Fenced JSON | Pass | A valid object in a JSON code fence parses |
| Final corpus chunk size bound | Fail | 77 of 1,854 chunks exceed 8,000 characters; maximum 8,271 |
| Paragraph overlap bound | Fail | Boundary fixture produced chunks of 7,900 and 8,152 characters |
| Reject invalid status | Fail | `status="completed"` is accepted |
| Reject missing fields | Fail | `{}` becomes five empty strings |
| Reject wrong field types | Fail | An object in `response` becomes a string |
| Canonicalize company case | Fail | `" hackerrank "` becomes `"hackerrank"`, not stored label `"HackerRank"` |
| Reject nonfinite embeddings | Fail | Mocked NaN vector passes the length-only check |
| Preserve results after service failure | Fail | Failure on ticket 2 prevents final CSV writing |
| Valid parse-error fallback | Fail | Invalid JSON emits `status=""`, outside the contract |

Generated chunks: **HackerRank 953, Claude 880, Visa 21**. These are local chunk-generation counts, not verified database counts. The previous note reports seven live retrieval cases passed in an earlier session. This review did not rerun those paid calls or establish current answer accuracy.

### Fix these first

1. **Validate the output contract.** Require five fields, string types, and the allowed status/request-type enums. Decide explicitly whether extra keys are allowed. Missing keys must not silently become empty strings. An unknown product area may be blank; an empty status is invalid. Validate useful response content and label consistency separately from JSON syntax.
2. **Handle failures per ticket.** Embedding, search, and generation happen outside the parsing `try` block. A failure aborts the run before CSV export. Save completed work by stable ticket ID and emit a valid escalation with a safe response/reason code for failed tickets. Do not claim delivery to a human unless a real handoff exists.
3. **Version and synchronize the index.** Changed bodies are inserted while old chunks remain; deleted files leave stale rows. Changing embedding model can reuse incompatible vectors because the skip key has no model identity. Build a staging version, validate it, atomically activate it, and retain a rollback version. Add database uniqueness rather than relying on an in-memory skip set under concurrent builds.
4. **Fix the chunk budget.** Prefixes are added after splitting. Overlap plus a nearly full paragraph can also exceed the limit. Reserve space for title, heading, separators, and overlap; validate the final text sent to the API.
5. **Preserve evidence metadata.** Frontmatter includes URLs and update dates, but chunks/DB do not retain them as structured metadata. Search returns a path and distance, yet `main.run` sends only bodies to the generator. Carry source identity through all stages.
6. **Normalize inputs.** Map recognized company labels to canonical values, handle BOM/Unicode, validate required headers, and distinguish blank/unknown/invalid company values. Avoid silent empty tickets caused by unexpected headers.

An 8,271-character chunk is not automatically an API-limit violation. The verified problem is breaking the project's intended 8,000-character budget. AWS documents separate character/token limits for Titan V2; verify the configured model before applying them. See [Titan embedding documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html).

## 3. Test every component independently

Use three layers:

- **Unit tests:** local functions and mocked dependencies; fast, deterministic, no credentials.
- **Integration tests:** disposable Postgres or small live provider calls; verify real boundaries.
- **Behavior evaluations:** reviewed tickets; verify correct decisions and grounded replies.

Mocks cannot prove AWS permissions or real SQL behavior. A connectivity check proves access, not relevance. Keep service tests separate from offline tests so a routine local run cannot unexpectedly make paid calls.

| Component | Cases to test | Passing evidence |
| --- | --- | --- |
| CSV input | Blank cells, BOM, mixed-case headers, commas/newlines, Unicode, missing headers | Correct row extraction or explicit validation error |
| Frontmatter | Valid/absent/malformed metadata, quoted titles | Expected title, URL, date, and body; clear malformed-file handling |
| Chunker | Empty/short articles, large paragraphs, many headings, tables, fenced code containing `##`, boundary steps | Stable chunks; no empty text; source coverage; final budget obeyed |
| Embedding adapter | Wrong dimension, NaN/Inf, malformed response, empty input, throttling, access denial | Finite numeric vectors; bounded retries; permanent errors do not retry |
| Indexer | Unchanged rerun, changed/deleted file, concurrent builders, model change, interrupted batch | Idempotence; no stale active chunks; compatible vectors; recovery |
| Database | Missing schema/extension, null vectors, company counts, disconnects | Expected active rows/schema; valid vectors; bounded failures |
| Search | Known evidence, no evidence, company casing/unknowns, ties, multi-domain tickets | Correct filtering/ranking and appropriate abstention |
| Prompt builder | Zero hits, oversized context, missing metadata, malicious document text | Stable evidence IDs; budgeted context; untrusted-data boundaries |
| Model adapter | Timeout, throttle, denial, truncated/empty output | Safe failure paths, usage/stop reason recorded, deadline enforced |
| Parser | Valid/fenced/malformed JSON, arrays, missing keys, wrong types/enums | Strict validation; valid fallback; no silent coercion |
| Routing | FAQ, feature request, outage, risky action, ambiguous/out-of-scope request | Correct labels independently of exact response wording |
| Batch/output | One failure among successes, crash/resume, repeated run, CSV round-trip | One final row per input; stable IDs/order; no lost work |

The existing long-article test only checks that multiple pieces exist. Add assertions for final size, preserved facts, headings, overlap, and metadata. Also test headings inside code fences: raw `##` scanning can split a fenced example incorrectly.

### Two first regression tests

These express desired behavior and currently fail. The following is an example for a future `code/tests/` suite, not a test file added by this review. Arrange imports from `code/` in the test setup.

```python
import json
import pytest
from chunking import MAX_CHARS, split_long_section
from parse import parse_answer

def test_overlap_respects_budget():
    text = "x" * 7900 + "\n\n" + "y" * 7950
    assert all(len(p) <= MAX_CHARS for p in split_long_section(text))

def test_invalid_status_is_rejected():
    raw = json.dumps({
        "status": "completed", "product_area": "general_support",
        "response": "Example", "justification": "Synthetic fixture",
        "request_type": "product_issue",
    })
    with pytest.raises(ValueError):
        parse_answer(raw)
```

Also test final prefixed `Chunk.body`; intermediate splitting alone is insufficient. Mock provider responses and replace sleep in retry tests. Use isolated temporary output directories and disposable database schemas. References: [pytest monkeypatch](https://pytest.org/en/latest/how-to/monkeypatch.html), [temporary paths](https://docs.pytest.org/en/stable/how-to/tmp_path.html).

### Existing checks you can run now

From the repository root; these Python commands work in PowerShell and Unix shells:

```text
# Offline smoke checks: no provider calls
python -c "import sys; sys.path.insert(0, 'code'); from test_retrieval import check_chunking; failures=check_chunking(); print(failures or 'PASS'); sys.exit(bool(failures))"

# Configured Postgres connectivity and row count only
python code/db.py

# Live retrieval check: requires AWS and a populated database
# Embeds seven queries and can incur charges
python code/test_retrieval.py
```

Do not use `index_chunks.py --rebuild` as a routine test: it deletes rows before embedding replacements. `main.py` overwrites the shared CSV and reuses raw filenames. Add configurable output paths and unique run IDs before repeatable end-to-end evaluations. Keep the challenge entry point and required fields compatible.

Future command after adding the proposed suite and pinned development dependencies: `python -m pytest code/tests -q`. That suite is not implemented yet. The current retrieval script mixes offline checks with live calls; choose the layer deliberately.

## 4. Build a gold evaluation set before tuning RAG

Start with the labeled sample rows and seven retrieval cases. Expand to approximately **60–100 reviewed cases** as a learning target, covering all companies and unknown-company tickets. This is an initial benchmark, not production readiness evidence.

Include FAQs, paraphrases, typos, exact error codes, noisy subjects, long tickets, adjacent product areas, two requests in one ticket, unavailable evidence, company ambiguity, bugs, feature requests, sensitive actions, and malicious instructions. Use redacted examples. Split by underlying intent/article so near-identical paraphrases do not leak across development and held-out sets.

Have a human label decisions before viewing model predictions. Mark ambiguous cases for adjudication. Model-proposed labels need review. Predictions on the unlabeled challenge file are not official gold labels.

For each case record input, answerability, expected status/request type, acceptable product areas, relevant source paths/headings, short supporting excerpts, required facts, forbidden claims, risk tags, and corpus snapshot/hash. Example annotation:

```json
{
  "id": "synthetic-no-evidence-001",
  "split": "development",
  "company": "HackerRank",
  "issue": "Explain a policy absent from the supplied corpus.",
  "answerable": false,
  "expected_status": "escalated",
  "expected_request_type": "product_issue",
  "acceptable_product_areas": ["", "general_support"],
  "relevant_sources": [],
  "required_facts": [],
  "forbidden_claims": ["A definitive invented policy", "A completed account action"],
  "risk_tags": ["missing_evidence"]
}
```

This is a synthetic annotation example, not an official expected row. A relevant article can contain many sections, and the retrieved section may not answer the question. Label **article relevance** and **evidence sufficiency** separately. For multi-part requests, annotate each needed fact.

Keep development cases for experiments, a frozen held-out set for selected candidates, and a separate safety/failure suite. Repeatedly tuning on held-out cases makes them development data; acquire a new independent set.

### Metrics and their meaning

| Metric | Definition | Reveals |
| --- | --- | --- |
| Hit@k | Fraction of answerable queries with an acceptable source among top k | Basic discovery; closest to the current seven-case test |
| Recall@k | Relevant sources retrieved / all labeled relevant sources; average across answerable queries | Coverage when multiple sources are needed |
| MRR@k | Average inverse rank of first relevant result; zero if absent within k | How early useful evidence appears |
| Evidence coverage | Required facts supported by selected context / all required facts | Whether actual chunks support a complete answer |
| Context precision | Relevant selected chunks / all selected chunks | Noise passed to the generator |
| Label quality | Confusion matrices and macro-F1 for status and request type | Class confusions and rare-class failures |
| Escalation recall | Correct escalations / all cases requiring escalation | Risky cases missed |
| Escalation precision | Correct escalations / all emitted escalations | Avoidable human workload |
| Unsupported claim rate | Unsupported factual claims / all evaluated factual claims | Hallucination exposure; track contradictions separately |
| Answer completeness | Required facts correctly communicated / all required facts | Grounded answers that omit the solution |
| Auto-reply coverage | Automatically replied in-scope cases / all in-scope cases | Useful automation; pair with error among auto-replies |
| Contract validity | Schema-valid rows / all output rows | Downstream usability |
| Operations | p50/p95 latency, errors, retries, usage, cost per ticket | Reliability and resource tradeoffs |

Compute document metrics on deduplicated paths and evidence/chunk metrics separately. Exclude no-source cases from retrieval-recall denominators and evaluate their abstention instead. Define behavior for replies with zero factual claims rather than dividing by zero or labeling them perfectly grounded.

**Example:** a question needs A and B but retrieves `[A, C, D]`. Hit@3 is 1, Recall@3 is 1/2, and document Precision@3 is 1/3. A high hit rate can hide an incomplete answer.

Evaluate each factual claim as supported, contradicted, or not evidenced by selected context. Check eligibility, region, prerequisites, dates, and negation. A citation establishes source identity, not entailment. LLM judges can assist with a fixed rubric and supplied evidence, but calibrate them against human reviews and investigate disagreements.

Report numerators/denominators, per-company/risk slices, and uncertainty. Averages can hide poor Visa performance when the corpus is dominated by other companies. Seven passed questions are a smoke check. Compare paired cases before trusting small gains.

## 5. Improve RAG with controlled experiments

Freeze baseline code revision or file hashes, corpus snapshot, model IDs/dimensions, prompt hash, retrieval configuration, dependencies, and evaluation IDs. Save unique run reports. With uncommitted changes, a Git revision alone cannot identify the implementation.

For each experiment: identify a failure, state a hypothesis, change one variable, rerun development cases, inspect fixes/regressions, and record quality/latency/cost. Evaluate the selected candidate on held-out cases. Revert changes with no defensible benefit.

| Experiment | Failure hypothesis | Comparison | Keep when |
| --- | --- | --- | --- |
| Metadata | Evidence arrives without provenance | Bodies vs stable IDs/URL/heading/date | Valid citations improve without changing facts |
| Chunking | Large chunks dilute matching; tiny chunks omit prerequisites | Current vs heading-aware budgets, e.g. 400/800/1,200 tokens | Evidence coverage improves; boundary facts remain |
| Query preparation | Noisy subject dominates similarity | Issue-only vs wrapper vs concise rewrite | Noisy cases improve without losing identifiers |
| Company routing | Unknown/mislabeled company hides docs | Current vs validated inference/scoped fallback | Wrong-domain hits fall without unacceptable recall loss |
| Hybrid retrieval | Dense search misses exact terms/error codes | Dense vs lexical vs fused rankings | Exact-term cases improve; semantic cases stay stable |
| Candidate depth | Relevant section is below top 5 | Candidates 5/10/20; fixed final context budget | Evidence coverage improves within latency budget |
| Diversity | Duplicate chunks crowd out other sources | Current vs grouping/MMR | Multi-source coverage improves without losing same-file steps |
| Reranker | Topical matches outrank answer-bearing sections | Same candidates/budget, with and without reranking | Quality gain justifies added latency and cost |
| Abstention | Unrelated nearest neighbors appear useful | Always top-5 vs calibrated evidence/relevance gate | Unsupported replies fall at acceptable automation coverage |
| Context assembly | Needed evidence is buried in long bodies | Raw bodies vs selected excerpts/prerequisites | Fewer tokens with equal or better complete answers |

### A. Reliable ingestion first

Preserve URL, update time, company/product area, path, heading hierarchy, stable document/chunk IDs, content hash, corpus version, and embedding model identity. Parse enough Markdown structure to preserve tables, lists, code fences, and prerequisites.

Use budgets appropriate to the configured model; honor both tokens and characters where applicable. Suggested chunk sizes are experiments, not universal defaults. Include prefix/separator/overlap cost in final validation. Small complete articles may outperform unnecessary splitting.

Do not permanently exclude release notes, glossaries, or plan tables merely because they can be noisy. Measure whether they contain needed evidence and document inclusion rules. Production needs freshness checks. For challenge evaluation, the provided static corpus remains authoritative; do not silently substitute today's web content.

### B. Add a lexical baseline, then consider fusion

Compare PostgreSQL full-text search over title/headings/body, or BM25, with current dense search. Check exact identifiers because stemming/tokenization can damage error-code matches. See [PostgreSQL full-text search](https://www.postgresql.org/docs/16/textsearch.html).

Reciprocal rank fusion is a transparent way to combine ranked candidates:

```text
RRF(candidate) = sum over ranking lists of 1 / (c + rank(candidate))
```

Use 1-based ranks and zero contribution when absent. `c=60` is an experiment starting point. Fuse on stable chunk IDs and apply access filters to both branches. Rank fusion avoids adding incompatible raw cosine/text-search scores. Rerank the union only if measured failures justify it.

### C. Treat company and product-area metadata carefully

Canonicalize known companies. Explicitly conflicting label/text is its own test case. Unknown company can trigger cautious inference, multi-company search, clarification, or escalation according to the content. “Unknown company means never retrieve” would discard answerable tickets.

Use a reviewed product-area map. The top hit can suggest a label but should not automatically determine it. Evaluate classification separately from retrieval.

### D. Calibrate abstention

The `<=>` operator measures cosine distance; smaller is closer. Distance is **not a probability of correctness**. It varies with model, corpus, query, and chunk strategy. Avoid magic cutoffs without labeled evidence.

Collect best distance, ranking margin, evidence coverage, domain agreement, and answerability labels. Sweep a cutoff/gate on development cases and compare auto-reply coverage with unsupported-answer rate. Choose according to error costs; verify on held-out cases. Recalibrate after model/corpus changes. Risk routing remains separate: a strong match does not authorize an account action.

### E. Assemble evidence deliberately

Retrieve more candidates than you show, select answer-bearing sections, retain necessary neighbors/prerequisites, and attach source IDs such as `[S1]`. Budget instructions, ticket, context, and output reserve against the generation model's context limit. Character caps are only an approximation.

Avoid a blanket one-chunk-per-file rule: a procedure may require several chunks from one article. Conversely, duplicate chunks can crowd out another necessary source. Measure evidence coverage after selection.

Require claim-level source IDs in an internal structured result and validate supplied IDs. Store detailed evidence in a sidecar trace while preserving the five-field challenge output. Resolve approved public links from metadata rather than model-invented URLs. Phone numbers must be present **and applicable** to the region/situation. Matching digit sequences is a rough alarm, not a factual grounding test.

### F. Optimize the database when measurements justify it

Keep exact search as the reference. Measure filtered p95 query latency and plans with `EXPLAIN (ANALYZE, BUFFERS)` in a safe test database. Consider a company index, connection pooling, or HNSW when data and workload justify them.

Compare approximate neighbors to exact neighbors with the same filters. That is index recall, distinct from relevance to human-labeled questions. pgvector documents reduced result counts with filtered approximate searches and iterative scans in supported versions. Verify your installed extension before configuring it. See [pgvector documentation](https://github.com/pgvector/pgvector).

Multiple readers alone do not require managed Postgres. Choose hosting for availability, backup/restore, security, ownership, and workload. This small corpus does not establish a need for a distributed vector database.

## 6. Separate routing, answerability, and writing

These decisions are different:

1. **Request type:** product issue, feature request, bug, or invalid.
2. **Risk/authority:** is handling safe and is the requested action authorized?
3. **Answerability:** does selected evidence support the needed response?
4. **Writing:** explain supported guidance or the next step.

Use a small reviewed policy layer for hard boundaries. A classifier can handle semantic cases if needed; evaluate its labels. Supply the writer with the chosen decision/evidence, then validate consistency. Add a second model call only when measured benefits justify latency/cost.

Keywords alone fail: “How do I reset my password?” differs from “Reset another user's password and bypass verification.” Safe general guidance can accompany escalation of a specific action. Test negation, quoted attacks, multi-intent tickets, and rare risk cases. Use challenge rules/reviewed labels rather than blanket bans on entire topics.

Schema validation protects structure, not truth. Add checks for source support, allowed actions, label consistency, and fabricated commitments. If action tools are introduced later, enforce authenticated authorization, least privilege, idempotency, and auditing outside the model.

## 7. Production practices and failure drills

| Area | Practice | Verification |
| --- | --- | --- |
| Reliability | Explicit SDK/DB timeouts, bounded retries with jitter, ticket deadline | Inject throttles/timeouts; inspect attempts and completion deadline |
| Recovery | Stable IDs, checkpoints, per-ticket failures, atomic export | Stop mid-run/resume; no lost work or duplicate final rows |
| Index lifecycle | Staging version, validated activation, rollback | Change/delete docs and fail a build; old active version stays usable |
| Schema | Migrations, uniqueness, non-null embeddings, compatibility checks | Clean install/upgrade, concurrent builders, invalid inserts |
| Configuration | Validate startup settings, reuse clients/connections | Clear failures; supported runtime versions/settings |
| Credentials | Provider chain, workload roles/temporary credentials, least privilege | Role-based workload runs without static-key env variables |
| Isolation | Server-derived tenant/user filters before retrieval | Unauthorized chunks never reach prompts or caches |
| Privacy | Restricted/redacted traces, retention/deletion policy | Seed fake sensitive values and inspect logs/exports/caches |
| Prompt attacks | Treat both tickets and documents as untrusted; external policy enforcement | Inject attacks via both channels; no secret exposure or unauthorized action |
| Monitoring | Stage timing/errors, evidence IDs, schema/fallback rates | Locate wrong reply and identify its failing stage |
| Performance | Bounded workers/queues, pooling, backpressure | Load test slow dependencies; inspect p95/p99 and queue growth |
| Cost | Usage, attempts, retries, cache hits, per-stage cost | Compare run totals/provider billing including failed work |
| Caching | Versioned model/corpus/prompt keys plus access scope | Changes invalidate stale entries; no cross-user leakage |
| Delivery | Pinned dependencies/Python/image versions, CI, rollback | Reproduce clean install and restore previous release |
| Operations | Owner, incident/runbook, backup and restore drill | A second operator can recover the service |
| Handoff | Real queue/case record with evidence and reason codes | Escalations arrive once and delivery failures are visible |

`bedrock_client.missing_env()` currently requires static AWS key variables. Boto3 supports other credential sources; permit the intended role/provider chain. The adapter does not configure application-specific retry/timeouts or record usage/stop reason. SDK defaults can retry; verify actual behavior rather than assuming no retries. References: [Boto3 credentials](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html), [retry configuration](https://docs.aws.amazon.com/boto3/latest/guide/retries.html).

Compose's default password and exposed database port are development conveniences. Production requires suitable credentials, restricted network access, and deployment-appropriate TLS. `runs/raw/` is not gitignored and may contain customer data. Define retention/access policy and exclude sensitive runtime artifacts from source control. Keep the mandatory challenge conversation log separate and redacted according to `AGENTS.md`.

Never put raw exceptions, credentials, connection details, or provider diagnostics in exported justification. Use safe reason codes such as `retrieval_unavailable` and restricted diagnostics linked by trace ID. Consider spreadsheet formula injection when humans open user-supplied CSV text; keep any sanitized human export separate from evaluator-required data.

Deleting suspicious phrases is insufficient and may erase legitimate attack reports. Use data boundaries, least privilege, source/access controls, policy enforcement, and adversarial evaluations. Optional [Bedrock prompt-attack filters](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-prompt-attack.html) add a layer; they do not prove every attack is blocked.

### Minimal internal trace

Record trace/run ID, stable ticket ID, sanitized input hash, company/decision reason, corpus version, model IDs, prompt version, retrieved IDs/distances, selected evidence IDs, stage timings, retries, usage, validation result, and outcome. Restrict customer text; use IDs/redacted excerpts in routine logs.

This separates source not retrieved, evidence dropped during selection, writer ignoring evidence, and correct response failing export. Without that separation, tuning becomes guesswork.

## 8. A measured learning sequence

Each session should leave an inspectable artifact. Order matters more than calendar duration.

| Session | Work | Deliverable / exit check |
| --- | --- | --- |
| 1. Baseline | Map modules, freeze settings, collect reviewed labels | Reproducible report; no invented quality numbers |
| 2. Output correctness | Input/parser tests and strict validation | Invalid enums/types rejected; all emitted rows valid |
| 3. Failures | Mock embedding, DB, generation, parse/export failures | Valid per-ticket results; completed work retained; duplicate-free resume |
| 4. Ingestion | Budget fixes, metadata, versioned synchronization | Final budget enforced; changed/deleted files handled |
| 5. Retrieval evaluation | Label source/evidence relevance; print ranks | Hit/Recall/MRR, evidence coverage, per-company failure analysis |
| 6. Retrieval experiments | Lexical/dense/fusion and one chunk variation | Paired table; retained changes fix identified cases |
| 7. Grounded writing | Source IDs, claim support, completeness tests | Human-reviewed support; writer tested with gold context |
| 8. Routing/abstention | Semantic/risk cases; calibrated operating point | Coverage/error tradeoff and escalation confusion matrix |
| 9. Operations | Traces, deadlines, checkpoints, isolation/load tests | Failure drill with recovery, latency, and cost evidence |
| 10. Release rehearsal | Clean install, CI, rollback, runbook review | Another person can reproduce, diagnose, and recover |

Suggested learning gates: **100% contract-valid outputs**, zero known access leaks/fabricated completed actions in safety fixtures, recovery preserving completed work, and no material regressions in frozen evaluation slices. A goal such as 90% Hit@5 is provisional, not proof of production readiness. Define actual latency/cost/error budgets from workload requirements and baseline data.

Use this experiment log:

```text
Run ID / code and corpus versions:
Observed failure and case IDs:
Hypothesis:
Single variable changed:
Baseline -> candidate counts/metrics:
Fixed cases / newly broken cases:
Latency and cost difference:
Human review disagreements:
Keep, revise, or revert; reason:
Next experiment:
```

Use ablations to learn causes: lexical vs dense vs fusion; gold vs retrieved context; current vs changed writer on identical evidence. Failure with gold context points toward writing/routing. Success with gold but failure with retrieved context points toward retrieval/selection.

## 9. Reason about architecture and alternatives

Before a classifier, reranker, framework, fine-tune, or additional model call, ask:

- Which labeled failures require it, and what metric should change?
- Does a simpler lexical/policy baseline fix those same cases?
- Is the change learning stable behavior or trying to memorize changing policies?
- What latency, provider dependence, and maintenance does it introduce?
- Can you explain one ticket from input to evidence to every output field?

These are possible approaches, not evidence about other contestants' code/scores. Your vector pipeline is a useful learning foundation. Production quality also requires verified recovery, traceability, access controls, and operational ownership.

For the challenge contract, use `problem_statement.md` and `evalutation_criteria.md`. External references above support engineering practices; they must not become outside evidence for ticket answers restricted to the supplied `data/` corpus.
