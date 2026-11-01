#!/usr/bin/env python3
"""transcribe — 转写原片 → 01-英文稿.txt（带起止时间）。

⚠️ 必须用「独立 ASR venv」运行，不能用 kit/.venv：
   DSH 运行时自带的 Python 加载 PyPI 二进制扩展会报签名校验错
   （mapping process and mapped file (non-platform) have different Team IDs）。

首次准备（每台机器一次）：
   /usr/bin/python3 -m venv .venv-asr
   .venv-asr/bin/pip install faster-whisper
   # 模型缓存放工作区（沙盒写不进 ~/.cache）
   mkdir -p .cache/hf

用法：
   HF_HOME=$PWD/.cache/hf .venv-asr/bin/python transcribe.py <视频> --lang en
   HF_HOME=$PWD/.cache/hf .venv-asr/bin/python transcribe.py <视频> --lang ja --out 某目录

产物（同目录）：
   01-英文稿.txt   每行 "起-止  文本"（--lang ja 时自动命名 01-日文稿-原声.txt）
   01-英文稿.srt   标准字幕，可直接给剪映
"""
import argparse
import subprocess
import sys
from pathlib import Path


def fmt(ts):
    h, rem = divmod(ts, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("--lang", default="en", help="原片语言：en / ja / auto")
    p.add_argument("--model", default="small", help="tiny/base/small/medium/large-v3")
    p.add_argument("--out", default=None, help="输出目录（默认同视频目录）")
    a = p.parse_args()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("缺少 faster-whisper：请用 .venv-asr 里的 python 运行本脚本（见文件头说明）")

    src = Path(a.video)
    outdir = Path(a.out) if a.out else src.parent
    outdir.mkdir(parents=True, exist_ok=True)

    model = WhisperModel(a.model, device="cpu", compute_type="int8")
    segs, info = model.transcribe(str(src),
                                  language=None if a.lang == "auto" else a.lang,
                                  vad_filter=True, beam_size=5)

    tag = "英文" if a.lang == "en" else ("日文" if a.lang == "ja" else "原文")
    txt_path = outdir / f"01-{tag}稿.txt"
    srt_path = outdir / f"01-{tag}稿.srt"

    lines, srt = [], []
    for i, s in enumerate(segs, 1):
        text = s.text.strip()
        if not text:
            continue
        lines.append(f"{s.start:7.2f}-{s.end:7.2f}  {text}")
        srt.append(f"{i}\n{fmt(s.start)} --> {fmt(s.end)}\n{text}\n")

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    srt_path.write_text("\n".join(srt), encoding="utf-8")

    print(f"语言: {info.language} ({info.language_probability:.0%})  时长: {info.duration:.1f}s")
    print(f"句数: {len(lines)}")
    print(f"wrote {txt_path}")
    print(f"wrote {srt_path}")


if __name__ == "__main__":
    main()
