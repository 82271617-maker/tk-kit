#!/usr/bin/env python3
"""clean — 去水印/去烧录文字：只遮文字所在的像素行，保留其余原始画面。

思路：
  1. 抽 12 帧，缩到 180x320 做时序分析
  2. 用「时序方差」把画面区（会动）和模板区（不动）分开
  3. 模板区里再找「文字行」：白像素占比高，或纯白底
  4. 合并成若干行段，按像素映射回原分辨率
  5. 只对这些行段做遮蔽（填充或模糊），其余画面原样保留

用法：
  python clean.py in.mp4                     # 自动检测 + 填充深色
  python clean.py in.mp4 --mode blur         # 自动检测 + 模糊
  python clean.py in.mp4 --rows 88:280,1008:28   # 手工指定（y:height）
  python clean.py in.mp4 --dry-run           # 只看检测结果，不渲染
"""
import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tk  # noqa: E402

FF = tk.FF
PROBE_W, PROBE_H = 180, 320
FILL = "0x101820"


def probe_size(path):
    r = subprocess.run([FF, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "Video:" in line:
            import re
            m = re.search(r"\b(\d{2,4})x(\d{2,4})\b", line)
            if m:
                return int(m.group(1)), int(m.group(2))
    raise SystemExit("无法识别视频尺寸")


def sample_frames(path, n=12):
    dur = 0
    r = subprocess.run([FF, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            dur = int(h) * 3600 + int(m) * 60 + float(s)
    frames = []
    for i in range(1, n + 1):
        t = dur * i / (n + 1)
        raw = subprocess.run(
            [FF, "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
             "-vf", f"scale={PROBE_W}:{PROBE_H}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
            capture_output=True).stdout
        if len(raw) == PROBE_W * PROBE_H * 3:
            frames.append(raw)
    return frames


def row_features(frames):
    """返回每行 (亮度均值, 白像素占比, 时序标准差)"""
    feats = []
    for y in range(PROBE_H):
        lums, whites = [], []
        for raw in frames:
            px = raw[y * PROBE_W * 3:(y + 1) * PROBE_W * 3]
            vals = [0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2]
                    for i in range(0, len(px), 3)]
            lums.append(sum(vals) / len(vals))
            whites.append(sum(1 for v in vals if v > 190) / len(vals))
        feats.append((sum(lums) / len(lums), sum(whites) / len(whites),
                      statistics.pstdev(lums)))
    return feats


def picture_band(feats, dyn_threshold=3.0):
    """最大的连续动态区 = 画面区"""
    runs, start = [], None
    for y, (_, _, std) in enumerate(feats):
        if std > dyn_threshold and start is None:
            start = y
        elif std <= dyn_threshold and start is not None:
            runs.append((start, y - 1))
            start = None
    if start is not None:
        runs.append((start, len(feats) - 1))
    if not runs:
        return (0, len(feats) - 1)
    return max(runs, key=lambda r: r[1] - r[0])


def text_rows(feats, pic):
    """画面区之外、像文字的行"""
    out = []
    for y, (lum, white, std) in enumerate(feats):
        inside = pic[0] - 1 <= y <= pic[1] + 1
        if inside:
            continue
        if white > 0.08 or (std < 1.2 and lum > 150) or (std < 2.5 and white > 0.05):
            out.append(y)
    return out


def to_bands(rows, total_h, min_run=1, gap=8, pad=8):
    """合并相邻行 → [(y, h)] 像素坐标"""
    if not rows:
        return []
    rows = sorted(rows)
    groups, cur = [], [rows[0]]
    for y in rows[1:]:
        if y - cur[-1] <= gap:
            cur.append(y)
        else:
            groups.append(cur)
            cur = [y]
    groups.append(cur)
    scale = total_h / PROBE_H
    bands = []
    for g in groups:
        if len(g) < min_run:
            continue
        y0 = max(0, int(g[0] * scale) - pad)
        y1 = min(total_h, int((g[-1] + 1) * scale) + pad)
        bands.append((y0, y1 - y0))
    return bands


def build_filter(bands, w, h, mode, fill):
    parts = []
    if mode == "blur":
        for i, (y, hh) in enumerate(bands):
            parts.append(f"crop={w}:{hh}:0:{y},boxblur=30:3[b{i}]")
        chain = ";".join(parts)
        last = "[0:v]"
        for i, (y, hh) in enumerate(bands):
            out = f"[v{i}]"
            chain += f";{last}[b{i}]overlay=0:{y}{out}"
            last = out
        return chain, last
    for y, hh in bands:
        parts.append(f"drawbox=x=0:y={y}:w={w}:h={hh}:color={fill}@1:t=fill")
    return ",".join(parts), None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("--out", default=None)
    p.add_argument("--mode", choices=["fill", "blur"], default="fill")
    p.add_argument("--fill", default=FILL)
    p.add_argument("--rows", default="", help="手工指定 y:height,y:height")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--preview", action="store_true", help="画一张带检测框的预览图")
    a = p.parse_args()

    src = Path(a.video)
    w, h = probe_size(src)

    if a.rows:
        bands = []
        for seg in a.rows.split(","):
            y, hh = seg.split(":")
            bands.append((int(y), int(hh)))
        pic = None
    else:
        frames = sample_frames(src)
        if len(frames) < 3:
            raise SystemExit("抽帧失败，改用 --rows 手工指定")
        feats = row_features(frames)
        pic = picture_band(feats)
        bands = to_bands(text_rows(feats, pic), h)

    report = {
        "video": str(src), "size": [w, h],
        "picture_band_px": [int(pic[0] * h / PROBE_H), int((pic[1] + 1) * h / PROBE_H)] if pic else None,
        "masked_bands": [{"y": y, "h": hh, "pct": round(hh / h * 100, 1)} for y, hh in bands],
        "masked_total_pct": round(sum(hh for _, hh in bands) / h * 100, 1),
        "mode": a.mode,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if a.preview and bands:
        prev = Path(str(src.with_suffix("")) + "-preview.png")
        marks = ",".join(f"drawbox=x=0:y={y}:w={w}:h=2:color=red@1:t=fill,"
                         f"drawbox=x=0:y={y + hh - 2}:w={w}:h=2:color=red@1:t=fill"
                         for y, hh in bands)
        subprocess.run([FF, "-v", "error", "-ss", "3", "-i", str(src), "-frames:v", "1",
                        "-vf", marks, "-y", str(prev)], check=True)
        print(f"preview {prev}")

    if a.dry_run or not bands:
        return

    out = Path(a.out) if a.out else src.with_name(f"{src.stem}-clean.mp4")
    chain, last = build_filter(bands, w, h, a.mode, a.fill)
    cmd = [FF, "-v", "error", "-i", str(src)]
    if a.mode == "blur":
        cmd += ["-filter_complex", chain, "-map", last, "-map", "0:a"]
    else:
        cmd += ["-vf", chain]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy", "-y", str(out)]
    subprocess.run(cmd, check=True)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
