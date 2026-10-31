#!/usr/bin/env python3
"""deliver — 把选中的视频变成「能直接用的东西」：干净链接 + 已下载的 mp4。

用法：
  python deliver.py links.txt                 # 每行一条 tiktok 链接（可带 query 参数）
  python deliver.py links.txt --no-download    # 只出链接清单，不下载

输出：
  out/links-<日期>.txt     一行一条干净链接，直接复制到飞书/群里
  out/deliver-<日期>.md    带标题/时长/播放的表，可贴进文档
  out/candidates/<id>.mp4  已下载素材（默认下载）
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pick  # noqa: E402
import tk  # noqa: E402


def clean(url):
    m = re.search(r"tiktok\.com/@[\w.\-]+/video/\d+", url)
    return f"https://www.{m.group(0)}" if m else url.split("?")[0]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("file")
    p.add_argument("--no-download", action="store_true")
    a = p.parse_args()

    urls = [clean(x) for x in Path(a.file).read_text().splitlines() if x.strip().startswith("http")]
    out_dir = tk.OUT / "candidates"
    today = dt.date.today().isoformat()

    rows, links = [], []
    for u in urls:
        try:
            meta = pick.ytdlp_json(u)
        except SystemExit as e:
            print("skip:", u, e)
            continue
        vid = meta.get("id")
        title = (meta.get("title") or "").strip()
        rows.append(dict(url=u, id=vid, title=title,
                         dur=meta.get("duration") or 0,
                         views=meta.get("view_count") or 0,
                         author=meta.get("uploader") or ""))
        links.append(u)
        if not a.no_download:
            tk.fetch(u, out_dir)

    md = [f"# 可用素材 · {today}", "", f"共 {len(rows)} 条", "",
          "| # | 账号 | 播放 | 时长 | 标题 | 链接 |", "| --- | --- | --- | --- | --- | --- |"]
    for i, r in enumerate(rows, 1):
        md.append(f"| {i} | @{r['author']} | {r['views']:,} | {r['dur']}s | {r['title'][:50]} | {r['url']} |")
    md += ["", "## 纯链接（复制这段发群）", "```"] + links + ["```"]

    tk.OUT.mkdir(exist_ok=True)
    (tk.OUT / f"links-{today}.txt").write_text("\n".join(links) + "\n", encoding="utf-8")
    (tk.OUT / f"deliver-{today}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    print(f"\n链接清单：{tk.OUT}/links-{today}.txt")
    if not a.no_download:
        print(f"素材目录：{out_dir}")


if __name__ == "__main__":
    main()
