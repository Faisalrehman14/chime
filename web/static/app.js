const $ = (sel) => document.querySelector(sel);

const tabs = document.querySelectorAll(".nav-item");
const tabSections = document.querySelectorAll(".view");

const PAGE_TITLES = {
  dashboard: "Dashboard",
  activity: "Activity",
  settings: "Settings",
};

tabs.forEach((btn) => {
  btn.addEventListener("click", () => {
    tabs.forEach((b) => b.classList.remove("active"));
    tabSections.forEach((t) => t.classList.remove("active"));
    btn.classList.add("active");
    const tab = btn.dataset.tab;
    $(`#tab-${tab}`).classList.add("active");
    $("#page-title").textContent = PAGE_TITLES[tab] || btn.textContent.trim();
    if (tab === "activity") loadActivity();
    if (tab === "settings") loadSettings();
  });
});

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 3200);
}

function fmtMoney(v) {
  return `$${Number(v || 0).toFixed(2)}`;
}

function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusPill(status) {
  const labels = {
    claimed: "Claimed",
    already_claimed: "Already Claimed",
    failed: "Failed",
    no_link: "No Link",
    parse_failed: "Parse Error",
    blocked: "Blocked",
  };
  return `<span class="pill ${status}">${labels[status] || status}</span>`;
}

function renderRecent(items) {
  const box = $("#recent-list");
  if (!items.length) {
    box.innerHTML = '<p class="empty-state">No transactions yet</p>';
    return;
  }
  box.innerHTML = items.slice(0, 5).map((row) => `
    <div class="timeline-item">
      <div><strong>${row.sender_name || "Unknown"}</strong> · ${row.amount != null ? fmtMoney(row.amount) : "—"}</div>
      <div>${statusPill(row.status)}</div>
      <div class="meta">${fmtTime(row.processed_at)} · ${row.subject || ""}</div>
    </div>
  `).join("");
}

function renderActivity(items) {
  const tbody = $("#activity-table");
  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">No history recorded</td></tr>`;
    return;
  }
  tbody.innerHTML = items.map((row) => {
    const canMark = ["failed", "blocked", "no_link"].includes(row.status);
    const action = canMark
      ? `<button class="btn btn-outline btn-sm mark-claimed" data-id="${row.message_id}" type="button">Mark Claimed</button>`
      : "";
    return `
    <tr>
      <td>${fmtTime(row.processed_at)}</td>
      <td>${row.sender_name || "—"}</td>
      <td>${row.amount != null ? fmtMoney(row.amount) : "—"}</td>
      <td>${statusPill(row.status)}</td>
      <td>${row.subject || ""}</td>
      <td>${action}</td>
    </tr>
  `;
  }).join("");

  tbody.querySelectorAll(".mark-claimed").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const res = await fetch(`/api/mark-claimed/${btn.dataset.id}`, { method: "POST" });
        const data = await res.json();
        toast(data.message || "Updated");
        await loadActivity();
        await refresh();
      } finally {
        btn.disabled = false;
      }
    });
  });
}

async function loadStatus() {
  const res = await fetch("/api/status");
  const data = await res.json();

  $("#stat-total-claimed").textContent = fmtMoney(data.summary.total_claimed);
  $("#stat-claimed-count").textContent = data.summary.claimed_count;
  $("#stat-failed-count").textContent =
    (data.summary.failed_count || 0) + (data.summary.blocked_count || 0);
  $("#stat-last-check").textContent = data.worker.last_check
    ? fmtTime(data.worker.last_check)
    : "—";

  $("#interval-label").textContent = data.worker.interval_seconds;

  const gmailEl = $("#gmail-status");
  if (data.gmail.connected) {
    gmailEl.textContent = data.gmail.email || "Connected";
    gmailEl.className = "health-value status-ok";
  } else if (data.gmail.credentials_exists) {
    gmailEl.textContent = "Not connected";
    gmailEl.className = "health-value status-bad";
  } else {
    gmailEl.textContent = "Credentials missing";
    gmailEl.className = "health-value status-bad";
  }

  const cardEl = $("#card-status");
  const cardMissing = data.config.card_missing || [];
  if (cardMissing.length) {
    cardEl.textContent = "Not configured";
    cardEl.className = "health-value status-bad";
  } else {
    cardEl.textContent = "Ready";
    cardEl.className = "health-value status-ok";
  }

  const workerEl = $("#worker-status");
  if (data.worker.running) {
    workerEl.textContent = data.worker.checking
      ? "Scanning inbox…"
      : `Active · every ${data.worker.interval_seconds}s`;
    workerEl.className = "health-value status-ok";
  } else {
    workerEl.textContent = "Stopped";
    workerEl.className = "health-value status-bad";
  }

  $("#last-result").textContent = data.worker.last_result || "—";

  const banner = $("#block-banner");
  const browser = data.worker.browser || {};
  if (browser.blocked) {
    const ip = browser.blocked_ip ? ` IP ${browser.blocked_ip}` : "";
    banner.textContent =
      `Cloudflare block${ip}. VPN band karo, open Chrome mein Chime tab rakho, Connect Open Chrome, phir Recheck.`;
    banner.classList.remove("hidden");
  } else if (browser.mode === "existing" && browser.connected === false && !data.config?.is_cloud) {
    banner.textContent =
      "Open Chrome connect nahi — terminal: ./scripts/start-chrome-debug.sh  phir Connect Open Chrome dabao.";
    banner.classList.remove("hidden");
  } else {
    banner.classList.add("hidden");
  }

  const badge = $("#watch-badge");
  const liveDot = $("#live-dot");
  const toggleBtn = $("#btn-toggle-watch");

  if (data.worker.running) {
    badge.textContent = "Monitoring Active";
    liveDot.className = "live-dot on";
    toggleBtn.textContent = "Stop Monitoring";
  } else {
    badge.textContent = "Monitoring Off";
    liveDot.className = "live-dot off";
    toggleBtn.textContent = "Start Monitoring";
  }
}

async function loadRecent() {
  const res = await fetch("/api/activity?limit=5");
  const data = await res.json();
  renderRecent(data.items);
}

async function loadActivity() {
  const res = await fetch("/api/activity?limit=50");
  const data = await res.json();
  renderActivity(data.items);
}

async function loadSettings() {
  const res = await fetch("/api/settings");
  const data = await res.json();
  const form = $("#settings-form");
  form.cardholder_name.value = data.cardholder_name || "";
  form.card_expiry.value = data.card_expiry || "";
  form.card_zip.value = data.card_zip || "";
  form.check_interval_seconds.value = data.check_interval_seconds || "10";
  form.chime_sender.value = data.chime_sender || "alerts@account.chime.com";
  form.headless.value = data.headless || "false";

  const hint = $("#card-saved-hint");
  if (data.card_configured) {
    hint.textContent = `Saved card ending ${data.card_number_masked.split(" ").pop()}`;
  } else {
    hint.textContent = "No card on file — complete all fields below";
  }

  updateGmailUi(data);
  const chromeStatus = $("#chrome-connect-status");
  const localBrowser = $("#local-browser-setup");
  const cloudNote = $("#cloud-deploy-note");
  const redirectEl = $("#gmail-redirect-uri");

  if (data.is_cloud) {
    localBrowser?.classList.add("hidden");
    cloudNote?.classList.remove("hidden");
    if (redirectEl && data.gmail_redirect_uri) {
      redirectEl.textContent = data.gmail_redirect_uri;
    }
    if (chromeStatus) chromeStatus.textContent = "Cloud: headless browser";
  } else {
    localBrowser?.classList.remove("hidden");
    cloudNote?.classList.add("hidden");
    if (chromeStatus) {
      chromeStatus.textContent = data.chrome_connected
        ? "Open Chrome connected"
        : "Open Chrome not connected — run ./scripts/start-chrome-debug.sh";
    }
  }
}

function updateGmailUi(data) {
  const status = $("#gmail-setup-status");
  const connectBtn = $("#btn-gmail-connect");
  const disconnectBtn = $("#btn-gmail-disconnect");
  const redirect = $("#redirect-uri");

  if (redirect && data.redirect_uri) {
    redirect.textContent = data.redirect_uri;
  }

  if (!data.gmail_credentials_exists) {
    status.textContent = "Upload credentials.json to enable OAuth";
    status.className = "integration-desc status-bad";
    connectBtn.classList.add("hidden");
    disconnectBtn.classList.add("hidden");
    return;
  }

  if (data.gmail_connected) {
    status.textContent = `Connected as ${data.gmail_email}`;
    status.className = "integration-desc status-ok";
    connectBtn.classList.add("hidden");
    disconnectBtn.classList.remove("hidden");
  } else {
    status.textContent = "Not connected — authorize to begin monitoring";
    status.className = "integration-desc status-bad";
    connectBtn.classList.remove("hidden");
    disconnectBtn.classList.add("hidden");
  }
}

$("#btn-gmail-disconnect").addEventListener("click", async () => {
  await fetch("/api/gmail/disconnect", { method: "POST" });
  toast("Gmail disconnected");
  await loadSettings();
  await refresh();
});

function handleUrlMessages() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("gmail_connected")) {
    toast(`Connected: ${decodeURIComponent(params.get("gmail_connected"))}`);
    history.replaceState({}, "", "/#settings");
    document.querySelector('[data-tab="settings"]').click();
  }
  if (params.get("gmail_error")) {
    toast(`Connection failed: ${decodeURIComponent(params.get("gmail_error"))}`);
    history.replaceState({}, "", "/#settings");
    document.querySelector('[data-tab="settings"]').click();
  }
  if (window.location.hash === "#settings") {
    document.querySelector('[data-tab="settings"]').click();
  }
}

handleUrlMessages();

$("#btn-check").addEventListener("click", async () => {
  $("#btn-check").disabled = true;
  try {
    const res = await fetch("/api/check-now", { method: "POST" });
    const data = await res.json();
    toast(data.message || "Scan complete");
    await refresh();
    if ($("#tab-activity").classList.contains("active")) await loadActivity();
  } finally {
    $("#btn-check").disabled = false;
  }
});

$("#btn-recheck-failed").addEventListener("click", async () => {
  const btn = $("#btn-recheck-failed");
  btn.disabled = true;
  try {
    const res = await fetch("/api/recheck-failed", { method: "POST" });
    const data = await res.json();
    toast(data.message || "Recheck complete");
    await loadActivity();
    await refresh();
  } finally {
    btn.disabled = false;
  }
});

$("#btn-browser-warmup").addEventListener("click", async () => {
  const btn = $("#btn-browser-warmup");
  btn.disabled = true;
  toast("Open Chrome se connect ho raha hai…");
  try {
    const res = await fetch("/api/browser/warmup", { method: "POST" });
    const data = await res.json();
    toast(data.message || "Connected");
    await loadSettings();
    await refresh();
  } finally {
    btn.disabled = false;
  }
});

$("#btn-toggle-watch").addEventListener("click", async () => {
  const status = await (await fetch("/api/status")).json();
  const running = status.worker.running;
  const endpoint = running ? "/api/watcher/stop" : "/api/watcher/start";
  await fetch(endpoint, { method: "POST" });
  toast(running ? "Monitoring stopped" : "Monitoring started");
  await refresh();
});

$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const payload = Object.fromEntries(new FormData(form).entries());
  Object.keys(payload).forEach((k) => {
    if (!payload[k]) delete payload[k];
  });

  const res = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (res.ok) {
    $("#settings-msg").textContent = "Configuration saved";
    toast("Settings saved successfully");
    await loadSettings();
    await refresh();
  } else {
    const err = await res.json().catch(() => ({}));
    const msg = err.detail || "Save failed";
    $("#settings-msg").textContent = msg;
    toast(msg);
  }
});

async function refresh() {
  await loadStatus();
  await loadRecent();
}

refresh();
setInterval(refresh, 3000);
