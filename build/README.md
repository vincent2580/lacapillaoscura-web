# build/ — generator of lacapillaoscura.es (v2)

```bash
python -m pip install --require-hashes -r build/requirements.txt
python build/build.py --source-url https://sacristia.lacapillaoscura.es/public/agenda.json \
                      --site-url https://sacristia.lacapillaoscura.es/public/site.json --out /tmp/site
python build/site_guard.py /tmp/site .        # last check against the published site (repo root)
bash build/rebuild.sh                         # what the workflow runs (MODE=branch|artifact, see the header)
```

| File | What |
|---|---|
| `build.py` | the site: pages, agenda files, Templos KML/KMZ/CSV. Fetches and checks both feeds before writing anything (exit 3 = feed unusable, nothing written). Default = public mode: any block whose text is still a placeholder is left out (exit 4 if one slips through); `--preview` shows them |
| `lco_agenda.py` | the v1 agenda builder, vendored unchanged except two default paths (so `agenda.json`, `agenda.ics`, `ics/<id>.ics` keep their exact format) |
| `maps_export.py` | Google Maps / Apple Maps links, KML/KMZ/CSV |
| `site_guard.py` | refuses a build with missing pages, private fields, placeholders, a broken KML or a big unexplained shrink |
| `site-config.json` | `MYMAPS_URL`: the public Google My Maps link of "LCO · Templos de Madrid" (empty = downloads only) |
| `content/` | the crónica and manifesto texts exactly as published on Instagram; `textos.json` = page texts by id (empty = not shown) |
| `tpl/`, `static/` | templates, CSS/JS, fonts (SIL OFL, licences included), Leaflet 1.9.4 (BSD-2), images cut from published posts |
