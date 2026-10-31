#!/usr/bin/env python3
"""pick — 选题入选判定（新闻/故事类）。标准见 ../选题标准.md，改阈值只改 THRESHOLDS。

用法：
  python pick.py <video-url> [<video-url> ...]
  python pick.py <video-url> --account https://www.tiktok.com/@xxx   # 显式指定账号基线
  python pick.py <video-url> --no-baseline                            # 跳过相对线（离线时）

输出：终端表格 + out/pick-<时间>.md
"""
import argparse
import datetime as dt
import json
import statistics as st
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
YTDLP = HERE / ".venv/bin/yt-dlp"
PROXY = "http://127.0.0.1:7890"

# ── 阈值：改这里就是改标准 ────────────────────────────────────────────────
THRESHOLDS = {
    "abs_views_floor": 100_000,     # 绝对底线：10 万播放
    "rel_multiple": 5,              # 相对线：≥ 账号近 30 天播放中位数 × 5
    "max_age_days": 30,             # 时效：发布 ≤ 30 天
    "dur_min": 45, "dur_max": 90,   # 时长：45–90 秒（二创改写空间）
    "like_rate_min": 1.0,           # 点赞率 ≥ 1.0%
    "cmt_rate_min": 0.03,           # 评论率 ≥ 0.03%
    "score_pass": 15,               # 软分 ≥ 15/25 入选
}


def ytdlp_json(url):
    r = subprocess.run([str(YTDLP), "--proxy", PROXY, "--no-playlist",
                        "--skip-download", "--dump-json", url],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"yt-dlp failed: {r.stderr.strip()[-300:]}")
    return json.loads(r.stdout)


def baseline(account_url, cache=OUT / "baseline.json"):
    """优先现场抓主页；抓不到（TikTok 反爬经常失败）就用 out/baseline/<@handle>.json 快照。"""
    key = account_url.rstrip("/").split("/")[-1]
    snap = OUT / "baseline" / f"{key}.json"
    if snap.exists():
        entry = json.loads(snap.read_text())
        entry["stale"] = (dt.date.today() - dt.date.fromisoformat(entry["date"])).days
        return entry
    if cache.exists():
        data = json.loads(cache.read_text())
        if key in data and data[key]["median"] and \
           (dt.date.today() - dt.date.fromisoformat(data[key]["date"])).days < 7:
            return data[key]
    r = subprocess.run([str(YTDLP), "--proxy", PROXY, "--flat-playlist",
                        "--playlist-end", "30",
                        "--print", "%(view_count)s", account_url],
                       capture_output=True, text=True)
    views = [int(x) for x in r.stdout.split() if x.isdigit()]
    entry = {"median": int(st.median(views)) if views else 0,
             "n": len(views), "date": dt.date.today().isoformat(),
             "source": "live profile scrape"}
    data = json.loads(cache.read_text()) if cache.exists() else {}
    data[key] = entry
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return entry


def judge(meta, base, use_baseline=True):
    views = meta.get("view_count") or 0
    likes = meta.get("like_count") or 0
    cmts = meta.get("comment_count") or 0
    dur = meta.get("duration") or 0
    age = (dt.date.today() - dt.date.fromtimestamp(meta["timestamp"])).days if meta.get("timestamp") else 999
    like_rate = likes / views * 100 if views else 0
    cmt_rate = cmts / views * 100 if views else 0
    T = THRESHOLDS

    hard = []
    hard.append(("绝对播放 ≥ 10万", views >= T["abs_views_floor"], f"{views:,}"))
    if use_baseline and base.get("median"):
        need = base["median"] * T["rel_multiple"]
        hard.append((f"相对 ≥ 账号中位数×{T['rel_multiple']}",
                     views >= need, f"{views:,} / 需 {need:,.0f}（中位 {base['median']:,}）"))
    hard.append(("发布 ≤ 30 天", age <= T["max_age_days"], f"{age} 天"))
    hard.append(("时长 45–90 秒", T["dur_min"] <= dur <= T["dur_max"], f"{dur} 秒"))
    hard.append(("点赞率 ≥ 1.0%", like_rate >= T["like_rate_min"], f"{like_rate:.2f}%"))
    hard.append(("评论率 ≥ 0.03%", cmt_rate >= T["cmt_rate_min"], f"{cmt_rate:.3f}%"))
    return hard, like_rate, cmt_rate, age, views


def main():
    p = argparse.ArgumentParser()
    p.add_argument("urls", nargs="+")
    p.add_argument("--account")
    p.add_argument("--no-baseline", action="store_true")
    a = p.parse_args()

    rows = []
    for url in a.urls:
        meta = ytdlp_json(url)
        acct = a.account or f"https://www.tiktok.com/@{meta.get('uploader')}"
        base = {} if a.no_baseline else baseline(acct)
        hard, lr, cr, age, views = judge(meta, base, not a.no_baseline)
        passed = all(ok for _, ok, _ in hard)
        rows.append((meta, hard, passed))

    lines = ["# 选题判定", "", f"生成：{dt.datetime.now():%Y-%m-%d %H:%M}", ""]
    for meta, hard, passed in rows:
        title = (meta.get("title") or "")[:40]
        lines += [f"## {'✅ 入选' if passed else '❌ 不入选'} · {meta.get('uploader')}", "",
                  f"[{title}]({meta.get('webpage_url')})", "",
                  "| 检查项 | 结果 | 实际值 |", "| --- | --- | --- |"]
        for name, ok, val in hard:
            lines.append(f"| {name} | {'✅' if ok else '❌'} | {val} |")
        lines.append("")
        print(("\n" + "=" * 60))
        print(f"{'✅ 入选' if passed else '❌ 不入选'}  @{meta.get('uploader')}  {title}")
        for name, ok, val in hard:
            print(f"  {'✅' if ok else '❌'} {name:24s} {val}")
    OUT.mkdir(exist_ok=True)
    out = OUT / f"pick-{dt.datetime.now():%Y%m%d-%H%M}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\nwrote", out)


if __name__ == "__main__":
    main()
