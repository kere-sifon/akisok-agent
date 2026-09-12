# Akisok curation agent

Deterministic LangGraph pipeline that **discovers** items with Bedrock native tool calling against a web search API (Tavily), classifies and drafts short posts, runs guardrails, and writes drafts to MongoDB Atlas as `pending` or `flagged`.

Flagged items are **never dropped** — they only need extra scrutiny. Review happens in a local FastAPI admin UI. Approve updates Mongo and calls `publish_item()`, which writes MDX into the `akisok-site` repo, commits, and pushes (Vercel rebuilds from `main`).

```
discover → classify → draft → guardrail_check → queue → record_run
                                 │
                                 ├── review_queue (pending | flagged | approved | rejected)
                                 ├── pipeline_runs (one doc per pipeline execution)
                                 └── quality_evals (one doc per quality-eval CLI run)
```

Publish is one item, one commit, one push per Approve. Approval in Mongo still succeeds if publish fails.

## Setup

Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` (no secrets or model IDs belong in code):

| Variable | Purpose |
| --- | --- |
| `AWS_REGION` | Bedrock Runtime region |
| `BEDROCK_MODEL_ID` | Claude model ID on Bedrock |
| `EMBEDDING_MODEL_ID` | Titan Embed Text (or compatible) model ID |
| `MONGODB_URI` | Atlas connection string |
| `MONGODB_DB_NAME` | Database name |
| `SEARCH_API_KEY` | Tavily API key used by `web_search` |
| `MAX_SEARCH_CALLS_PER_RUN` | Hard cap on search tool calls (default `10`) |
| `RELEVANCE_THRESHOLD` | Minimum score to draft (default `0.6`) |
| `REPRODUCTION_OVERLAP_THRESHOLD` | 8-gram overlap ratio that flags a draft (default `0.15`) |
| `DEDUP_SIMILARITY_THRESHOLD` | Vector similarity that flags a likely duplicate (default `0.92`) |
| `DEDUP_LOOKBACK_DAYS` | How far back `dedup_embeddings` is searched (default `14`) |
| `ADMIN_UI_PORT` | Local uvicorn port for the review UI (default `8001`) |
| `CONTENT_REPO_PATH` | Local checkout of `akisok-site` (required for real publishing), e.g. `/Users/you/dev/akisok-site` |
| `SEED_LGA_ROTATION_SIZE` | How many LGA names to offer per run (default `3`). Cycles through `lga_names` across runs. |
| `IMAGE_MODEL_ID` | Bedrock image model (default `stability.stable-image-core-v1:1`) |
| `IMAGE_MODEL_REGION` | Region for image generation only (default `us-west-2`; other Bedrock calls stay on `AWS_REGION`) |
| `CLOUDINARY_CLOUD_NAME` / `CLOUDINARY_API_KEY` / `CLOUDINARY_API_SECRET` | Upload API credentials for per-post images |

Discovery angles live in `config/seed_queries.yaml`. Put always-on topics under `evergreen`. Put the 31 LGAs under `lga_names` — each run offers every evergreen query plus the next rotation slice, not all LGAs at once.

IAM for Bedrock is sketched in `terraform/` (`main.tf`, `variables.tf`, `outputs.tf`). Atlas Vector Search is documented in `terraform/mongo.tf` (manual index step below).

## Run the pipeline once

From the repo root, with a valid `.env`:

```bash
python -m src.graph.pipeline
```

That run:

1. Asks Claude to pick seed queries and call `web_search` (Tavily), up to `MAX_SEARCH_CALLS_PER_RUN`.
2. Accepts the model’s `submit_candidates` list, drops URLs already in `review_queue`, then drops bare homepage/root URLs (`https://example.com` / `https://example.com/` with no further path). Category, tag, and other index paths are not filtered yet. Title-based heuristics are not used.
3. Classifies each new item (`pillar`, optional `lga`, `relevance_score`).
4. Drafts 150–400 word original posts for items at or above `RELEVANCE_THRESHOLD`.
5. Runs four guardrail checks (below) and sets `status` to `pending` or `flagged`.
6. Inserts every drafted item into `review_queue` and stores its embedding in `dedup_embeddings`.

Skipped before queue: already-queued URLs, bare homepage/root URLs, low-relevance items, and drafts without a valid `source_url`. Guardrail flags never skip an item.

## Running the admin UI locally

```bash
source .venv/bin/activate
uvicorn src.admin.main:app --reload --port "${ADMIN_UI_PORT:-8001}"
```

Use the project venv (not a global/conda `uvicorn`). Form routes need `python-multipart`, which is in `requirements.txt`.

Open `http://127.0.0.1:8001`. Tabs: Status (`/`), Eval scores (`/eval-scores`), Cost (`/cost`), Review queue (`/queue`). The queue lists `flagged` items first. On an item you can:

- **Save edit** — updates `draft_text` and `edited_at`; status stays the same
- **Approve** — sets `status=approved` and `approved_at`, then calls `publish_item()` (see below)
- **Reject** — sets `status=rejected`, `rejected_at`, and `rejection_reason` (stored even if blank)

There is no login. Run this only on localhost or behind your own network control.

`guardrail_details` is the full per-check payload for editors, not just flag names.

## Publishing to akisok-site

Set `CONTENT_REPO_PATH` to a local git checkout of `akisok-site`. On Approve, `publish_item()`:

1. Writes `content/posts/{slug}.mdx` with YAML front matter (`title`, `pillar`, `lga`, `date`, `image`, `source_name`, `source_url`) and `draft_text` as the body.
2. Slug is kebab-case of the title; collisions get `-2`, `-3`, …
3. `image` is a unique Cloudinary key (`akisok/{slug}`) generated at approve time via Stable Image Core (`us-west-2`) + Cloudinary Upload API. If generation or upload fails, it falls back to `pillar-{pillar}`. If the Mongo item already has `image_key`, that key is reused and nothing is regenerated.
4. Runs `git add`, `git commit -m "Add post: {title}"`, then `git pull --rebase` and `git push` **only if a remote is configured**.
5. A Vercel project attached to `akisok-site` `main` rebuilds from the push.

If `CONTENT_REPO_PATH` is unset, missing, or not a git repo, publish returns `{"published": False, "reason": "content repo not configured"}` and does not raise. Git step failures return `{"published": False, "reason": "..."}`; a successful local commit with a failed push is left in place for a later retry. Mongo approval still succeeds.

The public site is `https://akisok-site.vercel.app` from `kere-sifon/akisok-site` **`main`**. This agent never talks to Vercel. Approve writes MDX, commits, and `git push`es the **currently checked-out branch** of `CONTENT_REPO_PATH`. For the live site to update, that checkout must be on `main` with `origin` = `https://github.com/kere-sifon/akisok-site.git`, and Vercel must have the same Cloudinary server env vars as the site repo (`CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`) so `akisok/{image key}` resolves at build time.

## Guardrails

| Check | Flag | Behavior |
| --- | --- | --- |
| Source link | `broken_source_link` | HTTP GET (5s timeout). Non-2xx or network failure. Page text is reused for reproduction. |
| Reproduction | `high_reproduction_overlap` | 8-word shingle overlap vs fetched source. Skipped (not failed) if the fetch produced no text. |
| Near-duplicate | `likely_duplicate` | Titan embedding + Atlas `$vectorSearch` on `dedup_embeddings` for the last `DEDUP_LOOKBACK_DAYS`. |
| Sensitive topic | `sensitive_topic` | Bedrock tool call. Reason stored in `guardrail_details.sensitive_topic.reason`. |

`guardrail_flags` is the list of flag names that tripped. `guardrail_details` holds the full per-check payload for a future admin UI.

After the checks, the draft embedding is **always** inserted into `dedup_embeddings`, flagged or not.

## Atlas Vector Search index (manual)

Create this once before live duplicate checks will work. Tests do not need it.

1. In Atlas: Database → Search / Vector Search → Create Search Index.
2. Collection: `<MONGODB_DB_NAME>.dedup_embeddings`.
3. Index name: `dedup_embeddings_index`.
4. Definition:

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 1024,
      "similarity": "cosine"
    },
    { "type": "filter", "path": "created_at" }
  ]
}
```

Titan Text Embeddings V2 defaults to 1024 dimensions. A commented `mongodbatlas_search_index` sketch lives in `terraform/mongo.tf`.

## Tests

```bash
pytest
```

Bedrock, embeddings, `web_search`, HTTP fetches, and MongoDB (including `$vectorSearch`) are injected as fakes. Publish tests use a temporary local git repo and never push to a network remote.

## Architecture

| Node | Role |
| --- | --- |
| `discover` | Bedrock + `web_search` tool, then URL dedup against `review_queue` and a root-URL homepage filter |
| `classify` | One Bedrock tool call per item |
| `draft` | One Bedrock tool call per relevant item; skip invalid source URLs |
| `guardrail_check` | Link, reproduction, vector dedup, sensitive topic |
| `queue` | Insert `pending` or `flagged` review documents |
| `record_run` | Write one `pipeline_runs` cost/count summary (also on crash via `finally`) |

The admin app in `src/admin/` is separate from the graph. `publish_item()` writes MDX into `CONTENT_REPO_PATH` and never raises; route tests still mock it.

## Ops: cost and eval CLIs

Each pipeline run writes one `pipeline_runs` document (`run_id`, stage counts, per-model `token_usage`, `estimated_cost_usd`). Approve-time Stable Image Core images are billed per image (`PRICING_USD_PER_IMAGE`, currently $0.03) and stored in `image_generation_costs` — they are not part of the original discovery run. The Cost tab and `cost_report` CLI add those rows into the monthly total. Pricing lives in `src/ops/pricing.py`. Override without a code change via `PRICING_OVERRIDE_JSON` (token rates, or `{"model-id": {"per_image": 0.03}}`).

```bash
python -m src.ops.cost_report --month 2026-09
python -m src.ops.eval_quality --sample-size 20 --days 30
python -m src.ops.eval_guardrails --min-samples 20
```

`eval_quality` samples recent `review_queue` drafts, scores them with a Bedrock rubric, and appends a `quality_evals` document. `eval_guardrails` compares `guardrail_flags` to human `approved`/`rejected` decisions and prints precision/recall (with a warning if the decided sample is small).

`src/graph/pipeline.py` compiles a linear `StateGraph`. Clients are passed in through `PipelineDeps` so the same graph can run against live services or mocks.
