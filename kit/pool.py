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
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pick  # noqa: E402  复用阈值与判定逻辑

KANA = re.compile(r"[\u3041-\u309f\u30a1-\u30fa]")   # 平假名/片假名 → 视为日语源

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


def open_urls(urls):
    """macOS：用 Safari 新建标签页打开。open(1) 对已存在域名会复用，不建 tab，实测无效。"""
    urls = [u for u in urls if u]
    if not urls:
        return 0
    import subprocess, tempfile
    f = Path(tempfile.mkdtemp()) / "urls.txt"
    f.write_text("\n".join(urls), encoding="utf-8")
    script = f'''tell application "Safari"
activate
set u to paragraphs of (read (POSIX file "{f}") as «class utf8»)
repeat with x in u
  if x is not "" then make new tab at end of tabs of window 1 with properties {{URL:(x as text)}}
end repeat
end tell'''
    subprocess.run(["osascript", "-e", script], check=False)
    return len(urls)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--accounts", required=True)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--owner", default="default", help="剪辑师名，历史按人隔离（一人一份账号表+一份历史）")
    p.add_argument("--open", action="store_true", help="跑完自动在浏览器打开通过的视频")
    p.add_argument("--open-max", type=int, default=5, help="最多自动打开几条")
    p.add_argument("--include-ja", action="store_true",
                   help="默认排除日语源（已是日语，不能当二创素材）；加这个才包含")
    p.add_argument("--mark-done", default="", help="把逗号分隔的视频 id 直接记进历史（补录已做过的片）")
    p.add_argument("--backfill", default="", help="从某个素材目录反推已做过的片，补进历史")
    a = p.parse_args()

    handles = [h for h in (handle_of(x) for x in Path(a.accounts).read_text().splitlines()) if h]
    rows, failed, bases = [], [], {}

    hist_dir = OUT / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    hist_path = hist_dir / f"{a.owner}.json"
    history = json.loads(hist_path.read_text()) if hist_path.exists() else {}
    skipped_dup = 0
    meta_fail = 0

    # 补录：手工指定过的 id
    for vid in [x.strip() for x in a.mark_done.split(",") if x.strip()]:
        history.setdefault(vid, {"handle": "", "title": "(手工补录)", "url": "", "first_seen": "manual"})
    # 补录：从素材目录反推（01-素材/<id>.mp4 这类）
    if a.backfill:
        bf = Path(a.backfill).expanduser()
        for f in bf.glob("*.mp4"):
            history.setdefault(f.stem, {"handle": "", "title": "(目录补录)", "url": "", "first_seen": "backfill"})
    if a.mark_done or a.backfill:
        hist_path.write_text(json.dumps(history, ensure_ascii=False, indent=1))
        print(f"历史补录后共 {len(history)} 条")

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
            if vid in history:
                skipped_dup += 1
                continue
            url = f"https://www.tiktok.com/@{h}/video/{vid}"
            try:
                meta = pick.ytdlp_json(url)
            except SystemExit:
                meta_fail += 1
                continue
            hard, lr, cr, age, views_ = pick.judge(meta, bases[h], True)
            ja_src = bool(KANA.search(meta.get("title") or "") or KANA.search(meta.get("description") or ""))
            if ja_src and not a.include_ja:
                hard = hard + [("源语言=日语（仅参考）", False, "")]
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
             f"通过：{sum(r['passed'] for r in rows)} 条　"
             f"历史去重跳过：{skipped_dup} 条　元数据取不到：{meta_fail} 条（owner: {a.owner}）", ""]
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

    # 记录本 owner 已推荐过的片，避免明天/后天重复推
    now_iso = now.isoformat(timespec="seconds")
    for r in rows:
        if r["passed"]:
            vid = r["url"].rstrip("/").split("/")[-1]
            history[vid] = {"handle": r["handle"], "title": r["title"],
                            "url": r["url"], "first_seen": now_iso}
    hist_path.write_text(json.dumps(history, ensure_ascii=False, indent=1))
    print(f"history: {len(history)} 条已记录 → {hist_path}")

    # 自动打开（不用人再去复制链接）
    if a.open:
        picked = [r["url"] for r in rows if r["passed"]][: a.open_max]
        n = open_urls(picked)
        for i, u in enumerate(picked, 1):
            print(f"  open[{i}] {u}")
        print(f"opened: {n} 条（Safari 新标签页）")


if __name__ == "__main__":
    main()
