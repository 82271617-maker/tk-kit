---
name: tk-select
description: 从 TikTok 对标账号里选题——按飞书账号表抓取每个号近 20 条、按账号各自算中位数基线、用六条门槛判定、按可做性排序，交付纯链接清单 + 已下载素材。当用户说「从这些对标账号里选能做的」「跑一下选题」「看看今天有什么可做」「按标准筛一下这些账号」时使用。
---

# TK 选题（对标账号 → 候选清单 → 可用链接）

把「读账号表 → 抓取 → 算基线 → 判定 → 排序 → 交付」固化成一条可重复的流水线。
**判定靠脚本，不靠感觉**：同一条片子，谁跑都是同一个结论。

## 路径约定

本技能假设 `kit/` 与 `.agents/` 在**同一个仓库根目录**下：

| 安装方式 | `KIT` 指向 |
| --- | --- |
| 独立克隆（团队默认） | `~/tk-kit/kit` |
| DSH 工作区内运行 | `<workspace>/projects/tk-sop/kit` |

下文命令统一用 `KIT`。**不需要你手动 export**：每条命令里都写了兜底

```bash
KIT="${KIT:-$HOME/tk-kit/kit}"
```

所以无论当前 shell 有没有这个变量、是不是旧会话，都能跑。要换位置才需要 `export KIT=...`。

## 前置检查（每次先做）

1. **代理可用**：TikTok 直连不通，必须走 `http://127.0.0.1:7890`（可用 `TK_PROXY` 覆盖）。
   自检：`curl -x http://127.0.0.1:7890 -s -o /dev/null -w "%{http_code}" https://www.tiktok.com/` 应返回 200。
2. **工具在位**：`$KIT/.venv/bin/yt-dlp --version` 有输出。
   缺了就跑一遍安装：
   ```bash
   KIT="${KIT:-$HOME/tk-kit/kit}"   # 没设也能跑
cd "$KIT"
   python3 -m venv .venv && .venv/bin/pip install yt-dlp imageio-ffmpeg
   ```
3. **账号来源**：飞书工作表（`lark-cli sheets +csv-get --spreadsheet-token <token> --sheet-id <id> --as user`）。
   只有用户贴的链接时，从 URL 里取 `@handle`，忽略 query 参数。

## 流程

```text
① 读表取账号 ──► ② 每号抓近 20 条 ──► ③ 算各号中位数 ──► ④ 判定 ──► ⑤ 排序 ──► ⑥ 交付
```

### ② 抓取（有两个坑）

- 主页 URL **带 query 参数**成功率更高：`https://www.tiktok.com/@<handle>?is_from_webapp=1&sender_device=pc`
- 主页抓不到时：先用任意一条该号视频反查 `channel_id`，再用 `tiktokuser:<channel_id>` 拉列表。
  脚本已内置：`kit/pool.py` 的 `list_videos()`（3 次重试 + channel_id 兜底）。
- 仍然失败 → 写「未取到」，**不要猜、不要用别的号顶替**。

### ③b 评论附录（选题阶段，附在候选清单后面）

**每条过线的视频都跑一次评论扫描，把结果附在该条后面——不做判定、不淘汰、不参与排序，做不做由人决定。**

```bash
KIT="${KIT:-$HOME/tk-kit/kit}"; cd "$KIT"
.venv/bin/python comments.py <视频链接> --pages 2 --top 10 --views <播放>
```

每条附三行：

- **争议强度 X%**：观众在质疑真假/摆拍的比例。这不是风险，是题材——越吵越说明有话题
- **评论率 X%**：评论数 / 播放
- **最强 2–3 句原话**：脚本已标 🔥争议 / 💢愤怒，可直接当改写钩子

规则：

- 红线（政治人物、血腥）只提示，**不否决**
- 抓不到写「评论未取到」，该条仍进清单
- **不许**用评论改阈值、改排序，也不许替人下「做/不做」的结论
- 评论附录不进入⑤排序：排序仍按「软分 + 倍数」

为什么用第三方接口：yt-dlp 的 TikTok extractor 只给 `comment_count`，不抓评论内容。
接口单条上限约 4000 条、免费额度约 500 条，`--pages 2`（约 100 条）足够看地形。

### ④ 判定（顺序不能换）

| 顺序 | 筛子 | 规则 |
| --- | --- | --- |
| a | 一票否决 | 血腥/政治/医疗绝对化；纯画面无叙事；烧录字幕压在画面中部且裁不掉也盖不住 |
| b | 硬门槛 | 播放 ≥ 100,000；播放 ≥ 该号中位数 × 5（小号跳过）；45–90 秒；点赞率 ≥ 1.0% |
| c | 软分（只排序） | 时效（≤14 天 5 分 / 15–30 天 3 分 / >30 天 1 分）、评论率、结构清晰度 |

- **小号定义**：中位数 < 5 万。小号只按绝对值判，不参与倍数（实测中位 3,145 的号出现过 56 倍，纯噪声）。
- **倍数必须各号各算**，绝不跨账号比较。
- 阈值只改 `kit/pick.py` 的 `THRESHOLDS`，**不要**在提示词或对话里临时改数。

### ⑤ 排序

按「软分 + 倍数」，不按播放。成本约 3 小时/条，选「做得出来」而不是「播放最高」。

### ⑥ 交付（不能省）

必须交出三样：

1. **纯链接清单**：一行一条，去掉 query 参数，格式 `https://www.tiktok.com/@<handle>/video/<id>`
2. **汇总**：条数 + 文件路径 + 生成日期

只给标题不给链接 = 没交付。

> 下载与去水印是**下一步**（技能 `tk-clean`）：本技能只负责选出「值得下」的，产出链接清单即可。
> 快速验证时可以 `deliver.py` 顺手下一个，但正式流程走 `tk-clean`（带元数据 / manifest / 质检帧 / 行级去水印）。

## 命令

```bash
KIT="${KIT:-$HOME/tk-kit/kit}"   # 没设也能跑
cd "$KIT"

# 1) 批量抓取 + 判定（每号 20 条）
printf "@handle1\n@handle2\n" > out/accounts.txt
.venv/bin/python pool.py --accounts out/accounts.txt --limit 20

# 2) 交付链接 + 下载素材（把 pool 结果里通过的链接贴进 out/selected.txt）
.venv/bin/python deliver.py out/selected.txt
```

产物：`out/pool-<时间>.md`、`out/links-<日期>.txt`、`out/deliver-<日期>.md`、`out/candidates/`。

## 输出格式

```markdown
| 账号 | 播放 | 倍数 | 时效 | 点赞率 | 时长 | 标题 | 链接 | 结论 | 淘汰原因 |

各账号基线：@a 中位数 13.3 万 / @b 4.9 万
淘汰原因分布：倍数不足 40 条 · 时效软分低 3 条
已知限制：@c 主页抓取失败，未取到
```

每条入选再给一句**改写切入点**（这条片子换成日语后靠什么成立）。

## 失败处理

| 现象 | 处理 |
| --- | --- |
| `Unable to extract secondary user ID` | 换带 query 参数的主页 URL，或走 channel_id 兜底 |
| 某号一条都抓不到 | 让用户贴该号任意一条视频链接；仍不行就在清单里标「未取到」 |
| 播放数看起来忽高忽低 | TikTok 播放含推荐位波动，隔天可能差 10–20%，只看量级 |
| 用户说「按我说的时间算」 | 时效是软分，不淘汰；不要为了让某条入选而临时改阈值 |

## 边界（不要做）

- 不判断「片子好不好笑」——这是人的事，脚本只给数据。
- 不跨账号比倍数、不用英语区基线套日语区。
- 不自动发布、不改用户的对标表（除非明确要求写回）。
- 不因为某条「看着像爆款」就绕过门槛。

配套文档：`projects/tk-sop/选题标准.md`（阈值推导）、`团队提示词-选题.md`（团队版提示词）。

## 安装（团队）

一行装完（仓库公开）：

```bash
curl -fsSL https://raw.githubusercontent.com/82271617-maker/tk-kit/main/install.sh | bash
```

或手动：

```bash
git clone https://github.com/82271617-maker/tk-kit.git ~/tk-kit
bash ~/tk-kit/install.sh
```

安装脚本做三件事：装 venv 依赖（yt-dlp + ffmpeg）、把技能拷到 `~/.dsh/skills/`、打印自检结果。

⚠️ 技能依赖同仓的 `kit/`，只拷技能目录会跑不起来。
