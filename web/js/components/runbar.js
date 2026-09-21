import { add, h, clear, announce } from "../util/dom.js";
import { icon } from "../util/icons.js";

const POLL_MS = 2000;

/**
 * The small run control in the header: what the pipeline is doing, and buttons to
 * retry the emails that failed on the model API, or to run everything.
 * Deliberately compact; what it should offer is still to be confirmed.
 */
export function mountRunbar(host, { api, getReport, onDone }) {
  let status = null;
  let busy = false;
  let message = "";
  let timer = null;

  const running = () => busy || Boolean(status?.running);

  async function poll() {
    try {
      const wasRunning = running();
      status = await api.status();
      if (!running() && wasRunning) {
        stop();
        announce("The run finished.");
        await onDone();
      }
    } catch { /* the next tick will try again */ }
    render();
  }

  function start() {
    if (!timer) timer = setInterval(poll, POLL_MS);
  }
  function stop() {
    clearInterval(timer);
    timer = null;
  }

  async function launch(options) {
    message = "";
    busy = true;
    start();
    render();
    try {
      const result = await api.run(options);
      if (result?.stopped) {
        message = `Stopped after ${result.emails_processed} emails. Continue picks up the rest.`;
        announce("The run stopped.");
      } else {
        announce("The run finished.");
      }
    } catch (err) {
      message = err.status === 409 ? "A run is already in progress." : err.message;
    }
    busy = false;
    status = await api.status().catch(() => status);
    if (!running()) stop();
    await onDone();
    render();
  }

  function retryFailed() {
    const report = getReport();
    launch({ resume: true, limit: report?.scope === "sample" ? report.summary.total : null });
  }

  async function stopRun() {
    message = "";
    try {
      await api.stop();
      status = { ...status, stopping: true };
      announce("Stopping after the emails already being processed.");
    } catch (err) {
      message = err.message;
    }
    render();
  }

  function continueRun() {
    launch({ resume: true, limit: null });
  }

  function runAll() {
    const total = getReport()?.summary?.inbox_total ?? "all";
    if (confirm(`Run the pipeline on ${total} emails? This uses model quota.`)) launch({ resume: false });
  }

  function render() {
    clear(host);
    if (api.mode === "static") {
      add(host, h("span", { class: "dot demo" }), h("span", {}, "Demo, read-only"));
      return;
    }
    const summary = getReport()?.summary ?? {};
    const failed = summary.failed ?? 0;
    // emails a stopped or interrupted full run has not reached yet
    const left = getReport()?.scope === "full" && summary.total > 0 ? Math.max(0, (summary.inbox_total ?? 0) - summary.total) : 0;
    const label = status?.stopping
      ? "Stopping…"
      : running()
        ? status?.total ? `Running ${status.processed ?? 0} of ${status.total}` : "Running"
        : "Idle";
    add(
      host,
      h("span", { class: `dot${running() ? " running" : ""}` }),
      h("span", { role: "status" }, label),
      running()
        ? h("button", { class: "icon-btn stop", type: "button", title: "Stop after the emails already being processed. What has finished is kept.", disabled: status?.stopping ? true : null, onclick: stopRun }, icon("stop"), "Stop")
        : null,
      !running() && left > 0
        ? h("button", { class: "icon-btn", type: "button", title: "Carry on with the emails this run has not reached yet, and retry any that failed", onclick: continueRun }, icon("play"), `Continue ${left}`)
        : null,
      !running() && left === 0 && failed > 0
        ? h("button", { class: "icon-btn", type: "button", title: "Retry the emails that failed on the model API", onclick: retryFailed }, icon("refresh"), `Retry ${failed}`)
        : null,
      !running()
        ? h("button", { class: "icon-btn", type: "button", "aria-label": "Run the pipeline", title: "Run the pipeline", onclick: runAll }, icon("play"))
        : null,
      message ? h("span", { class: "muted" }, message) : null,
    );
  }

  (async () => {
    try { status = await api.status(); } catch { /* shown as idle */ }
    if (status?.running) start();
    render();
  })();

  return { render, refreshStatus: poll };
}
