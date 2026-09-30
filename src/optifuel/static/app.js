const $ = (id) => document.getElementById(id);
const form = $("submit-form");
const plan = $("plan");
const board = $("jobs");
const pass = $("pass");
const SAMPLE = plan.value;
const SVG = "http://www.w3.org/2000/svg";
const RAD = Math.PI / 180;
const STATUSES = ["succeeded", "running", "queued", "failed"];
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
  $("message-text").textContent = text;
  $("message").className = `radio ${kind}`;
}
function setStamp(state) {
  const stamp = $("stamp");
  stamp.className = `stamp ${state}`;
  stamp.textContent = { ready: "Ready", bad: "Check JSON", filed: "Filed" }[state];
}
function setLink(live) {
  $("link").classList.toggle("lost", !live);
  $("link-text").textContent = live ? `Live · synced ${hms(new Date())}Z` : "Signal lost · retrying";
}
function restartPoll() {
  const bar = $("poll");
  bar.style.animation = "none";
  void bar.offsetWidth;
  bar.style.animation = "";
}

// ---------- Plan preview ----------

function preview(animate = false) {
  const note = $("plan-note");
  const { body, error } = readPlan();
  if (error) {
    setStamp("bad");
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

  setStamp("ready");
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
    svg("text", { x: W / 2, y: H / 2, class: "placeholder", "text-anchor": "middle" }, map, "The route draws itself here");
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

  const rose = svg("g", { class: "rose", transform: `translate(${W - 34} 36)` }, map);
  svg("circle", { r: 17 }, rose);
  svg("path", { d: "M0 -13 L4 2 L0 -1 L-4 2 Z" }, rose);
  svg("text", { y: 12, "text-anchor": "middle" }, rose, "N");

  const at = points.map((w) => [px(w.longitude), py(w.latitude)]);
  const d = at.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  svg("path", { d, class: "halo" }, map);
  svg("path", { d, id: "route-line", class: animate && !reduceMotion ? "leg draw" : "leg", pathLength: 1 }, map);
  for (let i = 1; i < at.length; i++) {
    const [ax, ay] = at[i - 1];
    const [bx, by] = at[i];
    const angle = Math.atan2(by - ay, bx - ax) / RAD;
    svg("path", { d: "M-4 -4 L2 0 L-4 4", class: "chev", transform: `translate(${(ax + bx) / 2} ${(ay + by) / 2}) rotate(${angle})` }, map);
  }

  points.forEach((w, i) => {
    const g = svg("g", { class: "wp", transform: `translate(${at[i][0].toFixed(1)} ${at[i][1].toFixed(1)})` }, map);
    svg("title", {}, g, `Waypoint ${i + 1}: ${w.latitude}, ${w.longitude} · ${w.speed} km/h · ${w.altitude} ft`);
    svg("circle", { r: 7 }, g);
    svg("circle", { r: 2.5, class: "dot" }, g);
    const label = i === 0 ? "DEP" : i === points.length - 1 ? "ARR" : `WP${i + 1}`;
    svg("text", { y: -13, "text-anchor": "middle" }, g, label);
  });

  const plane = svg("g", { class: "plane" }, map);
  svg("use", { href: "#plane", x: -13, y: -11, width: 26, height: 22 }, plane);
  if (reduceMotion) {
    const [[ax, ay], [bx, by]] = at.slice(-2);
    plane.setAttribute("transform", `translate(${bx} ${by}) rotate(${Math.atan2(by - ay, bx - ax) / RAD})`);
  } else {
    const motion = svg("animateMotion", { dur: `${Math.min(14, 5 + points.length)}s`, repeatCount: "indefinite", rotate: "auto" }, plane);
    svg("mpath", { href: "#route-line" }, motion);
  }
}

function drawProfile(points, legs) {
  const chart = $("profile");
  const W = 640;
  const H = 120;
  const top = 28;
  const bottom = 24;
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
  svg("stop", { offset: 0, "stop-color": "#2b5d8f", "stop-opacity": 0.35 }, gradient);
  svg("stop", { offset: 1, "stop-color": "#2b5d8f", "stop-opacity": 0.02 }, gradient);
  const line = alts.map((a, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(a).toFixed(1)}`).join(" ");
  const last = alts.length - 1;
  svg("path", { d: `${line} L${x(last)} ${H - bottom} L${x(0)} ${H - bottom} Z`, fill: "url(#alt-fill)" }, chart);
  svg("line", { x1: side, x2: W - side, y1: H - bottom, y2: H - bottom, class: "ground" }, chart);
  svg("path", { d: line, class: "alt-line" }, chart);
  alts.forEach((a, i) => {
    svg("circle", { cx: x(i), cy: y(a), r: 3.5 }, chart);
    if (alts.length <= 8) {
      const anchor = i === 0 ? "start" : i === last ? "end" : "middle";
      svg("text", { x: x(i), y: y(a) - 9, "text-anchor": anchor }, chart, `${num(a)} ft`);
    }
  });
  svg("text", { x: side, y: H - 7 }, chart, "0 km");
  svg("text", { x: W / 2, y: H - 7, "text-anchor": "middle" }, chart, "Vertical profile");
  if (cumulative.at(-1) > 0) {
    svg("text", { x: W - side, y: H - 7, "text-anchor": "end" }, chart, `${num(cumulative.at(-1))} km`);
  }
}

// ---------- Departures board ----------

function statusBadge(target, status, flaps) {
  target.dataset.status = status;
  const lamp = tag("span", "lamp");
  lamp.setAttribute("aria-hidden", "true");
  const nodes = [lamp, tag("span", flaps ? "st-text" : "", status)];
  if (flaps) {
    const tiles = tag("span", "flaps");
    tiles.setAttribute("aria-hidden", "true");
    [...status.toUpperCase().padEnd(9)].forEach((ch, i) => {
      const tile = tag("span", "", ch);
      tile.style.setProperty("--i", i);
      tiles.append(tile);
    });
    nodes.push(tiles);
  }
  target.replaceChildren(...nodes);
}

function outcome(job) {
  if (job.result) {
    const fuel = tag("span", "fuel");
    fuel.append(tag("b", "", num(job.result.total_fuel_lb, 1)), tag("small", "", "lb"));
    return fuel;
  }
  if (job.error) {
    const error = tag("span", "job-error", job.error);
    error.title = job.error;
    return error;
  }
  return tag("span", "pending", job.status === "running" ? "estimating…" : "waiting for a worker");
}

function makeRow(id, index) {
  const tr = document.createElement("tr");
  tr.style.setProperty("--row", index);
  const head = tag("th");
  head.scope = "row";
  const button = tag("button", "job-btn");
  button.type = "button";
  const hash = tag("span", "hash", "#");
  hash.setAttribute("aria-hidden", "true");
  button.append(tag("span", "sr-only", "Job "), hash, String(id), tag("span", "sr-only", ", details"));
  button.addEventListener("click", () => openPass(id));
  head.append(button);
  const cells = { flight: tag("td"), status: tag("td"), attempts: tag("td", "attempts"), outcome: tag("td") };
  tr.append(head, ...Object.values(cells));
  return { tr, ...cells, job: null };
}

function updateRow(row, job) {
  const before = row.job;
  row.job = job;
  if (before && JSON.stringify(before) === JSON.stringify(job)) return;
  row.tr.dataset.status = job.status;
  row.flight.replaceChildren(tag("span", "carrier", job.airline), ` ${job.flight_id}`);
  if (before?.status !== job.status) {
    const badge = tag("span", "status");
    statusBadge(badge, job.status, true);
    row.status.replaceChildren(badge);
  }
  row.attempts.textContent = job.attempts;
  row.outcome.replaceChildren(outcome(job));
  if (openJob === job.id) fillPass(job);
}

function flash(tr) {
  tr.classList.remove("fresh");
  void tr.offsetWidth;
  tr.classList.add("fresh");
}

function renderJobs(list) {
  let created = 0;
  const ordered = list.map((job) => {
    let row = rows.get(job.id);
    if (!row) {
      row = makeRow(job.id, created++);
      rows.set(job.id, row);
    }
    updateRow(row, job);
    if (job.id === highlight) {
      flash(row.tr);
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
  // Move only rows out of place: reattaching replays their animations and blurs focus.
  ordered.forEach((tr, i) => {
    if (board.children[i] !== tr) board.insertBefore(tr, board.children[i] ?? null);
  });
  $("empty").hidden = list.length > 0;
}

function renderGauges(list) {
  const counts = Object.fromEntries(STATUSES.map((s) => [s, 0]));
  for (const job of list) counts[job.status] += 1;
  let offset = 0;
  for (const status of STATUSES) {
    const share = list.length ? (counts[status] / list.length) * 100 : 0;
    const arc = $(`arc-${status}`);
    arc.setAttribute("stroke-dasharray", `${share} ${100 - share}`);
    arc.setAttribute("stroke-dashoffset", -offset);
    offset += share;
    $(`count-${status}`).textContent = counts[status];
  }
  $("donut-total").textContent = list.length;
  $("fuel-total").textContent = num(list.reduce((sum, job) => sum + (job.result?.total_fuel_lb ?? 0), 0), 1);
  $("fuel-caption").textContent = list.length
    ? `from ${counts.succeeded} succeeded ${counts.succeeded === 1 ? "job" : "jobs"}`
    : "estimated fuel on the board";
}

async function refresh() {
  const code = current;
  if (!code) return;
  let list;
  try {
    const response = await api("/v1/jobs");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    list = await response.json();
  } catch {
    if (code === current) setLink(false);
    return;
  }
  // A poll started before an airline switch must not paint the old airline's jobs.
  if (code !== current) return;
  setLink(true);
  renderJobs(list);
  renderGauges(list);
}

// ---------- Boarding pass ----------

function fillPass(job) {
  const result = job.result;
  $("p-id").textContent = `#${job.id}`;
  $("p-airline").textContent = job.airline;
  $("p-flight").textContent = job.flight_id;
  statusBadge($("p-status"), job.status, false);
  $("p-attempts").textContent = job.attempts;
  $("p-model").textContent = result?.model_version ?? "—";
  $("p-distance").textContent = result ? `${num(result.distance_km, 1)} km` : "—";
  $("p-duration").textContent = result ? airTime(result.duration_h) : "—";
  $("p-submitted").textContent = when(job.submitted_at);
  $("p-finished").textContent = when(job.finished_at);
  $("p-fuel").textContent = result ? num(result.total_fuel_lb, 1) : "—";
  const error = $("p-error");
  error.hidden = !job.error;
  error.textContent = job.error ?? "";

  const code = $("p-barcode");
  code.replaceChildren();
  const seed = `${job.airline}-${job.id}-${job.flight_id}`;
  for (let x = 0, h = 7, i = 0; x < 120; i++) {
    h = (h * 31 + seed.charCodeAt(i % seed.length)) % 997;
    const width = 1 + (h % 3);
    if (h % 2 === 0) svg("rect", { x, y: 0, width, height: 40 }, code);
    x += width;
  }
}

function openPass(id) {
  const row = rows.get(id);
  if (!row) return;
  openJob = id;
  fillPass(row.job);
  if (!pass.open) pass.showModal();
}
pass.addEventListener("close", () => { openJob = null; });
pass.addEventListener("click", (event) => { if (event.target === pass) pass.close(); });

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
  if (pass.open) pass.close();
  rows.clear();
  board.replaceChildren();
  $("empty").hidden = true;
  renderGauges([]);
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
    say(`Can't tidy: ${error.message}`, "err");
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
  say(`Filing plan as ${current}…`);
  try {
    const response = await api("/v1/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).catch(() => null);
    if (!response) {
      say("Could not reach the API. Check the connection and file again.", "err");
    } else if (response.ok) {
      const { id } = await response.json();
      highlight = id;
      setStamp("filed");
      say(`Job ${id} filed for ${current}. Watch it on the departures board.`, "ok");
      refresh();
    } else {
      say(`Rejected (${response.status}): ${await detail(response)}`, "err");
    }
  } finally {
    filing = false;
    button.removeAttribute("aria-disabled");
  }
});

const tick = () => { $("clock").textContent = hms(new Date()); };
tick();
setInterval(tick, 1000);

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
    const label = tag("label", "tag");
    label.style.setProperty("--tag-hue", hueOf(code));
    const input = tag("input", "sr-only");
    Object.assign(input, { type: "radio", name: "airline", value: code, checked: i === 0 });
    label.append(input, tag("span", "", code));
    group.append(label);
  });
  group.addEventListener("change", selectAirline);
  selectAirline();
  setInterval(() => {
    restartPoll();
    refresh();
  }, 2000);
})();
