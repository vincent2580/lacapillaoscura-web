#!/usr/bin/env bash
# La Capilla Oscura · rebuild lacapillaoscura.es (v2) from La Sacristía's two public feeds. Runs inside the PUBLIC repo
# vincent2580/lacapillaoscura-web (called by .github/workflows/build-pages.yml; also runnable by hand in a clone).
# No credentials: both feeds and the week image are public.
#
#   bash build/rebuild.sh                     # from the repo root
#
# Env: SOURCE_URL, SITE_URL (or SOURCE_FILE / SITE_FILE for tests) · WEEK_IMAGE_URL (optional og image)
#      MODE = branch (default: put the site in the repo root, commit if changed; GitHub Pages "Deploy from a branch")
#           | artifact (only build into $WORK/site for actions/upload-pages-artifact; Pages source "GitHub Actions")
#      PUSH (1 = push the commit, default 1) · ACCEPT_SHRINK (1 = allow a big drop) · BUILD_ARGS (extra build.py args)
#      PY (default python3) · WORK (default $RUNNER_TEMP/lco-pages) · GITHUB_OUTPUT (set by Actions)
# Exit: 0 = built (and committed/pushed if something changed) · 3 = a feed is unreachable/invalid/empty: NOTHING
#       changed, the published site stays as it is (the job goes red on purpose) · 5 = site_guard refused the build
#       (nothing changed) · other = build/git error (nothing published)
# Outputs: changed=true|false · site=<dir of the new site>
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

PY="${PY:-python3}"
WORK="${WORK:-${RUNNER_TEMP:-/tmp}/lco-pages}"
MODE="${MODE:-branch}"
PUSH="${PUSH:-1}"
BRANCH="main"
OUT="${GITHUB_OUTPUT:-/dev/null}"
fail() { echo "::error::$*"; }

[ -f build/build.py ] && [ -f CNAME ] || { fail "run from the root of lacapillaoscura-web (build/build.py + CNAME)"; exit 2; }
case "$MODE" in branch|artifact) ;; *) fail "MODE must be branch or artifact"; exit 2;; esac
rm -rf "$WORK"; mkdir -p "$WORK"

# 1. og image: this week's feed picture from La Sacristía (optional; else the published og-semana.jpg is kept)
OG=()
if [ -n "${WEEK_IMAGE_URL:-}" ]; then
  if curl -fsSL --proto '=https' --proto-redir '=https' --max-time 30 --retry 2 --max-filesize 15000000 \
       -o "$WORK/week.png" "$WEEK_IMAGE_URL" 2>"$WORK/week.err" \
     && "$PY" -c 'import sys; b=open(sys.argv[1],"rb").read(8); sys.exit(0 if b==b"\x89PNG\r\n\x1a\n" else 1)' "$WORK/week.png"; then
    OG=(--og-image "$WORK/week.png")
    echo "== og image: week image fetched"
  else
    echo "== og image: none fetched; keeping the published one"
    rm -f "$WORK/week.png"
  fi
fi

# 2. build into WORK/site. build.py reads + checks BOTH feeds before writing anything (exit 3 = unusable feed)
if [ -n "${SOURCE_FILE:-}" ]; then SRC=(--source-file "$SOURCE_FILE"); else SRC=(--source-url "${SOURCE_URL:?SOURCE_URL needed}"); fi
if [ -n "${SITE_FILE:-}" ]; then SIT=(--site-file "$SITE_FILE"); else SIT=(--site-url "${SITE_URL:?SITE_URL needed}"); fi
read -r -a EXTRA <<< "${BUILD_ARGS:-}"
set +e
"$PY" build/build.py "${SRC[@]}" "${SIT[@]}" --out "$WORK/site" --report "$WORK/build-report.json" \
  --og-keep assets/og-semana.jpg ${OG[@]+"${OG[@]}"} ${EXTRA[@]+"${EXTRA[@]}"}
rc=$?
set -e
if [ "$rc" != 0 ]; then
  echo "changed=false" >> "$OUT"
  fail "build.py exit $rc (3 = a La Sacristía feed is unreachable/invalid/empty): nothing changed, the published site stays"
  exit "$rc"
fi

# 3. last check against the published site (the repo root holds what is published in branch mode)
GUARD=()
[ "${ACCEPT_SHRINK:-0}" = 1 ] && GUARD=(--accept-shrink)
CUR=()
[ -f index.html ] && [ -f agenda/index.html ] && CUR=(.)
"$PY" build/site_guard.py "$WORK/site" ${CUR[@]+"${CUR[@]}"} ${GUARD[@]+"${GUARD[@]}"} \
  || { echo "changed=false" >> "$OUT"; fail "site_guard refused the new build: nothing changed"; exit 5; }
echo "site=$WORK/site" >> "$OUT"
if [ "$MODE" = artifact ]; then
  echo "changed=true" >> "$OUT"
  exit 0
fi

# 4. branch mode: the new site replaces the repo root; build/, .github/, README.md, .gitignore are not site files
rsync -a --delete --exclude ".git/" --exclude ".github/" --exclude "build/" --exclude "README.md" \
  --exclude ".gitignore" "$WORK/site/" ./
git add -A
if git diff --cached --quiet; then
  echo "== nothing changed: no commit"
  echo "changed=false" >> "$OUT"
  exit 0
fi
git diff --cached --stat | tail -5
WEEK="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["week"]["label"])' agenda.json)"
git -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
  commit --quiet -m "lacapillaoscura.es: semana ${WEEK} (rebuild $(date +%Y-%m-%d))" \
  -m "Rebuilt by build-pages.yml from La Sacristía's public feeds (agenda.json + site.json)."
echo "changed=true" >> "$OUT"
if [ "$PUSH" = 1 ]; then
  if ! git push --quiet origin "HEAD:refs/heads/${BRANCH}"; then
    echo "== push rejected: rebasing on origin/${BRANCH} once"
    git pull --quiet --rebase origin "$BRANCH"
    git push --quiet origin "HEAD:refs/heads/${BRANCH}"
  fi
  echo "== pushed $(git rev-parse --short HEAD)"
fi
