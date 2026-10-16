#!/usr/bin/env bash
# Publish the static report to GitHub Pages: build it from the latest runs in eval-runs/ and
# push it as the only file of the `gh-pages` branch. Manual by design (ADR-0004): no CI.
# First time only, enable Pages in the repo settings (source: branch gh-pages, folder /).
set -euo pipefail

cd "$(dirname "$0")/.."
remote="${PAGES_REMOTE:-origin}"
work="$(mktemp -d)"
trap 'git worktree remove --force "$work/site" 2>/dev/null || true; rm -rf "$work"' EXIT

compgen -G "eval-runs/*.json" >/dev/null || {
  echo "no evaluation run in eval-runs/ (it is git-ignored: run 'make eval' first)" >&2
  exit 1
}
uv run legal-radar report "$work/index.html"

# Tell "no gh-pages branch yet" (exit 2) from a network or auth failure (anything else).
status=0
git ls-remote --exit-code --heads "$remote" gh-pages >/dev/null || status=$?
if [ "$status" -eq 0 ]; then
  git fetch -q "$remote" gh-pages
  git worktree add -q --detach "$work/site" "$remote/gh-pages"
  git -C "$work/site" checkout -q -B gh-pages
elif [ "$status" -eq 2 ]; then
  git worktree add -q --detach "$work/site"
  git -C "$work/site" checkout -q --orphan gh-pages
  git -C "$work/site" rm -rfq .
else
  echo "could not reach remote '$remote'" >&2
  exit 1
fi
# The page embeds its generation time; ignore it to tell whether anything else changed.
stamp() { sed 's/generated [0-9: -]* UTC//' "$1"; }
same=1
for page in index.html graph.html; do
  if [ -f "$work/$page" ] || [ -f "$work/site/$page" ]; then
    [ -f "$work/$page" ] && [ -f "$work/site/$page" ] &&
      diff -q <(stamp "$work/site/$page") <(stamp "$work/$page") >/dev/null || same=0
  fi
done
if [ "$same" -eq 1 ]; then
  echo "report unchanged; nothing to publish"
  exit 0
fi
cp "$work/index.html" "$work/site/index.html"
# graph.html exists only when the seed and an enrichment run were found; drop a stale one otherwise.
if [ -f "$work/graph.html" ]; then
  cp "$work/graph.html" "$work/site/graph.html"
else
  rm -f "$work/site/graph.html"
fi
touch "$work/site/.nojekyll"
git -C "$work/site" add -A  # the worktree holds only the generated pages; graph.html may be absent
# --no-verify: the gh-pages branch is generated output, not subject to the commit hooks.
git -C "$work/site" commit -q --no-verify -m "chore(report): publish report $(date -u +%Y-%m-%dT%H:%MZ)"
git -C "$work/site" push "$remote" gh-pages
echo "published: https://emvalencaf.github.io/legal-radar/"
