# tk-kit

TikTok 民生新闻类二创流水线的工具包：**选题 → 交付素材**。

## 目录

```
.agents/skills/tk-select/   DSH 技能：选题的标准与流程（装到工作区即可被 AI 发现）
kit/
  pool.py      批量抓对标账号近 20 条 → 算账号基线 → 按门槛判定 → 出候选清单
  deliver.py   把选中的视频变成「纯链接清单 + 已下载 mp4」
  pick.py      阈值与判定逻辑（THRESHOLDS，改标准只改这里）
  comments.py  抓评论 → 话题地形（争议强度 / 评论率 / 可当钩子的原句）
  rewrite_check.py  校验文案三步：行数一致 / 无标点 / 缩减≥30% / 人审留痕 / 标签合规
  tk.py        单节点命令：下载 / 体检 / 抽帧 / 裁边 / 模糊
docs/          选题标准（含阈值推导）、团队提示词、AI 化评估
prompts/       改写用的提示词库（简化 → 校对 → 中译日）
```

## 改完技能必须重装（最容易踩的坑）

`~/tk-kit/.agents/skills/` 是**源**，`~/.dsh/skills/` 和各个工作区的 `.agents/skills/` 是**副本**。
改了技能文件但不重装，等于**只改了源头、AI 还在读旧副本**——表现是"明明改了却没生效"。

改完任何 `SKILL.md` 或 `kit/*.py` 后，必须：

```bash
cd ~/tk-kit && git pull              # 拉最新
bash install.sh                      # 把技能同步到 ~/.dsh/skills
# 工作区级副本（如果你在某个工作区里也放了一份）
cp .agents/skills/*/SKILL.md <workspace>/.agents/skills/*/SKILL.md
```

自检（三处应当一致）：

```bash
diff -q ~/tk-kit/.agents/skills/tk-select/SKILL.md ~/.dsh/skills/tk-select/SKILL.md
```

> `kit/*.py` 不用重装，技能里直接跑 `$KIT/*.py`；只有 `SKILL.md` 需要同步。

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
.venv/bin/python comments.py <视频链接> --pages 2 --top 10 --views <播放>   # 每条附评论附录
.venv/bin/python deliver.py out/selected.txt                         # 交付链接 + 下载
```

`comments.py` 输出的是**话题地形**，不是风险评级：争议强度（质疑真假的比例）、评论率、
被反复提到的点、可当钩子的原句。它不淘汰任何片子，做不做由人决定。

## 技能一览

| 技能 | 干什么 | 卡点 |
| --- | --- | --- |
| `tk-select` | 找爆款：读取 → 分析 → 呈现（自动开标签页） | 你勾一条 |
| `tk-clean` | 下载 + 去水印（行级遮蔽 / blur / 保留装饰条） | 渲染前看预览图 |
| `tk-rewrite` | 文案五步：转写 → 评论取料 → 初翻 → 改写 → 人审 → 日文稿 | **④ 人审：审核通过才翻日文** |
| `tk-dub` | 去气口 + 字幕对轴 | 停顿数 ≠ 行数−1 就停 |

## 判定标准（摘要）

1. 一票否决：血腥/政治/医疗绝对化、纯画面无叙事、烧录字幕压在画面中部且裁不掉
2. 硬门槛：播放 ≥ 10 万 **且** ≥ 该账号近 20 条中位数 ×5（小号跳过）**且** 45–90 秒 **且** 点赞率 ≥ 1.0%
3. 软分排序：时效、评论率、结构清晰度

详见 `docs/选题标准.md`；评论怎么用见 `docs/评论地形.md`。

## 免责

`out/` 下的素材仅用于研究/二次创作分析，版权归原作者；本仓库不包含任何视频文件。
