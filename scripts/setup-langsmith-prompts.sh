#!/usr/bin/env bash
#
# A wizard walks a human through a manual procedure, step by step.
# Wizard: publish the prompts to the LangSmith Hub and capture their manifests (issue #42).
#
# Everything above the "STAGES" marker is the wizard library: do not hand-edit
# it. Author the per-step stages below the marker.

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────
# Wizard library: delightful, consistent UX, identical across every wizard.
# ──────────────────────────────────────────────────────────────────────────

if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
  BOLD=$(tput bold); DIM=$(tput dim); RESET=$(tput sgr0)
  BLUE=$(tput setaf 4); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3); RED=$(tput setaf 1)
else
  BOLD=""; DIM=""; RESET=""; BLUE=""; GREEN=""; YELLOW=""; RED=""
fi

# Author sets this at the top of the stages section.
TOTAL_STAGES=0

_STAGE_INDEX=0
ENV_FILE="${ENV_FILE:-.env}"
WRITTEN_ENV=()    # KEYs written to ENV_FILE this run
WRITTEN_SECRET=() # secret NAMEs set this run
SKIPPED=()        # things we couldn't do (e.g. gh missing)

# _clear wipes the terminal so only the current step is on screen. No-op when
# output isn't a terminal, so piped logs stay readable.
_clear() {
  [[ -t 1 ]] || return 0
  if command -v tput >/dev/null 2>&1; then tput clear; else printf '\033[2J\033[3J\033[H'; fi
}

# banner "Title" shows the opening frame: what this wizard does.
banner() {
  _clear
  printf '\n%s%s  %s%s\n' "$BOLD" "$BLUE" "$1" "$RESET"
  printf '%s  %s stages%s\n\n' "$DIM" "$TOTAL_STAGES" "$RESET"
  printf '%s  You drive the browser; this wizard tells you exactly what to do and\n' "$DIM"
  printf '  captures the values you copy back. Stop any time with Ctrl-C and re-run\n'
  printf '  later, since it remembers values already saved.%s\n' "$RESET"
  pause "Ready to start?"
}

# stage "Name" clears the screen, then announces a stage and shows progress.
# Clearing keeps only the current step on screen.
stage() {
  _clear
  _STAGE_INDEX=$((_STAGE_INDEX + 1))
  printf '\n%s%s▸ Stage %s/%s · %s%s\n' \
    "$BOLD" "$BLUE" "$_STAGE_INDEX" "$TOTAL_STAGES" "$1" "$RESET"
}

# say "..." prints a plain instruction line.
say()  { printf '  %s\n' "$1"; }
# step "..." is a numbered-feeling action the human takes in the browser.
step() { printf '  %s•%s %s\n' "$BLUE" "$RESET" "$1"; }
note() { printf '  %s%s%s\n' "$DIM" "$1" "$RESET"; }
warn() { printf '  %s⚠ %s%s\n' "$YELLOW" "$1" "$RESET"; }

# open_url URL opens it in the human's browser, cross-platform incl. WSL.
open_url() {
  local url="$1"
  printf '  %s↗ opening%s %s\n' "$GREEN" "$RESET" "$url"
  { if   command -v wslview     >/dev/null 2>&1; then wslview "$url"
    elif command -v explorer.exe >/dev/null 2>&1; then explorer.exe "$url"
    elif command -v xdg-open    >/dev/null 2>&1; then xdg-open "$url"
    elif command -v open        >/dev/null 2>&1; then open "$url"
    else warn "couldn't open a browser; visit it manually: $url"; fi
  } >/dev/null 2>&1 || warn "couldn't open a browser, so visit it manually: $url"
}

# pause "msg" waits for the human to confirm they've done the manual part.
pause() {
  printf '  %s%s%s ' "$DIM" "${1:-Press Enter to continue}" "$RESET"
  read -r _ || true
}

# confirm "question" is a y/N gate; returns success on yes.
confirm() {
  local reply=""
  printf '  %s? %s [y/N] ' "$YELLOW" "$1"
  read -r reply || true
  [[ "$reply" =~ ^[Yy] ]]
}

# _existing KEY: current value of KEY in ENV_FILE, if any.
_existing() {
  [[ -f "$ENV_FILE" ]] || return 1
  local line; line=$(grep -E "^${1}=" "$ENV_FILE" | tail -n1) || return 1
  printf '%s' "${line#*=}"
}

# ask KEY "Prompt" reads a value into $KEY. Offers the existing .env value as
# a default on re-runs (Enter keeps it). Visible input (non-secret).
ask() {
  local key="$1" prompt="$2" current input
  current=$(_existing "$key" || true)
  if [[ -n "$current" ]]; then
    printf '  %s%s%s %s[Enter keeps current]%s ' "$BOLD" "$prompt" "$RESET" "$DIM" "$RESET"
  else
    printf '  %s%s%s ' "$BOLD" "$prompt" "$RESET"
  fi
  read -r input || true
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}

# ask_secret KEY "Prompt" is like ask, but input is hidden.
ask_secret() {
  local key="$1" prompt="$2" current input
  current=$(_existing "$key" || true)
  if [[ -n "$current" ]]; then
    printf '  %s%s%s %s[Enter keeps current]%s ' "$BOLD" "$prompt" "$RESET" "$DIM" "$RESET"
  else
    printf '  %s%s%s ' "$BOLD" "$prompt" "$RESET"
  fi
  read -rs input || true
  printf '\n'
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}

# write_env KEY VALUE upserts KEY=VALUE into ENV_FILE (creates it; replaces
# any existing line). Idempotent.
write_env() {
  local key="$1" value="$2" tmp
  touch "$ENV_FILE"
  tmp=$(mktemp)
  grep -vE "^${key}=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$ENV_FILE"
  WRITTEN_ENV+=("$key")
  printf '  %s✓ wrote%s %s → %s\n' "$GREEN" "$RESET" "$key" "$ENV_FILE"
}

# set_secret NAME VALUE sets a GitHub Actions repo secret via gh. Falls back
# to a warning (and records it) if gh is unavailable or unauthenticated.
set_secret() {
  local name="$1" value="$2"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if printf '%s' "$value" | gh secret set "$name" >/dev/null 2>&1; then
      WRITTEN_SECRET+=("$name")
      printf '  %s✓ set%s GitHub secret %s\n' "$GREEN" "$RESET" "$name"
      return
    fi
  fi
  SKIPPED+=("GitHub secret $name (set it manually: gh secret set $name)")
  warn "skipped GitHub secret $name: gh not ready; set it later"
}

# set_var NAME VALUE sets a GitHub Actions repo variable (non-secret).
set_var() {
  local name="$1" value="$2"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if gh variable set "$name" --body "$value" >/dev/null 2>&1; then
      printf '  %s✓ set%s GitHub variable %s\n' "$GREEN" "$RESET" "$name"
      return
    fi
  fi
  SKIPPED+=("GitHub variable $name")
  warn "skipped GitHub variable $name, gh not ready; set it later"
}

# finish clears, then shows a closing summary of everything configured.
finish() {
  _clear
  printf '\n%s%s  ✓ Setup complete%s\n' "$BOLD" "$GREEN" "$RESET"
  (( ${#WRITTEN_ENV[@]} ))    && note "wrote ${#WRITTEN_ENV[@]} value(s) to $ENV_FILE: ${WRITTEN_ENV[*]}"
  (( ${#WRITTEN_SECRET[@]} )) && note "set ${#WRITTEN_SECRET[@]} GitHub secret(s): ${WRITTEN_SECRET[*]}"
  if (( ${#SKIPPED[@]} )); then
    printf '\n'; warn "still to do by hand:"
    for s in "${SKIPPED[@]}"; do note "  - $s"; done
  fi
  printf '\n'
}

# ──────────────────────────────────────────────────────────────────────────
# STAGES: publish the prompts to the LangSmith Hub, pin their commits, refresh the lockfile.
# ──────────────────────────────────────────────────────────────────────────

TOTAL_STAGES=5

MANIFEST_DIR="prompts/manifests"

banner "LangSmith Hub: publish, pin and refresh the prompts"

stage "LangSmith: API key"
say "Only 'make refresh-prompts' talks to LangSmith; the pipeline and tests stay offline."
open_url "https://smith.langchain.com/settings"
step "Sign in (the free Developer plan is enough)."
step "Settings → API Keys → Create API Key (type: Personal Access Token)."
step "Copy the key (starts lsv2_)."
ask_secret LANGSMITH_API_KEY "Paste the API key:"
write_env LANGSMITH_API_KEY "$LANGSMITH_API_KEY"
export LANGSMITH_API_KEY

stage "Install the langsmith extra"
say "Installs the optional 'prompts' extra (langsmith) into the project environment."
uv sync --extra prompts
say "Prompts to publish (names from prompts/pins.yml):"
grep -E '^[a-z]' prompts/pins.yml | cut -d: -f1 | sed 's/^/    - /'

stage "Publish the prompts to the Hub"
say "Pushes each template in prompts/lock.json to your LangSmith workspace under the same name."
say "concepts-count and concepts-extract are pushed as structured prompts (JSON Schema from"
say "legal_radar.application.concepts); the 'sources' enum of concepts-extract is a placeholder, because"
say "the real one is injected at run time."
warn "This publishes the prompt text to LangSmith (private to your workspace by default)."
if confirm "Push the prompts now?"; then
  uv run --extra prompts --with langchain-core python - <<'PY'
import json
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.prompts.structured import StructuredPrompt
from langsmith import Client

from legal_radar.application.concepts import count_schema, extract_schema
from legal_radar.adapters.prompt_lock import load_lock

schemas = {"concepts-count": count_schema(), "concepts-extract": extract_schema(["placeholder"])}
client = Client()
for name, entry in load_lock().prompts.items():
    messages = [("human", entry["template"])]
    if name in schemas:
        schema = {"title": name.replace("-", "_"), **schemas[name]}
        prompt = StructuredPrompt.from_messages_and_schema(messages, schema)
    else:
        prompt = ChatPromptTemplate.from_messages(messages)
    print(f"  pushed {name}: {client.push_prompt(name, object=prompt)}")
PY
else
  say "Skipped. Publish them by hand in the Playground under the names above, then continue."
  pause "Press Enter once all three prompts are saved in the Hub."
fi

stage "Capture the manifests"
say "Pulls each prompt's latest commit and saves its raw manifest, so we can see exactly where"
say "the template and the schema live (the part we could not confirm from the docs)."
mkdir -p "$MANIFEST_DIR"
uv run --extra prompts python - "$MANIFEST_DIR" <<'PY'
import json
import sys
from pathlib import Path

from langsmith import Client

from legal_radar.adapters.prompt_lock import load_pins

out = Path(sys.argv[1])
client = Client()
hashes = {}
for name in load_pins():
    commit = client.pull_prompt_commit(name)
    hashes[name] = commit.commit_hash
    (out / f"{name}.json").write_text(
        json.dumps(commit.manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"  {name}: commit {commit.commit_hash[:12]} → {out / (name + '.json')}")
(out / "commits.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
PY
note "Manifests are in $MANIFEST_DIR/. They contain only your prompt text and schemas, no secrets."

stage "Pin the commits and refresh the lockfile"
say "Replaces 'local' in prompts/pins.yml with the commit hashes just captured, then runs"
say "the refresh, which rewrites prompts/lock.json from the Hub at those hashes."
uv run python - "$MANIFEST_DIR/commits.json" <<'PY'
import json
import sys
from pathlib import Path

hashes = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
header = "# Hub commit each prompt follows.\n"
Path("prompts/pins.yml").write_text(
    header + "".join(f"{n}: {c}\n" for n, c in sorted(hashes.items())), encoding="utf-8"
)
PY
uv run --extra prompts legal-radar refresh-prompts || warn "refresh failed: send the output above to Claude"
say "Checking the offline tests still pass against the new lockfile..."
uv run pytest -q tests/test_prompts.py || warn "tests failed: send the output above to Claude"
step "Tell Claude the wizard is done; the manifests in $MANIFEST_DIR/ are what it needs next."

finish
