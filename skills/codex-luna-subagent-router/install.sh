#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./install.sh --global
  ./install.sh --project /path/to/repository

The script installs or upgrades the complete Skill package and overwrites every
cost-aware custom-agent profile bundled by this release.

When upgrading from any older version, rerun this installer from the new
release. Do not copy only SKILL.md, selected references/scripts, or individual
profiles; the whole installed Skill package and all bundled profiles must stay
on the same release.

The script does not edit user-managed config.toml, AGENTS.md, or routing.json.
Use references/codex-guided-install.md after installation/upgrade for managed
configuration and migration.
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

# Refresh every profile bundled by this release. User-created profiles with
# other names are outside this installer's management scope.
cp "$SOURCE_DIR"/assets/codex-agents/*.toml "$AGENTS_BASE"/
chmod +x \
  "$DEST_SKILL/install.sh" \
  "$DEST_SKILL/scripts/configure_guided_install.py" \
  "$DEST_SKILL/scripts/validate_route_plan.py"

python3 "$DEST_SKILL/scripts/validate_route_plan.py" \
  "$DEST_SKILL/examples/route-plan.valid.json" >/dev/null

INSTALLED_VERSION="$(tr -d '[:space:]' < "$DEST_SKILL/VERSION")"

echo "Installed/updated Skill: $DEST_SKILL"
echo "Installed version: $INSTALLED_VERSION"
echo "Refreshed cost-aware profiles:"
echo "  Luna:  luna-{low,medium,high,xhigh,max}.toml"
echo "  Terra: terra-{medium,high}.toml"
echo "  Sol:   sol-{high,xhigh}.toml"
echo "  Astra: astra-{high,xhigh,max}.toml"
echo
echo "Upgrade rule:"
echo "  Keep the entire Skill directory and every bundled profile on this same release."
echo "  Do not retain an older SKILL.md/reference/script/profile beside newer package files."
echo "  User-managed config.toml, unrelated AGENTS.md content, and routing choices are migrated separately."
echo
echo "Next steps:"
echo "1. Ask Codex to follow $DEST_SKILL/references/codex-guided-install.md."
echo "2. Choose standing delegation authorization: global / project / none."
echo "3. Choose routing mode:"
echo "   - luna_only: maximum economy and cost predictability; automatic Workers use Luna only, hard tasks stay with the Lead."
echo "   - adaptive: choose the cheapest sufficient Luna/Terra/Sol/Astra combination; can down-route or locally escalate."
echo "4. Existing v1 routing tables are backed up during guided migration."
