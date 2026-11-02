#!/usr/bin/env python3
"""dubline_sot —— 带 #SOT（原声保留）的文稿去气口 + 对轴
文稿里 `#SOT 2.72s | テキスト` 表示该行是原片同期声：
  - 不配音、不参与停顿匹配
  - 输出里留出该秒数的空隙，由剪辑贴上原声
用法: dubline_sot.py <audio> <script> [--gap 0.25] [--out-dir DIR]
"""
import argparse, json, re, shutil, subprocess
from pathlib import Path
import dubline as D

SOT = re.compile(r"^#SOT\s*([\d.]+)s\s*\|\s*(.*)$")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio"); ap.add_argument("script")
    ap.add_argument("--gap", type=float, default=0.25)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--sot-pad", action="store_true",
                    help="在同期声位置插入等长静音（默认不插：只出去掉同期声的旁白轨）")
    a = ap.parse_args()
    audio = Path(a.audio).resolve()
    outdir = Path(a.out_dir) if a.out_dir else audio.parent
    outdir.mkdir(parents=True, exist_ok=True)

    raw = [l for l in Path(a.script).read_text(encoding="utf-8").splitlines() if l.strip()]
    plan = []          # (is_sot, seconds_or_None, text)
    for l in raw:
        m = SOT.match(l)
        plan.append((True, float(m.group(1)), m.group(2)) if m else (False, None, l))
    narr = [i for i, (s, _, _) in enumerate(plan) if not s]
    total = D.duration(audio)
    # 自己扫一遍阈值：优先选「停顿数正好 = 旁白行数-1」，避免多检/漏检
    target = len(narr) - 1
    # 优先「比目标多 0~2 个」（多出来的用最短间隙合并），其次才是少
    best = None
    for th in (40, 45, 35, 50):
        for k in range(30, 150):
            dd = k / 100
            st = D.silences(audio, dd, thresh=f"-{th}")
            if not st:
                continue
            diff = len(st) - target
            score = diff if diff >= 0 else (-diff * 3)   # 少检更糟
            if best is None or score < best[0]:
                best = (score, dd, st, th)
            if diff == 0:
                break
        if best and best[0] == 0:
            break
    if best is None:
        raise SystemExit("未检测到停顿")
    _, d, starts, used_th = best
    print(f"阈值 {used_th}dB · d={d}s · 停顿 {len(starts)} 个（目标 {target}）")
    print(f"音频 {total:.2f}s · 总行 {len(plan)} · 旁白 {len(narr)} 行 · 停顿 {len(starts)} 个 · d={d}s")

    segs = D.segments_from(starts, total)
    segs = [x for x in segs if x[1] - x[0] > 0.12] or segs
    segs[-1] = (segs[-1][0], total)
    # 段比行多：合并「间隙最短」的相邻两段（多半是把句中呼吸当成断句）
    while len(segs) > len(narr):
        gaps = [(segs[i+1][0] - segs[i][1], i) for i in range(len(segs)-1)]
        _, i = min(gaps)
        segs[i:i+2] = [(segs[i][0], segs[i+1][1])]
    while len(segs) < len(narr):
        longest = max(range(len(segs)), key=lambda i: segs[i][1] - segs[i][0])
        s, e = segs[longest]; mid = (s + e) / 2
        segs[longest:longest+1] = [(s, mid), (mid, e)]
    segs = segs[:len(narr)]

    tmp = Path("/tmp/dubline_sot"); shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir()
    gapf = tmp / "gap.wav"
    D.ff("-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", a.gap, "-y", gapf)

    parts, srt, rows, t, si = [], [], [], 0.0, 0
    for i, (is_sot, secs, text) in enumerate(plan, 1):
        if is_sot:
            if not a.sot_pad:
                continue                      # 旁白轨不含同期声（剪辑时贴原声）
            sil = tmp / f"{i:02d}-sot.wav"
            D.ff("-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                 "-t", f"{secs}", "-y", sil)
            dur = secs; parts.append(sil)
        else:
            s, e = segs[si]; si += 1
            rawf, cutf = tmp / f"{i:02d}-raw.wav", tmp / f"{i:02d}-cut.wav"
            D.ff("-v", "error", "-ss", f"{s:.3f}", "-to", f"{e:.3f}", "-i", audio,
                 "-ac", "1", "-ar", "44100", "-y", rawf)
            D.trim(rawf, cutf)
            dur = D.duration(cutf)
            if dur < 0.05:
                D.ff("-v", "error", "-ss", f"{s:.3f}", "-to", f"{e:.3f}", "-i", audio,
                     "-ac", "1", "-ar", "44100", "-y", cutf)
                dur = D.duration(cutf)
            parts.append(cutf)
        if not is_sot:
            srt.append(f"{i}\n{D.ts(t)} --> {D.ts(t+dur)}\n{text}\n")
        rows.append({"i": i, "start": round(t,2), "end": round(t+dur,2), "dur": round(dur,2),
                     "sot": is_sot, "text": text})
        t += dur
        if i < len(plan):
            parts.append(gapf); t += a.gap

    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
    wav = tmp / "out.wav"
    D.ff("-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-y", wav)
    mp3 = outdir / f"{audio.stem}-去气口.mp3"
    D.ff("-v", "error", "-i", str(wav), "-b:a", "128k", "-y", mp3)
    (outdir / f"{audio.stem}-去气口.srt").write_text("\n".join(srt), encoding="utf-8")
    (outdir / f"{audio.stem}-去气口.json").write_text(
        json.dumps({"lines": len(plan), "narr": len(narr), "gap": a.gap,
                    "sot": sum(1 for p in plan if p[0]), "total": round(t,2),
                    "segments": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"去气口: {total:.2f}s → {D.duration(mp3):.2f}s · {len(plan)} 行（同期声 {sum(1 for p in plan if p[0])}）")
    print(f"wrote {mp3}")

if __name__ == "__main__":
    main()
