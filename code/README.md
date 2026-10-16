# Ticket pipeline

Reads support tickets, embeds each ticket with Titan, retrieves support chunks from pgvector, and sends the selected context to Amazon Bedrock with a triage prompt. It saves the exact model text and writes the parsed fields to the answer sheet.

For component test plans, verified gaps, RAG evaluation metrics, and a production learning roadmap, see [potential_improvements.md](../potential_improvements.md).

## Setup

From the repository root:

```bash
pip install -r code/requirements.txt
```

Copy credentials into `.env` in the repository root (never commit that file):

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `BEDROCK_MODEL`

## Run

One sample ticket:

```bash
python code/main.py --limit 1
```

More rows, or the unlabeled exam file:

```bash
python code/main.py --limit 10
python code/main.py --input support_tickets/support_tickets.csv --limit 5
```

Each run replaces `support_tickets/output.csv` with only the rows from that run. The exact model text for row 1 is `runs/raw/0001.txt`.

## Local database

Postgres with pgvector runs as the only service in `docker-compose.yml`. Data is kept in the `pgdata` volume. The host port is `5432`.

```bash
docker compose up -d
pip install -r code/requirements.txt
python code/db.py
```

The app connects with `DATABASE_URL`. If that variable is unset, it uses `postgresql://support:support@localhost:5432/support`, which matches the compose defaults.

The `chunks` table is empty until an embedding step fills it. Each row holds the article text plus a `vector(1024)` from `BEDROCK_EMBEDDING_MODEL`. The ticket pipeline queries this table, so populate it before processing tickets.

## Chunking

`code/chunking.py` reads `data/` and splits articles. An article of 8,000 characters or less stays one piece. Longer articles split on `##` headings. A section that is still longer splits on paragraphs and repeats the last 200 characters. Release notes are skipped. The title and heading are placed at the top of each piece so a later embedding call can use `Chunk.body` as-is.

```bash
python code/chunking.py
```

## Embedding

`code/index_chunks.py` sends each chunk to `BEDROCK_EMBEDDING_MODEL` and stores the 1,024 numbers in `chunks`. A later run skips text that is already stored. `--rebuild` deletes the rows and starts over.

```bash
python code/index_chunks.py
```

## Retrieval check

`code/test_retrieval.py` checks the chunking rules, then embeds seven hardcoded questions and checks that an expected article is in the top results.

```bash
python code/test_retrieval.py
```

The ticket command embeds the ticket, retrieves the nearest chunks for that company, and places those documents in the prompt before the model answers.

## Regression question dataset

`support_tickets/regression_questions.json` contains 30 candidate questions grounded in 10 supplied articles: 10 questions per company and five per category. There are 25 answerable cases and five cases that are unanswerable from their designated source document. The companion `regression_questions.schema.json` defines the JSON structure; no evaluation schema was supplied in the request.

Each answerable case includes an expected answer, supporting facts, exact source quotations, heading paths, line numbers, and character spans. The manifest records content hashes for the normalized source text. Offsets count Unicode code points, start at zero, and exclude the end position. Normalize source line endings to LF before matching. These spans let a retrieval experiment check coverage of the required evidence across arbitrary chunk boundaries. Article paths remain the document IDs used by the current retriever.

Run the local data-integrity check from the repository root (Node.js 18 or later; no dependencies, credentials, database, or network required):

```text
node code/validate_regression_dataset.mjs
```

The check verifies counts, IDs, source hashes, exact quotations, source locations, and answerability fields. It does not run retrieval or measure model quality. For answerable cases, measure evidence coverage and answer correctness separately. For unanswerable cases, measure abstention and explanation of missing information; the associated article is contextual and is not a required retrieval hit. Keep this dataset and its expected answers outside the retrieval index. The labels reflect the supplied corpus snapshot, and answerability is scoped to the individual source document, not the whole corpus.
