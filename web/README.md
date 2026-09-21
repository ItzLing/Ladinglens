# Ladinglens web

Static review UI over a completed pipeline run. No build step, no dependencies --
`index.html` fetches `report.json` at runtime.

## Regenerate the data

`report.json` is built from `results.jsonl` (the run checkpoint) joined with the
inbox records, so it carries the per-field SI/BL values that `output.json` drops.

```bash
python web/build_report.py     # from the repo root, after a run
```

Re-run this after every pipeline run, then redeploy.

## Preview locally

```bash
cd web && python -m http.server 8777
# open http://localhost:8777
```

Opening `index.html` directly off the filesystem will not work -- the `fetch`
of `report.json` needs to be served over http.

## Deploy to Vercel

Static hosting, no framework:

1. Import the repo at [vercel.com/new](https://vercel.com/new).
2. Set **Root Directory** to `web`.
3. Framework preset: **Other**. Leave build & output settings empty.

`report.json` must be committed for the deploy to serve it -- there is no build
step to generate it.

## Note on what gets published

`report.json` embeds dataset content: email subjects, senders, body excerpts and
the SI/BL document text. It contains no ground truth. Deploying makes that
content publicly readable by anyone with the URL.
