#!/usr/bin/env python3
"""comments — TikTok 评论地形：测「话题度」而不是「风险」。

判断口径（2026-11 修正）：
  争议 = 题材，不是风险。评论区吵「摆拍/不可能」本身就是最可用的钩子。
  本脚本输出：话题热度 → 争议强度 → 对立阵营 → 高频点 → 可钩子原句 → 红线单列（只提示，不否决）。

为什么不用 yt-dlp：TikTok extractor 只给 comment_count，不抓评论内容。
接口：tikwm（需代理），单条上限约 4000 条、免费额度约 500 条。

用法：
  python comments.py <链接或id>                       # 4 页 ≈ 200 条
  python comments.py <链接> --pages 1 --top 10        # 轻扫
  python comments.py <链接> --views 946800 --dump-md ../文案/<id>/00-评论.md
"""
import argparse, json, re, sys, time, urllib.parse, urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out" / "comments"
PROXY = "http://127.0.0.1:7890"
API = "https://www.tikwm.com/api/comment/list/"

# 争议信号：这些词出现 = 观众在吵，越吵越有题材
DISPUTE = r"is this real|not real|real\?|fake|staged|scripted|skit|acting|impossible|can't believe|cant believe|no way|bs\b|cap\b|doubt|set ?up|propaganda|lie"
# 情绪极性
ANGER = r"fire him|fired|arrest|jail|sue|cruel|disgusting|horrible|shame on|should be|boycott|evil"
WARM = r"angel|bless|god|pray|🙏|hero|beautiful|kind|touched|love|hope"
# 红线：只在真踩线时提示，**不自动否决**
REDLINE = {
    "政治人物/选举": r"\btrump\b|\bbiden\b|election|president|🇺🇸|racis|democrat|republican",
    "血腥": r"\bblood|corpse|dead body|behead",
}

STOP = set("the a an and or but to of in on for is are was were be been i you he she it we they my your his her this that with me not so just it's don't can't".split())


def video_id(s):
    m = re.search(r"/video/(\d+)", s)
    return m.group(1) if m else (s if s.isdigit() else None)


def fetch(url, count=50, cursor=0, tries=3):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    op.addheaders = [("User-Agent", "Mozilla/5.0")]
    last = ""
    for i in range(tries):
        try:
            q = urllib.parse.urlencode({"url": url, "count": count, "cursor": cursor})
            d = json.loads(op.open(API + "?" + q, timeout=30).read())
            if d.get("code") == 0:
                return d["data"]
            last = d.get("msg", "api code != 0")
        except Exception as e:
            last = repr(e)
        time.sleep(1.5 + i)
    raise RuntimeError(last)


def phrases(texts, n=(2, 3), top=12):
    c = Counter()
    for t in texts:
        w = [x for x in re.findall(r"[a-z']+", t.lower()) if x not in STOP and len(x) > 2]
        for k in n:
            for i in range(len(w) - k + 1):
                c[" ".join(w[i:i + k])] += 1
    return [(p, v) for p, v in c.most_common(60) if v >= 3][:top]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("target")
    p.add_argument("--pages", type=int, default=4)
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--views", type=int, default=0, help="可选：播放量，用来算评论率")
    p.add_argument("--dump-md", default=None)
    a = p.parse_args()

    url = a.target if a.target.startswith("http") else f"https://www.tiktok.com/@_/video/{a.target}"
    vid = video_id(url)
    if not vid:
        print(f"!! 解析不出视频 id：{a.target}", file=sys.stderr); return 1

    seen, items, cur, total = {}, [], 0, None
    try:
        for _ in range(a.pages):
            data = fetch(url, 50, cur)
            total = data.get("total", total)
            cs = data.get("comments") or []
            new = 0
            for c in cs:
                if c.get("id") not in seen:
                    seen[c["id"]] = 1; items.append(c); new += 1
            cur = data.get("cursor") or cur + 50
            if not data.get("hasMore") or not cs or new == 0:
                break
            time.sleep(0.5)
    except Exception as e:
        print(f"!! 未取到：{e}（不要猜内容，报告失败即可）", file=sys.stderr); return 1

    items = [c for c in items if c.get("text")]
    items.sort(key=lambda c: c.get("digg_count", 0), reverse=True)
    sub = [c for c in items if len(c["text"].split()) >= 3] or items
    low = [c["text"].lower() for c in sub]
    hit = lambda rx: sum(1 for t in low if re.search(rx, t))
    dispute, anger, warm = hit(DISPUTE), hit(ANGER), hit(WARM)
    likes = sum(c.get("digg_count", 0) for c in items)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{vid}.json").write_text(json.dumps(items, ensure_ascii=False, indent=1))

    L = [f"# 评论地形 · {vid}", "",
         f"样本 {len(items)} / 总量 {total}（按赞排序，偏热评）· 累计赞 {likes:,}　{time.strftime('%Y-%m-%d %H:%M')}"]
    if a.views:
        L.append(f"评论率 {len(items)}{'（抽样）' if total and len(items) < total else ''} / 播放 {a.views:,} = {len(items)/a.views*100:.2f}%（全量口径约 {total/a.views*100:.2f}%）")
    L += ["", "## 话题度", "",
          f"- **争议强度 {dispute/len(sub)*100:.0f}%**（{dispute}/{len(sub)} 条在质疑真假/摆拍）"
          + ("　← 越吵越是题材" if dispute / len(sub) > 0.1 else ""),
          f"- 愤怒/追责 {anger/len(sub)*100:.0f}%　温情/祝福 {warm/len(sub)*100:.0f}%"]
    red = {k: hit(rx) for k, rx in REDLINE.items()}
    if any(red.values()):
        L.append("- ⚠️ 红线（只提示，不否决，要不要做由人定）：" + "·".join(f"{k} {v} 条" for k, v in red.items() if v))
    else:
        L.append("- 红线：无命中")

    L += ["", "## 观众反复提到的点", ""]
    for ph, n in phrases([c["text"] for c in sub]):
        L.append(f"- {ph} ×{n}")

    L += ["", f"## 可当钩子的原句（TOP {a.top}）", ""]
    for i, c in enumerate(items[:a.top], 1):
        t = re.sub(r"\s+", " ", c["text"])
        tag = "🔥争议" if re.search(DISPUTE, t.lower()) else ("💢愤怒" if re.search(ANGER, t.lower()) else "")
        L.append(f"{i}. [{c.get('digg_count',0)}]{tag} {t[:180]}")
    md = "\n".join(L) + "\n"

    print(md)
    if a.dump_md:
        Path(a.dump_md).parent.mkdir(parents=True, exist_ok=True)
        Path(a.dump_md).write_text(md, encoding="utf-8")
        print(f">> 已写 {a.dump_md}")
    print(f">> json: {OUT / f'{vid}.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
