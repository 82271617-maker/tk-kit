#!/usr/bin/env python3
"""judge_list —— 给一批视频链接做判定（可无基线）
用法: judge_list.py urls.txt [--owner 赖程] [--open N]
自己算这批视频的中位数作相对线；单条失败不中断。
"""
import argparse, statistics as st, subprocess, sys, time
from pathlib import Path
import pick

def fetch(url, retries=3):
    for i in range(retries):
        try:
            m = pick.ytdlp_json(url)
            if m: return m
        except SystemExit:
            pass
        time.sleep(1.5 + i)
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls")
    ap.add_argument("--open", type=int, default=0)
    ap.add_argument("--max-age", type=int, default=pick.THRESHOLDS["max_age_days"])
    a = ap.parse_args()
    urls = [u.strip() for u in Path(a.urls).read_text().splitlines() if u.strip()]
    metas, fails = [], []
    for i, u in enumerate(urls, 1):
        m = fetch(u)
        if m: metas.append(m); print(f"  {i}/{len(urls)} ok {m.get('view_count',0):>9,} {u.split('/')[-1]}", flush=True)
        else: fails.append(u); print(f"  {i}/{len(urls)} FAIL {u.split('/')[-1]}", flush=True)
    if not metas:
        print("全部取不到元数据"); return
    views = [m.get("view_count", 0) for m in metas]
    med = st.median(views)
    print(f"\n样本 {len(metas)} 条 · 中位数 {med:,.0f} · 取不到 {len(fails)} 条\n")
    print("| 结论 | 播放 | 倍数 | 天 | 点赞率 | 时长 | 链接 |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    passed = []
    for m in sorted(metas, key=lambda x: -x.get("view_count", 0)):
        v = m.get("view_count", 0)
        like = (m.get("like_count") or 0) / v * 100 if v else 0
        # 复用 pick 的门槛
        T = pick.THRESHOLDS
        ok_abs = v >= T["abs_views_floor"]
        ok_rel = med < 50000 or v >= med * T["rel_multiple"]
        ok_age = True
        d = m.get("timestamp")
        if d:
            import datetime as dt
            age = (dt.date.today() - dt.date.fromtimestamp(d)).days
            ok_age = age <= a.max_age
        else:
            age = -1
        dur = (m.get("duration") or 0)
        ok_dur = T["dur_min"] <= dur <= T["dur_max"]
        ok_like = like >= T["like_rate_min"]
        ok = ok_abs and ok_rel and ok_age and ok_dur and ok_like
        if ok: passed.append(m.get("webpage_url") or m.get("original_url"))
        multip = f"{v/med:.1f}×" if med else "-"
        print(f"| {'✅' if ok else '❌'} | {v:,} | {multip} | {age} | {like:.2f}% | {dur:.0f}s | {m.get('webpage_url','')} |")
    print(f"\n通过 {len(passed)} 条 / 样本 {len(metas)} 条")
    if passed and a.open:
        import subprocess
        for u in passed[:a.open]:
            subprocess.run(["osascript", "-e",
                f'tell application "Safari" to make new tab at end of tabs of window 1 with properties {{URL:"{u}"}}'],
                capture_output=True)
        print(f"已在 Safari 打开 {min(len(passed), a.open)} 条")

if __name__ == "__main__":
    main()
