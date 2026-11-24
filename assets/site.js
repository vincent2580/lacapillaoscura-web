/* La Capilla Oscura · Horario de misas. Vanilla JS, no requests, no storage, no cookies.
   Without JS the page shows every week, then the month grids (anchors do the navigation).
   With JS: one week at a time (‹ ›), "Este finde", "Mes" tab with tap-a-day panel, filters by type and genre. */
(function () {
  "use strict";
  var doc = document, root = doc.documentElement;
  root.classList.add("js");

  var weeks = Array.prototype.slice.call(doc.querySelectorAll(".week"));
  var months = doc.getElementById("calendario");
  var ctl = doc.querySelector("[data-js]");
  var statusEl = doc.querySelector("[data-status]");
  var hint = doc.querySelector(".hint");
  var dayIds = {};
  try { dayIds = JSON.parse(doc.getElementById("lco-days").textContent || "{}"); } catch (e) { dayIds = {}; }

  function madridToday() {
    try {
      return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Madrid", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
    } catch (e) {
      var d = new Date(); return d.toISOString().slice(0, 10);
    }
  }
  var today = madridToday();

  // past days / today in the month grid (the build date can be a few days old)
  Array.prototype.forEach.call(doc.querySelectorAll(".day[data-date]"), function (el) {
    el.classList.toggle("past", el.getAttribute("data-date") < today);
    el.classList.toggle("today", el.getAttribute("data-date") === today);
  });
  Array.prototype.forEach.call(doc.querySelectorAll(".cal [data-day]"), function (a) {
    var td = a.parentNode, d = a.getAttribute("data-day");
    td.classList.toggle("past", d < today);
    td.classList.toggle("today", d === today);
  });

  var curWeek = 0;
  weeks.forEach(function (w, i) {
    if (w.getAttribute("data-start") <= today && today <= w.getAttribute("data-end")) curWeek = i;
  });
  var state = { view: "week", wi: curWeek, type: {}, genre: {} };

  // deep links: #semana-YYYY-MM-DD, #d-YYYY-MM-DD, #calendario
  function fromHash() {
    var h = (location.hash || "").slice(1);
    if (!h) return;
    if (h === "calendario" || h.indexOf("mes-") === 0) { state.view = "month"; return; }
    var el = doc.getElementById(h);
    if (!el) return;
    var w = el.closest ? el.closest(".week") : null;
    if (w) { state.view = "week"; state.wi = +w.getAttribute("data-i"); }
  }
  fromHash();

  function anyFilter(kind) { for (var k in state[kind]) if (state[kind][k]) return true; return false; }
  function match(li) {
    var t = li.getAttribute("data-type"), g = li.getAttribute("data-genre");
    if (anyFilter("type") && !state.type[t]) return false;
    if (anyFilter("genre") && !state.genre[g]) return false;
    return true;
  }
  function nFilters() {
    var n = 0, k;
    for (k in state.type) if (state.type[k]) n++;
    for (k in state.genre) if (state.genre[k]) n++;
    return n;
  }

  function applyFilters(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll(".evs"), function (ul) {
      var shown = 0, items = ul.querySelectorAll("li.ev");
      Array.prototype.forEach.call(items, function (li) { var ok = match(li); li.hidden = !ok; if (ok) shown++; });
      var day = ul.closest(".day");
      if (day && ul.closest(".week")) day.classList.toggle("fempty", items.length > 0 && shown === 0 || (items.length === 0 && (anyFilter("type") || anyFilter("genre"))));
      var empty = ul.querySelector("li.empty");
      if (empty) {
        empty.hidden = shown > 0;
        empty.textContent = items.length ? "Nada con estos filtros" : "Sin misa en el altar";
      }
    });
    Array.prototype.forEach.call(scope.querySelectorAll(".cal .dot[data-type]"), function (dot) {
      dot.hidden = !match(dot);
    });
  }

  function countVisible(w) {
    var n = 0;
    Array.prototype.forEach.call(w.querySelectorAll("li.ev"), function (li) {
      var day = li.closest(".day");
      if (!li.hidden && !(day && day.hidden)) n++;
    });
    return n;
  }

  function render(focusHead) {
    var finde = state.view === "finde";
    if (finde) state.wi = curWeek;
    weeks.forEach(function (w, i) {
      var on = state.view !== "month" && i === state.wi;
      w.hidden = !on;
      Array.prototype.forEach.call(w.querySelectorAll(".day[data-wd]"), function (d) {
        d.hidden = finde && +d.getAttribute("data-wd") < 4;
      });
      var wl = w.querySelector("[data-wl]");
      if (wl) wl.textContent = finde && on ? "finde " + w.getAttribute("data-finde-label") : w.getAttribute("data-label");
      var nav = w.querySelector(".wk-nav");
      if (nav) nav.hidden = finde;
      applyFilters(w);
      var total = w.querySelectorAll("li.ev").length;
      var shown = countVisible(w);
      var c = w.querySelector("[data-count]");
      var nm = w.querySelector("[data-nomatch]");
      if (nm) nm.hidden = !(total > 0 && shown === 0);
      if (c) c.textContent = (shown === total && !finde ? total : shown + " de " + total) + (total === 1 ? " plan" : " planes");
    });
    months.hidden = state.view !== "month";
    if (hint) hint.hidden = state.view === "month";
    applyFilters(months);
    Array.prototype.forEach.call(months.querySelectorAll("[data-panel]"), function (p) { if (!p.hidden) fillPanel(p, p.getAttribute("data-day")); });

    Array.prototype.forEach.call(ctl.querySelectorAll("[data-view]"), function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-view") === state.view));
    });
    var n = nFilters();
    ctl.querySelector("[data-nflt]").textContent = n ? String(n) : "";
    ctl.querySelector("[data-clear]").disabled = !n;
    Array.prototype.forEach.call(ctl.querySelectorAll(".chip"), function (b) {
      b.setAttribute("aria-pressed", String(!!state[b.getAttribute("data-f")][b.getAttribute("data-v")]));
    });

    var msg;
    if (state.view === "month") msg = "Calendario litúrgico";
    else {
      var w = weeks[state.wi];
      msg = (finde ? "Este finde, " + w.getAttribute("data-finde-label") : "Semana " + w.getAttribute("data-label")) + ": " + countVisible(w) + " planes";
    }
    if (statusEl) statusEl.textContent = msg;
    if (focusHead) {
      var target = state.view === "month" ? months.querySelector(".wk") : weeks[state.wi].querySelector(".wk");
      if (target) { target.setAttribute("tabindex", "-1"); target.focus({ preventScroll: true }); }
    }
  }

  // ---- month: tap a day -> its plans under the grid
  var rowById = {};
  Array.prototype.forEach.call(doc.querySelectorAll(".week li.ev[data-id]"), function (li) {
    var id = li.getAttribute("data-id");
    if (!rowById[id]) rowById[id] = li;
  });
  var DAYS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
  var MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
  function fillPanel(panel, day) {
    var ul = panel.querySelector("ul"), h = panel.querySelector("h4");
    var p = day.split("-"), dt = new Date(+p[0], +p[1] - 1, +p[2]);
    h.textContent = DAYS[dt.getDay()] + " " + (+p[2]) + " de " + MONTHS[+p[1] - 1];
    while (ul.firstChild) ul.removeChild(ul.firstChild);
    var ids = dayIds[day] || [], shown = 0;
    ids.forEach(function (id) {
      var src = rowById[id];
      if (!src) return;
      var li = src.cloneNode(true);
      li.removeAttribute("id");
      var det = li.querySelector("details"); if (det) det.open = false;
      li.hidden = !match(li);
      if (!li.hidden) shown++;
      ul.appendChild(li);
    });
    var empty = doc.createElement("li");
    empty.className = "empty";
    empty.textContent = ids.length ? "Nada con estos filtros" : "Sin misa en el altar";
    empty.hidden = shown > 0;
    ul.appendChild(empty);
  }
  Array.prototype.forEach.call(doc.querySelectorAll(".cal a[data-day]"), function (a) {
    a.addEventListener("click", function (ev) {
      ev.preventDefault();
      var month = a.closest(".month"), panel = month.querySelector("[data-panel]"), day = a.getAttribute("data-day");
      Array.prototype.forEach.call(months.querySelectorAll("td.sel"), function (td) { td.classList.remove("sel"); });
      Array.prototype.forEach.call(months.querySelectorAll("[data-panel]"), function (p) { if (p !== panel) p.hidden = true; });
      a.parentNode.classList.add("sel");
      panel.setAttribute("data-day", day);
      panel.hidden = false;
      fillPanel(panel, day);
      var h = panel.querySelector("h4");
      h.focus({ preventScroll: true });
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  });

  // ---- controls
  ctl.hidden = false;
  if (window.matchMedia && window.matchMedia("(min-width: 900px)").matches) ctl.querySelector(".flt").open = true;
  Array.prototype.forEach.call(ctl.querySelectorAll("[data-view]"), function (b) {
    b.addEventListener("click", function () {
      state.view = b.getAttribute("data-view");
      if (state.view !== "month") state.wi = curWeek;
      render(false);
      history.replaceState(null, "", state.view === "month" ? "#calendario" : location.pathname + location.search);
    });
  });
  Array.prototype.forEach.call(ctl.querySelectorAll(".chip"), function (b) {
    b.addEventListener("click", function () {
      var f = b.getAttribute("data-f"), v = b.getAttribute("data-v");
      state[f][v] = !state[f][v];
      render(false);
    });
  });
  Array.prototype.forEach.call(doc.querySelectorAll("[data-clear],[data-clear2]"), function (b) {
    b.addEventListener("click", function () { state.type = {}; state.genre = {}; render(false); });
  });
  Array.prototype.forEach.call(doc.querySelectorAll(".wk-nav a[data-go]"), function (a) {
    a.addEventListener("click", function (ev) {
      ev.preventDefault();
      state.view = "week";
      state.wi = +a.getAttribute("data-go");
      render(true);
      history.replaceState(null, "", "#" + weeks[state.wi].id);
      weeks[state.wi].scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
  window.addEventListener("hashchange", function () { fromHash(); render(false); });

  render(false);
  // a day link (#d-…) from outside: scroll to it once its week is visible
  if (location.hash.indexOf("#d-") === 0) {
    var target = doc.getElementById(location.hash.slice(1));
    if (target) target.scrollIntoView({ block: "start" });
  }
})();
