#!/usr/bin/env python3
"""La Capilla Oscura · lacapillaoscura.es v2 — the full website, static (generator for GitHub Pages).

Pages: / (Inicio) · /agenda/ · /lo-que-suena/ · /cronicas/ (+ /cronicas/<slug>/) · /saber/ · /templos/ · /tienda/ ·
/sobre/ · /aviso-legal/ · /privacidad/ · 404.html. Same root files as the v1 site: /agenda.json, /agenda.ics,
/ics/<id>.ics (calendar subscriptions keep working), CNAME, robots.txt, .nojekyll, /aviso-legal.html (redirect).
Templos for map apps: /templos/LCO-Templos-Madrid.kml|.kmz|.csv + per-place Google Maps / Apple Maps links.

Data — ONLY La Sacristía's two public feeds (no credentials, nothing private exists in them):
  agenda  --source-url https://sacristia.lacapillaoscura.es/public/agenda.json   (contract §5)   or --source-file
  site    --site-url   https://sacristia.lacapillaoscura.es/public/site.json     (contract §14.7) or --site-file
+ content/*.json (the crónica and manifesto texts exactly as published on Instagram) + site-config.json (MYMAPS_URL).
Both feeds are fetched and checked BEFORE --out is touched: on any problem the build exits 3 and writes nothing, so
the last good site stays online. The agenda files come from the v1 builder's own functions (lco_agenda.py, vendored
unchanged by tools/vendor_agenda.py), so agenda.json / agenda.ics / ics/<id>.ics are byte-identical to v1.

Modes: default = GO-LIVE (what the public sees): any block whose text is still a "[tu texto]" placeholder is left
out, and the build fails (exit 4) if one slipped through. --preview = the same site with those placeholders shown in
amber (for Vincent), optionally served under a sub-path (--base-path /_preview).

  python build.py --source-url https://sacristia.lacapillaoscura.es/public/agenda.json \
                  --site-url https://sacristia.lacapillaoscura.es/public/site.json --out _site
"""
import argparse
import datetime as dt
import json
import re
import shutil
import sys
import unicodedata
import urllib.parse
from pathlib import Path

sys.dont_write_bytecode = True

from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402

import lco_agenda as pb  # noqa: E402  (vendored v1 agenda builder)
import maps_export as mx  # noqa: E402

HERE = Path(__file__).resolve().parent
SITE = pb.SITE
EMAIL = pb.EMAIL
INSTAGRAM = pb.INSTAGRAM
TIKTOK = pb.TIKTOK
MONTHS, MONTHS_LONG, DAYS_SHORT = pb.MONTHS, pb.MONTHS_LONG, pb.DAYS_SHORT

NAV = [("agenda", "Agenda", "/agenda/"), ("suena", "Lo que suena", "/lo-que-suena/"),
       ("cronicas", "Crónicas", "/cronicas/"), ("saber", "Saber", "/saber/"), ("templos", "Templos", "/templos/"),
       ("tienda", "Tienda", "/tienda/"), ("sobre", "Sobre LCO", "/sobre/")]
KINDS = {"sala": ("Sala", "Salas"), "club": ("Club", "Clubs"), "bar": ("Bar", "Bares"),
         "tienda": ("Tienda de discos", "Tiendas de discos"), "museo": ("Museo", "Museos"), "otro": ("Otro", "Otros")}
CSP_BASE = ("default-src 'self'; img-src 'self' data:{img}; style-src 'self'; script-src 'self'; font-src 'self'; "
            "connect-src 'self'; base-uri 'self'; form-action 'none'; object-src 'none'")
OSM_TILES = "https://tile.openstreetmap.org"
AVISAME_SUBJECT = "Avísame · Edición 001"
PLACEHOLDER = "[tu texto"

# §14.7 shapes (exact keys). Anything else in the feed = refuse (a private field must never reach the site).
TEMPLO_KEYS = {"id", "name", "kind", "area", "address", "approx", "lat", "lon", "styles", "info", "status",
               "status_note", "url", "instagram"}
ESCUCHA_KEYS = {"id", "artist", "album", "year", "heard", "velas", "group", "release_date"}
SITE_KEYS = {"name", "url", "updated", "templos", "escucha", "edicion"}


def d_(s):
    return dt.date.fromisoformat(s) if s else None


def short_date(d):
    return f"{DAYS_SHORT[d.weekday()].lower()} {d.day} {MONTHS[d.month - 1]}"


# ---------------------------------------------------------------- site feed (§14.7)
def load_site_json(text, origin):
    """§14.7 JSON -> (templos, escucha, edicion). Malformed file / unknown keys -> SourceError (exit 3);
    a single malformed item is skipped with a warning (as the agenda builder does)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise pb.SourceError(f"{origin}: not JSON ({err})") from None
    if not isinstance(data, dict) or not isinstance(data.get("templos"), list) or \
            not isinstance(data.get("escucha"), list) or not isinstance(data.get("edicion"), dict):
        raise pb.SourceError(f"{origin}: not the §14.7 site shape (templos/escucha lists + edicion object)")
    extra = set(data) - SITE_KEYS
    if extra:
        raise pb.SourceError(f"{origin}: unexpected top-level keys {sorted(extra)} (contract §14.7)")
    if set(data["edicion"]) - {"title"}:
        raise pb.SourceError(f"{origin}: edicion carries more than its title")
    templos, escucha = [], []
    for n, t in enumerate(data["templos"]):
        if isinstance(t, dict) and set(t) - TEMPLO_KEYS:
            raise pb.SourceError(f"{origin}: templo #{n} has non-public keys {sorted(set(t) - TEMPLO_KEYS)}")
        try:
            if not isinstance(t, dict) or not isinstance(t.get("id"), str) or not t["id"].startswith("p-"):
                raise ValueError("bad id")
            if not isinstance(t.get("name"), str) or not t["name"].strip():
                raise ValueError("no name")
            for k in ("lat", "lon"):
                if t.get(k) is not None and not isinstance(t[k], (int, float)):
                    raise ValueError(f"{k} is not a number")
            for k in ("kind", "area", "address", "info", "status", "status_note", "url", "instagram"):
                if t.get(k) is not None and not isinstance(t[k], str):
                    raise ValueError(f"{k} is not a string")
            if not isinstance(t.get("styles") or [], list):
                raise ValueError("styles is not a list")
        except ValueError as err:
            print(f"  ! {origin}: templo #{n} skipped: {err}", file=sys.stderr)
            continue
        templos.append(t)
    for n, x in enumerate(data["escucha"]):
        if isinstance(x, dict) and set(x) - ESCUCHA_KEYS:
            raise pb.SourceError(f"{origin}: escucha #{n} has non-public keys {sorted(set(x) - ESCUCHA_KEYS)}")
        try:
            if not isinstance(x, dict) or not all(isinstance(x.get(k), str) and x[k] for k in ("id", "artist", "album")):
                raise ValueError("id/artist/album missing")
            if x.get("group") not in ("novedad", "nueva", "otro"):
                raise ValueError(f"unknown group {x.get('group')!r}")
            if x.get("release_date") is not None:
                d_(x["release_date"])
        except ValueError as err:
            print(f"  ! {origin}: escucha #{n} skipped: {err}", file=sys.stderr)
            continue
        escucha.append(x)
    title = data["edicion"].get("title")
    return templos, escucha, {"title": title if isinstance(title, str) and title else "Edición 001"}


def read_source(url, path):
    return pb.fetch_source(url) if url else Path(path).read_text(encoding="utf-8")


# ---------------------------------------------------------------- agenda (same selection as lco_agenda.main())
def agenda(all_evs, places, today, n_weeks_max):
    monday = today - dt.timedelta(days=today.weekday())
    pub = [e for e in all_evs if pb.is_public(e)]
    starts = [d_(e["date"]) for e in pub if d_(e["date"]) >= monday]
    last_start = max(starts) if starts else monday
    n_weeks = min(n_weeks_max, (last_start - monday).days // 7 + 1)
    mondays = [monday + dt.timedelta(weeks=i) for i in range(max(1, n_weeks))]
    horizon = mondays[-1] + dt.timedelta(days=6)
    weeks = [pb.build_week(pub, places, m, today) for m in mondays]

    months, y, mo = [], monday.year, monday.month
    week_dates = {d["date"] for w in weeks for d in w["days"]}
    while (y, mo) <= (horizon.year, horizon.month):
        mm = pb.build_month([e for e in pub if d_(e["date"]) <= horizon or pb.long_run(e, monday, horizon)],
                            y, mo, today, lambda d: d.isoformat() in week_dates)
        if any(c and c["count"] for wk in mm["weeks"] for c in wk):
            months.append(mm)
        y, mo = (y + (mo == 12), mo % 12 + 1)

    day_ids = {}
    for w in weeks:
        for d in w["days"]:
            ids = [r["id"] for r in d["rows"]]
            day = d_(d["date"])
            ids += [r["id"] for r in w["allweek"]
                    if pb.overlaps({"date": r["date"], "date_end": r["date_end"] or None}, day, day)]
            for d2 in w["days"]:
                for r in d2["rows"]:
                    if r["date_end"] and r["id"] not in ids and d_(d2["date"]) < day <= d_(r["date_end"]):
                        ids.append(r["id"])
            day_ids[d["date"]] = ids

    published = sorted([e for e in pub if pb.overlaps(e, monday, d_("9999-12-31")) and d_(e["date"]) <= horizon],
                       key=pb.sort_key)
    upcoming = [e for e in published if pb.end_of(e) >= today]
    return {"pub": pub, "weeks": weeks, "months": months, "day_ids": day_ids, "published": published,
            "upcoming": upcoming, "monday": monday, "horizon": horizon, "places": places}


def when_text(e):
    d, de = d_(e["date"]), d_(e.get("date_end"))
    if de and de != d:
        return f"del {d.day} {MONTHS[d.month - 1]} al {de.day} {MONTHS[de.month - 1]}"
    return short_date(d) + (f", {e['time']}" if e.get("time") else "")


def share_bits(e, site):
    """¿Vamos? (WhatsApp, wa.me with the plan text + link) and the Web Share / copy-link payload."""
    url = f"{site}/agenda/#e-{e['id']}"
    parts = [e["title"], when_text(e)]
    if e.get("venue"):
        parts.append(e["venue"])
    if e.get("price"):
        parts.append(e["price"])
    text = "¿Vamos? " + " · ".join(parts)
    return {"wa": "https://wa.me/?text=" + urllib.parse.quote(f"{text}\n{url}", safe=""),
            "share_text": text, "share_url": url, "when": when_text(e)}


def decorate_rows(ag, site):
    by_id = {e["id"]: e for e in ag["pub"]}
    for w in ag["weeks"]:
        for r in [r for d in w["days"] for r in d["rows"]] + w["allweek"]:
            r.update(share_bits(by_id[r["id"]], site))


# ---------------------------------------------------------------- Lo que suena (feed `escucha`)
def search_links(artist, album):
    q_txt = f"{artist} {album}" if artist.lower() != "varios" else album
    q = urllib.parse.quote_plus(q_txt)
    return [("Spotify", f"https://open.spotify.com/search/{urllib.parse.quote(q_txt)}"),
            ("Bandcamp", f"https://bandcamp.com/search?q={q}"),
            ("YouTube", f"https://www.youtube.com/results?search_query={q}")]


def velas(r):
    if r is None:
        return None
    full = int(r)
    half = (r - full) >= 0.5
    num = f"{r:.1f}".replace(".", ",").replace(",0", "")
    return {"full": full, "half": half, "empty": 5 - full - (1 if half else 0), "label": num + " de 5 velas",
            "num": num}


def listening(escucha, today):
    """Escuchado (heard + velas), novedades by release date, bandas nuevas. The feed has no notes and no deberes."""
    heard, novedades, nuevas = [], {}, []
    for x in escucha:
        item = {"id": x["id"], "artist": x["artist"], "album": x["album"], "year": x.get("year"),
                "heard": bool(x.get("heard")), "links": search_links(x["artist"], x["album"])}
        if item["heard"] and isinstance(x.get("velas"), (int, float)):
            item["v"] = velas(float(x["velas"]))
            heard.append(item)
        if x["group"] == "novedad":
            novedades.setdefault(d_(x.get("release_date")), []).append(item)
        elif x["group"] == "nueva":
            nuevas.append(item)
    heard.sort(key=lambda a: a["id"], reverse=True)
    nov = [{"date": k, "label": short_date(k) if k else "", "released": bool(k and k <= today), "albums": v}
           for k, v in sorted(novedades.items(), key=lambda kv: kv[0] or dt.date.min, reverse=True)]
    return {"heard": heard, "novedades": nov, "nuevas": nuevas}


# ---------------------------------------------------------------- Templos (feed `templos`)
def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return re.sub(r"^sala ", "", s)


def place_of_venue(venue, templos):
    """Agenda events carry the venue NAME only (§5 has no place_id): match it to one templo by name
    (accents/case ignored, a leading 'Sala' ignored, or one name followed by more words). Ambiguous -> none."""
    v = norm(venue)
    if not v:
        return None
    hits = [t["id"] for t in templos if norm(t["name"]) == v]
    if not hits:
        hits = [t["id"] for t in templos
                if v.startswith(norm(t["name"]) + " ") or norm(t["name"]).startswith(v + " ")]
    return hits[0] if len(hits) == 1 else None


def host_label(url):
    h = urllib.parse.urlsplit(url).hostname or ""
    return "Instagram" if "instagram.com" in h else (h[4:] if h.startswith("www.") else h)


def public_place(t, upcoming_by_place):
    approx = bool(t.get("approx"))
    url = t.get("url") or ""
    url = url if url.startswith("https://") else ""
    ig = (t.get("instagram") or "").strip()
    ig_url = f"https://www.instagram.com/{ig[1:]}/" if re.fullmatch(r"@[A-Za-z0-9._]{1,30}", ig) else ""
    if ig_url and url.rstrip("/").lower() == ig_url.rstrip("/").lower():
        url = ""
    p = {"id": t["id"], "name": t["name"].strip(), "kind": t.get("kind") if t.get("kind") in KINDS else "otro",
         "area": t.get("area") or "", "address": "" if approx else (t.get("address") or ""), "approx": approx,
         "lat": t.get("lat"), "lon": t.get("lon"), "style_ids": [s for s in t.get("styles") or [] if s in pb.GENRES],
         "info": (t.get("info") or "").strip(), "status": t.get("status") or "abierto",
         "status_note": (t.get("status_note") or "").strip(), "url": url, "url_label": host_label(url) if url else "",
         "instagram": ig if ig_url else "", "instagram_url": ig_url, "next": upcoming_by_place.get(t["id"], [])}
    p["kind_label"] = KINDS[p["kind"]][0]
    p["styles"] = [pb.GENRES[s][0] for s in p["style_ids"]]
    p["google"] = mx.google_url(p)
    p["apple"] = mx.apple_url(p)
    return p


# ---------------------------------------------------------------- helpers
def rebase(html, base):
    """Serve a build under a sub-path (preview at /_preview/): prefix root-relative links/sources."""
    html = re.sub(r'((?:href|src|action)=")/(?!/)(?!#publico")', r"\1" + base + "/", html)

    def _srcset(m):
        return 'srcset="' + re.sub(r"(^|,\s*)/(?!/)", lambda n: n.group(1) + base + "/", m.group(1)) + '"'
    return re.sub(r'srcset="([^"]*)"', _srcset, html)


def load_config(path):
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        cfg = {}
    return {"MYMAPS_URL": (cfg.get("MYMAPS_URL") or "").strip()}


def check_mymaps(mm):
    if mm and not re.match(r"^https://(www\.google\.[a-z.]+/maps/d/|maps\.app\.goo\.gl/)[^\s\"'<>]*$", mm):
        sys.exit(f"build: MYMAPS_URL {mm!r} is not a Google My Maps link (https://www.google.com/maps/d/viewer?mid=...)")
    return mm


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--source-url", help="La Sacristía public agenda JSON (contract §5)")
    src.add_argument("--source-file", help="same, from a local file")
    sit = ap.add_mutually_exclusive_group(required=True)
    sit.add_argument("--site-url", help="La Sacristía public site JSON (contract §14.7)")
    sit.add_argument("--site-file", help="same, from a local file")
    ap.add_argument("--out", default=str(HERE / "dist-golive"))
    ap.add_argument("--preview", action="store_true", help="show '[tu texto]' placeholders (amber) instead of dropping them")
    ap.add_argument("--base-path", default="", help="serve under a sub-path, e.g. /_preview (preview only)")
    ap.add_argument("--config", default=str(HERE / "site-config.json"), help="MYMAPS_URL etc.")
    ap.add_argument("--mymaps-url", help="overrides MYMAPS_URL of --config")
    ap.add_argument("--today")
    ap.add_argument("--weeks", type=int, default=8)
    ap.add_argument("--og-image", help="PNG of this week's feed image (og:image)")
    ap.add_argument("--og-keep", help="already published og-semana.jpg, reused byte for byte when no --og-image")
    ap.add_argument("--titular", default="Vincent Emmanuel Guacaran Bencomo")
    ap.add_argument("--site", default=SITE, help="absolute site URL used in share links and og tags")
    ap.add_argument("--allow-empty", action="store_true", help="build even with 0 events or 0 templos")
    ap.add_argument("--report", help="write a JSON build report here (default: none)")
    a = ap.parse_args()

    today = d_(a.today) if a.today else dt.date.today()
    now = dt.datetime(today.year, today.month, today.day, tzinfo=dt.timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    site = a.site.rstrip("/")
    cfg = load_config(a.config)
    if a.mymaps_url is not None:
        cfg["MYMAPS_URL"] = a.mymaps_url.strip()
    check_mymaps(cfg["MYMAPS_URL"])
    base = a.base_path.rstrip("/")
    if base and not a.preview:
        sys.exit("build: --base-path is for the preview build only")

    # ------------------------------------------------ fetch + check BOTH feeds before touching --out
    try:
        a_origin = a.source_url or a.source_file
        all_evs, places, src_monday = pb.load_public_json(read_source(a.source_url, a.source_file), a_origin)
        if not all_evs and not a.allow_empty:
            raise pb.SourceError(f"{a_origin}: no usable events (never publish an empty agenda)")
        s_origin = a.site_url or a.site_file
        feed_templos, feed_escucha, edicion = load_site_json(read_source(a.site_url, a.site_file), s_origin)
        if not feed_templos and not a.allow_empty:
            raise pb.SourceError(f"{s_origin}: no templos (never publish an empty Templos page)")
    except (pb.SourceError, OSError, UnicodeDecodeError) as err:
        print(f"build: {err} -> nothing written, the current site stays as it is", file=sys.stderr)
        sys.exit(3)
    monday = today - dt.timedelta(days=today.weekday())
    if src_monday and src_monday != monday.isoformat():
        print(f"  ! source week starts {src_monday}, this build's week starts {monday} (clock/time zone?)",
              file=sys.stderr)
    keep = None
    if a.og_keep and Path(a.og_keep).is_file():
        from PIL import Image
        try:
            with Image.open(a.og_keep) as im:
                if im.format == "JPEG":
                    keep = (Path(a.og_keep).read_bytes(), im.width, im.height)
        except Exception as err:  # noqa: BLE001
            print(f"  ! --og-keep {a.og_keep}: not usable ({err})", file=sys.stderr)

    ag = agenda(all_evs, places, today, a.weeks)
    decorate_rows(ag, site)
    cur = ag["weeks"][0]

    # ------------------------------------------------ content
    cron = json.loads((HERE / "content" / "cronicas.json").read_text(encoding="utf-8"))["cronicas"]
    for c in cron:
        c["velas"] = velas(c["rating"])
        c["url"] = f"/cronicas/{c['slug']}/"
        pd = d_(c["published"])
        c["published_label"] = f"{pd.day} {MONTHS[pd.month - 1]} {pd.year}"
        c["wa"] = "https://wa.me/?text=" + urllib.parse.quote(
            f"Crónica de {c['band']} en {c['venue']} ({c['date_label']}), {c['velas']['label']}: {site}{c['url']}", safe="")
        c["share_text"] = f"Crónica: {c['band']} en {c['venue']} ({c['date_label']})"
    cron.sort(key=lambda c: c["date"], reverse=True)
    manif = json.loads((HERE / "content" / "manifiesto.json").read_text(encoding="utf-8"))
    textos = {k: v for k, v in json.loads((HERE / "content" / "textos.json").read_text(encoding="utf-8")).items()
              if not k.startswith("_")}
    lis = listening(feed_escucha, today)

    # Templos + upcoming public events per templo (matched by venue name)
    upcoming_by_place, matched = {}, 0
    for e in ag["upcoming"]:
        pid = place_of_venue(e.get("venue"), feed_templos)
        if pid:
            matched += 1
            upcoming_by_place.setdefault(pid, []).append({"id": e["id"], "title": e["title"], "when": when_text(e)})
    templos = [public_place(t, upcoming_by_place) for t in feed_templos]
    kind_order = list(KINDS)
    templos.sort(key=lambda p: (kind_order.index(p["kind"]), p["name"].lower()))
    kinds_count = [{"id": k, "label": KINDS[k][1], "n": n} for k in kind_order
                   if (n := sum(1 for p in templos if p["kind"] == k))]
    map_json = json.dumps([{"id": p["id"], "n": p["name"], "k": p["kind"], "kl": p["kind_label"], "lat": p["lat"],
                            "lon": p["lon"], "ap": p["approx"], "a": p["area"]}
                           for p in templos if p["lat"] is not None and p["lon"] is not None],
                          ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    closing = [p for p in templos if p["status"] == "cierra"]

    def style_labels_of(p):
        return [pb.GENRES[s][1] for s in p["style_ids"]]

    exports = {"kml": f"/templos/{mx.FILE_STEM}.kml", "kmz": f"/templos/{mx.FILE_STEM}.kmz",
               "csv": f"/templos/{mx.FILE_STEM}.csv"}

    # home: this week's day strip + picks
    strip = [{"wd": d["wd"], "n": d["n"], "date": d["date"], "count": len(d["rows"]), "past": d["past"],
              "today": d["date"] == today.isoformat(), "aria": d["aria"]} for d in cur["days"]]
    picks = []
    for d in cur["days"]:
        for r in d["rows"]:
            if r["pick"]:
                picks.append({**r, "day": f"{d['wd'].lower()} {d['n']}", "past": d["past"]})
    for r in cur["allweek"]:
        if r["pick"]:
            picks.append({**r, "day": "toda la semana", "past": False})
    next_week = ag["weeks"][1] if len(ag["weeks"]) > 1 else None

    # ------------------------------------------------ write --out (only now)
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    (out / "ics").mkdir()
    for sub in ("fonts", "img", "vendor"):
        shutil.copytree(HERE / "static" / sub, out / "assets" / sub)
    for f in ("site.css", "agenda.js", "lco.js", "templos.js", "lco-mark.svg", "favicon.svg"):
        shutil.copy2(HERE / "static" / f, out / "assets" / f)
    og, og_note = pb.og_image(ag["monday"], a.og_image, out / "assets", keep)
    if og_note:
        print("  !", og_note, file=sys.stderr)

    env = Environment(loader=FileSystemLoader(str(HERE / "tpl")), autoescape=select_autoescape(["html", "j2"]),
                      trim_blocks=True, lstrip_blocks=True)
    ctx = {
        "site": site, "email": EMAIL, "instagram": INSTAGRAM, "tiktok": TIKTOK, "today": today.isoformat(),
        "nav": NAV, "weeks": ag["weeks"], "months": ag["months"], "cur": cur, "next_week": next_week, "og": og,
        "types": [{"id": k, "lit": v[0], "label": v[1]} for k, v in pb.TYPES.items()],
        "genres": [{"id": k, "label": v[0], "long": v[1]} for k, v in pb.GENRES.items()],
        "updated": f"{today.day} {MONTHS_LONG[today.month - 1]} {today.year}", "titular": a.titular,
        "day_ids_json": json.dumps(ag["day_ids"], ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"),
        "cronicas": cron, "manif": manif, "listening": lis, "edicion": edicion, "templos": templos,
        "kinds_count": kinds_count, "map_json": map_json, "closing": closing, "n_templos": len(templos),
        "strip": strip, "picks": picks, "csp": CSP_BASE.format(img=""), "preview": a.preview,
        "mymaps_url": cfg["MYMAPS_URL"], "exports": exports, "textos": textos,
        "avisame_href": f"mailto:{EMAIL}?subject=" + urllib.parse.quote(AVISAME_SUBJECT, safe=""),
    }
    pages = [("home.html.j2", "index.html", "inicio", {}),
             ("agenda.html.j2", "agenda/index.html", "agenda", {}),
             ("suena.html.j2", "lo-que-suena/index.html", "suena", {}),
             ("cronicas.html.j2", "cronicas/index.html", "cronicas", {}),
             ("saber.html.j2", "saber/index.html", "saber", {}),
             ("templos.html.j2", "templos/index.html", "templos", {"csp": CSP_BASE.format(img=" " + OSM_TILES)}),
             ("tienda.html.j2", "tienda/index.html", "tienda", {}),
             ("sobre.html.j2", "sobre/index.html", "sobre", {}),
             ("aviso-legal.html.j2", "aviso-legal/index.html", "legal", {}),
             ("privacidad.html.j2", "privacidad/index.html", "legal", {}),
             ("404.html.j2", "404.html", "", {}),
             ("redirect.html.j2", "aviso-legal.html", "", {"to": "/aviso-legal/"})]
    for c in cron:
        pages.append(("cronica.html.j2", f"cronicas/{c['slug']}/index.html", "cronicas", {"c": c}))
    for tpl, name, sec, extra in pages:
        p = out / name
        p.parent.mkdir(parents=True, exist_ok=True)
        html = env.get_template(tpl).render(**{**ctx, **extra}, section=sec, path="/" + name.replace("index.html", ""))
        if base:
            html = rebase(html, base)
        p.write_text(html, encoding="utf-8")

    # Templos for map apps
    kml_text = mx.kml(templos, style_labels_of)
    (out / "templos" / f"{mx.FILE_STEM}.kml").write_text(kml_text, encoding="utf-8")
    (out / "templos" / f"{mx.FILE_STEM}.kmz").write_bytes(mx.kmz(kml_text))
    (out / "templos" / f"{mx.FILE_STEM}.csv").write_text(mx.csv_text(templos, style_labels_of), encoding="utf-8",
                                                         newline="")

    # agenda data files: exactly as the v1 builder writes them
    published, upcoming = ag["published"], ag["upcoming"]
    weeks = ag["weeks"]
    (out / "agenda.json").write_text(json.dumps({
        "name": "La Capilla Oscura (LCO) · Horario de misas", "url": SITE + "/", "updated": today.isoformat(),
        "week": {"start": weeks[0]["start"], "end": weeks[0]["end"], "label": weeks[0]["label"]},
        "aviso": "Precios orientativos · compra en la web oficial. Solo eventos confirmados.",
        "events": [{k: e.get(k) for k in pb.PUBLIC_FIELDS} | {"pick": bool(e.get("pick"))} for e in published],
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "agenda.ics").write_text(pb.ics_calendar(upcoming, places, "Horario de misas · La Capilla Oscura", stamp),
                                    encoding="utf-8", newline="")
    for e in published:
        (out / "ics" / f"{e['id']}.ics").write_text(pb.ics_calendar([e], places, e["title"], stamp),
                                                    encoding="utf-8", newline="")
    (out / "CNAME").write_text(pb.DOMAIN + "\n", encoding="utf-8")
    (out / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    # ------------------------------------------------ go-live guard: no placeholder may be published
    if not a.preview:
        bad = [str(f.relative_to(out)) for f in out.rglob("*.html") if PLACEHOLDER in f.read_text(encoding="utf-8")]
        if bad:
            print(f"build: '{PLACEHOLDER}]' placeholder left in go-live pages {bad}: not publishable", file=sys.stderr)
            sys.exit(4)

    rep = {"built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "today": today.isoformat(),
           "mode": "preview" if a.preview else "go-live", "agenda_source": a_origin, "site_source": s_origin,
           "published": len(published), "ics_upcoming": len(upcoming), "cronicas": len(cron),
           "templos": len(templos), "templos_events_matched": matched,
           "listening_public": {"heard": len(lis["heard"]), "novedades": sum(len(n["albums"]) for n in lis["novedades"]),
                                "nuevas": len(lis["nuevas"])},
           "mymaps_url": cfg["MYMAPS_URL"], "og": og, "og_note": og_note, "out": str(out)}
    if a.report:
        Path(a.report).parent.mkdir(parents=True, exist_ok=True)
        Path(a.report).write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"built {out} ({rep['mode']}) · week {cur['label']} ({cur['count']} planes) · {len(published)} events · "
          f"{len(templos)} templos ({matched} agenda rows matched) · listening {rep['listening_public']}")


if __name__ == "__main__":
    main()
