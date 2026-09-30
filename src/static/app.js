const $ = (id) => document.getElementById(id);
const form = $("submit-form");
const plan = $("plan");
const board = $("jobs");
const dialog = $("job-dialog");
const SAMPLE = plan.value;
const SVG = "http://www.w3.org/2000/svg";
const RAD = Math.PI / 180;
const STATUSES = ["succeeded", "running", "queued", "failed"];
// List cap in controllers/jobs.py. Counts and fuel are this window, not all-time.
const JOB_LIMIT = 100;
for (const node of document.querySelectorAll(".job-window")) node.textContent = JOB_LIMIT;
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const rows = new Map();
let current = "";
let highlight = null;
let openJob = null;
let filing = false;

// Auth is mocked (ARCHITECTURE.md D9): the selected airline is the caller's identity.
const api = (path, init = {}) =>
  fetch(path, { ...init, headers: { ...init.headers, "X-Airline": current } });

// Every value from the server or the textarea goes in as text, never markup.
function tag(name, className, text) {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}
function svg(name, attrs, parent, text) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text != null) node.textContent = text;
  parent.appendChild(node);
  return node;
}

const num = (n, digits = 0) =>
  n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const hueOf = (code) => [...code].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
const hms = (date) => date.toISOString().slice(11, 19);
function when(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  return `${date.toISOString().slice(5, 10)} ${hms(date)}Z`;
}
function airTime(hours) {
  const minutes = Math.round(hours * 60);
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")} min`;
}
function km(a, b) {
  const dLat = (b.latitude - a.latitude) * RAD;
  const dLon = (b.longitude - a.longitude) * RAD;
  const h = Math.sin(dLat / 2) ** 2 +
    Math.cos(a.latitude * RAD) * Math.cos(b.latitude * RAD) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
}
// Inline each waypoint object, like the sample. JSON strings hold no raw newlines, so only
// whitespace between tokens changes.
const tidy = (body) =>
  JSON.stringify(body, null, 2).replace(
    /\{\n\s+([^{}[\]]*?)\n\s*\}/g,
    (_, inner) => `{${inner.replace(/\n\s+/g, " ")}}`,
  );
function readPlan() {
  try {
    return { body: JSON.parse(plan.value) };
  } catch (error) {
    return { error };
  }
}

function say(text, kind = "") {
  const message = $("message");
  message.textContent = text;
  message.className = `message ${kind}`;
}
function setLink(live, reason = "") {
  const link = $("link");
  link.classList.toggle("lost", !live);
  link.textContent = live ? `Live · ${hms(new Date())}Z` : `${reason || "Offline"} · retrying`;
}
function setStatus(node, status) {
  node.dataset.status = status;
  node.textContent = status;
}

// ---------- Plan preview ----------

function preview(animate = false) {
  const note = $("plan-note");
  const { body, error } = readPlan();
  if (error) {
    note.className = "note bad";
    note.textContent = `Not valid JSON yet: ${error.message}`;
    return;
  }
  const payload = body?.payload ?? {};
  const points = (Array.isArray(payload.waypoints) ? payload.waypoints : []).filter(
    (w) => Number.isFinite(w?.latitude) && Number.isFinite(w?.longitude),
  );
  const legs = points.slice(1).map((w, i) => km(points[i], w));
  const distance = legs.reduce((a, b) => a + b, 0);

  note.className = "note";
  note.textContent = points.length < 2
    ? "Add at least two waypoints to draw the route."
    : "Speeds are true airspeed in km/h, altitudes in ft. The server checks the model envelope.";
  $("s-flight").textContent = `${payload.airline ?? "—"} ${payload.flight_id ?? ""}`.trim();
  $("s-aircraft").textContent = payload.aircraft_type ?? "—";
  $("s-registration").textContent = payload.registration ?? "—";
  $("s-waypoints").textContent = points.length;
  $("s-distance").textContent = points.length > 1 ? `≈ ${num(distance)} km` : "—";
  $("s-departs").textContent = payload.departure_time ? when(payload.departure_time) : "On receipt";
  drawRoute(points, distance, animate);
  drawProfile(points, legs);
}

function drawRoute(points, distance, animate) {
  const map = $("route");
  const W = 640;
  const H = 300;
  map.replaceChildren();
  if (points.length < 2) {
    svg("text", { x: W / 2, y: H / 2, class: "placeholder", "text-anchor": "middle" }, map, "Route appears here");
    map.setAttribute("aria-label", "Route map: not enough waypoints");
    return;
  }
  map.setAttribute("aria-label", `Route map: ${points.length} waypoints, about ${num(distance)} km`);

  // Equirectangular projection around the route's mean latitude.
  const kx = Math.max(0.05, Math.cos((points.reduce((s, w) => s + w.latitude, 0) / points.length) * RAD));
  const xs = points.map((w) => w.longitude * kx);
  const ys = points.map((w) => -w.latitude);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const pad = Math.max(x1 - x0, y1 - y0, 0.2) * 0.22;
  const scale = Math.min(W / (x1 - x0 + 2 * pad), H / (y1 - y0 + 2 * pad));
  const mx = (x0 + x1) / 2;
  const my = (y0 + y1) / 2;
  const px = (lon) => W / 2 + (lon * kx - mx) * scale;
  const py = (lat) => H / 2 + (-lat - my) * scale;

  const steps = [0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 15, 30];
  const pick = (range, lines) => steps.find((s) => range / s <= lines) ?? 30;
  const deg = (v, step, pos, neg) =>
    `${Math.abs(v).toFixed(step < 0.1 ? 2 : step < 1 ? 1 : 0)}°${v >= 0 ? pos : neg}`;
  const latTop = -(my - H / 2 / scale);
  const latBottom = -(my + H / 2 / scale);
  const lonLeft = (mx - W / 2 / scale) / kx;
  const lonRight = (mx + W / 2 / scale) / kx;
  const grat = svg("g", { class: "grat" }, map);
  const latStep = pick(latTop - latBottom, 5);
  for (let i = Math.ceil(latBottom / latStep); i * latStep <= latTop; i++) {
    const y = py(i * latStep);
    svg("line", { x1: 0, x2: W, y1: y, y2: y }, grat);
    svg("text", { x: 8, y: y - 5 }, grat, deg(i * latStep, latStep, "N", "S"));
  }
  const lonStep = pick(lonRight - lonLeft, 7);
  for (let i = Math.ceil(lonLeft / lonStep); i * lonStep <= lonRight; i++) {
    const x = px(i * lonStep);
    svg("line", { x1: x, x2: x, y1: 0, y2: H }, grat);
    svg("text", { x: x + 5, y: H - 8 }, grat, deg(i * lonStep, lonStep, "E", "W"));
  }

  const at = points.map((w) => [px(w.longitude), py(w.latitude)]);
  const d = at.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  svg("path", { d, class: animate && !reduceMotion ? "leg draw" : "leg", pathLength: 1 }, map);

  points.forEach((w, i) => {
    const end = i === 0 || i === points.length - 1;
    const g = svg("g", { class: end ? "wp end" : "wp", transform: `translate(${at[i][0].toFixed(1)} ${at[i][1].toFixed(1)})` }, map);
    svg("title", {}, g, `Waypoint ${i + 1}: ${w.latitude}, ${w.longitude} · ${w.speed} km/h · ${w.altitude} ft`);
    svg("circle", { r: end ? 6 : 4 }, g);
    const label = i === 0 ? "DEP" : i === points.length - 1 ? "ARR" : `WP${i + 1}`;
    svg("text", { y: -12, "text-anchor": "middle" }, g, label);
  });
}

function drawProfile(points, legs) {
  const chart = $("profile");
  const W = 640;
  const H = 110;
  const top = 26;
  const bottom = 22;
  const side = 16;
  chart.replaceChildren();
  if (points.length < 2) {
    chart.setAttribute("aria-label", "Altitude profile: not enough waypoints");
    return;
  }
  const cumulative = legs.reduce((acc, d) => [...acc, acc.at(-1) + d], [0]);
  const along = cumulative.at(-1) > 0 ? cumulative : points.map((_, i) => i);
  const alts = points.map((w) => (Number.isFinite(w.altitude) ? w.altitude : 0));
  const peak = Math.max(...alts, 1);
  const x = (i) => side + (along[i] / along.at(-1)) * (W - 2 * side);
  const y = (a) => H - bottom - (Math.max(a, 0) / peak) * (H - top - bottom);
  chart.setAttribute("aria-label", `Altitude profile: ${alts.map((a) => num(a)).join(", ")} ft`);

  const gradient = svg("linearGradient", { id: "alt-fill", x1: 0, y1: 0, x2: 0, y2: 1 }, svg("defs", {}, chart));
  svg("stop", { offset: 0 }, gradient);
  svg("stop", { offset: 1 }, gradient);
  const line = alts.map((a, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(a).toFixed(1)}`).join(" ");
  const last = alts.length - 1;
  svg("path", { d: `${line} L${x(last)} ${H - bottom} L${x(0)} ${H - bottom} Z`, class: "area" }, chart);
  svg("path", { d: line, class: "alt-line" }, chart);
  alts.forEach((a, i) => {
    svg("circle", { cx: x(i), cy: y(a), r: 3 }, chart);
    if (alts.length <= 8) {
      const anchor = i === 0 ? "start" : i === last ? "end" : "middle";
      svg("text", { x: x(i), y: y(a) - 9, "text-anchor": anchor }, chart, `${num(a)} ft`);
    }
  });
  svg("text", { x: side, y: H - 6 }, chart, "0 km");
  if (cumulative.at(-1) > 0) {
    svg("text", { x: W - side, y: H - 6, "text-anchor": "end" }, chart, `${num(cumulative.at(-1))} km`);
  }
}

// ---------- Jobs ----------

function outcome(job) {
  if (job.result) {
    const fuel = tag("span", "fuel", num(job.result.total_fuel_lb, 1));
    fuel.append(tag("small", "", " lb"));
    return fuel;
  }
  if (job.error) {
    const error = tag("span", "job-error", job.error);
    error.title = job.error;
    return error;
  }
  return tag("span", "pending", job.status === "running" ? "Estimating…" : "Waiting for a worker");
}

function makeRow(id) {
  const tr = document.createElement("tr");
  const head = tag("th");
  head.scope = "row";
  const button = tag("button", "job-btn", `#${id}`);
  button.type = "button";
  button.setAttribute("aria-label", `Job ${id} details`);
  // The whole row opens the job; the button is its keyboard target, and its click bubbles here.
  tr.addEventListener("click", () => openDialog(id));
  head.append(button);
  const status = tag("span", "status");
  const cells = { flight: tag("td"), status: tag("td"), attempts: tag("td", "num"), outcome: tag("td") };
  cells.status.append(status);
  tr.append(head, ...Object.values(cells));
  return { tr, ...cells, badge: status, job: null };
}

function updateRow(row, job) {
  const before = row.job;
  row.job = job;
  if (before && JSON.stringify(before) === JSON.stringify(job)) return;
  row.flight.replaceChildren(tag("span", "carrier", job.airline), ` ${job.flight_id}`);
  setStatus(row.badge, job.status);
  row.attempts.textContent = job.attempts;
  row.outcome.replaceChildren(outcome(job));
  if (openJob === job.id) fillDialog(job);
}

function renderJobs(list) {
  const ordered = list.map((job) => {
    let row = rows.get(job.id);
    if (!row) {
      row = makeRow(job.id);
      rows.set(job.id, row);
    }
    updateRow(row, job);
    if (job.id === highlight) {
      row.tr.classList.add("fresh");
      highlight = null;
    }
    return row.tr;
  });
  const ids = new Set(list.map((job) => job.id));
  for (const [id, row] of rows) {
    if (!ids.has(id)) {
      row.tr.remove();
      rows.delete(id);
    }
  }
  // Move only rows out of place: reattaching blurs focus.
  ordered.forEach((tr, i) => {
    if (board.children[i] !== tr) board.insertBefore(tr, board.children[i] ?? null);
  });
  $("empty").hidden = list.length > 0;
}

function renderStats(list) {
  const counts = Object.fromEntries(STATUSES.map((s) => [s, 0]));
  for (const job of list) counts[job.status] += 1;
  for (const status of STATUSES) {
    $(`count-${status}`).textContent = counts[status];
    $(`bar-${status}`).style.flexGrow = counts[status];
  }
  $("fuel-total").textContent = num(list.reduce((sum, job) => sum + (job.result?.total_fuel_lb ?? 0), 0), 1);
}

async function refresh() {
  const code = current;
  if (!code) return;
  let list;
  try {
    const response = await api(`/v1/jobs?limit=${JOB_LIMIT}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    list = await response.json();
  } catch (error) {
    // Only a non-OK response carries an HTTP status; a thrown fetch is a network failure.
    if (code === current) setLink(false, error.message.startsWith("HTTP ") ? error.message : "");
    return;
  }
  // A poll started before an airline switch must not paint the old airline's jobs.
  if (code !== current) return;
  setLink(true);
  renderJobs(list);
  renderStats(list);
}

// ---------- Job dialog ----------

function fillDialog(job) {
  const result = job.result;
  $("d-id").textContent = `#${job.id}`;
  $("d-flight").textContent = `${job.airline} ${job.flight_id}`;
  setStatus($("d-status"), job.status);
  $("d-type").textContent = job.type;
  $("d-attempts").textContent = job.attempts;
  $("d-model").textContent = result?.model_version ?? "—";
  $("d-distance").textContent = result ? `${num(result.distance_km, 1)} km` : "—";
  $("d-duration").textContent = result ? airTime(result.duration_h) : "—";
  $("d-submitted").textContent = when(job.submitted_at);
  $("d-finished").textContent = when(job.finished_at);
  $("d-fuel").textContent = result ? num(result.total_fuel_lb, 1) : "—";
  const error = $("d-error");
  error.hidden = !job.error;
  error.textContent = job.error ?? "";
}

async function openDialog(id) {
  const row = rows.get(id);
  if (!row) return;
  openJob = id;
  fillDialog(row.job);
  if (!dialog.open) dialog.showModal();
  let response;
  try {
    response = await api(`/v1/jobs/${id}`);
  } catch {
    if (openJob === id) {
      $("d-error").hidden = false;
      $("d-error").textContent = "Request failed";
    }
    return;
  }
  if (openJob !== id) return;
  if (!response.ok) {
    $("d-error").hidden = false;
    $("d-error").textContent = `HTTP ${response.status}`;
    return;
  }
  fillDialog(await response.json());
}
dialog.addEventListener("close", () => { openJob = null; });
dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });

// ---------- Controls ----------

// Keep the plan's airline in step with the selector, so it is not rejected with 403.
function syncPlanAirline() {
  const { body } = readPlan();
  if (body?.payload && typeof body.payload === "object") {
    body.payload.airline = current;
    plan.value = tidy(body);
    plan.scrollLeft = 0;
  }
}

function selectAirline() {
  current = document.querySelector('input[name="airline"]:checked')?.value ?? "";
  document.documentElement.style.setProperty("--hue", hueOf(current));
  $("board-airline").textContent = current;
  if (dialog.open) dialog.close();
  rows.clear();
  board.replaceChildren();
  $("empty").hidden = true;
  renderStats([]);
  syncPlanAirline();
  preview(true);
  refresh();
}

let frame = 0;
plan.addEventListener("input", () => {
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(() => preview());
});
plan.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
    event.preventDefault();
    form.requestSubmit();
  }
});
$("tidy").addEventListener("click", () => {
  const { body, error } = readPlan();
  if (error) {
    say(`Can't format: ${error.message}`, "err");
    return;
  }
  plan.value = tidy(body);
  plan.scrollLeft = 0;
  preview();
});
$("reset").addEventListener("click", () => {
  plan.value = SAMPLE;
  syncPlanAirline();
  preview(true);
  say(`Sample plan restored for ${current}.`);
});

const detail = async (response) => {
  const body = await response.json().catch(() => null);
  const d = body?.detail;
  if (Array.isArray(d)) return d.map((e) => `${e.loc.join(".")}: ${e.msg}`).join("; ");
  return d ?? `HTTP ${response.status}`;
};

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (filing) return;
  const { body, error } = readPlan();
  if (error) {
    say(`The plan is not valid JSON: ${error.message}`, "err");
    plan.focus();
    return;
  }
  // aria-disabled, not disabled: disabling the focused button would drop keyboard focus.
  const button = $("file");
  filing = true;
  button.setAttribute("aria-disabled", "true");
  say(`Submitting as ${current}…`);
  try {
    const response = await api("/v1/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).catch(() => null);
    if (!response) {
      say("Could not reach the API. Check the connection and try again.", "err");
    } else if (response.ok) {
      const { id } = await response.json();
      highlight = id;
      say(`Job ${id} submitted for ${current}.`, "ok");
      refresh();
    } else {
      say(`Rejected (${response.status}): ${await detail(response)}`, "err");
    }
  } finally {
    filing = false;
    button.removeAttribute("aria-disabled");
  }
});

(async () => {
  const response = await fetch("/v1/tenants").catch(() => null);
  const codes = response?.ok ? await response.json().catch(() => null) : null;
  if (!Array.isArray(codes) || codes.length === 0) {
    say(codes ? "No airlines are configured on this server." : "Could not load airlines: the API is unreachable or failing.", "err");
    setLink(false);
    preview(true);
    return;
  }
  const group = $("airlines");
  codes.forEach((code, i) => {
    const label = tag("label");
    const input = tag("input", "sr-only");
    Object.assign(input, { type: "radio", name: "airline", value: code, checked: i === 0 });
    label.append(input, tag("span", "", code));
    group.append(label);
  });
  group.addEventListener("change", selectAirline);
  selectAirline();
  setInterval(refresh, 2000);
})();
