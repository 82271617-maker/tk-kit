#!/usr/bin/env python3
"""dub — 配音后处理：去气口 + 字幕对轴。

用法：
  python dub.py debreath <in.mp3|mp4> [--out out.mp3] [--min-silence 0.25] [--threshold -35]
  python dub.py subtitle <audio> [--out out.srt] [--lang ja] [--model small]
  python dub.py all      <audio> [--lang ja]        # 先剪气口，再对轴

为什么「剪完气口必须重新对轴」：
  剪气口会改变音频总时长和每句的绝对时间，
  原来按旧音频算的字幕会整体漂移。所以顺序必须是「先剪后对」。

字幕怎么来：
  用 whisper 转写「剪完之后」的音频，拿到每句真实起止时间，直接生成 SRT。
  不依赖原始日文稿的行数，因此气口剪多剪少都不影响。
"""
import argparse
import subprocess
import sys
from pathlib import Path

def _find_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    here = Path(__file__).resolve().parent
    for base in (here / ".venv", here / ".venv-asr"):
        d = next(base.glob("lib/python3.*/site-packages/imageio_ffmpeg/binaries"), None)
        if d:
            exe = next(iter(sorted(d.glob("ffmpeg-*"))), None)
            if exe:
                return str(exe)
    return "ffmpeg"


FF = _find_ffmpeg()


def run(cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg 失败:\n{r.stderr[-600:]}")
    return r


def duration(path):
    r = subprocess.run([FF, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


def debreath(src, out, min_silence=0.25, threshold=-35):
    """去掉句间静音（气口）。注意：会缩短总时长。"""
    before = duration(src)
    vf = (f"silenceremove=start_periods=0:stop_periods=-1:"
          f"stop_duration={min_silence}:stop_threshold={threshold}dB:detection=peak")
    run([FF, "-hide_banner", "-i", src, "-af", vf, "-ac", "1", "-ar", "32000", "-y", out])
    after = duration(out)
    print(f"去气口: {before:.2f}s → {after:.2f}s（缩短 {before - after:.2f}s）")
    return out


def subtitle(audio, out, lang="ja", model="small"):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("缺少 faster-whisper：请用 .venv-asr/bin/python 运行（见 翻写五步.md）")

    m = WhisperModel(model, device="cpu", compute_type="int8")
    segs, info = m.transcribe(str(audio), language=None if lang == "auto" else lang,
                              vad_filter=True, beam_size=5)

    def ts(t):
        h, rem = divmod(t, 3600)
        mi, s = divmod(rem, 60)
        return f"{int(h):02d}:{int(mi):02d}:{s:06.3f}"

    blocks, n = [], 0
    for s in segs:
        text = s.text.strip()
        if not text:
            continue
        n += 1
        blocks.append(f"{n}\n{ts(s.start)} --> {ts(s.end)}\n{text}\n")
    Path(out).write_text("\n".join(blocks), encoding="utf-8")
    print(f"对轴: {n} 句 → {out}（语言 {info.language}）")
    return out


def smart(src, lang="ja", model="small", gap=0.08):
    """按句切分 → 逐句去气口 → 拼接 → 用累加时长生成字幕。

    比「整段去气口再转写」可靠：整段剪完停顿消失，whisper 会把多句并成一段。
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("缺少 faster-whisper：请用 .venv-asr/bin/python 运行")

    m = WhisperModel(model, device="cpu", compute_type="int8")
    segs, info = m.transcribe(str(src), language=None if lang == "auto" else lang,
                              vad_filter=True, beam_size=5)
    segs = [s for s in segs if s.text.strip()]
    if not segs:
        sys.exit("没有识别到语音")

    tmp = Path("/tmp/dub-segs")
    tmp.mkdir(exist_ok=True)
    gapfile = tmp / "gap.wav"
    run([FF, "-hide_banner", "-f", "lavfi", "-i", "anullsrc=r=32000:cl=mono",
         "-t", str(gap), "-y", gapfile])
    t = 0.0
    srt, parts = [], []
    for i, s in enumerate(segs, 1):
        raw = tmp / f"{i:03d}-raw.wav"
        cut = tmp / f"{i:03d}-cut.wav"
        run([FF, "-hide_banner", "-ss", str(max(0, s.start - 0.03)),
             "-to", str(s.end + 0.03), "-i", src, "-ac", "1", "-ar", "32000", "-y", raw])
        run([FF, "-hide_banner", "-i", raw,
             "-af", "silenceremove=start_periods=1:start_silence=0.02:start_threshold=-40dB,"
                    "areverse,silenceremove=start_periods=1:start_silence=0.02:start_threshold=-40dB,areverse",
             "-ac", "1", "-ar", "32000", "-y", cut])
        dur = duration(cut)
        parts.append(cut)
        if i < len(segs):
            parts.append(gapfile)
        srt.append(f"{i}\n{fmt_ts(t)} --> {fmt_ts(t + dur)}\n{s.text.strip()}\n")
        t += dur + gap

    lst = tmp / "list.txt"
    lst.write_text("\n".join(f"file '{p}'" for p in parts) + "\n", encoding="utf-8")
    out_mp3 = src.with_name(src.stem + "-done.mp3")
    run([FF, "-hide_banner", "-f", "concat", "-safe", "0", "-i", lst,
         "-b:a", "128k", "-y", out_mp3])
    out_srt = src.with_name(src.stem + "-done.srt")
    Path(out_srt).write_text("\n".join(srt), encoding="utf-8")

    before, after = duration(src), duration(out_mp3)
    print(f"逐句去气口: {before:.2f}s → {after:.2f}s（缩短 {before - after:.2f}s）")
    print(f"字幕: {len(segs)} 句 → {out_srt}")
    print(f"音频: {out_mp3}")
    return out_mp3, out_srt


def fmt_ts(t):
    h, rem = divmod(t, 3600)
    mi, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(mi):02d}:{s:06.3f}"


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("debreath")
    d.add_argument("src")
    d.add_argument("--out", default=None)
    d.add_argument("--min-silence", type=float, default=0.25)
    d.add_argument("--threshold", type=float, default=-35)

    s = sub.add_parser("subtitle")
    s.add_argument("audio")
    s.add_argument("--out", default=None)
    s.add_argument("--lang", default="ja")
    s.add_argument("--model", default="small")

    a = sub.add_parser("all")
    a.add_argument("audio")
    a.add_argument("--lang", default="ja")
    a.add_argument("--model", default="small")
    a.add_argument("--gap", type=float, default=0.08, help="句间保留的停顿秒数")

    args = p.parse_args()
    if args.cmd == "debreath":
        src = Path(args.src)
        debreath(src, args.out or str(src.with_name(src.stem + "-noBreath.mp3")),
                 args.min_silence, args.threshold)
    elif args.cmd == "subtitle":
        src = Path(args.audio)
        subtitle(src, args.out or str(src.with_suffix(".srt")), args.lang, args.model)
    else:
        smart(Path(args.audio), args.lang, args.model, args.gap)


if __name__ == "__main__":
    main()
