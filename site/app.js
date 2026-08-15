"use strict";
(function () {
  if (!window.PERMITS || !Array.isArray(window.PERMITS)) {
    document.getElementById("error").hidden = false;
    return;
  }
  const permits = window.PERMITS;
  permits.forEach((p) => { p._search = Filters.searchText(p); });

  const CARD_LIMIT = 400;
  const COLORS = { Commercial: "#dd6b20", Residential: "#2f855a" };

  // --- map ---
  const map = L.map("map").setView([39.25, -76.93], 11);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    // OSM's tile policy rejects requests without a Referer (osm.wiki/Blocked);
    // send the page origin even if the host sets a stricter Referrer-Policy.
    referrerPolicy: "strict-origin-when-cross-origin",
  }).addTo(map);
  const cluster = L.markerClusterGroup({ chunkedLoading: true });
  map.addLayer(cluster);
  // Past neighborhood zoom the coverage polygon reads as parcel bounds, but
  // pins are road-geocoded, so suppress it. Registered after addLayer so it
  // runs after the plugin's own hover handler, same tick — nothing paints.
  const COVERAGE_MAX_ZOOM = 11;
  const COVERAGE_MIN_PINS = 7;
  cluster.on("clustermouseover", (e) => {
    if (map.getZoom() > COVERAGE_MAX_ZOOM || e.layer.getChildCount() < COVERAGE_MIN_PINS)
      cluster._hideCoverage();
  });

  const money = (n) => "$" + Math.round(n).toLocaleString("en-US");

  function popupHtml(p) {
    const el = document.createElement("div");
    el.className = "popup";
    el.innerHTML = `<h3></h3><dl>
      <dt>Permit</dt><dd class="pid"></dd>
      <dt>Issued</dt><dd class="pissued"></dd>
      <dt>Contractor</dt><dd class="pcontractor"></dd>
      <dt>Est. cost</dt><dd class="pcost"></dd>
      <dt>Source</dt><dd class="psource"></dd>
      </dl><div class="desc"></div>`;
    el.querySelector("h3").textContent = `${p.type} — ${p.address}`;
    el.querySelector(".pid").textContent = p.id;
    el.querySelector(".pissued").textContent = p.issued;
    el.querySelector(".pcontractor").textContent = p.contractor || "—";
    el.querySelector(".pcost").textContent = money(p.cost);
    el.querySelector(".psource").textContent = `${p.source} report`;
    el.querySelector(".desc").textContent = p.description;
    return el;
  }

  // --- state ---
  let state = Filters.fromHash(location.hash);
  const $ = (id) => document.getElementById(id);
  const searchEl = $("search"), fromEl = $("from"), toEl = $("to");

  const dates = permits.map((p) => p.issued.slice(0, 10));
  const minDate = dates.reduce((a, b) => (a < b ? a : b));
  const maxDate = dates.reduce((a, b) => (a > b ? a : b));
  fromEl.min = toEl.min = minDate;
  fromEl.max = toEl.max = maxDate;
  Object.assign(state, Filters.normalizeRange(state.from, state.to));

  // permit-type checklist, grouped by category
  const typesByCat = new Map();
  permits.forEach((p) => {
    if (!typesByCat.has(p.category)) typesByCat.set(p.category, new Set());
    typesByCat.get(p.category).add(p.type);
  });
  const typesEl = $("types");
  [...typesByCat.keys()].sort().forEach((cat) => {
    [...typesByCat.get(cat)].sort().forEach((t) => {
      const label = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = t;
      cb.dataset.cat = cat;
      cb.addEventListener("change", onTypesChange);
      label.append(cb, document.createTextNode(t));
      typesEl.append(label);
    });
  });

  function syncControls() {
    searchEl.value = state.q;
    fromEl.value = state.from;
    toEl.value = state.to;
    document.querySelectorAll("#date-presets button").forEach((b) => {
      const isAll = b.dataset.months === "all";
      const range = isAll
        ? { from: "", to: "" }
        : Filters.lastMonths(maxDate, Number(b.dataset.months), minDate);
      const active = state.from === range.from && state.to === range.to;
      b.classList.toggle("active", active);
      b.setAttribute("aria-pressed", String(active));
    });
    document.querySelectorAll("#cats button").forEach((b) =>
      b.classList.toggle("active", b.dataset.cat === state.cat));
    document.querySelectorAll("#types input").forEach((cb) => {
      cb.checked = state.types.includes(cb.value);
    });
  }

  // --- rendering ---
  let markers = new Map(); // permit -> marker (for card→pin linking)
  let selectedCard = null;

  function render() {
    const filtered = Filters.apply(permits, state);

    cluster.clearLayers();
    markers = new Map();
    const layerList = [];
    filtered.forEach((p) => {
      if (p.geoq === "failed") return;
      const m = L.circleMarker([p.lat, p.lng], {
        radius: 7, weight: 1.5, color: "#fff", fillOpacity: 0.85,
        fillColor: COLORS[p.category] || "#4a5568",
      });
      m.bindPopup(() => popupHtml(p));
      m.on("click", () => highlightCard(p));
      markers.set(p, m);
      layerList.push(m);
    });
    cluster.addLayers(layerList);

    const total = filtered.reduce((s, p) => s + p.cost, 0);
    $("summary").textContent =
      `${filtered.length.toLocaleString()} permits · ${money(total)} total est. cost`;

    const results = $("results");
    results.replaceChildren();
    const frag = document.createDocumentFragment();
    filtered.slice(0, CARD_LIMIT).forEach((p) => {
      const card = document.createElement("div");
      card.className = "card";
      const badge = p.geoq === "failed"
        ? ' <span class="badge">no map location</span>' : "";
      card.innerHTML =
        `<div class="type ${p.category === "Residential" ? "res" : "com"}"></div>
         <div class="addr"></div><div class="meta"></div>`;
      card.querySelector(".type").textContent = p.type;
      card.querySelector(".addr").textContent = p.address;
      card.querySelector(".meta").innerHTML =
        `${p.issued} · ${money(p.cost)}${badge}`;
      card.addEventListener("click", () => focusPermit(p, card));
      frag.append(card);
    });
    if (filtered.length > CARD_LIMIT) {
      const note = document.createElement("div");
      note.className = "truncated-note";
      note.textContent =
        `Showing first ${CARD_LIMIT} of ${filtered.length} — refine filters to see the rest. All pins are on the map.`;
      frag.append(note);
    }
    results.append(frag);

    const hash = Filters.toHash(state);
    history.replaceState(null, "", hash || location.pathname + location.search);
  }

  function focusPermit(p, card) {
    if (selectedCard) selectedCard.classList.remove("selected");
    selectedCard = card;
    card.classList.add("selected");
    const m = markers.get(p);
    if (!m) return;
    map.setView(m.getLatLng(), Math.max(map.getZoom(), 16));
    cluster.zoomToShowLayer(m, () => m.openPopup());
  }

  function highlightCard(p) {
    // find card by index in current filtered order — cheap approach:
    // re-query cards and match by displayed permit address+type
    document.querySelectorAll(".card").forEach((c) => c.classList.remove("selected"));
    const cards = document.querySelectorAll(".card");
    const filtered = Filters.apply(permits, state).slice(0, cards.length);
    const i = filtered.indexOf(p);
    if (i >= 0) {
      cards[i].classList.add("selected");
      cards[i].scrollIntoView({ block: "nearest" });
      selectedCard = cards[i];
    }
  }

  // --- events ---
  let debounce;
  searchEl.addEventListener("input", () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => { state.q = searchEl.value.trim(); render(); }, 150);
  });
  fromEl.addEventListener("change", () => {
    state.from = fromEl.value;
    syncControls();
    render();
  });
  toEl.addEventListener("change", () => {
    state.to = toEl.value;
    syncControls();
    render();
  });
  $("date-presets").addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    const range = btn.dataset.months === "all"
      ? { from: "", to: "" }
      : Filters.lastMonths(maxDate, Number(btn.dataset.months), minDate);
    Object.assign(state, range);
    syncControls();
    render();
  });
  $("cats").addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    state.cat = btn.dataset.cat;
    state.types = [];
    syncControls();
    render();
  });
  function onTypesChange() {
    state.types = [...document.querySelectorAll("#types input:checked")]
      .map((cb) => cb.value);
    render();
  }
  window.addEventListener("hashchange", () => {
    state = Filters.fromHash(location.hash);
    Object.assign(state, Filters.normalizeRange(state.from, state.to));
    syncControls();
    render();
  });
  $("sidebar-toggle").addEventListener("click", () =>
    $("sidebar").classList.toggle("open"));

  syncControls();
  render();
})();
