#!/usr/bin/env bash
# شاخه‌ی bot-state فقط برای ذخیره‌ی وضعیت روزانه است (جلوگیری از ارسال تکراری اگر ربات وسط بازه دوباره اجرا شود).
set -u
git config user.name  "ny1m-bot"
git config user.email "ny1m-bot@users.noreply.github.com"
rm -rf state
if git ls-remote --exit-code --heads origin bot-state >/dev/null 2>&1; then
  git fetch --depth=1 origin bot-state:refs/remotes/origin/bot-state
  git worktree add -B bot-state state origin/bot-state
else
  git worktree add --orphan -b bot-state state 2>/dev/null || {
    git worktree add -B bot-state state HEAD
    git -C state rm -rq . 2>/dev/null
  }
  echo "{}" > state/state.json
  git -C state add -A
  git -C state commit -qm "init state" && git -C state push origin bot-state || echo "push اولیه ناموفق (ادامه می‌دهیم)"
fi
ls -la state
