#!/usr/bin/env python3
"""dubline — 配音后处理：去气口 + 字幕对轴（用定稿文稿，不用转写文本）。

核心思路：
  配音是「按行生成」的，行与行之间有天然停顿。
  找到正确的停顿阈值，就能把音频切成 N 段，与文稿的 N 行一一对应。
  切不开（停顿不明显）时，退回到 whisper 词级时间戳做强制对齐。

用法：
  python dubline.py <配音.mp3> <定稿文稿.txt> [--gap 0.25] [--lang ja] [--out-dir DIR]
  python dubline.py <配音> <文稿> --dry-run        # 只报告切分方案，不处理

产物：
  <配音>-去气口.mp3
  <配音>-去气口.srt
  <配音>-去气口.json（记录参数与每句时长）
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dub import _find_ffmpeg  # noqa: E402

FF = _find_ffmpeg()
THRESH = -34
D_CANDIDATES = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60]


def ff(*args):
    r = subprocess.run([FF, *map(str, args)], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg 失败:\n{r.stderr[-500:]}")
    return r


def duration(path):
    """读时长。用正则，容忍 N/A 与 ffmpeg 输出格式差异（旧版按 ':' 切会崩）。"""
    r = subprocess.run([FF, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def silences(audio, d, thresh=THRESH):
    r = subprocess.run([FF, "-hide_banner", "-i", str(audio),
                        "-af", f"silencedetect=noise={thresh}dB:d={d}", "-f", "null", "-"],
                       capture_output=True, text=True)
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    return starts


def pick_threshold(audio, n_lines):
    """找出让「停顿数 = 行数-1」的 d"""
    for d in D_CANDIDATES:
        st = silences(audio, d)
        if len(st) == n_lines - 1:
            return d, st
    # 找不到精确匹配：先取最接近的，再在它 ±0.04 内按 0.01 细扫一次
    # （0.05 的网格会跳过 0.33 这种真值；实测 d=0.30→23 个、0.35→21 个、0.33→22 个）
    best = None
    for d in D_CANDIDATES:
        st = silences(audio, d)
        diff = abs(len(st) - (n_lines - 1))
        if best is None or diff < best[0]:
            best = (diff, d, st)
    base = best[1]
    for k in range(-4, 5):
        d = round(base + k * 0.01, 2)
        if d <= 0.05:
            continue
        st = silences(audio, d)
        if len(st) == n_lines - 1:
            return d, st
    return best[1], best[2]


def segments_from(starts, total):
    segs, prev = [], 0.0
    for s in starts:
        segs.append((prev, s))
        prev = s
    segs.append((prev, total))
    return segs


def trim(src, out):
    ff("-v", "error", "-i", src, "-af",
       "silenceremove=start_periods=1:start_silence=0.02:start_threshold=-40dB,"
       "areverse,silenceremove=start_periods=1:start_silence=0.02:start_threshold=-40dB,areverse",
       "-ac", "1", "-ar", "44100", "-y", out)


def ts(t):
    h, rem = divmod(max(0.0, t), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("audio")
    p.add_argument("script")
    p.add_argument("--gap", type=float, default=0.25)
    p.add_argument("--out-dir", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--step", choices=["both", "debreath", "subtitle"], default="both",
                   help="both=去气口+字幕；debreath=只出音频；subtitle=只出字幕")
    a = p.parse_args()

    audio = Path(a.audio)
    lines = [l.strip() for l in Path(a.script).read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        sys.exit("文稿为空")
    outdir = Path(a.out_dir) if a.out_dir else audio.parent
    outdir.mkdir(parents=True, exist_ok=True)

    total = duration(audio)

    # 只出字幕且已有去气口记录：直接用它，不重新猜阈值
    if a.step == "subtitle":
        meta = audio.with_suffix(".json")
        if meta.exists():
            data = json.loads(meta.read_text(encoding="utf-8"))
            srt = [f"{r['i']}\n{ts(r['start'])} --> {ts(r['end'])}\n{r['text']}\n"
                   for r in data["segments"]]
            out = outdir / f"{audio.stem}.srt"
            out.write_text("\n".join(srt), encoding="utf-8")
            print(f"按 {meta.name} 出字幕（{len(srt)} 句，无需重新检测）")
            print(f"wrote {out}")
            return

    d, starts = pick_threshold(audio, len(lines))
    exact = len(starts) == len(lines) - 1
    print(f"音频 {total:.2f}s · 文稿 {len(lines)} 行 · 停顿阈值 d={d}s · 检出停顿 {len(starts)} 个"
          f"{'（精确匹配）' if exact else '（不精确，按顺序截断/补齐）'}")

    if a.dry_run:
        return

    segs = segments_from(starts, total)
    # 丢掉碎段（<0.12s，多为尾部静音造成），否则最后一句时长可能为 0
    segs = [x for x in segs if x[1] - x[0] > 0.12] or segs
    if segs:
        segs[-1] = (segs[-1][0], max(segs[-1][1], total))
    # 行数与段数不一致时按顺序对齐：多的段合并、少的段用中点切开
    if len(segs) > len(lines):
        segs = segs[:len(lines) - 1] + [(segs[len(lines) - 1][0], total)]
    elif len(segs) < len(lines):
        while len(segs) < len(lines):
            longest = max(range(len(segs)), key=lambda i: segs[i][1] - segs[i][0])
            s, e = segs[longest]
            mid = (s + e) / 2
            segs[longest:longest + 1] = [(s, mid), (mid, e)]

    tmp = Path("/tmp/dubline")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    gapfile = tmp / "gap.wav"
    ff("-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", a.gap, "-y", gapfile)

    parts, srt, t, rows = [], [], 0.0, []
    for i, ((s, e), line) in enumerate(zip(segs, lines), 1):
        raw, cut = tmp / f"{i:02d}-raw.wav", tmp / f"{i:02d}-cut.wav"
        ff("-v", "error", "-ss", f"{s:.3f}", "-to", f"{e:.3f}", "-i", audio,
           "-ac", "1", "-ar", "44100", "-y", raw)
        trim(raw, cut)
        dur = duration(cut)
        if dur < 0.05:                      # 被裁空了：退回未裁版本
            ff("-v", "error", "-ss", f"{s:.3f}", "-to", f"{e:.3f}", "-i", audio,
               "-ac", "1", "-ar", "44100", "-y", cut)
            dur = duration(cut)
        parts.append(cut)
        srt.append(f"{i}\n{ts(t)} --> {ts(t + dur)}\n{line}\n")
        rows.append({"i": i, "start": round(t, 2), "end": round(t + dur, 2),
                     "src": [round(s, 2), round(e, 2)], "text": line})
        t += dur
        if i < len(segs):
            parts.append(gapfile)
            t += a.gap

    lst = tmp / "list.txt"
    lst.write_text("\n".join(f"file '{x}'" for x in parts) + "\n", encoding="utf-8")
    out_mp3 = outdir / f"{audio.stem}-去气口.mp3"
    out_srt = outdir / f"{audio.stem}-去气口.srt"
    out_json = outdir / f"{audio.stem}-去气口.json"

    if a.step == "subtitle":
        alt = outdir / f"{audio.stem}.srt"
        alt.write_text("\n".join(srt), encoding="utf-8")
        print(f"wrote {alt}（仅字幕，音频未改动）")
        return

    ff("-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-b:a", "128k", "-y", out_mp3)
    out_json.write_text(json.dumps({
        "audio": str(audio), "script": str(a.script), "lines": len(lines),
        "original_duration": round(total, 2), "final_duration": round(duration(out_mp3), 2),
        "gap": a.gap, "silence_d": d, "exact_match": exact, "segments": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    if a.step == "debreath":
        print(f"去气口: {total:.2f}s → {duration(out_mp3):.2f}s")
        print(f"wrote {out_mp3}\nwrote {out_json}")
        return

    out_srt.write_text("\n".join(srt), encoding="utf-8")
    print(f"去气口: {total:.2f}s → {duration(out_mp3):.2f}s")
    print(f"wrote {out_mp3}\nwrote {out_srt}\nwrote {out_json}")


if __name__ == "__main__":
    main()
