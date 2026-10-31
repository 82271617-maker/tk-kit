#!/usr/bin/env python3
"""tk — TK 剪辑流水线的逐节点命令。一次只跑一个节点，产物落在 out/。

用法：
  python tk.py fetch <tiktok-url>           # 节点4：下载（无平台水印）
  python tk.py probe <file>                 # 体检：时长/分辨率/帧率/音轨
  python tk.py frame <file> --at 2          # 抽一帧看画面/字幕位置
  python tk.py crop-bottom <file> --pct 12  # 节点5：裁掉底部烧录字幕
  python tk.py blur-bottom <file> --pct 12  # 节点5：模糊底部（保留画面）
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
YTDLP = HERE / ".venv/bin/yt-dlp"
FF = imageio_ffmpeg.get_ffmpeg_exe()
PROXY = os.environ.get("TK_PROXY", "http://127.0.0.1:7890")


def run(cmd):
    print("$", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def fetch(url, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    run([YTDLP, "--proxy", PROXY, "--no-playlist",
         "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
         "--merge-output-format", "mp4",
         "-o", f"{outdir}/%(id)s.%(ext)s", url])


def probe(path):
    r = subprocess.run([FF, "-hide_banner", "-i", str(path)],
                       capture_output=True, text=True)
    info = [l.strip() for l in r.stderr.splitlines()
            if any(k in l for k in ("Duration", "Stream #"))]
    print(f"file: {path}")
    for l in info:
        print(" ", l)


def frame(path, at, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    run([FF, "-v", "error", "-ss", str(at), "-i", path, "-frames:v", "1",
         "-vf", "scale=540:-1", "-y", out])
    print("wrote", out)


def crop_bottom(path, pct, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    run([FF, "-v", "error", "-i", path,
         "-vf", f"crop=iw:ih*{1 - pct / 100:.4f}:0:0",
         "-c:a", "copy", "-y", out])
    print("wrote", out)


def blur_bottom(path, pct, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    h = pct / 100
    vf = (f"split[a][b];[b]crop=iw:ih*{h:.4f}:0:ih*{1 - h:.4f},"
          f"boxblur=20:3[c];[a][c]overlay=0:H*{1 - h:.4f}")
    run([FF, "-v", "error", "-i", path, "-filter_complex", vf,
         "-c:a", "copy", "-y", out])
    print("wrote", out)


def main():
    p = argparse.ArgumentParser(prog="tk")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch")
    f.add_argument("url")
    f.add_argument("--out", default=str(OUT))

    pr = sub.add_parser("probe")
    pr.add_argument("file")

    fr = sub.add_parser("frame")
    fr.add_argument("file")
    fr.add_argument("--at", type=float, default=1.0)
    fr.add_argument("--out", default=str(OUT / "frame.png"))

    cb = sub.add_parser("crop-bottom")
    cb.add_argument("file")
    cb.add_argument("--pct", type=float, default=12)
    cb.add_argument("--out", default=str(OUT / "cropped.mp4"))

    bb = sub.add_parser("blur-bottom")
    bb.add_argument("file")
    bb.add_argument("--pct", type=float, default=12)
    bb.add_argument("--out", default=str(OUT / "blurred.mp4"))

    a = p.parse_args()
    if a.cmd == "fetch":
        fetch(a.url, Path(a.out))
    elif a.cmd == "probe":
        probe(a.file)
    elif a.cmd == "frame":
        frame(a.file, a.at, Path(a.out))
    elif a.cmd == "crop-bottom":
        crop_bottom(a.file, a.pct, Path(a.out))
    elif a.cmd == "blur-bottom":
        blur_bottom(a.file, a.pct, Path(a.out))


if __name__ == "__main__":
    main()
