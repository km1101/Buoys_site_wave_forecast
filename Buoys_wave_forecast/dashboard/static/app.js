const state = {
  sites: [],
  models: [],
  parameters: [],
  map: null,
  markers: {},
  chart: null,
  parameterMenuOpen: false,
};

const DEFAULT_PARAMETERS = ["wave_height", "swell_wave_height"];

const COLORS = [
  "#2bb3c0", "#4d8dff", "#ffb347", "#7dffb3", "#ff6b6b",
  "#c084fc", "#f472b6", "#facc15", "#60a5fa", "#34d399",
  "#fb7185", "#a78bfa", "#fde047", "#38bdf8", "#4ade80", "#f97316",
];

async function api(path) {
  const res = await fetch(path);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Request failed: ${res.status}`);
  }
  return res.json();
}

function setStatus(text, ok = true) {
  const el = document.getElementById("status");
  el.textContent = text;
  el.className = ok ? "status ok" : "status error";
}

function selectedSiteId() {
  return document.getElementById("siteSelect").value;
}

function selectedModelId() {
  return document.getElementById("modelSelect").value;
}

function selectedParameters() {
  return [...document.querySelectorAll("#parameterMenu input[type=checkbox]:checked")]
    .map((el) => el.value);
}

function currentSite() {
  return state.sites.find((s) => s.site_id === selectedSiteId());
}

function fillSelect(id, items, valueKey, labelKey, includeEmpty = false) {
  const select = document.getElementById(id);
  select.innerHTML = "";
  if (includeEmpty) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "Compare all models";
    select.appendChild(opt);
  }
  for (const item of items) {
    const opt = document.createElement("option");
    opt.value = item[valueKey];
    opt.textContent = item[labelKey];
    select.appendChild(opt);
  }
}

function renderParameterMenu() {
  const menu = document.getElementById("parameterMenu");
  menu.innerHTML = "";

  const groups = {};
  for (const param of state.parameters) {
    if (!groups[param.group]) groups[param.group] = [];
    groups[param.group].push(param);
  }

  for (const [groupName, params] of Object.entries(groups)) {
    const groupEl = document.createElement("div");
    groupEl.className = "param-group";

    const title = document.createElement("div");
    title.className = "param-group-title";
    title.textContent = groupName;
    groupEl.appendChild(title);

    for (const param of params) {
      const label = document.createElement("label");
      label.className = "param-option";

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = param.id;
      checkbox.checked = DEFAULT_PARAMETERS.includes(param.id);
      checkbox.addEventListener("change", () => {
        if (selectedParameters().length === 0) {
          checkbox.checked = true;
        }
        updateParameterTriggerLabel();
        refreshAll();
      });

      const text = document.createElement("span");
      text.textContent = param.label;

      label.appendChild(checkbox);
      label.appendChild(text);
      groupEl.appendChild(label);
    }

    menu.appendChild(groupEl);
  }

  updateParameterTriggerLabel();
}

function updateParameterTriggerLabel() {
  const selected = selectedParameters();
  const labels = selected.map((id) => {
    const param = state.parameters.find((p) => p.id === id);
    return param ? param.label : id;
  });

  const trigger = document.getElementById("parameterTrigger");
  if (!selected.length) {
    trigger.textContent = "Select parameters";
    return;
  }
  if (selected.length === 1) {
    trigger.textContent = labels[0];
    return;
  }
  if (selected.length <= 2) {
    trigger.textContent = labels.join(", ");
    return;
  }
  trigger.textContent = `${selected.length} parameters selected`;
}

function toggleParameterMenu(forceOpen) {
  const menu = document.getElementById("parameterMenu");
  const trigger = document.getElementById("parameterTrigger");
  const open = forceOpen ?? !state.parameterMenuOpen;
  state.parameterMenuOpen = open;
  menu.hidden = !open;
  trigger.setAttribute("aria-expanded", open ? "true" : "false");
}

function initMap() {
  state.map = L.map("map").setView([51.5, -9], 6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap",
  }).addTo(state.map);
}

function renderMapMarkers() {
  Object.values(state.markers).forEach((m) => m.remove());
  state.markers = {};

  for (const site of state.sites) {
    const marker = L.marker([site.latitude, site.longitude])
      .addTo(state.map)
      .bindPopup(`<strong>${site.site_name}</strong><br>${site.latitude.toFixed(3)}, ${site.longitude.toFixed(3)}`);
    marker.on("click", () => {
      document.getElementById("siteSelect").value = site.site_id;
      onSiteChange();
    });
    state.markers[site.site_id] = marker;
  }

  if (state.sites.length) {
    const bounds = L.latLngBounds(state.sites.map((s) => [s.latitude, s.longitude]));
    state.map.fitBounds(bounds.pad(0.2));
  }
}

function updateSiteMeta() {
  const site = currentSite();
  const meta = document.getElementById("siteMeta");
  if (!site) {
    meta.textContent = "";
    return;
  }
  meta.innerHTML = `
    <div><strong>${site.site_name}</strong></div>
    <div>Lat ${Number(site.latitude).toFixed(4)} · Lon ${Number(site.longitude).toFixed(4)}</div>
  `;

  const marker = state.markers[site.site_id];
  if (marker) {
    marker.openPopup();
    state.map.panTo([site.latitude, site.longitude]);
  }
}

function buildChart(series, compareAllModels) {
  const ctx = document.getElementById("forecastChart");
  if (state.chart) state.chart.destroy();

  const datasets = [];
  const grouped = {};

  for (const row of series) {
    if (row.value == null) continue;
    const key = compareAllModels
      ? `${row.model_name} · ${row.parameter_label}`
      : row.parameter_label;
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push({ x: row.forecast_time, y: row.value });
  }

  Object.keys(grouped).sort().forEach((label, idx) => {
    datasets.push({
      label,
      data: grouped[label],
      borderColor: COLORS[idx % COLORS.length],
      backgroundColor: "transparent",
      tension: 0.25,
      pointRadius: 0,
      borderWidth: 2,
    });
  });

  state.chart = new Chart(ctx, {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          type: "time",
          time: { tooltipFormat: "yyyy-MM-dd HH:mm", displayFormats: { hour: "MMM d HH:mm" } },
          ticks: { color: "#8aa4bd" },
          grid: { color: "rgba(255,255,255,0.06)" },
        },
        y: {
          ticks: { color: "#8aa4bd" },
          grid: { color: "rgba(255,255,255,0.06)" },
        },
      },
      plugins: {
        legend: { labels: { color: "#e8f1fa" } },
      },
    },
  });
}

function renderSummaryCards(latestRows) {
  const container = document.getElementById("summaryCards");
  if (!latestRows.length) {
    container.innerHTML = `<div class="card"><div class="label">No data</div><div class="value">—</div></div>`;
    return;
  }

  const heights = latestRows.map((r) => r.wave_height).filter((v) => v != null);
  const maxWave = heights.length ? Math.max(...heights) : null;
  const minWave = heights.length ? Math.min(...heights) : null;
  const avgWave = heights.length ? heights.reduce((a, b) => a + b, 0) / heights.length : null;

  container.innerHTML = `
    <div class="card"><div class="label">Models</div><div class="value">${latestRows.length}</div></div>
    <div class="card"><div class="label">Max wave height (m)</div><div class="value">${maxWave?.toFixed(2) ?? "—"}</div></div>
    <div class="card"><div class="label">Min wave height (m)</div><div class="value">${minWave?.toFixed(2) ?? "—"}</div></div>
    <div class="card"><div class="label">Mean wave height (m)</div><div class="value">${avgWave?.toFixed(2) ?? "—"}</div></div>
  `;
}

function renderLatestTable(rows) {
  const tbody = document.querySelector("#latestTable tbody");
  tbody.innerHTML = rows.map((row) => `
    <tr>
      <td>${row.model_name}</td>
      <td>${row.latest_forecast_time ? new Date(row.latest_forecast_time).toUTCString() : "—"}</td>
      <td>${row.wave_height != null ? Number(row.wave_height).toFixed(2) : "—"}</td>
      <td>${row.swell_wave_height != null ? Number(row.swell_wave_height).toFixed(2) : "—"}</td>
    </tr>
  `).join("");
}

async function loadForecastChart() {
  const siteId = selectedSiteId();
  if (!siteId) return;

  const parameters = selectedParameters();
  if (!parameters.length) return;

  const modelId = selectedModelId();
  const daysAhead = document.getElementById("daysAhead").value;

  const query = new URLSearchParams({
    site_id: siteId,
    parameters: parameters.join(","),
    days_ahead: daysAhead,
  });
  if (modelId) query.set("model_id", modelId);

  const data = await api(`/api/forecast?${query.toString()}`);
  buildChart(data.series, !modelId);
}

async function loadLatest() {
  const siteId = selectedSiteId();
  if (!siteId) return;
  const rows = await api(`/api/forecast/latest?site_id=${encodeURIComponent(siteId)}`);
  renderSummaryCards(rows);
  renderLatestTable(rows);
}

async function refreshAll() {
  try {
    setStatus("Refreshing…", true);
    await Promise.all([loadForecastChart(), loadLatest()]);
    setStatus("Connected", true);
  } catch (err) {
    console.error(err);
    setStatus(err.message, false);
  }
}

async function onSiteChange() {
  updateSiteMeta();
  await refreshAll();
}

async function init() {
  try {
    initMap();
    const [health, sites, models, parameters] = await Promise.all([
      api("/api/health"),
      api("/api/sites"),
      api("/api/models"),
      api("/api/parameters"),
    ]);

    state.sites = sites;
    state.models = models;
    state.parameters = parameters;

    fillSelect("siteSelect", sites, "site_id", "site_name");
    fillSelect("modelSelect", models, "model_id", "model_name", true);
    renderParameterMenu();

    renderMapMarkers();
    updateSiteMeta();
    await refreshAll();
    setStatus(`${health.service} · ${sites.length} sites`, true);
  } catch (err) {
    console.error(err);
    setStatus(err.message, false);
  }
}

document.getElementById("siteSelect").addEventListener("change", onSiteChange);
document.getElementById("modelSelect").addEventListener("change", refreshAll);
document.getElementById("daysAhead").addEventListener("change", refreshAll);
document.getElementById("refreshBtn").addEventListener("click", refreshAll);

document.getElementById("parameterTrigger").addEventListener("click", (event) => {
  event.stopPropagation();
  toggleParameterMenu();
});

document.addEventListener("click", (event) => {
  const multiselect = document.getElementById("parameterMultiselect");
  if (!multiselect.contains(event.target)) {
    toggleParameterMenu(false);
  }
});

document.getElementById("parameterMenu").addEventListener("click", (event) => {
  event.stopPropagation();
});

init();
