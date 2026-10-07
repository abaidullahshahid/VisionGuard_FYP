import { spawn } from "node:child_process";
import { access, mkdtemp, rm } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const APP_URL = process.env.VISIONGUARD_FRONTEND_URL || "http://localhost:3000";
const TARGET_PREFIX = process.env.VISIONGUARD_INCIDENT_PREFIX || "3401ddd1";
const TOKEN = process.env.VISIONGUARD_TEST_TOKEN;
const ADMIN_TOKEN = process.env.VISIONGUARD_ADMIN_TOKEN;
const WORKER_TOKEN = process.env.VISIONGUARD_WORKER_TOKEN;

const chromeCandidates = [
  process.env.CHROME_PATH,
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
].filter(Boolean);

async function findChrome() {
  for (const candidate of chromeCandidates) {
    try {
      await access(candidate);
      return candidate;
    } catch {
      // Try the next installed Chromium browser.
    }
  }
  throw new Error("Chrome or Edge was not found. Set CHROME_PATH and retry.");
}

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function poll(url, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return response.json();
    } catch {
      // Chrome is still starting.
    }
    await delay(200);
  }
  throw new Error(`Timed out waiting for ${url}`);
}

function createCdpClient(webSocketUrl) {
  const socket = new WebSocket(webSocketUrl);
  const pending = new Map();
  let nextId = 1;

  const ready = new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) return;
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error.message));
    else resolve(message.result);
  });

  async function send(method, params = {}) {
    await ready;
    return new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject });
      socket.send(JSON.stringify({ id, method, params }));
    });
  }

  return { send, close: () => socket.close() };
}

async function main() {
  if (!TOKEN) {
    throw new Error("VISIONGUARD_TEST_TOKEN must contain a real Officer JWT.");
  }
  const chromePath = await findChrome();
  const port = await freePort();
  const profilePath = await mkdtemp(path.join(os.tmpdir(), "visionguard-ui-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profilePath}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-gpu",
    "--no-proxy-server",
    "about:blank",
  ], { windowsHide: true, stdio: "ignore" });

  let client;
  try {
    await poll(`http://127.0.0.1:${port}/json/version`);
    const pages = await poll(`http://127.0.0.1:${port}/json/list`);
    const page = pages.find((entry) => entry.type === "page");
    if (!page) throw new Error("Chrome did not expose a page target.");

    client = createCdpClient(page.webSocketDebuggerUrl);
    await client.send("Page.enable");
    await client.send("Runtime.enable");

    const evaluate = async (expression) => {
      const result = await client.send("Runtime.evaluate", {
        expression,
        awaitPromise: true,
        returnByValue: true,
      });
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
      return result.result.value;
    };

    const navigate = async (route, readyText) => {
      await client.send("Page.navigate", { url: `${APP_URL}${route}` });
      const deadline = Date.now() + 20000;
      while (Date.now() < deadline) {
        const ready = await evaluate(`document.readyState === "complete" && document.body.innerText.includes(${JSON.stringify(readyText)})`);
        if (ready) return;
        await delay(250);
      }
      const diagnostic = await evaluate(`({
        url: location.href,
        title: document.title,
        readyState: document.readyState,
        bodyText: document.body?.innerText?.slice(0, 500),
        rootHtml: document.querySelector("#root")?.innerHTML?.slice(0, 500),
      })`);
      throw new Error(`Timed out loading ${route}: ${JSON.stringify(diagnostic)}`);
    };

    const waitUntil = async (expression, label, timeoutMs = 15000) => {
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        if (await evaluate(expression)) return;
        await delay(250);
      }
      throw new Error(`Timed out waiting for ${label}`);
    };

    await navigate("/", "Workplace intelligence for safer teams.");
    await evaluate(`sessionStorage.setItem("token", ${JSON.stringify(TOKEN)}); sessionStorage.setItem("role", "officer"); sessionStorage.setItem("name", "UI Test Officer"); true`);
    await navigate("/officer/incidents", "Incident Register");
    await delay(2000);

    await evaluate(`(() => {
      const select = document.querySelector("#incident-type");
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
      setter.call(select, "PPE_VIOLATION");
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()`);
    await waitUntil(`document.querySelectorAll("tbody tr").length === 2`, "PPE incident filter");
    const filterResult = await evaluate(`(() => {
      const rows = [...document.querySelectorAll("tbody tr")];
      return { ppeRowCount: rows.length, onlyPpe: rows.every((row) => row.innerText.includes("PPE Violation")) };
    })()`);
    await evaluate(`(() => {
      const select = document.querySelector("#incident-type");
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
      setter.call(select, "");
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()`);
    await waitUntil(`document.querySelectorAll("tbody tr").length === 7`, "cleared incident filter");

    const listResult = await evaluate(`(() => {
      const text = document.body.innerText;
      const rows = [...document.querySelectorAll("tbody tr")];
      const target = rows.find((row) => row.innerText.includes(${JSON.stringify(TARGET_PREFIX)}));
      if (!target) return { error: "Target incident row was not rendered", rowCount: rows.length };
      target.querySelector("button")?.click();
      return {
        rowCount: rows.length,
        hasPpe: text.includes("PPE Violation"),
        hasZone: text.includes("Restricted Zone Violation"),
        hasCamera: text.includes("FYP E2E Test Camera"),
        hasLocation: text.includes("construction block 1"),
      };
    })()`);
    if (listResult.error) throw new Error(listResult.error);

    const dialogDeadline = Date.now() + 15000;
    let detailResult;
    while (Date.now() < dialogDeadline) {
      detailResult = await evaluate(`(() => {
        const dialog = document.querySelector('[role="dialog"]');
        const image = dialog?.querySelector('img[alt^="Evidence for incident"]');
        if (!dialog || !image || !image.complete) return null;
        const text = dialog.innerText;
        return {
          fullIncidentId: text.includes("3401ddd1-4208-4585-bcb2-916ae85df3e1"),
          trackingIdLabel: text.toLowerCase().includes("tracking id"),
          notesPersisted: dialog.querySelector("textarea")?.value === "E2E verified by Safety Officer workflow on 2026-10-04.",
          actionVisible: text.includes("Review restricted-zone controls, brief the assigned team, and document completion."),
          resolved: text.includes("Incident resolved"),
          evidenceLoaded: image.naturalWidth > 0 && image.naturalHeight > 0,
          evidenceWidth: image.naturalWidth,
          evidenceHeight: image.naturalHeight,
        };
      })()`);
      if (detailResult?.evidenceLoaded) break;
      await delay(250);
    }
    if (!detailResult?.evidenceLoaded) throw new Error("Incident evidence did not load in the detail dialog.");

    // Exercise the status and notes controls through React on a second real AI incident.
    await evaluate(`document.querySelector('button[aria-label="Close incident details"]')?.click(); true`);
    await evaluate(`(() => {
      const row = [...document.querySelectorAll("tbody tr")].find((entry) => entry.innerText.includes("ba5235e9"));
      row?.querySelector("button")?.click();
      return Boolean(row);
    })()`);
    await waitUntil(`document.querySelector('[role="dialog"]')?.innerText.includes("ba5235e9-44d2-4882-b954-cdf57da80d20")`, "workflow incident detail");
    await evaluate(`(() => {
      const textarea = document.querySelector('[role="dialog"] textarea');
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
      setter.call(textarea, "React UI E2E review verified on 2026-10-04.");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    })()`);
    await delay(250);
    await evaluate(`(() => {
      const button = [...document.querySelectorAll('[role="dialog"] button')].find((entry) => entry.innerText.includes("Save Notes"));
      button?.click();
      return Boolean(button);
    })()`);
    await waitUntil(`document.querySelector('[role="dialog"]')?.innerText.includes("Officer notes saved.")`, "React notes save");

    const startedReview = await evaluate(`(() => {
      const button = [...document.querySelectorAll('[role="dialog"] button')].find((entry) => entry.innerText.includes("Start Review"));
      button?.click();
      return Boolean(button);
    })()`);
    if (startedReview) {
      await waitUntil(`[...document.querySelectorAll('[role="dialog"] button')].some((entry) => entry.innerText.includes("Resolve Incident"))`, "in-progress workflow state");
    }
    const resolvedThroughUi = await evaluate(`(() => {
      const button = [...document.querySelectorAll('[role="dialog"] button')].find((entry) => entry.innerText.includes("Resolve Incident"));
      button?.click();
      return Boolean(button);
    })()`);
    if (resolvedThroughUi) {
      await waitUntil(`document.querySelector('[role="dialog"]')?.innerText.includes("Incident resolved")`, "resolved workflow state");
    }

    await navigate("/officer/incidents", "Incident Register");
    await delay(1000);
    await evaluate(`(() => {
      const row = [...document.querySelectorAll("tbody tr")].find((entry) => entry.innerText.includes("ba5235e9"));
      row?.querySelector("button")?.click();
      return Boolean(row);
    })()`);
    await waitUntil(`document.querySelector('[role="dialog"]')?.innerText.includes("ba5235e9-44d2-4882-b954-cdf57da80d20")`, "refreshed workflow detail");
    const workflowResult = await evaluate(`(() => {
      const dialog = document.querySelector('[role="dialog"]');
      return {
        notesPersistedAfterRefresh: dialog?.querySelector("textarea")?.value === "React UI E2E review verified on 2026-10-04.",
        resolvedAfterRefresh: dialog?.innerText.includes("Incident resolved"),
      };
    })()`);

    await navigate("/officer", "Incident Workload");
    await delay(1000);
    const dashboardResult = await evaluate(`(() => {
      const cards = {};
      document.querySelectorAll(".stat-item").forEach((card) => {
        const label = card.querySelector(".stat-label")?.innerText;
        const value = card.querySelector(".stat-value")?.innerText;
        if (label) cards[label] = value;
      });
      return { cards, databaseBacked: document.body.innerText.includes("Database backed") };
    })()`);

    await navigate("/officer/actions", "All Corrective Actions");
    await delay(1000);
    const actionResult = await evaluate(`(() => {
      const text = document.body.innerText;
      return {
        actionVisible: text.includes("Review restricted-zone controls, brief the assigned team, and document completion."),
        assigneeVisible: text.includes("Safety Officer"),
        statusVisible: text.includes("In Progress"),
      };
    })()`);

    await navigate("/officer/live", "Available Cameras");
    await waitUntil(
      `document.querySelector(".live-video-image")?.naturalWidth > 0`,
      "real MJPEG camera frame",
      30000,
    );
    const liveResult = await evaluate(`(() => {
      const text = document.body.innerText;
      const image = document.querySelector(".live-video-image");
      return {
        cameraVisible: text.includes("FYP E2E Test Camera"),
        locationResolved: text.includes("construction block 1"),
        noLocationIdFallback: !text.includes("Location #2"),
        alertsSectionVisible: text.includes("Open Incident Alerts"),
        realFrameRendered: image?.naturalWidth > 0 && image?.naturalHeight > 0,
        frameWidth: image?.naturalWidth || 0,
        frameHeight: image?.naturalHeight || 0,
      };
    })()`);

    let adminResult = null;
    if (ADMIN_TOKEN) {
      await evaluate(`sessionStorage.setItem("token", ${JSON.stringify(ADMIN_TOKEN)}); sessionStorage.setItem("role", "admin"); sessionStorage.setItem("name", "Release Audit Admin"); true`);
      const adminPages = [
        ["/admin", "Admin Dashboard"],
        ["/admin/users", "Manage Users"],
        ["/admin/locations", "Manage Locations"],
        ["/admin/cameras", "Manage Cameras"],
        ["/admin/rules", "Safety Rules"],
      ];
      const visited = [];
      for (const [route, title] of adminPages) {
        await navigate(route, title);
        await delay(500);
        const hasError = await evaluate(`Boolean(document.querySelector(".alert-error"))`);
        visited.push({ route, title, hasError });
      }
      adminResult = {
        pagesVisited: visited.length,
        noVisibleErrors: visited.every((pageResult) => !pageResult.hasError),
      };
    }

    let workerResult = null;
    if (WORKER_TOKEN) {
      await evaluate(`sessionStorage.setItem("token", ${JSON.stringify(WORKER_TOKEN)}); sessionStorage.setItem("role", "worker"); sessionStorage.setItem("name", "Release Audit Worker"); true`);
      const workerPages = [
        ["/worker", "Worker Dashboard"],
        ["/worker/locations", "Assigned Locations"],
        ["/worker/instructions", "Safety Instructions"],
      ];
      const visited = [];
      for (const [route, title] of workerPages) {
        await navigate(route, title);
        await delay(500);
        const hasError = await evaluate(`Boolean(document.querySelector(".alert-error"))`);
        visited.push({ route, title, hasError });
      }
      const instructionScope = await evaluate(`(() => {
        const text = document.body.innerText;
        return {
          assignedInstructionVisible: text.includes("construction block 1"),
          unassignedRestrictedRuleHidden: !text.includes("CS building") && !text.includes("construction second floor"),
        };
      })()`);
      const acknowledgementStart = await evaluate(`(() => {
        const cards = [...document.querySelectorAll(".instructions-layout > div:first-child > .content-section")];
        const card = cards.find((entry) => entry.innerText.includes("PPE Safety Briefing"));
        if (!card) return { found: false };
        card.firstElementChild?.click();
        return { found: true };
      })()`);
      if (!acknowledgementStart.found) throw new Error("The real PPE Safety Briefing was not rendered for the worker.");
      await waitUntil(
        `[...document.querySelectorAll(".instructions-layout > div:first-child > .content-section")].some((entry) => entry.innerText.includes("PPE Safety Briefing") && (entry.innerText.includes("Acknowledged") || [...entry.querySelectorAll("button")].some((button) => button.innerText.trim() === "Acknowledge")))`,
        "expanded worker instruction",
      );
      await evaluate(`(() => {
        const cards = [...document.querySelectorAll(".instructions-layout > div:first-child > .content-section")];
        const card = cards.find((entry) => entry.innerText.includes("PPE Safety Briefing"));
        const button = [...(card?.querySelectorAll("button") || [])].find((entry) => entry.innerText.trim() === "Acknowledge");
        button?.click();
        return true;
      })()`);
      await waitUntil(
        `[...document.querySelectorAll(".instructions-layout > div:first-child > .content-section")].some((entry) => entry.innerText.includes("PPE Safety Briefing") && entry.innerText.includes("Acknowledged"))`,
        "worker acknowledgement save",
      );
      await navigate("/worker/locations", "Assigned Locations");
      await navigate("/worker/instructions", "Safety Instructions");
      await waitUntil(
        `[...document.querySelectorAll(".instructions-layout > div:first-child > .content-section")].some((entry) => entry.innerText.includes("PPE Safety Briefing"))`,
        "refreshed worker instruction",
      );
      await evaluate(`(() => {
        const cards = [...document.querySelectorAll(".instructions-layout > div:first-child > .content-section")];
        const card = cards.find((entry) => entry.innerText.includes("PPE Safety Briefing"));
        card?.firstElementChild?.click();
        return true;
      })()`);
      await waitUntil(
        `[...document.querySelectorAll(".instructions-layout > div:first-child > .content-section")].some((entry) => entry.innerText.includes("PPE Safety Briefing") && [...entry.querySelectorAll("button")].some((button) => button.innerText.includes("Acknowledged")))`,
        "persisted worker acknowledgement after refresh",
      );
      const acknowledgementRefresh = await evaluate(`(() => {
        const cards = [...document.querySelectorAll(".instructions-layout > div:first-child > .content-section")];
        const card = cards.find((entry) => entry.innerText.includes("PPE Safety Briefing"));
        return {
          acknowledgedAfterRefresh: [...(card?.querySelectorAll("button") || [])].some((entry) => entry.innerText.includes("Acknowledged")),
          noAcknowledgeButtonAfterRefresh: ![...(card?.querySelectorAll("button") || [])].some((entry) => entry.innerText.trim() === "Acknowledge"),
        };
      })()`);
      workerResult = {
        pagesVisited: visited.length,
        noVisibleErrors: visited.every((pageResult) => !pageResult.hasError),
        ...instructionScope,
        instructionFound: acknowledgementStart.found,
        acknowledgedAfterRefresh: acknowledgementRefresh.acknowledgedAfterRefresh,
        noAcknowledgeButtonAfterRefresh: acknowledgementRefresh.noAcknowledgeButtonAfterRefresh,
      };
    }

    const checks = [
      ...Object.values(filterResult).filter((value) => typeof value === "boolean"),
      ...Object.values(listResult).filter((value) => typeof value === "boolean"),
      ...Object.values(detailResult).filter((value) => typeof value === "boolean"),
      ...Object.values(workflowResult),
      dashboardResult.databaseBacked,
      ...Object.values(actionResult),
      ...Object.values(liveResult).filter((value) => typeof value === "boolean"),
      ...Object.values(adminResult || {}).filter((value) => typeof value === "boolean"),
      ...Object.values(workerResult || {}).filter((value) => typeof value === "boolean"),
    ];
    if (checks.some((value) => value !== true)) {
      throw new Error(`One or more UI assertions failed: ${JSON.stringify({ filterResult, listResult, detailResult, workflowResult, dashboardResult, actionResult, liveResult, adminResult, workerResult })}`);
    }

    console.log(JSON.stringify({ filterResult, listResult, detailResult, workflowResult, dashboardResult, actionResult, liveResult, adminResult, workerResult }, null, 2));
  } finally {
    client?.close();
    chrome.kill();
    await delay(300);
    await rm(profilePath, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
