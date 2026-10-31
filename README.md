# tk-kit

TikTok 民生新闻类二创流水线的工具包：**选题 → 交付素材**。

## 目录

```
.agents/skills/tk-select/   DSH 技能：选题的标准与流程（装到工作区即可被 AI 发现）
kit/
  pool.py      批量抓对标账号近 20 条 → 算账号基线 → 按门槛判定 → 出候选清单
  deliver.py   把选中的视频变成「纯链接清单 + 已下载 mp4」
  pick.py      阈值与判定逻辑（THRESHOLDS，改标准只改这里）
  tk.py        单节点命令：下载 / 体检 / 抽帧 / 裁边 / 模糊
docs/          选题标准（含阈值推导）、团队提示词、AI 化评估
prompts/       改写用的提示词库（简化 → 校对 → 中译日）
```

## 安装

一行装完（仓库公开）：

```bash
curl -fsSL https://raw.githubusercontent.com/82271617-maker/tk-kit/main/install.sh | bash
```

或手动：

```bash
git clone https://github.com/82271617-maker/tk-kit.git ~/tk-kit
bash ~/tk-kit/install.sh
```

脚本做三件事：建 `.venv` 装 yt-dlp + ffmpeg、把技能拷到 `~/.dsh/skills/tk-select`、跑自检。
可用 `SKILL_DEST=/path` 改技能安装位置。

装完设置路径变量（SKILL.md 里所有命令都用 `$KIT`）：

```bash
export KIT=~/tk-kit/kit
```

## 前置

- TikTok 直连不通，需要本地代理：默认 `http://127.0.0.1:7890`，可用 `TK_PROXY` 覆盖。
- 判定阈值在 `kit/pick.py` 的 `THRESHOLDS`，**不要**在提示词里临时改数字，否则多人结论不一致。

## 用法

```bash
cd kit
printf "@handle1\n@handle2\n" > out/accounts.txt
.venv/bin/python pool.py --accounts out/accounts.txt --limit 20      # 抓取 + 判定
.venv/bin/python deliver.py out/selected.txt                         # 交付链接 + 下载
```

## 判定标准（摘要）

1. 一票否决：血腥/政治/医疗绝对化、纯画面无叙事、烧录字幕压在画面中部且裁不掉
2. 硬门槛：播放 ≥ 10 万 **且** ≥ 该账号近 20 条中位数 ×5（小号跳过）**且** 45–90 秒 **且** 点赞率 ≥ 1.0%
3. 软分排序：时效、评论率、结构清晰度

详见 `docs/选题标准.md`。

## 免责

`out/` 下的素材仅用于研究/二次创作分析，版权归原作者；本仓库不包含任何视频文件。
