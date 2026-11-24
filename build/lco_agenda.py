# Vendored copy of the La Capilla Oscura v1 agenda builder (public/build.py); regenerate with tools/vendor_agenda.py.
#!/usr/bin/env python3
"""La Capilla Oscura · public agenda website (lacapillaoscura.es) — static site builder.

Reads the Desk's events.jsonl + places.json (READ-ONLY; later line with the same id wins) and writes a static
site to dist/:

  index.html        "Horario de misas": this week LUNES→DOMINGO (same order/rows as the T11 image), next weeks,
                    "Este finde", month tab (Calendario litúrgico), filters by type and genre
  aviso-legal.html  simple legal notice (titular = --titular, default the {{TITULAR}} placeholder)
  404.html          GitHub Pages "not found" page
  agenda.json       PUBLIC fields only (id, date, date_end, time, title, venue, type, genre, price, url, pick)
  agenda.ics        every upcoming event (from --today on)
  ics/<id>.ics      one "Añadir a mi calendario" file per event
  assets/           self-hosted fonts (WOFF2, OFL), site.css, site.js, LCO mark, favicon, og image
  CNAME, robots.txt

Honesty rule (same as the posts): only events with verify == false and hidden != true are published.
Internal fields (source, note, verify, place_id, hidden) never reach dist/.

  (vendored into lacapillaoscura.es v2 as lco_agenda.py: its functions are imported by build.py; the v1 main()
   below is kept unchanged so the agenda files stay byte-identical to the v1 builder)

La Sacristía source (lane F, 24 Nov 2026): instead of the Desk files, read the public JSON of La Sacristía
(CONTRACT-sacristia.md §5: confirmed, visible events of this Madrid week's Monday .. +69 days, public fields + `place`):

  build.py --source-url https://sacristia.lacapillaoscura.es/public/agenda.json
  build.py --source-file agenda.json                  # same, from a local file (tests)

Same data -> same dist/ byte for byte as the Desk build. `place` only feeds the row address and the .ics LOCATION;
dist/agenda.json keeps the 11 public fields. If the source cannot be fetched, is not §5-shaped or has no events,
the build stops with exit code 3 BEFORE touching --out (the published site stays as it is). --allow-empty overrides
the empty check. --og-keep <jpg> reuses an already published og image byte for byte when no T11 image is at hand.
"""
import argparse
import datetime as dt
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

HERE = Path(__file__).resolve().parent
DESK = Path("desk-not-in-this-repo")  # v2: data only from La Sacristía (--source-url); the Desk is retired
WEEKLY = Path("weekly-not-in-this-repo")  # v2: og image via --og-image / --og-keep
SITE = "https://lacapillaoscura.es"
DOMAIN = "lacapillaoscura.es"
EMAIL = "info@lacapillaoscura.es"
INSTAGRAM = "https://www.instagram.com/lacapillaoscura/"
TIKTOK = "https://www.tiktok.com/@lacapillaoscura"

# Contract (CONTRACT-horario-de-misas.md): type id -> (liturgical label, public filter label, ticket link label)
TYPES = {
    "misa": ("misa", "Conciertos", "Entradas"),
    "vigilia": ("vigilia", "Fiestas", "Entradas"),
    "procesion": ("procesión", "Festivales", "Entradas"),
    "reliquias": ("reliquias", "Ferias y tiendas", "Entradas"),
    "arte-sacro": ("arte sacro", "Cultura", "Más info"),
}
GENRES = {  # genre id -> (chip label, long label)
    "metal": ("Metal", "Metal y heavy"),
    "rock-punk": ("Rock/punk", "Rock y punk"),
    "oscuro": ("Oscuro", "Oscuro (goth · darkwave · EBM · post-punk)"),
    "otros": ("Fuera del altar", "Fuera del altar (jazz, folk, otros)"),
}
PUBLIC_FIELDS = ("id", "date", "date_end", "time", "title", "venue", "type", "genre", "price", "url", "pick")
DAYS = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO"]
DAYS_SHORT = ["LUN", "MAR", "MIÉ", "JUE", "VIE", "SÁB", "DOM"]
DAYS_LOWER = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MONTHS_LONG = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
               "octubre", "noviembre", "diciembre"]


def d_(s):
    return dt.date.fromisoformat(s) if s else None


# ---------------------------------------------------------------- data
def load_events(path):
    by_id = {}
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError as err:
            print(f"  ! {path}:{n}: bad JSON line skipped ({err})", file=sys.stderr)
            continue
        if "id" in e and "date" in e:
            by_id[e["id"]] = e
    return known_types(by_id)


def known_types(by_id):
    out = []
    for e in by_id.values():
        if e.get("type") not in TYPES:
            print(f"  ! {e['id']}: unknown type {e.get('type')!r} -> not published", file=sys.stderr)
            continue
        if e.get("genre") not in (None, *GENRES):
            print(f"  ! {e['id']}: unknown genre {e.get('genre')!r} -> genre dropped", file=sys.stderr)
            e = {**e, "genre": None}
        out.append(e)
    return out


def load_places(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    pl = data.get("places", data) if isinstance(data, dict) else data
    return {p["id"]: p for p in pl if isinstance(p, dict) and "id" in p}


# ---------------------------------------------------------------- La Sacristía public JSON (contract §5, lane F)
SOURCE_MAX_BYTES = 2_000_000
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class SourceError(Exception):
    """The public JSON cannot be used: the build stops before writing anything (exit 3)."""


def fetch_source(url, timeout=20, tries=3, wait=5):
    """GET the public JSON. https only (plain http only for localhost tests); no credentials, no cookies."""
    u = urllib.parse.urlsplit(url)
    if not (u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost"))):
        raise SourceError(f"refusing non-https source URL {url!r}")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "lco-public-rebuild/1"})
    last = None
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                ctype = r.headers.get("Content-Type", "")
                body = r.read(SOURCE_MAX_BYTES + 1)
            if "json" not in ctype.lower():
                raise SourceError(f"source answered Content-Type {ctype!r}, not JSON")
            if len(body) > SOURCE_MAX_BYTES:
                raise SourceError(f"source body larger than {SOURCE_MAX_BYTES} bytes")
            return body.decode("utf-8")
        except SourceError:
            raise
        except urllib.error.HTTPError as err:  # 4xx: no point retrying; 5xx/429: retry
            last = f"HTTP {err.code}"
            if err.code < 500 and err.code != 429:
                break
        except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError) as err:
            last = f"{type(err).__name__}: {err}"
        if attempt < tries:
            time.sleep(wait * attempt)
    raise SourceError(f"cannot fetch {url}: {last}")


def _iso_date(s):
    if s is None:
        return None
    if not isinstance(s, str):
        raise ValueError("not a string")
    return dt.date.fromisoformat(s)


def load_public_json(text, origin="source"):
    """§5 public JSON -> (events in the Desk events.jsonl shape, places dict), so the rest of the build is shared.

    Every §5 event is confirmed and visible by definition (verify false, hidden false). `place` {address, area}
    becomes a synthetic place (approx false) referenced by place_id, exactly what row()/vevent() read from
    places.json. A malformed event is skipped with a warning (as a bad events.jsonl line); a malformed file raises."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise SourceError(f"{origin}: not JSON ({err})") from None
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise SourceError(f"{origin}: not the §5 public agenda shape (no 'events' list)")
    by_id, places = {}, {}
    for n, x in enumerate(data["events"]):
        try:
            if not isinstance(x, dict):
                raise ValueError("not an object")
            if not isinstance(x.get("id"), str) or not x["id"] or "/" in x["id"] or x["id"].startswith("."):
                raise ValueError(f"bad id {x.get('id')!r}")
            if not isinstance(x.get("title"), str) or not x["title"].strip():
                raise ValueError("no title")
            d0, d1 = _iso_date(x.get("date")), _iso_date(x.get("date_end"))
            if d0 is None or (d1 is not None and d1 < d0):
                raise ValueError("bad date / date_end")
            if x.get("time") is not None and not (isinstance(x["time"], str) and TIME_RE.match(x["time"])):
                raise ValueError(f"bad time {x.get('time')!r}")
            for k in ("venue", "price", "url", "type", "genre"):
                if x.get(k) is not None and not isinstance(x[k], str):
                    raise ValueError(f"{k} is not a string")
        except ValueError as err:
            ident = x.get("id") if isinstance(x, dict) else None
            print(f"  ! {origin}: event #{n} ({ident!r}) skipped: {err}", file=sys.stderr)
            continue
        e = {k: x.get(k) for k in PUBLIC_FIELDS}
        e["pick"] = bool(x.get("pick"))
        e["verify"], e["hidden"], e["place_id"] = False, False, None
        p = x.get("place")
        if isinstance(p, dict) and isinstance(p.get("address"), str) and p["address"]:
            pid = "src:" + e["id"]
            area = p.get("area") if isinstance(p.get("area"), str) else ""
            places[pid] = {"id": pid, "address": p["address"], "area": area, "approx": False}
            e["place_id"] = pid
        by_id[e["id"]] = e  # a later entry with the same id wins (as in events.jsonl)
    week = data.get("week") if isinstance(data.get("week"), dict) else {}
    return known_types(by_id), places, week.get("start")


def is_public(e):
    return not e.get("hidden") and not e.get("verify")


def end_of(e):
    return d_(e.get("date_end")) or d_(e["date"])


def overlaps(e, a, b):
    return d_(e["date"]) <= b and end_of(e) >= a


def sort_key(e):  # identical to horario._sort_key (T9/T11): date, time (none last), title
    return (e["date"], e.get("time") or "99:99", e["title"].lower())


def long_run(e, a, b, min_days=4):  # identical to horario._long_run: runs across (most of) the period
    d, de = d_(e["date"]), d_(e.get("date_end"))
    if not de or de == d:
        return False
    return (min(de, b) - max(d, a)).days >= min_days


def week_label(a, b):
    return f"{a.day}–{b.day} {MONTHS[b.month - 1]}" if a.month == b.month else f"{a.day} {MONTHS[a.month - 1]}–{b.day} {MONTHS[b.month - 1]}"


def span_text(e, a, b):
    """Multi-day note, same wording as the T11 image ('hasta 7 mar', 'cada día', 'vie–dom 4–6')."""
    d, de = d_(e["date"]), d_(e.get("date_end"))
    if not de or de == d:
        return ""
    if de > b:
        return f"hasta {de.day} {MONTHS[de.month - 1]}"
    if d <= a:
        return "cada día"
    return f"{DAYS_SHORT[d.weekday()].lower()}–{DAYS_SHORT[de.weekday()].lower()} {d.day}–{de.day}"


def row(e, places, a=None, b=None):
    t = TYPES[e["type"]]
    p = places.get(e.get("place_id") or "")
    address = ""
    if p and p.get("address") and not p.get("approx"):
        address = p["address"] + (f" · {p['area']}" if p.get("area") else "")
    url = e.get("url") or ""
    return {
        "id": e["id"], "title": e["title"], "venue": e.get("venue") or "", "price": e.get("price") or "—",
        "price_known": bool(e.get("price")), "pick": bool(e.get("pick")), "type": e["type"],
        "type_label": t[0], "type_public": t[1], "link_label": t[2],
        "genre": e.get("genre") or "", "genre_label": GENRES.get(e.get("genre"), ("", ""))[1],
        "time": e.get("time") or "", "url": url if url.startswith("https://") else "",
        "span": span_text(e, a, b) if a else "", "address": address,
        "date": e["date"], "date_end": e.get("date_end") or "",
    }


def build_week(evs, places, monday, today):
    sunday = monday + dt.timedelta(days=6)
    days = {monday + dt.timedelta(days=i): [] for i in range(7)}
    allweek = []
    for e in sorted((e for e in evs if overlaps(e, monday, sunday)), key=sort_key):
        if long_run(e, monday, sunday):
            allweek.append(row(e, places, monday, sunday))
        else:
            days[max(d_(e["date"]), monday)].append(row(e, places, monday, sunday))
    out_days = []
    for d, rows in days.items():
        out_days.append({"date": d.isoformat(), "wd": DAYS_SHORT[d.weekday()], "wd_i": d.weekday(), "n": d.day,
                         "aria": f"{DAYS_LOWER[d.weekday()]} {d.day} de {MONTHS_LONG[d.month - 1]}",
                         "rows": rows, "past": d < today})
    n = sum(len(x["rows"]) for x in out_days) + len(allweek)
    return {"id": f"semana-{monday.isoformat()}", "start": monday.isoformat(), "end": sunday.isoformat(),
            "label": week_label(monday, sunday), "days": out_days, "allweek": allweek, "count": n,
            "finde_label": week_label(monday + dt.timedelta(days=4), sunday)}


def build_month(evs, y, m, today, day_anchor_ok):
    first = dt.date(y, m, 1)
    last = dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)
    in_month = [e for e in evs if overlaps(e, first, last)]
    longs = [e for e in sorted(in_month, key=sort_key)
             if long_run(e, first, last) and (min(end_of(e), last) - max(d_(e["date"]), first)).days >= 7]
    long_ids = {e["id"] for e in longs}
    cells = [None] * first.weekday()
    d = first
    while d <= last:
        todays = sorted((e for e in in_month if e["id"] not in long_ids and overlaps(e, d, d)), key=sort_key)
        cells.append({"date": d.isoformat(), "n": d.day, "past": d < today, "today": d == today,
                      "dots": [{"type": e["type"], "genre": e.get("genre") or "", "pick": bool(e.get("pick"))} for e in todays],
                      "count": len(todays), "anchor": day_anchor_ok(d),
                      "aria_pre": DAYS_LOWER[d.weekday()],
                      "aria_post": f"de {MONTHS_LONG[m - 1]}: "
                                   + (f"{len(todays)} plan{'es' if len(todays) != 1 else ''}" if todays else "sin planes")})
        d += dt.timedelta(days=1)
    while len(cells) % 7:
        cells.append(None)
    return {"id": f"mes-{y:04d}-{m:02d}", "label": f"{MONTHS_LONG[m - 1]} {y}", "name": MONTHS_LONG[m - 1],
            "weeks": [cells[i:i + 7] for i in range(0, len(cells), 7)],
            "longs": [{"id": e["id"], "title": e["title"], "venue": e.get("venue") or "", "pick": bool(e.get("pick")),
                       "type": e["type"], "until": f"hasta {end_of(e).day} {MONTHS[end_of(e).month - 1]}"} for e in longs]}


# ---------------------------------------------------------------- iCalendar (RFC 5545, written by hand)
VTIMEZONE = """BEGIN:VTIMEZONE
TZID:Europe/Madrid
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE"""


def ics_text(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        cb = ch.encode("utf-8")
        if len(cur) + len(cb) > (75 if not parts else 74):
            parts.append(cur.decode("utf-8"))
            cur = b""
        cur += cb
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def vevent(e, places, stamp):
    t = TYPES[e["type"]]
    d, de = d_(e["date"]), d_(e.get("date_end"))
    lines = ["BEGIN:VEVENT", f"UID:{e['id']}@{DOMAIN}", f"DTSTAMP:{stamp}"]
    if de and de != d:  # multi-day: all-day range (DTEND is exclusive)
        lines += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{de + dt.timedelta(days=1):%Y%m%d}"]
    elif e.get("time"):  # timed, one day
        hh, mm = e["time"].split(":")
        start = dt.datetime(d.year, d.month, d.day, int(hh), int(mm))
        end = start + dt.timedelta(hours=3)  # end time unknown: a 3-hour block (Vincent, 24 Nov 2026)
        lines += [f"DTSTART;TZID=Europe/Madrid:{start:%Y%m%dT%H%M%S}", f"DTEND;TZID=Europe/Madrid:{end:%Y%m%dT%H%M%S}"]
    else:
        lines += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + dt.timedelta(days=1):%Y%m%d}"]
    summary = e["title"] + (" ★" if e.get("pick") else "")
    p = places.get(e.get("place_id") or "")
    loc = e.get("venue") or ""
    if p and p.get("address") and not p.get("approx"):
        loc += f", {p['address']}"
    desc = [f"{t[0].upper()} · {t[1]}" + (f" · {GENRES[e['genre']][1]}" if e.get("genre") in GENRES else "")]
    if e.get("time") and de and de != d:
        desc.append(f"Hora: {e['time']}")
    desc.append(f"Precio orientativo: {e.get('price') or 'sin confirmar'} (compra en la web oficial)")
    if (e.get("url") or "").startswith("https://"):
        desc.append(f"{t[2]}: {e['url']}")
    desc.append(f"Horario de misas · La Capilla Oscura · {SITE}/")
    lines += [f"SUMMARY:{ics_text(summary)}", f"LOCATION:{ics_text(loc)}", f"DESCRIPTION:{ics_text(chr(10).join(desc))}"]
    if (e.get("url") or "").startswith("https://"):
        lines.append(f"URL:{e['url']}")
    lines += ["TRANSP:TRANSPARENT", "END:VEVENT"]
    return lines


def ics_calendar(evs, places, name, stamp):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//La Capilla Oscura//Horario de misas//ES",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{ics_text(name)}", "X-WR-TIMEZONE:Europe/Madrid",
             *VTIMEZONE.splitlines()]
    for e in evs:
        lines += vevent(e, places, stamp)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(x) for x in lines) + "\r\n"


# ---------------------------------------------------------------- og image
def og_image(monday, explicit, out_dir, keep=None):
    """Copy this week's T11 feed image (as JPEG ≤ ~300 KB so WhatsApp shows it). Falls back to the newest earlier week.
    keep = (bytes, w, h) of an already published og-semana.jpg (--og-keep): used as is when no T11 image is found."""
    src = Path(explicit) if explicit else WEEKLY / monday.isoformat() / "LCO-T11-semana-feed.png"
    note = ""
    if not src.exists() and not explicit:
        cands = sorted(p for p in WEEKLY.glob("*/LCO-T11-semana-feed.png") if p.parent.name <= monday.isoformat())
        if cands:
            src = cands[-1]
            note = f"og image falls back to week {src.parent.name} (no T11 feed image for {monday})"
        elif keep:
            dst = out_dir / "og-semana.jpg"
            dst.write_bytes(keep[0])
            return {"path": "assets/og-semana.jpg", "w": keep[1], "h": keep[2], "src": "--og-keep",
                    "bytes": len(keep[0])}, "no T11 feed image found: og image kept from --og-keep (unchanged bytes)"
        else:
            return None, "no T11 feed image found: og:image left out"
    from PIL import Image
    im = Image.open(src).convert("RGB")
    dst = out_dir / "og-semana.jpg"
    for w, q in ((1080, 82), (1080, 72), (864, 72), (720, 70)):
        img = im if im.width == w else im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
        img.save(dst, "JPEG", quality=q, optimize=True, progressive=True)
        if dst.stat().st_size <= 300_000:
            break
    return {"path": "assets/og-semana.jpg", "w": img.width, "h": img.height, "src": str(src),
            "bytes": dst.stat().st_size}, note


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", default=str(DESK / "events.jsonl"))
    ap.add_argument("--places", default=str(DESK / "places.json"))
    ap.add_argument("--out", default=str(HERE / "dist"))
    ap.add_argument("--today", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--weeks", type=int, default=8, help="max weeks shown, this one included (default 8)")
    ap.add_argument("--og-image", help="PNG for og:image (default: this week's T11 feed image)")
    ap.add_argument("--titular", default="Vincent Emmanuel Guacaran Bencomo",
                    help="name of the holder for the Aviso legal (confirmed by Vincent, 24 Nov 2026)")
    ap.add_argument("--report", default=str(HERE.parent / "qa" / "build-report.json"))
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--source-url", help="La Sacristía public JSON (contract §5) instead of --events/--places, "
                                          "e.g. https://sacristia.lacapillaoscura.es/public/agenda.json")
    src.add_argument("--source-file", help="same as --source-url, from a local file (tests)")
    ap.add_argument("--allow-empty", action="store_true",
                    help="with --source-*: build even if the source has no events (default: stop, exit 3)")
    ap.add_argument("--og-keep", help="already published og-semana.jpg, reused byte for byte when no T11 image is found")
    a = ap.parse_args()

    today = d_(a.today) if a.today else dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    # stamps depend on the build day only, so re-running on the same day with the same data gives identical files
    # (publish.sh commits only when something really changed)
    now = dt.datetime(today.year, today.month, today.day, tzinfo=dt.timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    if a.source_url or a.source_file:
        # everything is read and checked BEFORE --out is touched: on any problem the current site stays as it is
        origin = a.source_url or a.source_file
        try:
            text = fetch_source(a.source_url) if a.source_url else Path(a.source_file).read_text(encoding="utf-8")
            all_evs, places, src_monday = load_public_json(text, origin)
            if not all_evs and not a.allow_empty:
                raise SourceError(f"{origin}: no usable events (never publish an empty agenda; --allow-empty overrides)")
        except (SourceError, OSError, UnicodeDecodeError) as err:
            print(f"build: {err} -> nothing written, the current site stays as it is", file=sys.stderr)
            sys.exit(3)
        if src_monday and src_monday != monday.isoformat():
            print(f"  ! source week starts {src_monday}, this build's week starts {monday} (clock/time zone?)",
                  file=sys.stderr)
        a.events = origin
    else:
        all_evs = load_events(a.events)
        places = load_places(a.places)
    keep = None
    if a.og_keep and Path(a.og_keep).is_file():
        from PIL import Image
        try:
            with Image.open(a.og_keep) as im:
                if im.format == "JPEG":
                    keep = (Path(a.og_keep).read_bytes(), im.width, im.height)
        except Exception as err:  # noqa: BLE001 - a broken keep file only means "no og image"
            print(f"  ! --og-keep {a.og_keep}: not usable ({err})", file=sys.stderr)
    pub = [e for e in all_evs if is_public(e)]

    # weeks: this one up to the last week where a (non long-running) public event starts, max --weeks
    starts = [d_(e["date"]) for e in pub if d_(e["date"]) >= monday]
    last_start = max(starts) if starts else monday
    n_weeks = min(a.weeks, (last_start - monday).days // 7 + 1)
    mondays = [monday + dt.timedelta(weeks=i) for i in range(max(1, n_weeks))]
    horizon = mondays[-1] + dt.timedelta(days=6)
    weeks = [build_week(pub, places, m, today) for m in mondays]

    # per-week honesty report (unconfirmed = verify true and not hidden)
    report_weeks = []
    for m in mondays:
        s = m + dt.timedelta(days=6)
        inw = [e for e in all_evs if overlaps(e, m, s)]
        hidden = [e for e in inw if e.get("hidden")]
        unconf = [e for e in inw if not e.get("hidden") and e.get("verify")]
        shown = [e for e in inw if is_public(e)]
        cand = len(shown) + len(unconf)
        pct = round(100 * len(unconf) / cand, 1) if cand else 0.0
        report_weeks.append({"week": week_label(m, s), "monday": m.isoformat(), "shown": len(shown),
                             "left_out_unconfirmed": len(unconf), "hidden": len(hidden), "pct_left_out": pct,
                             "over_30pct": pct > 30, "unconfirmed_ids": [e["id"] for e in unconf]})

    # months: this month up to the horizon's month
    months, y, m = [], monday.year, monday.month
    week_dates = {d["date"] for w in weeks for d in w["days"]}
    while (y, m) <= (horizon.year, horizon.month):
        mo = build_month([e for e in pub if d_(e["date"]) <= horizon or long_run(e, monday, horizon)],
                         y, m, today, lambda d: d.isoformat() in week_dates)
        if any(c and c["count"] for wk in mo["weeks"] for c in wk):  # skip a month with only long-running items
            months.append(mo)
        y, m = (y + (m == 12), m % 12 + 1)

    # day -> ids (for the month tab's "tap a day" panel), only within the rendered weeks
    day_ids = {}
    for w in weeks:
        for d in w["days"]:
            ids = [r["id"] for r in d["rows"]]
            day = d_(d["date"])
            ids += [r["id"] for r in w["allweek"] if overlaps({"date": r["date"], "date_end": r["date_end"] or None}, day, day)]
            # short multi-day events placed on their first day also run on the following days
            for d2 in w["days"]:
                for r in d2["rows"]:
                    if r["date_end"] and r["id"] not in ids and d_(d2["date"]) < day <= d_(r["date_end"]):
                        ids.append(r["id"])
            day_ids[d["date"]] = ids

    published = sorted([e for e in pub if overlaps(e, monday, d_("9999-12-31")) and (d_(e["date"]) <= horizon)],
                       key=sort_key)
    upcoming = [e for e in published if end_of(e) >= today]

    # ------------------------------------------------ write dist/
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "assets" / "fonts").mkdir(parents=True)
    (out / "ics").mkdir()
    for f in (HERE / "static" / "fonts").iterdir():
        shutil.copy2(f, out / "assets" / "fonts" / f.name)
    for f in ("site.css", "site.js", "lco-mark.svg", "favicon.svg"):
        shutil.copy2(HERE / "static" / f, out / "assets" / f)
    og, og_note = og_image(monday, a.og_image, out / "assets", keep)
    if og_note:
        print("  !", og_note, file=sys.stderr)

    env = Environment(loader=FileSystemLoader(str(HERE / "tpl")), autoescape=select_autoescape(["html", "j2"]),
                      trim_blocks=True, lstrip_blocks=True)
    ctx = {
        "site": SITE, "email": EMAIL, "instagram": INSTAGRAM, "tiktok": TIKTOK, "today": today.isoformat(),
        "weeks": weeks, "months": months, "cur": weeks[0], "og": og,
        "types": [{"id": k, "lit": v[0], "label": v[1]} for k, v in TYPES.items()],
        "genres": [{"id": k, "label": v[0]} for k, v in GENRES.items()],
        "updated": f"{today.day} {MONTHS_LONG[today.month - 1]} {today.year}",
        "titular": a.titular, "build_stamp": now.isoformat(timespec="seconds"),
        "day_ids_json": json.dumps(day_ids, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"),
    }
    for tpl, name, root in (("index.html.j2", "index.html", ""), ("aviso-legal.html.j2", "aviso-legal.html", ""),
                            ("404.html.j2", "404.html", "/")):  # 404 is served at any path on GitHub Pages
        (out / name).write_text(env.get_template(tpl).render(**ctx, root=root), encoding="utf-8")

    (out / "agenda.json").write_text(json.dumps({
        "name": "La Capilla Oscura (LCO) · Horario de misas", "url": SITE + "/", "updated": today.isoformat(),
        "week": {"start": weeks[0]["start"], "end": weeks[0]["end"], "label": weeks[0]["label"]},
        "aviso": "Precios orientativos · compra en la web oficial. Solo eventos confirmados.",
        "events": [{k: e.get(k) for k in PUBLIC_FIELDS} | {"pick": bool(e.get("pick"))} for e in published],
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "agenda.ics").write_text(ics_calendar(upcoming, places, "Horario de misas · La Capilla Oscura", stamp),
                                    encoding="utf-8", newline="")
    for e in published:
        (out / "ics" / f"{e['id']}.ics").write_text(ics_calendar([e], places, e["title"], stamp),
                                                    encoding="utf-8", newline="")
    (out / "CNAME").write_text(DOMAIN + "\n", encoding="utf-8")
    (out / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    rep = {"built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "today": today.isoformat(), "events_file": a.events,
           "weeks": report_weeks, "published": len(published), "ics_upcoming": len(upcoming),
           "og_image": og, "og_note": og_note, "out": str(out)}
    Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    Path(a.report).write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"built {out} for week {weeks[0]['label']} (today {today}) · {len(weeks)} week(s), {len(months)} month(s), "
          f"{len(published)} events published, {len(upcoming)} in agenda.ics")
    for w in report_weeks:
        flag = "  <-- MORE THAN 30 % LEFT OUT" if w["over_30pct"] else ""
        print(f"  {w['week']:>14}: {w['shown']:2d} shown · {w['left_out_unconfirmed']:2d} left out (unconfirmed, "
              f"{w['pct_left_out']} %) · {w['hidden']} hidden{flag}")


if __name__ == "__main__":
    main()
