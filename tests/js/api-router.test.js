import test from "node:test";
import assert from "node:assert/strict";
import { ApiError, createApi } from "../../web/js/api.js";
import { parseRoute, routeHash } from "../../web/js/router.js";
import { categoryLabel, formatConfidence, plural } from "../../web/js/util/format.js";

const ok = (body) => ({ ok: true, status: 200, json: async () => body });
const fail = (status, body) => ({ ok: false, status, json: async () => body });

test("routes parse to a tab and an optional case", () => {
  assert.deepEqual(parseRoute(""), { tab: "home", id: null });
  assert.deepEqual(parseRoute("#/"), { tab: "home", id: null });
  assert.deepEqual(parseRoute("#/parsing"), { tab: "parsing", id: null });
  assert.deepEqual(parseRoute("#/parsing/email_004"), { tab: "parsing", id: "email_004" });
  assert.deepEqual(parseRoute("#/review"), { tab: "review", id: null });
  assert.deepEqual(parseRoute("#/data"), { tab: "data", id: null });
  assert.deepEqual(parseRoute("#/nonsense/x"), { tab: "home", id: null });
});

test("only the Parsing tab carries a case ID", () => {
  assert.deepEqual(parseRoute("#/report/email_004"), { tab: "report", id: null });
});

test("routes round-trip, including awkward IDs", () => {
  for (const [tab, id] of [["home", null], ["parsing", null], ["parsing", "email_004"], ["parsing", "a b/c"], ["data", null]]) {
    assert.deepEqual(parseRoute(routeHash(tab, id)), { tab, id });
  }
});

test("the live API is used when the server answers", async () => {
  const api = await createApi(async () => ok({ version: "0.0.1" }));
  assert.equal(api.mode, "live");
});

test("the static report is used when there is no server", async () => {
  for (const fetchFn of [async () => { throw new TypeError("network"); }, async () => fail(404, {})]) {
    assert.equal((await createApi(fetchFn)).mode, "static");
  }
});

test("live requests are built with the right URLs and methods", async () => {
  const calls = [];
  const api = await createApi(async (url, options) => { calls.push([url, options?.method ?? "GET"]); return ok({}); });
  calls.length = 0;
  await api.report("sample");
  await api.caseFor("email_004", "full");
  await api.retry("email_004");
  await api.run({ limit: 5, resume: true });
  await api.run();
  await api.dbDocs("results", { emailId: "email_004", limit: 10, skip: 20 });
  assert.deepEqual(calls, [
    ["api/report?scope=sample", "GET"],
    ["api/emails/email_004?scope=full", "GET"],
    ["api/emails/email_004/retry?scope=auto", "POST"],
    ["run?resume=true&limit=5", "POST"],
    ["run?resume=false", "POST"],
    ["api/db/collections/results?limit=10&skip=20&email_id=email_004", "GET"],
  ]);
  assert.equal(api.pageUrl("email_003", "SI", 2), "api/emails/email_003/documents/SI/pages/2.png");
});

test("a failed request carries the server's reason", async () => {
  let live = true;
  const api = await createApi(async () => (live ? ok({}) : fail(409, { detail: "a run is already in progress" })));
  live = false;
  await assert.rejects(api.run(), (e) => e instanceof ApiError && e.status === 409 && /already in progress/.test(e.message));
});

test("a network failure is reported in plain words, not as a raw exception", async () => {
  let live = true;
  const api = await createApi(async () => { if (live) return ok({}); throw new TypeError("Failed to fetch"); });
  live = false;
  await assert.rejects(api.status(), (e) => e.status === 0 && !/Failed to fetch/.test(e.message));
});

const REPORT = { version: "0.0.1", generated_at: "t", summary: {}, emails: [{ email_id: "e1" }], cases: { e1: { record: {} } } };

test("the static adapter serves the report and cases from report.json, once", async () => {
  let fetches = 0;
  const api = await createApi(async (url) => {
    if (url === "api/status") return fail(404, {});
    fetches++;
    return ok(REPORT);
  });
  assert.equal((await api.report()).emails.length, 1);
  assert.deepEqual(await api.caseFor("e1"), { record: {} });
  assert.equal((await api.status()).storage, "static");
  assert.equal(fetches, 1);
  await assert.rejects(api.caseFor("nope"), (e) => e.status === 404);
});

test("the static adapter refuses anything that needs the app", async () => {
  const api = await createApi(async () => { throw new TypeError("x"); });
  await assert.rejects(api.run(), /read-only demo/);
  await assert.rejects(api.retry("e1"), /read-only demo/);
  assert.equal(api.pageUrl("e1", "SI", 1), null);
  assert.equal((await api.dbStatus()).backend, "static");
});

test("formatting helpers", () => {
  assert.equal(categoryLabel("BL_COMPARISON"), "BL comparison");
  assert.equal(categoryLabel("WHATEVER"), "WHATEVER");
  assert.equal(categoryLabel(undefined), "Unknown");
  assert.equal(formatConfidence(0.98), "0.98");
  assert.equal(formatConfidence(1), "1.00");
  assert.equal(formatConfidence(null), "—");
  assert.equal(formatConfidence(NaN), "—");
  assert.equal(plural(1, "mismatch", "mismatches"), "1 mismatch");
  assert.equal(plural(3, "email"), "3 emails");
});
