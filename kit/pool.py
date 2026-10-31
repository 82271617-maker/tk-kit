#!/usr/bin/env python3
"""pool — 对一个或多个对标账号：取近期视频池 → 按选题标准判 → 输出候选清单。

用法：
  python pool.py --accounts accounts.txt            # 每行一个 @handle 或主页链接
  python pool.py --accounts accounts.txt --limit 20

账号列表抓取不稳（TikTok 反爬），脚本内置 3 次重试；仍失败会明确告诉你哪个号要手动补链接。
"""
import argparse
import datetime as dt
import json
import statistics as st
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pick  # noqa: E402  复用阈值与判定逻辑

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
YTDLP = HERE / ".venv/bin/yt-dlp"
PROXY = "http://127.0.0.1:7890"


def handle_of(s):
    s = s.strip().rstrip("/")
    if not s:
        return None
    if s.startswith("@"):
        return s[1:]
    if "tiktok.com/@" in s:
        return s.split("tiktok.com/@")[1].split("/")[0]
    return s.lstrip("@")


def _run_list(target, limit):
    r = subprocess.run(
        [str(YTDLP), "--proxy", PROXY, "--flat-playlist",
         "--playlist-end", str(limit), "--print", "%(id)s %(view_count)s", target],
        capture_output=True, text=True)
    items = []
    for line in r.stdout.splitlines():
        p = line.split()
        if len(p) == 2 and p[0].isdigit():
            items.append((p[0], int(p[1]) if p[1].isdigit() else 0))
    return items


def channel_id(handle, vid):
    """从任意一条视频反查 channel_id，之后用 tiktokuser:<id> 列主页最稳"""
    cache = OUT / "channels.json"
    data = json.loads(cache.read_text()) if cache.exists() else {}
    if handle in data:
        return data[handle]
    r = subprocess.run(
        [str(YTDLP), "--proxy", PROXY, "--no-playlist", "--skip-download",
         "--dump-json", f"https://www.tiktok.com/@{handle}/video/{vid}"],
        capture_output=True, text=True)
    if r.returncode != 0:
        return None
    d = json.loads(r.stdout)
    cid = d.get("channel_id") or d.get("uploader_id")
    if cid:
        data[handle] = cid
        cache.parent.mkdir(exist_ok=True)
        cache.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return cid


def list_videos(handle, limit, attempts=3):
    """先小批量探一条 → 拿 channel_id → 用 tiktokuser 批量拉。失败返回 []"""
    prof = f"https://www.tiktok.com/@{handle}?is_from_webapp=1&sender_device=pc"
    seed = []
    for i in range(attempts):
        seed = _run_list(prof, 3)
        if seed:
            break
        time.sleep(3 + i * 2)
    if not seed:
        return []
    cid = channel_id(handle, seed[0][0])
    if cid:
        full = _run_list(f"tiktokuser:{cid}", limit)
        if full:
            return full
    return seed


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--accounts", required=True)
    p.add_argument("--limit", type=int, default=20)
    a = p.parse_args()

    handles = [h for h in (handle_of(x) for x in Path(a.accounts).read_text().splitlines()) if h]
    rows, failed, bases = [], [], {}

    for h in handles:
        items = list_videos(h, a.limit)
        views = sorted(v for _, v in items if v)
        if not views:
            snap = OUT / "baseline" / f"@{h}.json"
            if snap.exists():
                bases[h] = json.loads(snap.read_text())
            failed.append(h)
            continue
        bases[h] = {"median": int(st.median(views)), "n": len(views), "source": "live"}
        print(f"@{h}: {len(items)} 条，中位数 {bases[h]['median']:,}", flush=True)

        for vid, _ in items:
            url = f"https://www.tiktok.com/@{h}/video/{vid}"
            try:
                meta = pick.ytdlp_json(url)
            except SystemExit:
                continue
            hard, lr, cr, age, views_ = pick.judge(meta, bases[h], True)
            rows.append(dict(handle=h, title=(meta.get("title") or "")[:60], url=url,
                             views=views_,
                             mult=views_ / bases[h]["median"] if bases[h]["median"] else 0,
                             age=age, lr=lr, dur=meta.get("duration") or 0,
                             passed=all(ok for _, ok, _ in hard),
                             fails=[n for n, ok, _ in hard if not ok]))

    rows.sort(key=lambda r: (r["passed"], r["mult"]), reverse=True)
    now = dt.datetime.now()
    lines = [f"# 候选清单 · {now:%Y-%m-%d %H:%M}", "",
             f"账号：{', '.join('@' + h for h in handles)}　池子：{len(rows)} 条　"
             f"通过：{sum(r['passed'] for r in rows)} 条", ""]
    for h, b in bases.items():
        lines.append(f"- @{h} 基线：中位数 {b['median']:,}（{b['n']} 条，{b.get('source','')}）")
    lines.append("")
    if failed:
        lines += [f"> ⚠️ 抓不到主页：{', '.join('@' + h for h in failed)}（需手动贴视频链接）", ""]
    lines += ["| 结论 | 账号 | 播放 | 倍数 | 天 | 点赞率 | 时长 | 标题 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        flag = "✅" if r["passed"] else "❌"
        why = "" if r["passed"] else " " + "/".join(x.split(" ")[0] for x in r["fails"][:2])
        lines.append(
            f"| {flag}{why} | @{r['handle']} | {r['views']:,} | {r['mult']:.1f}× | "
            f"{r['age']} | {r['lr']:.2f}% | {r['dur']}s | [{r['title']}]({r['url']}) |")
    OUT.mkdir(exist_ok=True)
    out = OUT / f"pool-{now:%Y%m%d-%H%M}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print("\nwrote", out)


if __name__ == "__main__":
    main()
