#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./install.sh --global
  ./install.sh --project /path/to/repository

The script installs the Skill and four optional Luna custom-agent profiles.
It does not edit config.toml, AGENTS.md, or custom routing tables.
For the recommended Codex-guided setup, read references/codex-guided-install.md.
EOF
}

MODE="global"
PROJECT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --global)
      MODE="global"
      shift
      ;;
    --project)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      MODE="project"
      PROJECT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$MODE" == "global" ]]; then
  SKILLS_BASE="${CODEX_SKILLS_DIR:-$HOME/.agents/skills}"
  AGENTS_BASE="${CODEX_AGENTS_DIR:-${CODEX_HOME:-$HOME/.codex}/agents}"
else
  PROJECT="$(cd "$PROJECT" && pwd)"
  SKILLS_BASE="$PROJECT/.agents/skills"
  AGENTS_BASE="$PROJECT/.codex/agents"
fi

DEST_SKILL="$SKILLS_BASE/codex-luna-subagent-router"
mkdir -p "$SKILLS_BASE" "$AGENTS_BASE"

python3 - "$SOURCE_DIR" "$DEST_SKILL" <<'PY'
from pathlib import Path
import shutil
import sys

src = Path(sys.argv[1]).resolve()
dst = Path(sys.argv[2]).resolve()
if src == dst:
    raise SystemExit(0)

def ignore(path: str, names: list[str]) -> set[str]:
    return {name for name in names if name in {'.git', '__pycache__', 'dist'}}

if dst.exists():
    shutil.rmtree(dst)
shutil.copytree(src, dst, ignore=ignore)
PY

cp "$SOURCE_DIR"/assets/codex-agents/*.toml "$AGENTS_BASE"/
chmod +x \
  "$DEST_SKILL/install.sh" \
  "$DEST_SKILL/scripts/configure_guided_install.py" \
  "$DEST_SKILL/scripts/validate_route_plan.py"

python3 "$DEST_SKILL/scripts/validate_route_plan.py" \
  "$DEST_SKILL/examples/route-plan.valid.json" >/dev/null

echo "Installed Skill: $DEST_SKILL"
echo "Installed Luna profiles: $AGENTS_BASE/luna-{medium,high,xhigh,max}.toml"
echo
echo "Next steps:"
echo "1. Recommended: ask Codex to follow $DEST_SKILL/references/codex-guided-install.md."
echo "2. Optional guardrail: merge $DEST_SKILL/references/config-snippet.toml only if you want a global Luna default."
echo "3. Restart Codex only if the new Skill or profiles do not appear automatically."
