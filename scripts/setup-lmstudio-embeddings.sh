#!/usr/bin/env bash
#
# Wizard: configure LM Studio embeddings (text-embedding-bge-m3) for legal-radar.
# Everything above the "STAGES" marker is the wizard library from the /wizard skill.

set -euo pipefail

if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
  BOLD=$(tput bold); DIM=$(tput dim); RESET=$(tput sgr0)
  BLUE=$(tput setaf 4); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3); RED=$(tput setaf 1)
else
  BOLD=""; DIM=""; RESET=""; BLUE=""; GREEN=""; YELLOW=""; RED=""
fi

TOTAL_STAGES=0

_STAGE_INDEX=0
ENV_FILE="${ENV_FILE:-.env}"
WRITTEN_ENV=()
WRITTEN_SECRET=()
SKIPPED=()

_clear() {
  [[ -t 1 ]] || return 0
  if command -v tput >/dev/null 2>&1; then tput clear; else printf '\033[2J\033[3J\033[H'; fi
}

banner() {
  _clear
  printf '\n%s%s  %s%s\n' "$BOLD" "$BLUE" "$1" "$RESET"
  printf '%s  %s stages%s\n\n' "$DIM" "$TOTAL_STAGES" "$RESET"
  printf '%s  You drive the browser; this wizard tells you exactly what to do and\n' "$DIM"
  printf '  captures the values you copy back. Stop any time with Ctrl-C and re-run\n'
  printf '  later, since it remembers values already saved.%s\n' "$RESET"
  pause "Ready to start?"
}

stage() {
  _clear
  _STAGE_INDEX=$((_STAGE_INDEX + 1))
  printf '\n%s%s▸ Stage %s/%s · %s%s\n' \
    "$BOLD" "$BLUE" "$_STAGE_INDEX" "$TOTAL_STAGES" "$1" "$RESET"
}

say()  { printf '  %s\n' "$1"; }
step() { printf '  %s•%s %s\n' "$BLUE" "$RESET" "$1"; }
note() { printf '  %s%s%s\n' "$DIM" "$1" "$RESET"; }
warn() { printf '  %s⚠ %s%s\n' "$YELLOW" "$1" "$RESET"; }

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

pause() {
  printf '  %s%s%s ' "$DIM" "${1:-Press Enter to continue}" "$RESET"
  read -r _ || true
}

confirm() {
  local reply=""
  printf '  %s? %s [y/N] ' "$YELLOW" "$1"
  read -r reply || true
  [[ "$reply" =~ ^[Yy] ]]
}

_existing() {
  [[ -f "$ENV_FILE" ]] || return 1
  local line; line=$(grep -E "^${1}=" "$ENV_FILE" | tail -n1) || return 1
  printf '%s' "${line#*=}"
}

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

finish() {
  _clear
  printf '\n%s%s  ✓ Setup complete%s\n' "$BOLD" "$GREEN" "$RESET"
  (( ${#WRITTEN_ENV[@]} ))    && note "wrote ${#WRITTEN_ENV[@]} value(s) to $ENV_FILE: ${WRITTEN_ENV[*]}"
  if (( ${#SKIPPED[@]} )); then
    printf '\n'; warn "still to do by hand:"
    for s in "${SKIPPED[@]}"; do note "  - $s"; done
  fi
  printf '\n'
}

# ──────────────────────────────────────────────────────────────────────────
# STAGES
# ──────────────────────────────────────────────────────────────────────────

TOTAL_STAGES=3

banner "LM Studio embeddings (text-embedding-bge-m3) for legal-radar"

stage "Load the embedding model in LM Studio"
say "router.yaml expects the model id text-embedding-bge-m3 (multilingual, handles Portuguese)."
open_url "https://lmstudio.ai/models/baai/bge-m3"
step "In LM Studio, open Discover, search 'bge-m3' and download a GGUF build."
step "Open the Developer tab, load the model, and start the local server."
step "If its id differs from text-embedding-bge-m3, set embedding_models.lmstudio in router.yaml."
step "WSL only: enable 'Serve on Local Network' so Linux can reach the Windows host."
pause "Model loaded and server running?"

stage "Save the server URL to .env"
say "Default is http://localhost:1234/v1. Under WSL use the Windows host IP instead,"
say "e.g. http://$(awk '/nameserver/ {print $2; exit}' /etc/resolv.conf 2>/dev/null || echo HOST):1234/v1"
ask LMSTUDIO_BASE_URL "LM Studio base URL (ending in /v1):"
LMSTUDIO_BASE_URL="${LMSTUDIO_BASE_URL:-http://localhost:1234/v1}"
write_env LMSTUDIO_BASE_URL "$LMSTUDIO_BASE_URL"
if curl -s -m 5 "$LMSTUDIO_BASE_URL/models" | grep -q bge; then
  say "${GREEN}✓ server reachable and a bge model is listed${RESET}"
else
  warn "couldn't see a bge model at $LMSTUDIO_BASE_URL/models; check the server and model id"
fi

stage "Live check: embed call and threshold scores"
say "Runs one real embed call, then scores related vs unrelated queries against the"
say "anchor assunto catalog, so you can judge the 0.5 resolver threshold."
if confirm "Run it now?"; then
  if LMSTUDIO_BASE_URL="$LMSTUDIO_BASE_URL" uv run python scripts/check_embeddings.py lmstudio; then
    say ""
    step "Related queries should say RESOLVED, unrelated ones rejected."
    step "If not, tune DEFAULT_THRESHOLD in src/legal_radar/application/assunto.py between the two groups' scores."
  else
    SKIPPED+=("live check failed: see the error above (server down, model not loaded, or wrong id)")
  fi
else
  SKIPPED+=("run: LMSTUDIO_BASE_URL=$LMSTUDIO_BASE_URL uv run python scripts/check_embeddings.py lmstudio")
fi
pause "Done reading?"

finish
