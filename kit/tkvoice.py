#!/usr/bin/env python3
"""tkvoice — 逐句配音 → 去气口 → 精确 SRT（MiniMax TTS）

设计要点：**逐句合成**，不是整段合成。
每句时长已知 → 不需要 silencedetect 猜停顿，字幕天然精确。

用法：
  python tkvoice.py <05-日文稿.txt> --voice-id jp_news_male_laicheng --out-dir <04-配音> [--gap 0.25]

产物：
  <名>-原配音.mp3     各句原样拼接（保留句间 0.35s）
  <名>-去气口.mp3     每句裁首尾静音后拼接（句间 0.25s）
  <名>-精确.srt       与去气口音轨逐句对齐
  <名>-时间表.json    每句起止 + 时长 + voice_id
"""
import argparse, base64, json, os, pathlib, re, subprocess, sys, tempfile, time
import urllib.request, urllib.error

FF = os.path.expanduser("~/tk-kit/kit/.venv/lib/python3.9/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1")

def env():
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    ep = os.environ.get("MINIMAX_ENDPOINT", "https://api.minimaxi.com").rstrip("/")
    if not key:
        sys.exit("缺 MINIMAX_API_KEY（在 ~/.tk-voice.env 里）")
    return key, ep

def tts(text, voice_id, model, key, ep, speed=1.0, retries=3):
    body = json.dumps({
        "model": model, "text": text, "stream": False,
        "voice_setting": {"voice_id": voice_id, "speed": speed},
        "audio_setting": {"format": "mp3", "sample_rate": 32000},
    }).encode()
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(ep + "/v1/t2a_v2", data=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.loads(r.read())
            st = (d.get("base_resp") or {}).get("status_code")
            if st != 0:
                last = f"{st} {(d.get('base_resp') or {}).get('status_msg')}"
            else:
                a = d["data"]["audio"]
                # MiniMax 返回的是十六进制串，不是 base64（实测 494433 = "ID3"）
                try:
                    if re.fullmatch(r"[0-9a-fA-F]+", a) and len(a) % 2 == 0:
                        return bytes.fromhex(a)
                except Exception:
                    pass
                return base64.b64decode(a)
        except Exception as e:
            last = repr(e)
        time.sleep(1.5 + i)
    raise RuntimeError(f"TTS 失败: {last}")

def dur(path):
    r = subprocess.run([FF, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    if not m: raise RuntimeError(f"读不到时长: {path}")
    return int(m[1])*3600 + int(m[2])*60 + float(m[3])

def trim(src, dst):
    af = ("silenceremove=start_periods=1:start_silence=0.02:start_threshold=-40dB,"
          "areverse,silenceremove=start_periods=1:start_silence=0.02:start_threshold=-40dB,areverse")
    subprocess.run([FF, "-v", "error", "-i", str(src), "-af", af,
                    "-ac", "1", "-ar", "32000", "-y", str(dst)], check=True)

def tstamp(t, sep=","):
    h = int(t//3600); m = int(t%3600//60); s = t%60
    return f"{h:02d}:{m:02d}:{int(s):02d}{sep}{int(round((s-int(s))*1000)):03d}"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("script")
    p.add_argument("--voice-id", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--name", default=None)
    p.add_argument("--model", default="speech-2.5-hd-preview")
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--gap", type=float, default=0.25, help="去气口版句间停顿")
    p.add_argument("--raw-gap", type=float, default=0.35, help="原配音版句间停顿")
    p.add_argument("--dry-run", action="store_true", help="只打印计划与预估调用数，不调接口")
    p.add_argument("--yes", action="store_true", help="确认花钱：没有它不会调用任何付费接口")
    p.add_argument("--mode", choices=["fast", "precise"], default="fast",
                   help="fast=整段合成自然（默认）；precise=逐句合成字幕零误差")
    a = p.parse_args()

    lines_pre = [l.strip() for l in pathlib.Path(a.script).read_text(encoding="utf-8").splitlines() if l.strip()]
    chars = sum(len(l) for l in lines_pre)
    calls = 1 if a.mode == "fast" else len(lines_pre)
    print("== 花钱计划 ==")
    print(f"  模式      {a.mode}")
    print(f"  句数      {len(lines_pre)} 句 · {chars} 字符")
    print(f"  调用      {calls} 次合成")
    print(f"  音色      {a.voice_id}")
    print(f"  计费单位  {chars} 字符（按字符计费；单价与扣费以下单后台账单为准，不在此估算）")
    if a.dry_run or not a.yes:
        print("\n未执行：需要用户同意后加 --yes 才真正调用接口。")
        return
    key, ep = env()
    lines = [l.strip() for l in pathlib.Path(a.script).read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines: sys.exit("稿子为空")
    out = pathlib.Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    name = a.name or pathlib.Path(a.script).stem
    tmp = pathlib.Path(tempfile.mkdtemp())

    if a.mode == "fast":
        # 整段合成：把每行的空格换成「、」，行间用「。」，让模型自己控制呼吸
        # 行内空格只是人工断句标记，直接去掉；行间用「。」让模型自己呼吸
        punct = "。".join("".join(l.split()) for l in lines) + "。"
        raw_mp3 = out/f"{name}-原配音.mp3"
        raw_mp3.write_bytes(tts(punct, a.voice_id, a.model, key, ep, a.speed))
        print(f"整段合成完成：{dur(raw_mp3):.2f}s / {len(punct)} 字符")
        r = subprocess.run([sys.executable, str(pathlib.Path(__file__).parent/"dubline.py"),
                            str(raw_mp3), a.script, "--gap", str(a.gap), "--out-dir", str(out)],
                           capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip()[:400])
        print(f"\n原配音  {raw_mp3}  {dur(raw_mp3):.2f}s")
        return

    segs, raws = [], []
    for i, text in enumerate(lines, 1):
        raw = tmp/f"{i:02d}-raw.mp3"
        raw.write_bytes(tts(text, a.voice_id, a.model, key, ep, a.speed))
        cut = tmp/f"{i:02d}-cut.wav"
        trim(raw, cut)
        raws.append(raw); segs.append(cut)
        print(f"  {i:02d}/{len(lines)}  {dur(cut):.2f}s  {text[:26]}", flush=True)

    def build(parts, gap, dst):
        sil = tmp/f"sil-{gap}.wav"
        if not sil.exists():
            subprocess.run([FF, "-v", "error", "-f", "lavfi", "-i",
                            f"anullsrc=r=32000:cl=mono", "-t", str(gap), "-y", str(sil)], check=True)
        lst = tmp/"list.txt"
        with lst.open("w") as f:
            for j, s in enumerate(parts):
                f.write(f"file '{s}'\n")
                if j != len(parts)-1: f.write(f"file '{sil}'\n")
        wav = tmp/f"concat-{gap}.wav"
        subprocess.run([FF, "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-y", str(wav)], check=True)
        subprocess.run([FF, "-v", "error", "-i", str(wav), "-b:a", "128k", "-y", str(dst)], check=True)

    raw_mp3 = out/f"{name}-原配音.mp3"
    cut_mp3 = out/f"{name}-去气口.mp3"
    build(raws, a.raw_gap, raw_mp3)
    build(segs, a.gap, cut_mp3)

    # 精确 SRT：按去气口音轨的真实时长累加
    cur, rows, tm = 0.0, [], []
    cut_d = [dur(s) for s in segs]
    for i, (text, d) in enumerate(zip(lines, cut_d), 1):
        start, end = cur, cur + d
        rows.append(f"{i}\n{tstamp(start)} --> {tstamp(end)}\n{text}\n")
        tm.append({"i": i, "start": round(start,3), "end": round(end,3), "dur": round(d,3), "text": text})
        cur = end + a.gap
    srt = out/f"{name}-精确.srt"
    srt.write_text("\n".join(rows), encoding="utf-8")
    js = out/f"{name}-时间表.json"
    js.write_text(json.dumps({"voice_id": a.voice_id, "model": a.model, "gap": a.gap,
                              "lines": len(lines), "total": round(cut_d and (sum(cut_d)+a.gap*(len(cut_d)-1)),3),
                              "segments": tm}, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n原配音  {raw_mp3}  {dur(raw_mp3):.2f}s")
    print(f"去气口  {cut_mp3}  {dur(cut_mp3):.2f}s")
    print(f"字幕    {srt}  {len(lines)} 条")
    print(f"时间表  {js}")

if __name__ == "__main__":
    main()
