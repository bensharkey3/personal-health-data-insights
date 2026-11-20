#!/usr/bin/env bash
# Claude Code PreToolUse hook (Bash and PowerShell tools): stop commits and pushes that would land on main.
# Exit code 2 blocks the tool call and shows stderr to Claude, which then creates a branch.
# Deliberately plain bash + grep (no jq/python) so it works on macOS, Linux and cloud sessions.

input=$(cat)

# Only care about git commit / git push (optionally "git -C <dir> ...").
is_commit=$(grep -Eq '(^|[^[:alnum:]_-])git +(-C +[^ ]+ +)?commit([^[:alnum:]_-]|$)' <<<"$input" && echo 1)
is_push=$(grep -Eq '(^|[^[:alnum:]_-])git +(-C +[^ ]+ +)?push([^[:alnum:]_-]|$)' <<<"$input" && echo 1)
[[ -z $is_commit && -z $is_push ]] && exit 0

# Same command creates a new branch first (e.g. "git switch -c x && git commit") -> fine.
if grep -Eq 'git +(switch +-c|checkout +-b) ' <<<"$input"; then
  branch_created=1
fi

branch=$(git -C "${CLAUDE_PROJECT_DIR:-.}" rev-parse --abbrev-ref HEAD 2>/dev/null)

block() {
  echo "Blocked: $1 Direct commits/pushes to main are not allowed in this repo." >&2
  echo "Create a feature branch first (git switch -c <short-descriptive-name>), commit there, push it, and open a PR." >&2
  exit 2
}

if [[ $branch == "main" && -z $branch_created ]]; then
  [[ -n $is_commit ]] && block "you are on main and tried to commit."
  [[ -n $is_push ]] && block "you are on main and tried to push."
fi

# Explicit pushes to main from any branch, e.g. "git push origin main" or "HEAD:main".
if [[ -n $is_push ]] && grep -Eq 'git +(-C +[^ ]+ +)?push[^"]*[ :]main([ "]|$)' <<<"$input"; then
  block "the push targets main."
fi

exit 0
