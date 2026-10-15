// Second Sense frontend demo — captures raw keystroke + mouse events from the
// typing area, batches them every BATCH_INTERVAL_MS, sends them to the
// backend's /sessions/ingest endpoint for scoring, and renders the
// result on the arc dial + live waveform.

const API_BASE = window.SECONDSENSE_API_BASE || "http://localhost:8001";
const BATCH_INTERVAL_MS = 4000;
const DIAL_ARC_LENGTH = 251; // matches the SVG path's stroke-dasharray

let authToken = null;
let eventBuffer = [];

const $ = (id) => document.getElementById(id);

// ---------- auth ----------

function setAuthStatus(text, connected = false) {
  const dotClass = connected ? "dot-on" : "dot-off";
  $("auth-status").innerHTML = `<span class="dot ${dotClass}"></span>${text}`;
}

async function apiRequest(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

  const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${resp.status}`);
  }
  return resp.json();
}

async function signup() {
  const email = $("email").value;
  const password = $("password").value;
  try {
    const data = await apiRequest("/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    authToken = data.access_token;
    setAuthStatus(`connected as ${email}`, true);
  } catch (err) {
    setAuthStatus(`signup failed — ${err.message}`, false);
  }
}

async function login() {
  const email = $("email").value;
  const password = $("password").value;
  try {
    const data = await apiRequest("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    authToken = data.access_token;
    setAuthStatus(`connected as ${email}`, true);
  } catch (err) {
    setAuthStatus(`login failed — ${err.message}`, false);
  }
}

// ---------- event capture ----------

function recordKeyEvent(type) {
  return (e) => {
    eventBuffer.push({ type, timestamp: performance.now(), key: e.key });
    pingWaveform(type === "keydown" ? 1 : 0.5);
  };
}

function recordMouseMove(e) {
  const now = performance.now();
  if (recordMouseMove._last && now - recordMouseMove._last < 40) return;
  recordMouseMove._last = now;
  eventBuffer.push({ type: "mousemove", timestamp: now, x: e.clientX, y: e.clientY });
}

// ---------- dial + waveform rendering ----------

function riskColor(risk) {
  if (risk >= 70) return getComputedStyle(document.documentElement).getPropertyValue("--danger").trim();
  if (risk >= 40) return getComputedStyle(document.documentElement).getPropertyValue("--warn").trim();
  return getComputedStyle(document.documentElement).getPropertyValue("--phosphor").trim();
}

function renderScore(result) {
  const risk = result.risk_score;
  const color = riskColor(risk);

  $("risk-value").textContent = String(Math.round(risk)).padStart(2, "0");
  $("sample-count").textContent = result.baseline_sample_count;

  const statusEl = $("anomaly-status");
  statusEl.textContent = result.is_anomalous ? "anomalous — flagged" : "within baseline";
  statusEl.style.color = result.is_anomalous ? "var(--danger)" : "var(--text)";

  const dialFill = $("dial-fill");
  const offset = DIAL_ARC_LENGTH - (risk / 100) * DIAL_ARC_LENGTH;
  dialFill.style.strokeDashoffset = offset;
  dialFill.style.stroke = color;
  $("risk-value").style.color = color;

  // clear the "no readings yet" placeholder row on first real reading
  const emptyRow = document.querySelector("#log-body .empty-row");
  if (emptyRow) emptyRow.remove();

  const row = document.createElement("tr");
  const time = new Date().toLocaleTimeString();
  row.innerHTML = `
    <td>${time}</td>
    <td style="color:${color}">${risk.toFixed(1)}</td>
    <td class="${result.is_anomalous ? "flag-yes" : "flag-no"}">${result.is_anomalous ? "yes" : "no"}</td>
  `;
  $("log-body").prepend(row);
}

async function flushBuffer() {
  if (!authToken || eventBuffer.length === 0) return;
  const events = eventBuffer;
  eventBuffer = [];

  try {
    const result = await apiRequest("/sessions/ingest", {
      method: "POST",
      body: JSON.stringify({ events }),
    });
    renderScore(result);
  } catch (err) {
    setAuthStatus(`scoring request failed — ${err.message}`, false);
  }
}

// ---------- waveform: the live "rhythm" signature strip ----------
// A simple scrolling line that spikes on each keystroke and eases
// back to baseline — a visual metaphor for the behavioral rhythm
// Second Sense is actually measuring underneath.

let waveformCtx, waveformWidth, waveformHeight;
let waveformLevel = 0.15;
const waveformHistory = [];

function initWaveform() {
  const canvas = $("waveform");
  const dpr = window.devicePixelRatio || 1;
  waveformWidth = canvas.clientWidth;
  waveformHeight = canvas.clientHeight || 64;
  canvas.width = waveformWidth * dpr;
  canvas.height = waveformHeight * dpr;
  waveformCtx = canvas.getContext("2d");
  waveformCtx.scale(dpr, dpr);

  for (let i = 0; i < waveformWidth; i++) waveformHistory.push(0.15);
  requestAnimationFrame(drawWaveform);
}

function pingWaveform(magnitude) {
  waveformLevel = Math.min(1, waveformLevel + magnitude * 0.6);
}

function drawWaveform() {
  waveformLevel *= 0.9; // ease back down
  waveformHistory.push(waveformLevel);
  if (waveformHistory.length > waveformWidth) waveformHistory.shift();

  const ctx = waveformCtx;
  ctx.clearRect(0, 0, waveformWidth, waveformHeight);

  const mid = waveformHeight / 2;
  ctx.beginPath();
  ctx.strokeStyle = "#6ffcb0";
  ctx.lineWidth = 1.5;
  ctx.globalAlpha = 0.85;

  waveformHistory.forEach((v, i) => {
    const y = mid - v * (waveformHeight / 2 - 4) * Math.sin(i * 0.4 + performance.now() * 0.002);
    if (i === 0) ctx.moveTo(i, y);
    else ctx.lineTo(i, y);
  });
  ctx.stroke();

  requestAnimationFrame(drawWaveform);
}

// ---------- init ----------

function init() {
  $("signup-btn").addEventListener("click", signup);
  $("login-btn").addEventListener("click", login);

  const typingArea = $("typing-area");
  typingArea.addEventListener("keydown", recordKeyEvent("keydown"));
  typingArea.addEventListener("keyup", recordKeyEvent("keyup"));
  typingArea.addEventListener("mousemove", recordMouseMove);
  document.addEventListener("mousemove", recordMouseMove);

  setInterval(flushBuffer, BATCH_INTERVAL_MS);
  initWaveform();
}

document.addEventListener("DOMContentLoaded", init);
