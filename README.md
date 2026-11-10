# self-evolving-web-crawler-agent

The self evolving web crawler agent automatically discovers websites, adapts to
different country and regional domains, learns new page layouts, and extracts
relevant information without manually coding each website.

It targets public, legitimate regulatory websites (US Federal Register, UK
Legislation, EU EUR-Lex), uses Claude to extract structured regulatory items from
each page, and uses structural diffing to detect when a site's page layout
changes — which is what "self-evolving" means here: the agent notices and logs a
"learned new layout" event instead of silently breaking. A LangGraph agent loop
also notices when a site is serving a bot-mitigation page instead of real content
(CAPTCHA, access-denied, JS-only shell) and reacts — escalating to a real browser
fetch, or giving up and logging it as blocked — instead of quietly storing an
empty crawl as if it succeeded. It also deduces upcoming regulatory changes
(proposed rules, future effective dates) and stores everything in a local
SQLite database.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,browser,ui]"
.venv/bin/crawl4ai-setup   # only needed for fetch_mode: browser -- installs its Playwright browser
cp .env.example .env   # then set ANTHROPIC_API_KEY
```

## Usage

```bash
.venv/bin/crawler-agent init-db
.venv/bin/crawler-agent crawl --site us_federal_register
.venv/bin/crawler-agent crawl --all
.venv/bin/crawler-agent list-upcoming --country US
.venv/bin/crawler-agent list-layout-events
```

### Dashboard

```bash
.venv/bin/crawler-agent ui
```

Opens a local Streamlit dashboard (`src/crawler_agent/ui/app.py`) at
`http://localhost:8501` for browsing what's been crawled: an overview with
counts per site, deduced upcoming changes, all tracked regulation items
(filterable by country/site/status, with search), the layout-learning
history, and the full change-event log. It reads directly from the same
SQLite database the CLI writes to — run a crawl, then refresh the dashboard
(or click "Refresh data" in the sidebar) to see new results.

Add a new regulatory site without touching code:

```bash
.venv/bin/crawler-agent add-site my_new_site.yaml
```

```yaml
# my_new_site.yaml
id: ca_gazette
name: Canada Gazette
country: CA
base_url: https://gazette.gc.ca
seed_urls:
  - https://gazette.gc.ca/rp-pr/p2/index-eng.html
fetch_mode: http   # or "browser" if the site requires real browser rendering
crawl_interval_hours: 24
```

## How it works

Each seed URL is run through a small LangGraph agent (`crawler_agent/agent/graph.py`)
instead of a fixed fetch-then-extract pipeline:

1. **Fetch** — `crawler_agent/fetch/` polls the page via HTTP, or via
   `BrowserFetcher` (Crawl4AI, which wraps Playwright) for JS-rendered or
   bot-protected pages. `fetch/robots.py` uses `protego` (RFC 9309 compliant)
   to honor `robots.txt` for both fetchers, and the HTTP fetcher rate-limits
   per domain.
2. **Assess** — `agent/assess.py` asks Claude whether the fetched content is
   genuine regulatory content or a bot-mitigation page (CAPTCHA, access-denied,
   empty JS shell). This step exists because real sites don't 404 when they
   don't want to be scraped — they return a 200/202 that looks structurally
   fine but carries no real data.
3. **Escalate or give up** — if the page looks blocked and it was fetched with
   a plain HTTP client, the agent retries with a real browser (bounded to one
   retry). If it's still blocked, it logs an `access_blocked` change event and
   moves on, rather than treating a block page as "zero items this crawl" or
   (worse) as a newly learned layout.
4. **Fingerprint** — `layout/fingerprint.py` computes a structural signature of
   the page's DOM shape (tag/class skeleton, ignoring text), so a content
   update doesn't look like a layout change but a real HTML restructure does.
   `layout/diff.py` logs a `layout_relearned` event the first time a new
   fingerprint appears for a site.
5. **Extract** — `extraction/llm_extractor.py` sends the cleaned page text to
   Claude with a forced structured-output tool call, extracting regulation
   items (title, dates, status, summary).
6. **Detect changes** — `change_detection/detector.py` classifies each
   extracted item as new, updated, or unchanged versus what's stored, and
   flags items with a future effective date or a `proposed`/`upcoming` status
   as deduced upcoming changes.
7. **Store** — everything lands in a local SQLite DB (`db/models.py`): sites,
   layout versions, page snapshots, regulation items, and a change-event log.

### Per-site fetch strategy (discovered by testing against the real sites)

- **US Federal Register** — its `robots.txt` disallows the HTML `/documents/search`
  listing pages, and its access-denied page explicitly tells automated tools to
  use its public JSON API instead. The registry points at that sanctioned
  `/api/v1/documents.json` endpoint — no key required, and it isn't disallowed.
- **UK Legislation / EU EUR-Lex** — plain HTTP requests get an empty `202`
  response from these sites' CDN-level bot mitigation; a real (headless)
  browser renders the actual page, so both are configured with
  `fetch_mode: browser`.

### Content cleaning and markdown

`BrowserFetcher` uses Crawl4AI, which can optionally prune a page's HTML down
to a dense-content-focused markdown before extraction. That pruning filter
is a density heuristic, not currently enabled by default
(`fetch/browser_fetcher.py`'s `select_markdown`, unused by default): tested
against two real EUR-Lex pages, it correctly kept the real per-document rows
on one (a daily-issue listing, where content is dense prose with one link
each) but discarded them on the other (an index page, where the real content
is sparse one-line links and the filter kept denser-but-irrelevant "about
this site" prose instead). Enabling it for a given site needs verifying
extraction quality on that site's actual pages, not assuming the ratio helps
generally. Every browser-fetched page instead goes through
`utils/html_clean.to_text()` by default — the same deterministic cleaner used
for HTTP-fetched pages.

### Known limitations

- **EU EUR-Lex's current seed page** (`direct-access.html`) is an index/hub
  page with no real per-document rows of its own — the actual content lives
  on a dated daily-view page (e.g. `.../daily-view/L-series/default.html?ojDate=09112026`)
  that changes every day, so a static seed URL would go stale. A dynamic
  "resolve today's issue URL" step would fix this but isn't built yet; until
  then, EU extraction occasionally still flags an unchanged item as updated,
  because the only available seed content is ambiguous descriptive prose
  rather than a real listing.
- LLM extraction is not perfectly deterministic in general. Change detection
  (`change_detection/detector.py`) only hashes material fields (title, status,
  dates, document type) — not free-text summary — and normalizes trailing
  punctuation on titles, specifically so that harmless extraction variance
  doesn't get logged as a false "updated" event. US Federal Register and UK
  Legislation have been verified stable (zero false updates) across repeated
  crawls; EU has not, for the reason above.

## Tests

```bash
.venv/bin/pytest
```

Fingerprinting, change-detection, and the agent's fetch/assess/escalate routing
are all tested with local fixtures and fakes — no network or LLM calls
required.
