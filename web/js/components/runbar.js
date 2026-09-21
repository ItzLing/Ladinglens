import { add, h, clear, announce } from "../util/dom.js";
import { icon } from "../util/icons.js";
import { runPlan } from "../store.js";

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
      if (result?.backup_path) {
        const kept = String(result.backup_path).split(/[\\/]/).pop();
        message = `${message ? `${message} ` : ""}Previous results kept in ${kept}.`;
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

  // only the emails with no saved result; everything saved, failed ones included, is left alone
  function runNew() {
    launch({ newOnly: true, limit: null });
  }

  function runAll() {
    if (confirm(runPlan(getReport()).startOver)) launch({ resume: false });
  }

  function render() {
    clear(host);
    if (api.mode === "static") {
      add(host, h("span", { class: "dot demo" }), h("span", {}, "Demo, read-only"));
      return;
    }
    const { left, failed } = runPlan(getReport());
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
        ? h("button", { class: "icon-btn", type: "button", title: "Process only the emails with no saved result yet: new ones, or ones a stopped run did not reach. Everything saved, failed ones included, is left alone.", onclick: runNew }, icon("play"), `Run ${left} new`)
        : null,
      !running() && failed > 0
        ? h("button", { class: "icon-btn", type: "button", title: "Retry the emails that failed on the model API. Also processes any new emails.", onclick: retryFailed }, icon("refresh"), `Retry ${failed}`)
        : null,
      !running()
        ? h("button", { class: "icon-btn", type: "button", "aria-label": "Start over: run every email again", title: "Start over: run every email again. Replaces the saved results, keeping a backup copy.", onclick: runAll }, icon("refresh"), "Start over")
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
