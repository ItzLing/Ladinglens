# Ladinglens web

## What you are looking at

Start the app (`uvicorn app.main:app` from the repo root, then <http://localhost:8000>)
and the left rail has four tabs:

| tab | what it shows |
|---|---|
| **Home** | the run at a glance: how many emails, how they were classified, how many mismatches, how many went to a person |
| **Parsing** | how each attachment was read -- plain text, PDF, Word, Excel, or a scan that needed OCR or a vision model |
| **Review** | the human-in-the-loop queue: emails the system would not decide on its own, with the reason and the source evidence, where a person can correct a field or delegate the case |
| **Report** | every email, filterable. Open one to see the **SI and BL values side by side**, with the differing fields marked, and the source documents underneath |
| **Database** | the MongoDB collections behind it, when a database is configured |

The Report tab is the one that answers the brief: pick any email marked *Mismatch* and it
shows exactly which of the seven shipment fields disagree, what each document said, and the
text those values came from.

The UI: plain JavaScript (ES modules) and CSS, no build step and no dependencies. The plan
and design are in [`DESIGN.md`](DESIGN.md).

It runs in two modes, chosen automatically when the page loads:

- **Live**, when the FastAPI app is running (`uvicorn app.main:app`, then
  <http://localhost:8000>). It reads from `/api`, and can retry emails and start runs.
- **Read-only demo**, when there is no API. It reads `report.json` instead. This is what a
  static host such as Vercel serves.

```
index.html          the shell
css/                tokens (light and dark), base, layout, components
js/main.js          start-up, hash router, keyboard
js/api.js           the live adapter and the static adapter, one interface
js/store.js         list filtering, sorting, counts, banners (pure, unit-tested)
js/views/           home, parsing, report, data (the Database tab), soon (Review)
js/components/      rail, run control, chips, the field table and documents
js/util/            dom helpers, icons, the word diff, formatting
report.json         the demo data
build_report.py     builds report.json
```

## Regenerate the demo data

`report.json` is built by asking the app's own API functions for the report and for every
case, so the demo shows what the running app shows. It reads from MongoDB if that is
configured, otherwise from `results/`.

```bash
python web/build_report.py            # the full run, else the latest limited run
python web/build_report.py --sample   # the latest limited run
```

Re-run this after a pipeline run, then commit and redeploy. The file that is checked in was
converted from an older 520-email run, so it has no email summaries and only records the
fields that differ; rebuild it after the next full run.

## Preview locally

The live app: `uvicorn app.main:app` from the repo root, then open <http://localhost:8000>.

The read-only demo, exactly as a static host serves it:

```bash
cd web && python -m http.server 8777
# open http://localhost:8777
```

Opening `index.html` straight from the filesystem will not work: modules and `fetch` need
http.

## Tests

The pure modules (the word diff, list filtering, routing, and the API adapters) are tested
with Node's built-in runner. From the repo root:

```bash
node --test "tests/js/*.test.js"
```

`js/package.json` (`{"type": "module"}`) is what lets Node load the browser modules; browsers
ignore it.

## Deploy to Vercel

Static hosting, no framework:

1. Import the repo at [vercel.com/new](https://vercel.com/new).
2. Set **Root Directory** to `web`.
3. Framework preset: **Other**. Leave build & output settings empty.

`report.json` must be committed for the deploy to serve it; there is no build step to
generate it. The deployed page is the read-only demo: retrying, running, and the Database tab
need the live app.

## Note on what gets published

`report.json` embeds dataset content: email subjects, senders, bodies and the SI/BL document
text. It contains no ground truth. Deploying makes that content publicly readable by anyone
with the URL.
