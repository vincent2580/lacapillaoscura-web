/* La Capilla Oscura v2 · Templos: filter by kind, and the map ON DEMAND.
   Leaflet (vendored, same origin) and the OpenStreetMap tiles (the only outside request of the whole site) are
   loaded only after a click on "Abrir el mapa". Pins are SVG circles (no marker images). */
(function () {
  "use strict";
  var doc = document;
  var data = [];
  try { data = JSON.parse(doc.getElementById("lco-templos").textContent || "[]"); } catch (e) { data = []; }
  var COLORS = { sala: "#D83A3F", club: "#9B7FD6", bar: "#D6A43E", tienda: "#46B3A5", museo: "#6F98DE", otro: "#A39C90" };

  // ---- filter chips
  var ctl = doc.querySelector("[data-js-tp]");
  var cards = Array.prototype.slice.call(doc.querySelectorAll(".tp[data-kind]"));
  var status = doc.querySelector("[data-tp-status]");
  var kind = "";
  var layers = {};
  function apply() {
    var n = 0;
    cards.forEach(function (c) {
      var on = !kind || c.getAttribute("data-kind") === kind;
      c.classList.toggle("off", !on);
      if (on) n++;
    });
    Array.prototype.forEach.call(ctl.querySelectorAll("[data-k]"), function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-k") === kind));
    });
    if (status) status.textContent = n + " templos";
    Object.keys(layers).forEach(function (k) {
      if (!map) return;
      var want = !kind || k === kind;
      if (want && !map.hasLayer(layers[k])) layers[k].addTo(map);
      if (!want && map.hasLayer(layers[k])) map.removeLayer(layers[k]);
    });
  }
  if (ctl) {
    ctl.hidden = false;
    Array.prototype.forEach.call(ctl.querySelectorAll("[data-k]"), function (b) {
      b.addEventListener("click", function () { kind = b.getAttribute("data-k"); apply(); });
    });
  }

  // ---- map on demand
  var btn = doc.querySelector("[data-map-open]");
  var box = doc.querySelector("[data-map]");
  var leg = doc.querySelector("[data-map-leg]");
  var map = null;
  function load(src, isCss) {
    return new Promise(function (ok, ko) {
      var el = doc.createElement(isCss ? "link" : "script");
      if (isCss) { el.rel = "stylesheet"; el.href = src; } else { el.src = src; }
      el.onload = ok; el.onerror = ko;
      doc.head.appendChild(el);
    });
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function build() {
    var L = window.L;
    map = L.map(box, { scrollWheelZoom: false, zoomControl: true }).setView([40.4245, -3.7038], 12);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18, attribution: "© colaboradores de <a href=\"https://www.openstreetmap.org/copyright\" rel=\"noopener external\" target=\"_blank\">OpenStreetMap</a>"
    }).addTo(map);
    var bounds = [];
    data.forEach(function (p) {
      var k = COLORS[p.k] ? p.k : "otro";
      if (!layers[k]) layers[k] = L.layerGroup().addTo(map);
      var mk = L.circleMarker([p.lat, p.lon], {
        radius: 8, color: "#EDE6D6", weight: 2, dashArray: p.ap ? "3 3" : null,
        fillColor: COLORS[k], fillOpacity: p.ap ? 0.45 : 0.95
      });
      mk.bindPopup("<b>" + esc(p.n) + "</b><br>" + esc(p.kl) + (p.a ? " · " + esc(p.a) : "") +
        (p.ap ? "<br><i>ubicación aproximada</i>" : "") + "<br><a href=\"#" + esc(p.id) + "\">Ver ficha</a>");
      mk.addTo(layers[k]);
      bounds.push([p.lat, p.lon]);
    });
    if (bounds.length) map.fitBounds(bounds, { padding: [24, 24], maxZoom: 13 });
    apply();
  }
  if (btn && box) {
    btn.hidden = false;
    btn.addEventListener("click", function () {
      btn.disabled = true;
      btn.textContent = "Cargando el mapa…";
      Promise.all([load("/assets/vendor/leaflet/leaflet.css", true), load("/assets/vendor/leaflet/leaflet.js", false)]).then(function () {
        box.hidden = false;
        if (leg) leg.hidden = false;
        btn.hidden = true;
        build();
        box.focus && box.setAttribute("tabindex", "-1");
      }, function () {
        btn.disabled = false;
        btn.textContent = "Abrir el mapa";
      });
    });
  }
  apply();
})();
