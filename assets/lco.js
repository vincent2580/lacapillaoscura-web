/* La Capilla Oscura v2 · shared behaviour. Vanilla JS: no requests, no cookies, no storage.
   - "Compartir" buttons: native share sheet (Web Share API: Instagram, WhatsApp, Telegram…) or copy the link.
   - Old v1 links: lacapillaoscura.es/#semana-… (and #d-, #e-, #mes-, #calendario) now live on /agenda/.
   - Phone header: keeps the current section visible in the scrolling nav. */
(function () {
  "use strict";
  var doc = document;
  // ---- v1 agenda anchors on the home page -> the agenda's new address (the hash never reaches the server)
  if ((location.pathname === "/" || location.pathname === "/index.html") &&
      /^#(semana-|d-|e-|mes-|calendario)/.test(location.hash)) {
    location.replace("/agenda/" + location.hash);
    return;
  }
  doc.documentElement.classList.add("js");

  // ---- current nav item into view (phone: the nav scrolls sideways)
  var cur = doc.querySelector('.nav a[aria-current="page"]');
  if (cur && cur.parentNode && cur.parentNode.parentNode) {
    var ul = cur.parentNode.parentNode;
    var left = cur.getBoundingClientRect().left - ul.getBoundingClientRect().left + ul.scrollLeft - 12;
    if (left + cur.offsetWidth + 24 > ul.clientWidth) ul.scrollLeft = Math.max(0, left - 56);
  }

  // ---- share buttons
  var canShare = typeof navigator.share === "function";
  var canCopy = !!(navigator.clipboard && navigator.clipboard.writeText);
  Array.prototype.forEach.call(doc.querySelectorAll(".js-share"), function (b) {
    if (!canShare && !canCopy) return;
    b.hidden = false;
    if (!canShare) b.firstChild.nodeValue = "Copiar enlace";
    b.addEventListener("click", function () {
      var url = b.getAttribute("data-url"), text = b.getAttribute("data-text");
      if (canShare) {
        navigator.share({ title: "La Capilla Oscura", text: text, url: url }).catch(function () {});
        return;
      }
      navigator.clipboard.writeText(text + " " + url).then(function () {
        var old = b.firstChild.nodeValue;
        b.firstChild.nodeValue = "Enlace copiado";
        setTimeout(function () { b.firstChild.nodeValue = old; }, 2200);
      }, function () {});
    });
  });

})();
