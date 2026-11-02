#!/bin/bash
# 抓一个号：手机UA取 secUid → tiktokuser 列表 → judge_list 判定
# 用法: crawl_account.sh <handle> [条数]
set -u
H="${1#@}"; N="${2:-20}"
UA="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
SID=$(curl -s -m 25 -x http://127.0.0.1:7890 -A "$UA" "https://www.tiktok.com/@$H" | grep -oE '"secUid":"[^"]+"' | head -1 | sed 's/.*:"//;s/"//')
if [ -z "$SID" ]; then echo "[$H] ✗ 取不到 secUid（主页被拦）"; exit 1; fi
echo "[$H] secUid=$SID"
.venv/bin/yt-dlp --proxy http://127.0.0.1:7890 --flat-playlist --playlist-end "$N" --print "%(id)s" "tiktokuser:$SID" 2>/dev/null \
  | sed "s|.*|https://www.tiktok.com/@$H/video/&|" > "/tmp/urls-$H.txt"
C=$(wc -l < "/tmp/urls-$H.txt" | tr -d ' ')
echo "[$H] 列表 $C 条"
[ "$C" = "0" ] && { echo "[$H] ✗ 列表为空"; exit 1; }
.venv/bin/python judge_list.py "/tmp/urls-$H.txt" --open 2 2>&1 | grep -E "中位数|^\| ✅|^通过|已打开"
