#!/usr/bin/env python3
"""La Capilla Oscura v2 · last check before a freshly built site replaces the published one.

  python site_guard.py <new site dir> [<published site dir>] [--accept-shrink]

Exit 0 = OK to publish · 5 = refuse (the published site stays as it is). Standard library only.
Refuses when: a required page/file is missing or empty, CNAME is not lacapillaoscura.es, agenda.json has no events or
non-public fields, a private field / placeholder / private phrase shows up anywhere in the site, the Templos KML does
not parse or does not match the Templos page, or (vs the published site) the agenda shrank under 25 % (>= 8 events
before) or the Templos list under 50 % (--accept-shrink overrides after a real clean-up).
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

DOMAIN = "lacapillaoscura.es"
REQUIRED = ("index.html", "agenda/index.html", "lo-que-suena/index.html", "cronicas/index.html", "saber/index.html",
            "templos/index.html", "tienda/index.html", "sobre/index.html", "aviso-legal/index.html",
            "privacidad/index.html", "404.html", "aviso-legal.html", "agenda.json", "agenda.ics", "CNAME",
            "robots.txt", "assets/site.css", "assets/lco.js", "assets/agenda.js", "assets/templos.js",
            "templos/LCO-Templos-Madrid.kml", "templos/LCO-Templos-Madrid.kmz", "templos/LCO-Templos-Madrid.csv")
PUBLIC_FIELDS = {"id", "date", "date_end", "time", "title", "venue", "type", "genre", "price", "url", "pick"}
LEAKS = ('"verify"', '"hidden"', "place_id", "src:e-", "{{", "{%", "[tu texto", "visited", "geo_q", "heard_on",
         "Nada encontrado para", "Aliada natural de LCO", "guías antiguas", "nota interna", "NIF", "Culto a la música",
         "CULTO A LA MÚSICA", "@gmail", "/Volumes/", "/Users/", "entrada comprada",
         "Mis entradas", "pendiente de conectar")
GIG_DEBERES = re.compile(r"deberes:\s*[^()<]{2,60}\(\d{1,2} [a-z]{3}")  # 'deberes: <gig> (9 mar …' = a concert he attends
KML_NS = "{http://www.opengis.net/kml/2.2}"


def events_of(p):
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("events")
    except (OSError, ValueError, AttributeError):
        return None


def n_templos(site):
    try:
        return len(re.findall(r'<li class="card tp" id="p-', (site / "templos/index.html").read_text(encoding="utf-8")))
    except OSError:
        return None


def check(new, cur=None, accept_shrink=False):
    errs = []
    for f in REQUIRED:
        p = new / f
        if not p.is_file() or p.stat().st_size == 0:
            errs.append(f"missing or empty: {f}")
    if errs:
        return errs
    if not (new / ".nojekyll").is_file():
        errs.append("missing .nojekyll")
    if (new / "CNAME").read_text(encoding="utf-8").strip() != DOMAIN:
        errs.append(f"CNAME is not {DOMAIN}")
    evs = events_of(new / "agenda.json")
    if not isinstance(evs, list) or not evs:
        errs.append("agenda.json has no events (never publish an empty agenda)")
    else:
        extra = set().union(*(e.keys() for e in evs if isinstance(e, dict))) - PUBLIC_FIELDS
        if extra:
            errs.append(f"agenda.json has non-public fields {sorted(extra)}")
    for p in sorted(new.rglob("*")):
        if p.suffix not in (".html", ".json", ".kml", ".csv", ".ics") or not p.is_file():
            continue
        txt = p.read_text(encoding="utf-8")
        hits = [k for k in LEAKS if k in txt]
        if p.name == "agenda.ics":  # event titles are the organisers' words, never Vincent's: only the field checks
            hits = [k for k in hits if k in ("place_id", "src:e-", "{{", "/Volumes/", "/Users/")]
        if GIG_DEBERES.search(txt):
            hits.append("deberes linked to a concert")
        if hits:
            errs.append(f"{p.relative_to(new)} contains {hits}")
    if "Colto a la música" not in (new / "index.html").read_text(encoding="utf-8"):
        errs.append("index.html lost the slogan 'Colto a la música'")
    try:
        root = ET.parse(new / "templos/LCO-Templos-Madrid.kml").getroot()
        marks = root.findall(f".//{KML_NS}Placemark")
        with zipfile.ZipFile(new / "templos/LCO-Templos-Madrid.kmz") as z:
            same = z.read("doc.kml") == (new / "templos/LCO-Templos-Madrid.kml").read_bytes()
        if not same:
            errs.append("KMZ doc.kml differs from the KML")
        if len(marks) != n_templos(new):
            errs.append(f"KML has {len(marks)} placemarks but the Templos page {n_templos(new)} templos")
    except (ET.ParseError, zipfile.BadZipFile, KeyError, OSError) as err:
        errs.append(f"Templos KML/KMZ unusable: {err}")
    if cur and not accept_shrink:
        old = events_of(cur / "agenda.json")
        if isinstance(evs, list) and isinstance(old, list) and len(old) >= 8 and len(evs) < 0.25 * len(old):
            errs.append(f"agenda shrank from {len(old)} to {len(evs)} events (< 25 %)")
        ot, nt = n_templos(cur), n_templos(new)
        if ot and nt is not None and ot >= 8 and nt < 0.5 * ot:
            errs.append(f"Templos shrank from {ot} to {nt} (< 50 %)")
    return errs


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if len(args) not in (1, 2):
        print(__doc__, file=sys.stderr)
        return 2
    cur = Path(args[1]) if len(args) == 2 else None
    errs = check(Path(args[0]), cur, "--accept-shrink" in argv)
    for e in errs:
        print(f"site_guard: {e}", file=sys.stderr)
    if errs:
        print("site_guard: REFUSED -> the published site stays as it is", file=sys.stderr)
        return 5
    print(f"site_guard: OK ({len(events_of(Path(args[0]) / 'agenda.json'))} events, {n_templos(Path(args[0]))} templos)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
