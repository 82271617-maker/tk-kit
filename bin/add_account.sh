#!/bin/bash
# 加对标账号：本地 CSV + 飞书表 + GitHub 三处同步
# 用法: add_account.sh <handle> <类型> <责任人> [备注]
set -e
H="${1#@}"; TYPE="${2:-英文民生}"; OWNER="${3:-赖程}"; NOTE="${4:-}"
[ -z "$H" ] && { echo "用法: add_account.sh <handle> [类型] [责任人] [备注]"; exit 1; }
CSV="$HOME/Desktop/TK库/00-GitHub音乐库/对标账号.csv"
SHEET=Drw9sHqgah1i1OtTw7Qc5PvMn7v; SID=dfd0e3
grep -q ",$H," "$CSV" && { echo "已存在: $H"; exit 0; }
echo "$H,$H,https://www.tiktok.com/@$H,$TYPE,$OWNER,$NOTE" >> "$CSV"
echo "✔ 本地已加：$H"
if command -v lark-cli >/dev/null 2>&1; then
  ROWS=$(($(lark-cli sheets +csv-get --spreadsheet-token $SHEET --sheet-id $SID --range "A1:F200" --as user 2>/dev/null | wc -l)))
  lark-cli sheets +csv-put --spreadsheet-token $SHEET --sheet-id $SID --start-cell "A${ROWS}" --as user \
    --csv "$H,$H,https://www.tiktok.com/@$H,$TYPE,$OWNER,$NOTE" >/dev/null 2>&1 && echo "✔ 飞书表已加" || echo "⚠ 飞书表失败（可手动补）"
fi
cd "$HOME/Desktop/TK库/00-GitHub音乐库" && git add -A >/dev/null 2>&1 && \
  git -c user.name="laicheng" -c user.email="82271617-maker@users.noreply.github.com" \
      commit -q -m "add account: $H" 2>/dev/null && \
  git -c http.proxy=http://127.0.0.1:7890 push origin main >/dev/null 2>&1 && echo "✔ 已推 GitHub" || echo "（GitHub 无变化或推送失败）"
echo "完成：$H · $TYPE · $OWNER"
