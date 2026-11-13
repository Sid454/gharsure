// GharSure AI frontend: vanilla JS + Leaflet (OpenStreetMap)
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const inr = (n) => "₹" + Number(n || 0).toLocaleString("en-IN");
const shortInr = (n) => (n >= 100000 ? "₹" + (n / 100000).toFixed(1) + "L" : "₹" + Math.round(n / 1000) + "k");
const today = () => new Date().toISOString().slice(0, 10);
const addDays = (d) => new Date(Date.now() + d * 864e5).toISOString().slice(0, 10);
const LEVEL = { low: "✓ Verified safe", medium: "⚠ Check carefully", high: "✕ High risk" };

const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch { /* blocked */ } },
};
let META = null;
let exploreMap, pickMap, pickMarker;
const markers = {};

async function api(path, opts = {}) {
  const session = store.get("gharsure_session");
  if (session) opts = { ...opts, headers: { ...(opts.headers || {}), Authorization: "Bearer " + session } };
  const res = await fetch(path, opts);
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) {
    let msg = body?.detail ?? res.statusText;
    if (Array.isArray(msg)) msg = msg.map((e) => e.msg.replace(/^Value error, /, "")).join("; ");
    throw new Error(msg);
  }
  return body;
}
const postJSON = (path, data) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (err ? " err" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.className = "toast hidden"), 3500);
}
async function busy(btn, fn) {
  btn.disabled = true;
  try { await fn(); } catch (e) { toast(e.message, true); } finally { btn.disabled = false; }
}
function openModal(html) { $("#modal-body").innerHTML = html; $("#modal").classList.remove("hidden"); }
function closeModal() {
  $("#modal").classList.add("hidden"); $("#modal-body").innerHTML = "";
  if (location.hash.startsWith("#listing=")) history.replaceState(null, "", "#explore");
}
$("#modal .close").onclick = closeModal;
$("#modal").onclick = (e) => { if (e.target.id === "modal") closeModal(); };

// ---------------- routing (#explore, #post, #listing=id, #booking=id, #owner=token) ----------------
function route() {
  if (location.hash.startsWith("#own-")) { document.getElementById(location.hash.slice(1))?.scrollIntoView({ behavior: "smooth" }); history.replaceState(null, "", "#owner"); return; }
  const h = location.hash.slice(1) || "explore";
  const [key, val] = h.split("=");
  const tab = { listing: "explore", owner: "owner" }[key] || key;
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + tab));
  $$("#nav a, #tabbar a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
  if (key !== "listing") window.scrollTo(0, 0);
  if (tab === "explore") { setTimeout(fitExplore, 50); if (key === "listing" && val) showListing(val); }
  if (tab === "post") setTimeout(() => pickMap?.invalidateSize(), 50);
  if (key === "booking") { renderMyBookings(); if (val) { $("#booking-lookup [name=id]").value = val; loadBooking(val); } else $("#booking-view").innerHTML = ""; }
  if (key === "owner") { const t = val || ME?.owner_token; if (t) loadOwner(t); else $("#owner-view").innerHTML = `<div class="card authbox"><h3>Owner dashboard</h3><p>Sign in as an owner to manage your flats, visit requests, tenants and bills.</p><a class="btn primary" href="#account">Sign in / Create account</a></div>`; }
  if (key === "roommates") loadRoommates(val || ME?.roommate_token);
  if (key === "account") renderAccount();
  if (key === "post" && ME) { const f = $("#post-form"); if (!f.owner_name.value) f.owner_name.value = ME.name; if (!f.owner_phone.value) f.owner_phone.value = ME.phone; }
}
window.addEventListener("hashchange", route);

// ---------------- setup ----------------
function fillCity(sel, withBlank) {
  sel.innerHTML = (withBlank ? `<option value="">${withBlank}</option>` : "") +
    Object.keys(META.cities).map((c) => `<option>${esc(c)}</option>`).join("");
}
function fillLocality(citySel, locSel, blank) {
  const c = META.cities[citySel.value];
  locSel.innerHTML = (blank ? `<option value="">${blank}</option>` : "") +
    (c ? c.localities.map((l) => `<option>${esc(l)}</option>`).join("") : "");
}

async function init() {
  META = await api("/api/meta");
  fillCity($("#f-city"), "All cities");
  fillCity($("#p-city"));
  fillCity($("#c-city"), "Unknown");
  fillLocality($("#p-city"), $("#p-locality"));
  $("#p-city").onchange = () => { fillLocality($("#p-city"), $("#p-locality")); centerPick(); };
  $("#c-city").onchange = () => fillLocality($("#c-city"), $("#c-locality"), "Unknown");

  exploreMap = L.map("map").setView([21.5, 78.5], 5);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(exploreMap);

  pickMap = L.map("pick-map");
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(pickMap);
  pickMap.on("click", (e) => setPick(e.latlng));
  centerPick();

  initChat();
  await loadMe();
  renderNav();
  route();
  await search();
}

// ---------------- accounts & modes (Owner / Renter) ----------------
let ME = null;
const getMode = () => store.get("gharsure_mode") || ME?.default_mode || "renter";

const TABS = {
  renter: [["explore", "Explore"], ["roommates", "Roommates"], ["booking", "My bookings"], ["check", "Scam check"], ["ask", "Ask AI"]],
  owner: [["owner", "Dashboard"], ["post", "Add flat"], ["check", "Scam check"], ["ask", "Ask AI"]],
};
const MOBILE_TABS = {
  owner: [["owner", "📊", "Dashboard"], ["check", "🛡️", "Scam check"], ["post", "＋", "Add flat", true], ["ask", "💬", "Ask AI"], ["account", "👤", "Account"]],
  renter: [["explore", "🏠", "Explore"], ["roommates", "👥", "Roommates"], ["check", "🛡️", "Check", true], ["booking", "📅", "Bookings"], ["account", "👤", "Account"]],
};

function renderNav() {
  const mode = getMode();
  $("#nav").innerHTML = TABS[mode].map(([t, label]) => `<a href="#${t}" data-tab="${t}">${label}</a>`).join("");
  $("#tabbar").innerHTML = MOBILE_TABS[mode].map(([t, icon, label, fab]) =>
    `<a href="#${t}" data-tab="${t}" ${fab ? 'class="fab"' : ""}><span>${icon}</span>${label}</a>`).join("");
  $("#mode-switch").classList.toggle("hidden", !ME);
  $$("#mode-switch button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
  $("#acct-btn").textContent = ME ? "👤 " + ME.name.split(" ")[0] : "Sign in";
}

$$("#mode-switch button").forEach((b) => (b.onclick = () => {
  store.set("gharsure_mode", b.dataset.mode);
  renderNav();
  const target = b.dataset.mode === "owner" ? "owner" : "explore";
  if (location.hash === "#" + target) route(); else location.hash = target;
}));

async function loadMe() {
  if (!store.get("gharsure_session")) { ME = null; return; }
  try { ME = await api("/api/auth/me"); } catch { ME = null; store.set("gharsure_session", null); }
}

async function signedIn(session, mode) {
  store.set("gharsure_session", session);
  await loadMe();
  store.set("gharsure_mode", mode || ME.default_mode);
  renderNav();
  toast(`Welcome, ${ME.name.split(" ")[0]}!`);
  location.hash = getMode() === "owner" ? "owner" : "explore";
}

function renderAccount() {
  const v = $("#account-view");
  if (!ME) {
    v.innerHTML = `<div class="authbox">
      <div class="rm-hero"><h2>Welcome to GharSure</h2><p>One account for everything: rent a flat, find roommates, or list your own flat as an owner.</p></div>
      <div class="authtabs"><button class="btn primary" data-auth="signup">Create account</button><button class="btn" data-auth="login">Sign in</button></div>
      <form id="auth-form" class="card form"></form></div>`;
    const draw = (kind) => {
      $$("[data-auth]").forEach((b) => (b.className = "btn" + (b.dataset.auth === kind ? " primary" : "")));
      $("#auth-form").dataset.kind = kind;
      $("#auth-form").innerHTML = kind === "signup" ? `
        <div class="full"><span class="lbl">I mainly want to…</span><div class="rolepick">
          <label><input type="radio" name="mode" value="renter" checked><span>🔑</span>Rent a flat / find roommate</label>
          <label><input type="radio" name="mode" value="owner"><span>🏠</span>List my flat (Owner)</label></div>
          <p class="small muted">You can switch between Owner and Renter anytime.</p></div>
        <label class="full">Full name<input name="name" required minlength="2" autocomplete="name"></label>
        <label class="full">Phone<input name="phone" required placeholder="10-digit mobile" autocomplete="tel"></label>
        <label class="full">Password<input name="password" type="password" required minlength="6" autocomplete="new-password"></label>
        <button class="btn primary full">Create account</button>` : `
        <label class="full">Phone<input name="phone" required autocomplete="tel"></label>
        <label class="full">Password<input name="password" type="password" required autocomplete="current-password"></label>
        <button class="btn primary full">Sign in</button>`;
    };
    $$("[data-auth]").forEach((b) => (b.onclick = () => draw(b.dataset.auth)));
    draw("signup");
    $("#auth-form").onsubmit = (e) => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(e.target));
      busy(e.submitter, async () => {
        const kind = e.target.dataset.kind;
        const r = await postJSON(kind === "signup" ? "/api/auth/signup" : "/api/auth/login", data);
        await signedIn(r.session, data.mode);
      });
    };
    return;
  }
  const mode = getMode();
  v.innerHTML = `<div class="card"><div style="display:flex;gap:14px;align-items:center">
      <div class="avatar" style="background:${COLORS[ME.name.charCodeAt(0) % COLORS.length]}">${esc(ME.name[0])}</div>
      <div><h2 style="margin:0">${esc(ME.name)}</h2><div class="muted">${esc(ME.phone)}</div></div></div>
      <h3 style="margin-top:18px">Mode</h3>
      <div class="rolepick"><label><input type="radio" name="m" value="renter" ${mode === "renter" ? "checked" : ""}><span>🔑</span>Renter</label>
        <label><input type="radio" name="m" value="owner" ${mode === "owner" ? "checked" : ""}><span>🏠</span>Owner</label></div></div>
    <div class="card"><h3>Quick links</h3>
      <a class="bookrow" href="#owner"><span>📊 Owner dashboard</span><span class="muted">${ME.listings} flat(s) ›</span></a>
      <a class="bookrow" href="#booking"><span>📅 My bookings</span><span class="muted">${ME.bookings.length} ›</span></a>
      <a class="bookrow" href="#roommates"><span>👥 Roommate profile</span><span class="muted">${ME.roommate_token ? "Active" : "Create"} ›</span></a>
      <a class="bookrow" href="#ask"><span>💬 Rental safety assistant</span><span class="muted">›</span></a></div>
    <button class="btn" id="logout" style="width:100%">Sign out</button>`;
  $$("[name=m]").forEach((r) => (r.onchange = () => { store.set("gharsure_mode", r.value); renderNav(); }));
  $("#logout").onclick = async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    store.set("gharsure_session", null); store.set("gharsure_mode", null); ME = null;
    renderNav(); location.hash = "explore"; toast("Signed out");
  };
}

function renderMyBookings() {
  const box = $("#my-bookings");
  if (!ME) { box.innerHTML = `<div class="card small muted"><a href="#account">Sign in</a> to see all your bookings here, or open one with its booking ID below.</div>`; return; }
  if (!ME.bookings.length) { box.innerHTML = `<div class="card muted">No bookings yet. Explore flats and request a visit.</div>`; return; }
  box.innerHTML = `<div class="card"><h3>Your bookings</h3>${ME.bookings.map((b) => `
    <a class="bookrow" href="#booking=${esc(b.id)}"><span><b>${esc(b.title)}</b><br><span class="small muted">${esc(b.locality)}, ${esc(b.city)} · visit ${esc(b.visit_date)}</span></span>
      <span class="badge ${b.moved_in ? "accepted" : esc(b.status)}">${b.moved_in ? "living here" : esc(b.status)}</span></a>`).join("")}</div>`;
}

// ---------------- explore ----------------
async function search(e) {
  e?.preventDefault();
  const params = new URLSearchParams([...new FormData($("#search"))].filter(([, v]) => v));
  const list = await api("/api/listings?" + params);
  $("#result-count").textContent = `${list.length} vacant flat${list.length === 1 ? "" : "s"} found`;
  $("#cards").innerHTML = list.length ? list.map(cardHTML).join("") :
    `<div class="card">No vacant flats match. Try another city or a higher budget.</div>`;
  $$(".lcard").forEach((c) => {
    c.onclick = () => (location.hash = "listing=" + c.dataset.id);
    c.onmouseenter = () => markers[c.dataset.id]?.getElement()?.querySelector(".pricepin")?.classList.add("on");
    c.onmouseleave = () => markers[c.dataset.id]?.getElement()?.querySelector(".pricepin")?.classList.remove("on");
  });
  Object.values(markers).forEach((m) => m.remove());
  for (const k in markers) delete markers[k];
  list.forEach((l) => {
    const icon = L.divIcon({ className: "", html: `<div class="pricepin">${shortInr(l.rent)}</div>`, iconSize: null });
    markers[l.id] = L.marker([l.lat, l.lng], { icon }).addTo(exploreMap)
      .bindPopup(`<b>${esc(l.title)}</b><br>${esc(l.locality)} · ${l.bhk} BHK<br><b>${inr(l.rent)}</b>/month<br>
        <span style="color:#0f9d58">● Vacant</span><br><a href="#listing=${l.id}">View & book visit →</a>`);
  });
  lastBounds = list.length ? L.latLngBounds(list.map((l) => [l.lat, l.lng])).pad(0.2) : null;
  fitExplore();
}
let lastBounds = null;
function fitExplore() {
  if (!exploreMap) return;
  exploreMap.invalidateSize();
  if (lastBounds) exploreMap.fitBounds(lastBounds, { maxZoom: 13 });
}
$("#search").onsubmit = search;

function dealText(l) {
  const f = l.safety.fair_rent;
  if (!f) return "";
  const gap = Math.round(((l.rent - f) / f) * 100);
  if (gap <= -5) return `<div class="deal">${Math.abs(gap)}% below area average</div>`;
  if (gap >= 10) return `<div class="small muted">${gap}% above area average</div>`;
  return `<div class="small muted">Fair price for the area</div>`;
}

function cardHTML(l) {
  return `<div class="lcard" data-id="${l.id}">
    <div class="img"><div class="ph" style="background-image:url('${esc(l.photos[0] || "")}')"></div><span class="badge ${l.safety.level}">${LEVEL[l.safety.level]}</span>
      <span class="pricechip">${inr(l.rent)} <small>/ month</small></span></div>
    <div class="body">
      <div class="title">${esc(l.title)}</div>
      <div class="muted small">${esc(l.locality)}, ${esc(l.city)} · ${l.bhk} BHK · ${l.sqft} sq ft · ${esc(l.furnishing)}</div>
      ${dealText(l)}
    </div></div>`;
}

async function showListing(id) {
  let l;
  try { l = await api("/api/listings/" + id); } catch (e) { toast(e.message, true); return; }
  const [main, ...rest] = l.photos;
  openModal(`
    <h2>${esc(l.title)}</h2>
    <div class="muted">${esc(l.locality)}, ${esc(l.city)} · Listed by owner ${esc(l.owner_name)} ·
      <span class="badge ${l.available ? "vacant" : "rented"}">${l.available ? "Vacant now" : "Rented out"}</span></div>
    <div class="gallery"><img src="${esc(main)}" alt="Main photo"><div class="side">${rest.slice(0, 2).map((p) => `<img src="${esc(p)}" alt="Photo">`).join("")}</div></div>
    <div class="detail">
      <div>
        <div class="facts">
          <div>${l.bhk} BHK<span>Bedrooms</span></div><div>${l.sqft} sq ft<span>Area</span></div>
          <div>${esc(l.furnishing)}<span>Furnishing</span></div><div>No brokerage<span>Direct owner</span></div>
        </div>
        <p style="white-space:pre-line">${esc(l.description)}</p>
        <div class="safety ${l.safety.level}"><b>${LEVEL[l.safety.level]}</b> · AI risk score ${l.safety.score}/100<br>
          <span class="small">Photos are original, the rent is in line with the area${l.safety.fair_rent ? ` (fair rent ≈ ${inr(l.safety.fair_rent)})` : ""}, and the description has no scam patterns.</span></div>
        <h3>Location</h3><div id="minimap" class="minimap"></div>
      </div>
      <div class="bookbox">
        <div class="price">${inr(l.rent)} <small>/ month</small></div>
        <p class="small muted">Request a visit. The owner's number is shared once they accept. <b>Never pay before visiting.</b></p>
        <form id="book-form" class="form">
          <label>Visit date<input type="date" name="visit_date" min="${today()}" value="${addDays(1)}" required></label>
          <label>Move-in date<input type="date" name="move_in_date" min="${today()}" value="${addDays(7)}" required></label>
          <label>Your name<input name="name" required minlength="2"></label>
          <label>Phone<input name="phone" required placeholder="10-digit mobile"></label>
          <label class="full">Occupants<select name="occupants">${[1, 2, 3, 4, 5, 6].map((n) => `<option>${n}</option>`).join("")}</select></label>
          <label class="full">Message to owner<textarea name="message" rows="2" placeholder="About you, profession, preferred visit time"></textarea></label>
          <button class="btn primary full" ${l.available ? "" : "disabled"}>Request to book visit</button>
        </form>
      </div>
    </div>`);
  $$(".gallery img").forEach((img) => (img.onclick = () => window.open(img.src, "_blank")));
  const mm = L.map("minimap", { scrollWheelZoom: false }).setView([l.lat, l.lng], 14);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(mm);
  L.circle([l.lat, l.lng], { radius: 250, color: "#ff385c" }).addTo(mm); // approx area until booking is accepted
  setTimeout(() => mm.invalidateSize(), 100);
  $("#book-form").onsubmit = (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target));
    busy(e.submitter, async () => {
      const r = await postJSON("/api/bookings", { ...data, listing_id: l.id, occupants: Number(data.occupants) });
      remember("bookings", r.booking_id);
      $(".bookbox").innerHTML = `<h3>🎉 Request sent!</h3>
        <p>The owner will accept or suggest another time. Your booking ID:</p><div class="copy">${esc(r.booking_id)}</div>
        <p class="small muted">Save it. You'll use it to track the booking and later to pay rent & bills.</p>
        <a class="btn primary full" href="#booking=${esc(r.booking_id)}" onclick="document.getElementById('modal').classList.add('hidden')">Track my booking</a>`;
    });
  };
}

// ---------------- post a listing (owner) ----------------
function centerPick() {
  const c = META.cities[$("#p-city").value]?.center || [21.5, 78.5];
  pickMap.setView(c, 12);
  setPick({ lat: c[0], lng: c[1] });
}
function setPick(ll) {
  if (pickMarker) pickMarker.setLatLng(ll); else pickMarker = L.marker(ll, { draggable: true }).addTo(pickMap).on("dragend", (e) => setPick(e.target.getLatLng()));
  pickMarker._ll = ll;
  $("#pick-coords").textContent = `📍 ${ll.lat.toFixed(5)}, ${ll.lng.toFixed(5)}`;
}
$("#p-photos").onchange = (e) => {
  $("#p-previews").innerHTML = [...e.target.files].slice(0, 6).map((f) => `<img src="${URL.createObjectURL(f)}" alt="">`).join("");
};
$("#post-form").onsubmit = (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  fd.set("lat", pickMarker._ll.lat);
  fd.set("lng", pickMarker._ll.lng);
  busy($("#post-btn"), async () => {
    const r = await api("/api/listings", { method: "POST", body: fd });
    remember("owner", r.owner_token);
    if (ME) await loadMe();
    const link = `${location.origin}/#owner=${r.owner_token}`;
    $("#post-result").innerHTML = r.published
      ? `<div class="card"><h3>✅ Your flat is live!</h3>${riskHTML(r.risk)}
          <p><b>Your private owner dashboard link</b>. Bookmark it; it's how you manage requests, tenants and bills:</p>
          <div class="copy">${esc(link)}</div><p><a class="btn primary" href="#owner=${esc(r.owner_token)}">Open owner dashboard</a></p></div>`
      : `<div class="card"><h3>⛔ Listing held for review</h3><p>Our AI found serious problems with this listing, so it is not shown to tenants.</p>${riskHTML(r.risk)}</div>`;
    e.target.reset(); $("#p-previews").innerHTML = ""; fillLocality($("#p-city"), $("#p-locality"));
    $("#post-result").scrollIntoView({ behavior: "smooth" });
    search();
  });
};

// ---------------- scam check ----------------
function riskHTML(r) {
  const color = { low: "var(--ok)", medium: "var(--warn)", high: "var(--bad)" }[r.level];
  const pct = r.score * 3.6;
  return `<div class="gauge">
      <div class="ring" style="background:conic-gradient(${color} ${pct}deg,#eef0f5 0);"><div style="background:#fff;width:84px;height:84px;border-radius:50%;display:grid;place-items:center;color:${color}">${r.score}</div></div>
      <div><h3 style="color:${color}">${{ low: "Low risk", medium: "Medium risk: be careful", high: "High risk: likely a scam" }[r.level]}</h3>
        ${r.price ? `<div>Listed ${inr(r.price.listed_rent)} vs AI fair rent ${inr(r.price.fair_rent)} (${r.price.gap_percent > 0 ? "+" : ""}${r.price.gap_percent}%)</div>` : ""}
        <div class="small muted">${esc(r.disclaimer)}</div></div></div>
    <ul class="reasons">${r.reasons.map((x) => `<li class="${x.severity}"><b>${esc(x.signal)}</b>: ${esc(x.detail)}</li>`).join("")}</ul>`;
}
$("#check-form").onsubmit = (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  for (const [k, v] of [...fd]) if (v === "" || (v instanceof File && !v.name)) fd.delete(k);
  busy(e.submitter, async () => {
    const r = await api("/api/check", { method: "POST", body: fd });
    $("#check-result").innerHTML = `<div class="card">${riskHTML(r)}</div>`;
    $("#check-result").scrollIntoView({ behavior: "smooth" });
  });
};
$("#report-form").onsubmit = (e) => {
  e.preventDefault();
  busy(e.submitter, async () => {
    const r = await postJSON("/api/report", Object.fromEntries(new FormData(e.target)));
    toast(`Reported. This number now has ${r.total_reports} report(s).`);
    e.target.reset();
  });
};

// ---------------- tenant: booking + rent & bills ----------------
$("#booking-lookup").onsubmit = (e) => { e.preventDefault(); location.hash = "booking=" + e.target.id.value.trim(); };

async function loadBooking(id) {
  const v = $("#booking-view");
  let b;
  try { b = await api("/api/bookings/" + encodeURIComponent(id)); } catch (e) { v.innerHTML = `<div class="card">${esc(e.message)}</div>`; return; }
  const steps = [["Requested", true], ["Owner accepted", b.status === "accepted"], ["Moved in", b.moved_in]];
  v.innerHTML = `<div class="card">
      <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap"><h3>${esc(b.title)}</h3><span class="badge ${b.status}">${esc(b.status)}</span></div>
      <div class="muted">${esc(b.locality)}, ${esc(b.city)} · ${inr(b.rent)}/month · Visit ${esc(b.visit_date)} · Move-in ${esc(b.move_in_date)}</div>
      <div class="timeline">${steps.map(([s, d]) => `<div class="${d ? "done" : ""}">${s}</div>`).join("")}</div>
      ${b.owner_note ? `<div class="notice">Owner's note: ${esc(b.owner_note)}</div>` : ""}
      ${b.owner ? `<h3>Connect with the owner</h3><div>${esc(b.owner.name)} · ${esc(b.owner.phone)}</div>
        <div class="contact"><a class="btn primary" href="tel:+91${esc(b.owner.phone)}">📞 Call</a>
        <a class="btn ok" target="_blank" rel="noopener" href="${esc(b.owner.whatsapp)}">💬 WhatsApp</a>
        <a class="btn" target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&destination=${b.owner.lat},${b.owner.lng}">🧭 Directions</a></div>
        <p class="small muted">Visit first, check the owner's ID and property papers, sign the agreement, then pay.</p>` :
        b.status === "pending" ? `<p class="muted">Waiting for the owner to respond. Their number will appear here once they accept.</p>` : ""}
      ${["pending", "accepted"].includes(b.status) && !b.moved_in ? `<button class="btn sm" id="cancel-b">Cancel booking</button>` : ""}
    </div><div id="bills-view"></div>`;
  $("#cancel-b") && ($("#cancel-b").onclick = (e) => busy(e.target, async () => {
    if (!confirm("Cancel this booking?")) return;
    await postJSON(`/api/bookings/${encodeURIComponent(id)}/cancel`, {}); loadBooking(id);
  }));
  if (b.moved_in) loadTenantBills(id);
}

function summaryHTML(s) {
  return `<div class="stats">
    <div class="stat"><b>${inr(s.deposit_held)}</b><span>Security deposit held by owner</span></div>
    <div class="stat"><b>${inr(s.total_due)}</b><span>Due now${s.overdue_count ? ` · ${s.overdue_count} overdue` : ""}</span></div>
    <div class="stat"><b>${inr(s.awaiting_confirmation)}</b><span>Paid, awaiting owner confirmation</span></div>
    <div class="stat"><b>${inr(s.total_paid)}</b><span>Total paid</span></div></div>`;
}
const billStatus = (b) => (b.overdue ? `<span class="badge overdue">overdue</span>` : `<span class="badge ${b.status}">${b.status === "submitted" ? "awaiting confirmation" : b.status}</span>`);
const KIND = { rent: "🏠 Rent", water: "💧 Water", electricity: "⚡ Electricity", maintenance: "🛠 Maintenance", other: "📄 Other" };

async function loadTenantBills(bookingId) {
  const d = await api(`/api/tenancy/${encodeURIComponent(bookingId)}`);
  $("#bills-view").innerHTML = `<div class="card"><h3>Rent & bills</h3>
    <div class="muted small">Pay directly to your owner's UPI (${esc(d.tenancy.owner_upi)}). GharSure never holds your money.</div>
    ${summaryHTML(d.summary)}
    <div class="tablewrap"><table><tr><th>Bill</th><th>Period</th><th>Amount</th><th>Due</th><th>Status</th><th></th></tr>
    ${d.bills.map((b) => `<tr><td>${KIND[b.kind]}<div class="small muted mobile-only">${esc(b.period)}</div>${b.note ? `<div class="small muted">${esc(b.note)}</div>` : ""}</td><td>${esc(b.period)}</td><td><b>${inr(b.amount)}</b></td><td>${esc(b.due_date)}</td><td>${billStatus(b)}</td>
      <td>${b.status === "due" ? `<button class="btn primary sm" data-pay="${b.id}">Pay</button>` : b.utr ? `<span class="small muted">UTR ${esc(b.utr)}</span>` : ""}</td></tr>`).join("")}
    </table></div></div>`;
  $$("[data-pay]").forEach((btn) => (btn.onclick = () => payModal(bookingId, d.bills.find((b) => b.id === btn.dataset.pay), d.tenancy.owner_upi)));
}

function payModal(bookingId, b, upi) {
  openModal(`<h2>Pay ${KIND[b.kind]} · ${esc(b.period)}</h2>
    <div class="qr"><img src="/api/tenancy/${encodeURIComponent(bookingId)}/bills/${b.id}/qr.png" alt="UPI QR code">
    <div><div class="price">${inr(b.amount)}</div><p>To owner's UPI: <b>${esc(upi)}</b></p>
      <p class="small muted">Scan with GPay / PhonePe / Paytm, or tap below on your phone. Check that the name shown in your UPI app matches your owner.</p>
      <a class="btn ok" href="${esc(b.upi_link)}">Open UPI app</a></div></div>
    <form id="utr-form" class="card form" style="margin-top:18px"><label class="full">After paying, enter the 12-digit UPI reference (UTR)<input name="utr" required pattern="[A-Za-z0-9]{8,22}" placeholder="e.g. 412345678901"></label>
    <button class="btn primary full">I have paid</button></form>`);
  $("#utr-form").onsubmit = (e) => {
    e.preventDefault();
    busy(e.submitter, async () => {
      await postJSON(`/api/tenancy/${encodeURIComponent(bookingId)}/bills/${b.id}/paid`, { utr: e.target.utr.value.trim() });
      closeModal(); toast("Marked as paid. The owner will confirm."); loadTenantBills(bookingId);
    });
  };
}

// ---------------- owner dashboard ----------------
async function loadOwner(token) {
  const v = $("#owner-view");
  let d;
  try { d = await api("/api/owner/" + encodeURIComponent(token)); } catch (e) { v.innerHTML = `<div class="card">${esc(e.message)}</div>`; return; }
  const T = encodeURIComponent(token);
  const pending = d.bookings.filter((b) => b.status === "pending").length;
  const bills = d.tenancies.flatMap((t) => t.bills);
  const thisMonth = new Date().toISOString().slice(0, 7);
  const collected = bills.filter((b) => b.status === "paid" && (b.confirmed_at || "").startsWith(thisMonth)).reduce((a, b) => a + b.amount, 0);
  const dues = bills.filter((b) => b.status !== "paid").reduce((a, b) => a + b.amount, 0);
  const toConfirm = bills.filter((b) => b.status === "submitted").length;
  const deposits = d.tenancies.filter((t) => t.tenancy.status === "active").reduce((a, t) => a + t.summary.deposit_held, 0);
  v.innerHTML = `<h2>Namaste, ${esc(d.owner_name.split(" ")[0])} 👋</h2>
    <p class="muted">${pending ? `<b>${pending} new visit request(s)</b> waiting. ` : ""}${toConfirm ? `<b>${toConfirm} payment(s)</b> to confirm.` : ""}</p>
    <div class="stats">
      <div class="stat"><b>${d.listings.length}</b><span>Flats listed · ${d.listings.filter((l) => l.available).length} vacant</span></div>
      <div class="stat"><b>${pending}</b><span>New visit requests</span></div>
      <div class="stat"><b>${inr(collected)}</b><span>Collected this month</span></div>
      <div class="stat"><b>${inr(dues)}</b><span>Pending dues · ${inr(deposits)} deposits held</span></div>
    </div>
    <div class="ownernav">
      <a class="btn sm" href="#own-flats">🏠 My flats</a><a class="btn sm" href="#own-requests">📩 Visit requests</a>
      <a class="btn sm" href="#own-tenants">🧾 Tenants & bills</a><a class="btn primary sm" href="#post">＋ Add new flat</a>
    </div>
    <h3 id="own-flats">My flats</h3>
    ${d.listings.length ? "" : `<div class="card">You haven't listed a flat yet. <a href="#post">List your first flat →</a></div>`}
    ${d.listings.map((l) => `<div class="card ownerlisting"><img src="${esc(l.photos[0])}" alt="">
      <div><b>${esc(l.title)}</b><div class="muted small">${esc(l.locality)}, ${esc(l.city)} · ${inr(l.rent)}/month</div>
      <span class="badge ${l.safety.level}">${LEVEL[l.safety.level]} · risk ${l.safety.score}</span> <span class="badge ${l.available ? "vacant" : "rented"}">${l.available ? "Vacant" : "Rented"}</span></div>
      <button class="btn sm" data-avail="${l.id}" data-to="${!l.available}">${l.available ? "Mark as rented" : "Mark as vacant"}</button></div>`).join("")}
    <h3 id="own-requests">Visit requests</h3>
    <div class="card tablewrap">${d.bookings.length ? `<table><tr><th>Tenant</th><th>Visit</th><th>Move-in</th><th>Message</th><th>Status</th><th></th></tr>
      ${d.bookings.map((b) => {
        const moved = d.tenancies.some((t) => t.tenancy.listing_id === b.listing_id && t.tenancy.tenant_phone === b.tenant_phone);
        return `<tr><td><b>${esc(b.tenant_name)}</b><div class="small muted">${b.status === "accepted" ? esc(b.tenant_phone) : "number shown after accepting"} · ${b.occupants} person(s)</div></td>
        <td>${esc(b.visit_date)}</td><td>${esc(b.move_in_date)}</td><td class="small">${esc(b.message)}</td><td><span class="badge ${b.status}">${esc(b.status)}</span></td>
        <td>${b.status === "pending" ? `<button class="btn ok sm" data-decide="${b.id}" data-s="accepted">Accept</button> <button class="btn sm" data-decide="${b.id}" data-s="declined">Decline</button>`
          : b.status === "accepted" && !moved ? `<button class="btn primary sm" data-movein="${b.id}">Move tenant in</button>` : ""}</td></tr>`;
      }).join("")}</table>` : `<p class="muted">No requests yet.</p>`}</div>
    <h3 id="own-tenants">Tenants, rent & bills</h3>
    ${d.tenancies.length ? d.tenancies.map((t) => tenancyHTML(t)).join("") : `<div class="card muted">When a tenant moves in, you can raise rent, water and electricity bills here.</div>`}`;

  $$("[data-avail]").forEach((b) => (b.onclick = () => busy(b, async () => {
    await postJSON(`/api/owner/${T}/listings/${b.dataset.avail}/availability`, { available: b.dataset.to === "true" }); loadOwner(token); search();
  })));
  $$("[data-decide]").forEach((b) => (b.onclick = () => busy(b, async () => {
    const note = b.dataset.s === "accepted" ? prompt("Optional note for the tenant (e.g. 'Come at 6pm, ask for flat 302')", "") ?? "" : "";
    await postJSON(`/api/owner/${T}/bookings/${b.dataset.decide}`, { status: b.dataset.s, note }); loadOwner(token);
  })));
  $$("[data-movein]").forEach((b) => (b.onclick = () => moveInModal(token, b.dataset.movein)));
  $$("[data-confirm]").forEach((b) => (b.onclick = () => busy(b, async () => {
    await postJSON(`/api/owner/${T}/bills/${b.dataset.confirm}/confirm`, {}); toast("Payment confirmed"); loadOwner(token);
  })));
  $$("form[data-bill]").forEach((f) => (f.onsubmit = (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(f));
    busy(e.submitter, async () => {
      await postJSON(`/api/owner/${T}/tenancies/${f.dataset.bill}/bills`, { ...data, amount: Number(data.amount) });
      toast("Bill sent to tenant"); loadOwner(token);
    });
  }));
  $$("[data-refund]").forEach((b) => (b.onclick = () => busy(b, async () => {
    const amt = prompt("Deposit amount to refund (tenancy will end and the flat becomes vacant):", b.dataset.max);
    if (amt === null) return;
    await postJSON(`/api/owner/${T}/tenancies/${b.dataset.refund}/deposit-refund`, { amount: Number(amt), end_tenancy: true });
    loadOwner(token); search();
  })));
}

function tenancyHTML(t) {
  const tn = t.tenancy;
  const month = new Date().toLocaleString("en-IN", { month: "short", year: "numeric" });
  return `<div class="card">
    <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px"><div><b>${esc(tn.tenant_name)}</b> · ${esc(tn.tenant_phone)}
      <div class="muted small">${esc(t.listing?.title)} · since ${esc(tn.start_date)} · UPI ${esc(tn.owner_upi)}</div></div>
      <span class="badge ${tn.status === "active" ? "accepted" : "cancelled"}">${esc(tn.status)}</span></div>
    ${summaryHTML(t.summary)}
    <div class="tablewrap"><table><tr><th>Bill</th><th>Period</th><th>Amount</th><th>Due</th><th>Status</th><th></th></tr>
    ${t.bills.map((b) => `<tr><td>${KIND[b.kind]}<div class="small muted mobile-only">${esc(b.period)}</div></td><td>${esc(b.period)}</td><td>${inr(b.amount)}</td><td>${esc(b.due_date)}</td><td>${billStatus(b)}${b.utr ? `<div class="small muted">UTR ${esc(b.utr)}</div>` : ""}</td>
      <td>${b.status === "submitted" ? `<button class="btn ok sm" data-confirm="${b.id}">Confirm received</button>` : b.status === "due" ? `<button class="btn sm" data-confirm="${b.id}">Mark paid (cash)</button>` : ""}</td></tr>`).join("")}</table></div>
    ${tn.status === "active" ? `<form class="form" data-bill="${tn.id}" style="margin-top:14px;grid-template-columns:repeat(5,1fr) auto">
      <select name="kind"><option value="rent">Rent</option><option value="electricity">Electricity</option><option value="water">Water</option><option value="maintenance">Maintenance</option><option value="other">Other</option></select>
      <input name="period" value="${esc(month)}" required><input name="amount" type="number" min="1" placeholder="Amount ₹" required>
      <input name="due_date" type="date" value="${addDays(7)}" required><input name="note" placeholder="Note (optional)">
      <button class="btn primary">Raise bill</button></form>
      <p><button class="btn sm" data-refund="${tn.id}" data-max="${t.summary.deposit_held}">End tenancy & refund deposit</button></p>` : ""}
  </div>`;
}

function moveInModal(token, bookingId) {
  openModal(`<h2>Move tenant in</h2><p class="muted">This starts the rent ledger. The first month's rent bill is created automatically and the flat is marked as rented.</p>
    <form id="movein" class="form">
      <label>Security deposit received (₹)<input name="deposit" type="number" min="0" required></label>
      <label>Tenancy start date<input name="start_date" type="date" value="${today()}" required></label>
      <label class="full">Your UPI ID (tenants pay you directly)<input name="owner_upi" required placeholder="yourname@okaxis"></label>
      <button class="btn primary full">Start tenancy</button></form>`);
  $("#movein").onsubmit = (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target));
    busy(e.submitter, async () => {
      await postJSON(`/api/owner/${encodeURIComponent(token)}/tenancies`, { ...data, booking_id: bookingId, deposit: Number(data.deposit) });
      closeModal(); toast("Tenant moved in"); loadOwner(token); search();
    });
  };
}

// ---------------- assistant ----------------
function initChat() {
  const qs = ["Should I pay token before visiting?", "Owner says he is in army and will courier keys", "What should a rent agreement contain?", "I got scammed, what now?"];
  $("#chips").innerHTML = qs.map((q) => `<button class="chip">${esc(q)}</button>`).join("");
  $$(".chip").forEach((c) => (c.onclick = () => ask(c.textContent)));
  addMsg("bot", "Hi! Ask me anything about renting safely: tokens, deposits, agreements, scams.");
}
function addMsg(who, text, sources = []) {
  const m = document.createElement("div");
  m.className = "msg " + who;
  m.innerHTML = esc(text) + (sources.length ? `<div class="src">Source: ${sources.map((s) => esc(s.title)).join(" · ")}</div>` : "");
  $("#chat").appendChild(m);
  $("#chat").scrollTop = 1e9;
}
async function ask(q) {
  addMsg("me", q);
  try { const r = await postJSON("/api/ask", { question: q }); addMsg("bot", r.answer, r.sources); } catch (e) { addMsg("bot", e.message); }
}
$("#ask-form").onsubmit = (e) => { e.preventDefault(); ask(e.target.q.value.trim()); e.target.reset(); };

function remember(key, val) {
  try { const a = JSON.parse(localStorage.getItem("rs_" + key) || "[]"); a.unshift(val); localStorage.setItem("rs_" + key, JSON.stringify(a.slice(0, 10))); } catch { /* storage blocked */ }
}

// ---------------- roommate matching ----------------
const RM_KEY = "rs_rm_token";
const rmToken = () => { try { return localStorage.getItem(RM_KEY); } catch { return null; } };
const COLORS = ["#ff385c", "#7b5cff", "#0f9d58", "#f29900", "#1a73e8", "#a1176f"];
const SLEEP = { early: "🌅 Early sleeper", normal: "🌙 Sleeps ~midnight", late: "🦉 Night owl" };
const FOOD = { veg: "🥗 Veg", egg: "🍳 Eggetarian", nonveg: "🍗 Non-veg" };

function seg(name, options, checked) {
  return `<div class="seg">${options.map(([v, label]) =>
    `<label><input type="radio" name="${name}" value="${v}" ${String(v) === String(checked) ? "checked" : ""} required><span>${label}</span></label>`).join("")}</div>`;
}

async function loadRoommates(tokenFromHash) {
  if (tokenFromHash) store.set(RM_KEY, tokenFromHash);
  const token = tokenFromHash || rmToken();
  if (!token) return rmForm();
  let d;
  try { d = await api("/api/roommates/" + encodeURIComponent(token)); } catch { return rmForm(); }
  rmDashboard(token, d);
}

function rmForm(existing = null, token = null) {
  const e = existing || {};
  const nextMonth = new Date(new Date().getFullYear(), new Date().getMonth() + 1, 1).toISOString().slice(0, 7);
  const city = e.city || Object.keys(META.cities)[0];
  $("#rm-view").innerHTML = `
    <div class="rm-hero"><h2>👥 Find a roommate who's like you</h2>
      <p>Tell us your habits once. AI matches you with students from your city and college, with a compatibility score and the reasons behind it.</p></div>
    <form id="rm-form" class="card form">
      <label>Name<input name="name" required minlength="2" value="${esc(e.name || "")}"></label>
      <label>Phone (shared only after you both agree)<input name="phone" required value="${esc(e.phone || "")}" placeholder="10-digit mobile"></label>
      <label>Age<input name="age" type="number" min="16" max="60" required value="${e.age || 21}"></label>
      <label>College / company<input name="college" value="${esc(e.college || "")}" placeholder="e.g. COEP Technological University"></label>
      <div class="fieldset"><b>I am</b>${seg("gender", [["male", "Male"], ["female", "Female"], ["other", "Other"]], e.gender || "male")}</div>
      <div class="fieldset"><b>Roommate gender</b>${seg("pref_gender", [["male", "Male"], ["female", "Female"], ["any", "Any"]], e.pref_gender || "any")}</div>
      <div class="fieldset"><b>Occupation</b>${seg("occupation", [["student", "Student"], ["intern", "Intern"], ["working", "Working"]], e.occupation || "student")}</div>
      <label>City<select name="city" id="rm-city">${Object.keys(META.cities).map((c) => `<option ${c === city ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></label>
      <div class="fieldset full"><b>Preferred areas</b><div class="seg" id="rm-locs"></div></div>
      <label>Budget for my share, min (₹)<input name="budget_min" type="number" min="1000" step="500" required value="${e.budget_min || 6000}"></label>
      <label>Budget for my share, max (₹)<input name="budget_max" type="number" min="1000" step="500" required value="${e.budget_max || 12000}"></label>
      <label>Move-in month<input name="move_in" type="month" required value="${esc(e.move_in || nextMonth)}"></label>
      <div class="fieldset full"><b>😴 Sleep time</b>${seg("sleep", [["early", "🌅 Before 11pm"], ["normal", "🌙 11pm – 1am"], ["late", "🦉 After 1am"]], e.sleep || "normal")}</div>
      <div class="fieldset"><b>🚬 I smoke</b>${seg("smoking", [["never", "Never"], ["occasionally", "Sometimes"], ["regularly", "Regularly"]], e.smoking || "never")}</div>
      <div class="fieldset"><b>OK living with a smoker?</b>${seg("smoke_ok", [["true", "Yes"], ["false", "No"]], e.smoke_ok ?? false)}</div>
      <div class="fieldset"><b>🍺 I drink</b>${seg("drinking", [["never", "Never"], ["occasionally", "Sometimes"], ["regularly", "Regularly"]], e.drinking || "never")}</div>
      <div class="fieldset"><b>OK living with someone who drinks?</b>${seg("drink_ok", [["true", "Yes"], ["false", "No"]], e.drink_ok ?? true)}</div>
      <div class="fieldset"><b>🍽 Food</b>${seg("food", [["veg", "Veg"], ["egg", "Eggetarian"], ["nonveg", "Non-veg"]], e.food || "veg")}</div>
      <div class="fieldset"><b>🧹 Cleanliness (1 = relaxed, 5 = very neat)</b>${seg("cleanliness", [[1, "1"], [2, "2"], [3, "3"], [4, "4"], [5, "5"]], e.cleanliness || 3)}</div>
      <div class="fieldset"><b>🧑‍🤝‍🧑 Guests over</b>${seg("guests", [["rarely", "Rarely"], ["sometimes", "Sometimes"], ["often", "Often"]], e.guests || "sometimes")}</div>
      <div class="fieldset"><b>🔊 Home vibe</b>${seg("noise", [["quiet", "Quiet"], ["moderate", "Moderate"], ["lively", "Lively"]], e.noise || "moderate")}</div>
      <div class="fieldset"><b>🐶 Pets</b>${seg("pets", [["false", "No pets"], ["true", "Have / want pets"]], e.pets ?? false)}</div>
      <label>Interests (comma separated)<input name="interests" value="${esc((e.interests || []).join(", "))}" placeholder="coding, cricket, music, gym"></label>
      <label>Languages<input name="languages" value="${esc((e.languages || []).join(", "))}" placeholder="hindi, english"></label>
      <label class="full">About me<textarea name="bio" rows="2" maxlength="400" placeholder="Your routine, what you're looking for">${esc(e.bio || "")}</textarea></label>
      <button class="btn primary full">${token ? "Save profile" : "Find my matches →"}</button>
    </form>`;
  const drawLocs = () => {
    const sel = new Set(e.localities || []);
    $("#rm-locs").innerHTML = META.cities[$("#rm-city").value].localities.map((l) =>
      `<label><input type="checkbox" name="localities" value="${esc(l)}" ${sel.has(l) ? "checked" : ""}><span>${esc(l)}</span></label>`).join("");
  };
  $("#rm-city").onchange = drawLocs;
  drawLocs();
  $("#rm-form").onsubmit = (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    const split = (v) => String(v || "").split(",").map((s) => s.trim()).filter(Boolean);
    const body = {
      ...Object.fromEntries(fd), localities: fd.getAll("localities"),
      age: Number(fd.get("age")), budget_min: Number(fd.get("budget_min")), budget_max: Number(fd.get("budget_max")),
      cleanliness: Number(fd.get("cleanliness")), smoke_ok: fd.get("smoke_ok") === "true", drink_ok: fd.get("drink_ok") === "true",
      pets: fd.get("pets") === "true", interests: split(fd.get("interests")), languages: split(fd.get("languages")),
    };
    busy(ev.submitter, async () => {
      if (token) { await api(`/api/roommates/${encodeURIComponent(token)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); loadRoommates(token); }
      else { const r = await postJSON("/api/roommates", body); location.hash = "roommates=" + r.token; }
    });
  };
}

function rmCardHTML(m, token, incoming = false) {
  const color = m.match.score >= 75 ? "var(--ok)" : m.match.score >= 50 ? "var(--warn)" : "var(--bad)";
  const req = m.request;
  let action = `<button class="btn primary sm" data-rmconnect="${m.id}">👋 Connect</button>`;
  if (req?.status === "accepted") action = "";
  else if (req?.status === "declined") action = `<span class="badge declined">Not interested</span>`;
  else if (req?.direction === "sent") action = `<span class="badge pending">Request sent</span>`;
  else if (req?.direction === "received") action = `<button class="btn ok sm" data-rmreply="${req.id}" data-s="accepted">Accept</button> <button class="btn sm" data-rmreply="${req.id}" data-s="declined">Decline</button>`;
  return `<div class="card rm-card">
    <div class="avatar" style="background:${COLORS[m.name.charCodeAt(0) % COLORS.length]}">${esc(m.name[0])}</div>
    <div>
      <b>${esc(m.name)}</b>, ${m.age} <span class="muted small">· ${esc(m.occupation)}${m.college ? " · " + esc(m.college) : ""}</span>
      <div class="habits"><span>${SLEEP[m.sleep]}</span><span>${FOOD[m.food]}</span><span>🚬 ${esc(m.smoking)}</span><span>🍺 ${esc(m.drinking)}</span>
        <span>🧹 ${m.cleanliness}/5</span><span>💰 ₹${m.budget_min.toLocaleString("en-IN")}–${m.budget_max.toLocaleString("en-IN")}</span>
        <span>📍 ${esc(m.localities.join(", ") || m.city)}</span><span>📅 ${esc(m.move_in)}</span></div>
      ${m.bio ? `<p class="small" style="margin:6px 0">"${esc(m.bio)}"</p>` : ""}
      ${incoming && req?.message ? `<div class="notice small">💬 ${esc(req.message)}</div>` : ""}
      <div class="tags">${m.match.good.map((g) => `<span class="tag good">✓ ${esc(g)}</span>`).join("")}${m.match.bad.map((b) => `<span class="tag bad">✕ ${esc(b)}</span>`).join("")}</div>
      ${m.contact ? `<div class="notice">🎉 You both agreed! <b>${esc(m.contact.phone)}</b>
          <div class="contact"><a class="btn primary sm" href="tel:+91${esc(m.contact.phone)}">📞 Call</a><a class="btn ok sm" target="_blank" rel="noopener" href="${esc(m.contact.whatsapp)}">💬 WhatsApp</a></div>
          ${m.flats?.length ? `<p class="small" style="margin:10px 0 4px"><b>Flats for you two:</b></p>${m.flats.map((f) => `<a class="small" href="#listing=${f.id}">🏠 ${esc(f.title)} · ${inr(f.rent)} (≈ ${inr(f.each_pays)} each)</a>`).join("<br>")}` : ""}
        </div>` : ""}
      <div style="margin-top:8px">${action}</div>
    </div>
    <div class="match-ring" style="background:conic-gradient(${color} ${m.match.score * 3.6}deg,#eef0f5 0)"><div style="color:${color}">${m.match.score}%</div></div>
  </div>`;
}

function rmDashboard(token, d) {
  const T = encodeURIComponent(token);
  const top = d.matches.filter((m) => m.request?.status !== "declined" && !(m.request?.direction === "received" && m.request?.status === "pending"));
  $("#rm-view").innerHTML = `
    <div class="rm-hero"><h2>Hi ${esc(d.me.name.split(" ")[0])} 👋</h2>
      <p>${top.length} people in ${esc(d.me.city)} are looking for a roommate. Sorted by how well you'd get along.</p>
      <div class="contact"><button class="btn sm" id="rm-edit">✏️ Edit profile</button>
        <button class="btn sm" id="rm-pause">${d.me.active ? "⏸ Hide my profile" : "▶️ Show my profile"}</button></div></div>
    ${d.incoming.length ? `<h3>📩 Requests for you</h3>${d.incoming.map((m) => rmCardHTML(m, token, true)).join("")}` : ""}
    <h3>✨ Best matches</h3>
    ${top.length ? top.map((m) => rmCardHTML(m, token)).join("") : `<div class="card muted">No matches yet in ${esc(d.me.city)}. Share GharSure with your college friends!</div>`}
    <p class="small muted">Your profile link (keep it private): <span class="copy">${esc(location.origin)}/#roommates=${esc(token)}</span></p>`;
  $("#rm-edit").onclick = () => rmForm(d.me, token);
  $("#rm-pause").onclick = (e) => busy(e.target, async () => { await postJSON(`/api/roommates/${T}/active`, { active: !d.me.active }); loadRoommates(token); });
  $$("[data-rmconnect]").forEach((b) => (b.onclick = () => busy(b, async () => {
    const msg = prompt("Say hi! (optional message)", "Hey! Looks like we'd make good roommates. Want to look for a flat together?");
    if (msg === null) return;
    const r = await postJSON(`/api/roommates/${T}/connect`, { to_id: b.dataset.rmconnect, message: msg });
    toast(r.status === "accepted" ? "It's a match! Contact details unlocked 🎉" : "Request sent");
    loadRoommates(token);
  })));
  $$("[data-rmreply]").forEach((b) => (b.onclick = () => busy(b, async () => {
    await postJSON(`/api/roommates/${T}/requests/${b.dataset.rmreply}`, { status: b.dataset.s });
    toast(b.dataset.s === "accepted" ? "Connected! Contact details unlocked 🎉" : "Declined");
    loadRoommates(token);
  })));
}

// ---------------- installable app (PWA) ----------------
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
let installPrompt = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installPrompt = e;
  $("#install-btn").classList.remove("hidden");
});
$("#install-btn").onclick = async () => {
  if (!installPrompt) return;
  installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  $("#install-btn").classList.add("hidden");
};

init().catch((e) => toast("Failed to load: " + e.message, true));
