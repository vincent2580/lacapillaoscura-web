"""La Capilla Oscura v2 · Templos for map apps: per-place Google Maps / Apple Maps links and the downloadable
"LCO · Templos de Madrid" list (KML, KMZ, CSV). Standard library only.

Link formats (checked 24 Nov 2026):
- Google Maps URLs, Search action: https://www.google.com/maps/search/?api=1&query=<name, address> — Google
  documents "place name, address" as the way to show a specific place's details (coordinates alone = a bare pin).
  https://developers.google.com/maps/documentation/urls/get-started
- Apple unified Maps URLs (iOS 18.4+ / macOS 15.4+; Apple Maps on the web elsewhere), /search with `query` and an
  optional `center`: https://maps.apple.com/search?query=<name, address>&center=<lat,lon>
  https://developer.apple.com/documentation/mapkit/unified-map-urls
"""
import csv
import io
import urllib.parse
import zipfile
from xml.sax.saxutils import escape

SITE = "https://lacapillaoscura.es"
DOC_NAME = "LCO · Templos de Madrid"
DOC_DESC = "Recomendaciones de La Capilla Oscura · https://lacapillaoscura.es/templos/"
FILE_STEM = "LCO-Templos-Madrid"
# kind -> (singular label, KML folder name, colour #RRGGBB = the site's map pins)
KIND_META = {
    "sala": ("Sala", "Salas", "#D83A3F"),
    "club": ("Club", "Clubs", "#9B7FD6"),
    "bar": ("Bar", "Bares", "#D6A43E"),
    "tienda": ("Tienda de discos", "Tiendas", "#46B3A5"),
    "museo": ("Museo", "Museos", "#6F98DE"),
    "otro": ("Otro", "Otros", "#A39C90"),
}
ICON = "https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png"  # My Maps' own plain pin (tinted)
CSV_COLUMNS = ("name", "latitude", "longitude", "address", "kind", "styles", "info", "link")
ZIP_DATE = (2026, 1, 1, 0, 0, 0)  # fixed, so the KMZ is byte-identical for identical data


def query_text(t):
    """'<name>, <address or area>, Madrid' — name + address so the business listing opens, not a bare pin."""
    where = t["address"] if t["address"] and not t["approx"] else t["area"]
    parts = [t["name"]]
    if where and where.lower() not in t["name"].lower():
        parts.append(where)
    if not any("madrid" in p.lower() for p in parts):
        parts.append("Madrid")
    return ", ".join(parts)


def google_url(t):
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(query_text(t), safe="")


def apple_url(t):
    u = "https://maps.apple.com/search?query=" + urllib.parse.quote(query_text(t), safe="")
    if t.get("lat") is not None and t.get("lon") is not None:
        u += f"&center={t['lat']:.5f},{t['lon']:.5f}"
    return u


def kind_of(t):
    return t["kind"] if t["kind"] in KIND_META else "otro"


def where_line(t):
    if t["address"] and not t["approx"]:
        return t["address"] + (f" · {t['area']}" if t["area"] else "") + " · Madrid"
    return (t["area"] or "Madrid") + " · ubicación aproximada"


def links_of(t):
    out = []
    if t.get("url"):
        out.append(t["url"])
    if t.get("instagram_url"):
        out.append(t["instagram_url"])
    return out


def description(t, style_labels):
    lines = [KIND_META[kind_of(t)][0] + (" · " + ", ".join(style_labels) if style_labels else ""), where_line(t)]
    if t.get("status") == "cierra":
        lines.append("Cierra" + (f": {t['status_note']}" if t.get("status_note") else ""))
    elif t.get("status") == "cerrado":
        lines.append("Cerrado" + (f": {t['status_note']}" if t.get("status_note") else ""))
    elif t.get("status_note"):
        lines.append(t["status_note"])
    if t.get("info"):
        lines.append(t["info"])
    lines += links_of(t)
    lines.append(f"Más en lacapillaoscura.es/templos/#{t['id']}")
    return "\n".join(lines)


def kml_color(hex_rgb):
    r, g, b = hex_rgb[1:3], hex_rgb[3:5], hex_rgb[5:7]
    return ("ff" + b + g + r).lower()


def kml(templos, style_labels_of):
    """KML 2.2: document name/description, one colour style per kind, one Folder per kind (only kinds in use)."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<kml xmlns="http://www.opengis.net/kml/2.2">',
           "<Document>",
           f"<name>{escape(DOC_NAME)}</name>",
           f"<description>{escape(DOC_DESC)}</description>"]
    for k, (_, _, color) in KIND_META.items():
        out += [f'<Style id="lco-{k}">',
                f"<IconStyle><color>{kml_color(color)}</color><scale>1.1</scale>"
                f"<Icon><href>{ICON}</href></Icon></IconStyle>",
                "<LabelStyle><scale>0.9</scale></LabelStyle>",
                "</Style>"]
    for k, (_, folder, _) in KIND_META.items():
        items = [t for t in templos if kind_of(t) == k and t.get("lat") is not None and t.get("lon") is not None]
        if not items:
            continue
        out += ["<Folder>", f"<name>{escape(folder)}</name>"]
        for t in items:
            desc = description(t, style_labels_of(t))
            out += [f'<Placemark id="{escape(t["id"])}">',
                    f"<name>{escape(t['name'])}</name>",
                    f"<description>{escape(desc)}</description>",
                    f"<styleUrl>#lco-{k}</styleUrl>",
                    "<ExtendedData>"
                    f'<Data name="Tipo"><value>{escape(KIND_META[k][0])}</value></Data>'
                    f'<Data name="Ubicación"><value>{"aproximada" if t["approx"] else "exacta"}</value></Data>'
                    f'<Data name="Ficha LCO"><value>{SITE}/templos/#{escape(t["id"])}</value></Data>'
                    "</ExtendedData>",
                    f"<Point><coordinates>{t['lon']:.5f},{t['lat']:.5f},0</coordinates></Point>",
                    "</Placemark>"]
        out.append("</Folder>")
    out += ["</Document>", "</kml>"]
    return "\n".join(out) + "\n"


def kmz(kml_text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo("doc.kml", date_time=ZIP_DATE)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        z.writestr(info, kml_text.encode("utf-8"))
    return buf.getvalue()


def csv_text(templos, style_labels_of):
    """Columns for Google My Maps import (position = latitude/longitude, title = name)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNS)
    for t in templos:
        if t.get("lat") is None or t.get("lon") is None:
            continue
        info = " · ".join(x for x in (t.get("info"), t.get("status_note"),
                                       "ubicación aproximada" if t["approx"] else "",
                                       f"Más en lacapillaoscura.es/templos/#{t['id']}") if x)
        addr = (t["address"] + ", Madrid") if t["address"] and not t["approx"] else \
            f"{t['area'] or 'Madrid'}, Madrid (ubicación aproximada)"
        w.writerow([t["name"], f"{t['lat']:.5f}", f"{t['lon']:.5f}", addr, KIND_META[kind_of(t)][0],
                    ", ".join(style_labels_of(t)), info, (links_of(t) or [f"{SITE}/templos/#{t['id']}"])[0]])
    return buf.getvalue()
