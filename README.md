# lacapillaoscura.es

Web de **La Capilla Oscura (LCO)**: horario de misas (conciertos de rock, metal y cultura oscura en Madrid), lo que
suena, crónicas, saber, templos y tienda. Colto a la música.

- The site is static and rebuilt **every 2 hours** by `.github/workflows/build-pages.yml` from La Sacristía's two
  public feeds: `https://sacristia.lacapillaoscura.es/public/agenda.json` and `.../public/site.json`. They contain
  only public information (confirmed events, public data of the places, album titles and ratings).
- `build/` is the generator (Python + Jinja2, `build/README.md`). The repo root is the published site.
- Calendar subscriptions keep working: `/agenda.ics`, `/agenda.json`, `/ics/<id>.ics`.
- Templos for map apps: `/templos/LCO-Templos-Madrid.kml` (also `.kmz`, `.csv`).
- No cookies, no analytics, no third-party requests (the OpenStreetMap tiles load only after "Abrir el mapa").

Contacto: info@lacapillaoscura.es · Instagram [@lacapillaoscura](https://www.instagram.com/lacapillaoscura/)
