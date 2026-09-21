# results/

Everything a pipeline run writes goes here, and nowhere else. Only this README is
tracked by git; the run files are ignored.

| File | What it is |
|---|---|
| `results.jsonl` | One line per email, written as each one finishes. The full detail: verdict, one-line `summary`, every value read from the SI and BL (`extracted`), per-field mismatches, and `field_issues` (why a field went to a human, with the evidence). `?resume=true` continues from this file. Always written, whether or not MongoDB is used. |
| `output.json` | The submission: one object per `email_id`, in the shape of `data/sample_submission.json`. This is the file you score or submit. |
| `classify_cache.json` | The same verdicts plus each email's classification confidence, for tuning the threshold offline. |
| `*.sample.*` | The same three files from a limited run (`POST /run?limit=N`). Kept apart so a small test run can never overwrite a full one. |

If `MONGODB_URI` is set, every record in `results.jsonl` is also copied into the `results` collection of your MongoDB (and each run into `runs`), and the web app reads from there. The file stays as the crash-safe checkpoint, so a database that is down never loses a run.

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

## Adding emails, and starting fresh

Three ways to run again, from safest to most destructive:

- **New emails only:** `POST /run?new_only=true` (the **Run N new** button). It processes only
  the emails that have no saved result, such as ones you added to the inbox since the last run,
  and leaves every saved result alone, failed ones included. Nothing already done goes back
  through the model.
- **Resume:** `POST /run?resume=true` (**Retry N**). Skips what finished, retries what failed,
  and does any new emails.
- **Start over:** `POST /run` (**Start over**). Replaces `results.jsonl` and runs every email
  again. Before it does, it copies the old file to `results.jsonl.<timestamp>.bak`, but only if
  it holds at least one real verdict, so a run of failures never pushes a good backup out. The
  backups are ignored by git; delete them when you no longer want them. If MongoDB is used, its
  copy of the results is replaced too; the `.bak` file is the copy to restore from.
