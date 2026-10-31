#!/usr/bin/env python3
"""fetch — 素材下载：链接清单 → 规范素材库（mp4 + 元数据 + manifest + 质检帧）。

用法：
  python fetch.py links.txt                    # 下载到 materials/
  python fetch.py links.txt --out materials --force
  python fetch.py links.txt --frames 3         # 每条约 3 帧用于看字幕位置

产物：
  materials/<id>.mp4          素材（文件名用视频 id，跨平台安全）
  materials/meta/<id>.json    元数据（账号/标题/播放/时长/分辨率/链接/下载时间）
  materials/manifest.csv      汇总表，可直接给剪辑或导入表格
  materials/qc/<id>-<n>.png   质检帧（可选）

幂等：已存在则跳过；--force 覆盖。
"""
import argparse
import csv
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pick  # noqa: E402  复用 yt-dlp 抓元数据
import tk  # noqa: E402   复用 ffmpeg 路径与抽帧

HERE = Path(__file__).resolve().parent
OUT = HERE / "materials"
YTDLP = HERE / ".venv/bin/yt-dlp"
FF = tk.FF
PROXY = "http://127.0.0.1:7890"


def probe(path):
    r = subprocess.run([FF, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    info = {"width": 0, "height": 0, "fps": 0, "duration": 0.0, "audio": False}
    for line in r.stderr.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            info["duration"] = round(int(h) * 3600 + int(m) * 60 + float(s), 1)
        if "Video:" in line:
            m = re.search(r"\b(\d{2,4})x(\d{2,4})\b", line)
            if m:
                info["width"], info["height"] = int(m.group(1)), int(m.group(2))
            m = re.search(r"([\d.]+)\s*fps", line)
            if m:
                info["fps"] = float(m.group(1))
        if "Audio:" in line:
            info["audio"] = True
    return info


def target_ok(tok):
    try:
        w, h = tok.split("x")
        return 100 <= int(w) <= 8000 and 100 <= int(h) <= 8000
    except Exception:
        return False


def download(url, outdir, force=False):
    meta = pick.ytdlp_json(url)
    vid = meta["id"]
    target = outdir / f"{vid}.mp4"
    if target.exists() and not force:
        print(f"  skip {vid} (已存在)")
        return vid, meta, target, True
    print(f"  download {vid} ...", flush=True)
    for attempt in range(1, 3):
        r = subprocess.run([str(YTDLP), "--proxy", PROXY, "--no-playlist",
                            "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
                            "--merge-output-format", "mp4",
                            "-o", str(outdir / "%(id)s.%(ext)s"), url],
                           capture_output=True, text=True)
        if r.returncode == 0 and target.exists():
            return vid, meta, target, False
        print(f"  retry {attempt}/2: {r.stderr.strip().splitlines()[-1][:120]}")
    return vid, meta, None, False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("links")
    p.add_argument("--out", default=str(OUT))
    p.add_argument("--force", action="store_true")
    p.add_argument("--frames", type=int, default=0, help="每条的质检帧数（0=不抽）")
    a = p.parse_args()

    outdir = Path(a.out)
    (outdir / "meta").mkdir(parents=True, exist_ok=True)
    if a.frames:
        (outdir / "qc").mkdir(exist_ok=True)

    urls = []
    for line in Path(a.links).read_text().splitlines():
        line = line.strip()
        if line.startswith("http"):
            urls.append(line)
    print(f"共 {len(urls)} 条链接")

    rows, ok, skipped, failed = [], 0, 0, 0
    for url in urls:
        try:
            vid, meta, path, existed = download(url, outdir, a.force)
        except SystemExit as e:
            print(f"  FAIL {url}: {e}")
            failed += 1
            continue
        if path is None:
            failed += 1
            continue
        skipped += existed
        ok += (not existed)

        info = probe(path)
        rec = {
            "id": vid,
            "account": meta.get("uploader"),
            "title": (meta.get("title") or "").strip(),
            "views": meta.get("view_count") or 0,
            "likes": meta.get("like_count") or 0,
            "duration_s": info["duration"] or meta.get("duration"),
            "width": info["width"], "height": info["height"], "fps": info["fps"],
            "audio": info["audio"],
            "upload_date": meta.get("upload_date"),
            "url": url,
            "file": str(path),
            "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
        (outdir / "meta" / f"{vid}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2))
        rows.append(rec)

        if a.frames:
            dur = rec["duration_s"] or 10
            for i in range(a.frames):
                at = dur * (i + 1) / (a.frames + 1)
                tk.frame(str(path), at, outdir / "qc" / f"{vid}-{i + 1}.png")
        print(f"    {rec['width']}x{rec['height']} {rec['duration_s']}s "
              f"{'有音轨' if rec['audio'] else '⚠️ 无音轨'}")

    if rows:
        manifest = outdir / "manifest.csv"
        with manifest.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\nmanifest: {manifest}")

    print(f"\n完成：新下载 {ok} · 跳过 {skipped} · 失败 {failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
