# results/

Everything a pipeline run writes goes here, and nowhere else. Only this README is
tracked by git; the run files are ignored.

| File | What it is |
|---|---|
| `results.jsonl` | One line per email, written as each one finishes. The full detail: verdict, per-field mismatches, and `field_issues` (why a field went to a human, with the evidence). `?resume=true` continues from this file. |
| `output.json` | The submission: one object per `email_id`, in the shape of `data/sample_submission.json`. This is the file you score or submit. |
| `classify_cache.json` | The same verdicts plus each email's classification confidence, for tuning the threshold offline. |
| `*.sample.*` | The same three files from a limited run (`POST /run?limit=N`). Kept apart so a small test run can never overwrite a full one. |

`web/report.json` is the one output that lives elsewhere: the dashboard is a static page
served from `web/`, so it reads its data from there. Build it from these files with
`python web/build_report.py` (or `--sample`).

## Reading a run

Each record has a `status`:

- `OK`: all 7 fields match.
- `MISMATCH`: at least one field differs (`defect_fields` says which).
- `NEEDS_REVIEW`: the system would not guess. `review_reason` says why.

**If every record says `NEEDS_REVIEW` with `processing_error`, nothing was actually
checked.** That reason means the model API call failed, usually because the free-tier daily
quota ran out. It is not a verdict on any document. Fix the cause (another model, a new day,
a paid key) and re-run with `?resume=true`, which retries only the failed emails.

## Starting fresh

Delete the files in this folder, or run without `?resume=true`, which starts over.
