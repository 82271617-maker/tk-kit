---
name: tk-voice
description: 配音三件套：按音克隆库取音色 → 逐句合成 → 去气口 → 输出原配音 mp3、去气口 mp3、精确 SRT。当用户说「配音」「用 XX 音色配音」「出配音和字幕」「跑 tk-voice」时使用。上游是 tk-rewrite 的 05-日文稿，下游是剪映。
---

# 配音：逐句合成 → 去气口 → 精确字幕

一句话：**一句合成一次，每句时长已知，字幕不用再对轴。**

## 音色从库里取（不现问）

```bash
KIT="${KIT:-$HOME/tk-kit/kit}"; ROOT="$HOME/Desktop/TK库"
cat "$ROOT/02-音克隆库/<责任人>/<音色名>/voice_id.txt"
```

库里没有就先克隆（见「新增音色」）。**voice_id 不许出现在对话里或仓库里**，只从库文件读。

## 跑一条

```bash
set -a; . ~/.tk-voice.env; set +a      # MINIMAX_API_KEY / MINIMAX_ENDPOINT
D="$ROOT/<年-月>/<年-月-日>/<编号>-<id>"
$KIT/.venv/bin/python $KIT/tkvoice.py "$D/03-文案/05-日文稿.txt" \
  --voice-id <voice_id> --out-dir "$D/04-配音" --name <id>
```

产物四样：

| 文件 | 内容 |
| --- | --- |
| `<id>-原配音.mp3` | 各句原样拼接，句间 0.35s |
| `<id>-去气口.mp3` | 每句裁首尾静音（留 0.02s），句间 0.25s |
| `<id>-精确.srt` | 与去气口音轨逐句对齐，导入剪映直接可用 |
| `<id>-时间表.json` | 每句起止 + 时长 + voice_id |

## 新增音色（一次性）

```bash
# 1) 样音：10–30 秒、单人、无背景音乐，存进库
mkdir -p "$ROOT/02-音克隆库/<责任人>/<音色名>"
ffmpeg -ss 3 -t 18 -i 原音频.mp3 -ac 1 -ar 32000 -b:a 128k \
  "$ROOT/02-音克隆库/<责任人>/<音色名>/sample.mp3"
# 2) 上传 + 克隆（file_id → voice_clone，必须带 model）
# 3) 写 voice_id.txt + meta.json，更新音克隆库.csv 与飞书表
```

## 三个实测坑（已经踩过，别重犯）

1. **样音短于 10 秒** → `2037 voice duration too short`。最小 10s，建议 15–20s
2. **`voice_clone` 不带 `model`** → `2013 model not allowed`。用 `speech-2.5-hd-preview`
3. **返回的 audio 是十六进制串，不是 base64** → 直接 base64 解码会得到乱码，ffmpeg 报 `Failed to find two consecutive MPEG audio frames`。判断方式：字符串以 `494433`（ID3）开头就用 `bytes.fromhex`

## 为什么逐句合成

| | 整段合成 | 逐句合成（本技能） |
| --- | --- | --- |
| 去气口 | 靠 `silencedetect` 猜阈值 | 不需要，逐句天然分开 |
| 字幕 | 要转写或强制对齐，会错 | 每句时长已知，SRT 零误差 |
| 改一句 | 整段重跑 | 只重跑那一句 |

## 校验（交付前必看）

- 段数 == 稿子行数
- 去气口总长 == Σ句长 + (N−1)×0.25
- SRT 末条结束时间与音频时长差 ≤ 0.1s
- 没有单句 < 0.6s（会听不出字）

## 边界

- 只做配音与字幕，**不剪片**
- 不改稿子内容；发现句子拗口要回到 `tk-rewrite` 改 05
- key 只在 `~/.tk-voice.env`（权限 600），不进仓库、不进日志
