#!/usr/bin/env python3
"""align — 用「已知文稿」给配音生成字幕（强制对齐，不依赖转写文本）。

为什么不用 whisper 直接转写出字幕：
  whisper 会把「住所」听成「重症」、把「下を向いて」听成「元を向いて」，
  字幕文本必须用你定稿的文稿，只有时间戳从音频里取。

做法：
  1 whisper 取词级时间戳（word_timestamps=True）
  2 把词拼成字符流，每个字符带着它出现的时间
  3 用 difflib 把文稿的每一行依次匹配到字符流上
  4 取该行首字符的开始时间、末字符的结束时间 → SRT

用法：
  python align.py <配音.mp3> <文稿.txt> [--out out.srt] [--lang ja]
"""
import argparse
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def norm(s):
    """去掉标点、空格、空白，只留可比较字符"""
    return re.sub(r"[\s、。,.!?！？…「」『』（）()・~〜\-—]", "", s)


def ts(t):
    h, rem = divmod(max(0.0, t), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("audio")
    p.add_argument("script")
    p.add_argument("--out", default=None)
    p.add_argument("--lang", default="ja")
    p.add_argument("--model", default="small")
    a = p.parse_args()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("缺少 faster-whisper：请用 .venv-asr/bin/python 运行")

    lines = [l.strip() for l in Path(a.script).read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        sys.exit("文稿是空的")

    m = WhisperModel(a.model, device="cpu", compute_type="int8")
    segs, info = m.transcribe(a.audio, language=a.lang, beam_size=5, word_timestamps=True)

    chars, times = [], []          # 字符流 + 每个字符对应的 (start, end)
    for s in segs:
        for w in (s.words or []):
            for ch in norm(w.word):
                chars.append(ch)
                times.append((w.start, w.end))
    if not chars:
        sys.exit("没有拿到词级时间戳")

    stream = "".join(chars)
    cursor = 0
    out, used = [], 0
    sm = difflib.SequenceMatcher(None, stream, "")
    for idx, line in enumerate(lines, 1):
        target = norm(line)
        if not target:
            continue
        sm.set_seq2(target)
        blocks = [b for b in sm.get_matching_blocks() if b.size > 0 and b.a >= cursor]
        if not blocks:
            out.append(f"{idx}\n{ts(0)} --> {ts(0.5)}\n{line}\n（未对齐）")
            continue
        first = blocks[0]
        last = blocks[-1]
        start = times[first.a][0]
        end = times[min(len(times) - 1, last.a + last.size - 1)][1]
        cursor = last.a + last.size
        out.append(f"{idx}\n{ts(start)} --> {ts(end)}\n{line}\n")
        used += 1

    out_path = Path(a.out) if a.out else Path(a.audio).with_suffix(".srt")
    out_path.write_text("\n".join(out), encoding="utf-8")
    print(f"语言 {info.language} · 对齐 {used}/{len(lines)} 句 → {out_path}")


if __name__ == "__main__":
    main()
