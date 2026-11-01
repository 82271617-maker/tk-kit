#!/usr/bin/env python3
"""gate — 翻写流程的门禁检查（不依赖固定文件名）。

读 <目录>/index.json：
  {"01":"转写稿.txt","02":"中文初稿.txt","03":"调整稿.txt","04":"已审核.txt","guard":"03"}
没有 index.json 时退回「目录里最新修改的同类型文件」。

用法：python gate.py <文案目录>
退出码：0 = 可以往下做；1 = 卡住。
"""
import json
import sys
from pathlib import Path

LABEL = {"01": "转写", "02": "初翻", "03": "改写", "04": "人工审核", "05": "日文稿"}


def load(d):
    idx = d / "index.json"
    if idx.exists():
        try:
            return json.loads(idx.read_text(encoding="utf-8")), idx
        except Exception:
            pass
    return {}, idx


def newest(d, exclude):
    files = [p for p in d.glob("*") if p.is_file() and p.name not in exclude
             and p.suffix.lower() in (".txt", ".md", ".srt")]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def main():
    if len(sys.argv) < 2:
        sys.exit("用法: python gate.py <文案目录>")
    d = Path(sys.argv[1])
    if not d.is_dir():
        sys.exit(f"目录不存在: {d}")

    data, idx = load(d)
    print(f"目录: {d}")
    print(f"索引: {idx.relative_to(d) if idx.exists() and idx.exists() else '（无 index.json，按最新文件推断）'}")

    for k in ("01", "02", "03", "04", "05"):
        name = data.get(k)
        p = d / name if name else None
        if p and p.exists():
            print(f"  ✅ {k} {LABEL[k]:6s} → {name}")
        elif p:
            print(f"  ⚠️  {k} {LABEL[k]:6s} → {name}（索引有但文件不存在）")
        else:
            print(f"  ⬜ {k} {LABEL[k]:6s} → 未登记")

    if not (data.get("04") and (d / data["04"]).exists()):
        print("\n🚫 停在 ④ 人工审核")
        print("   下一步：人工检查 03 那份文件，确认后复制一份并在 index.json 登记 \"04\"")
        sys.exit(1)

    print("\n✅ 门禁通过，可以进 ⑤ 日文稿")
    sys.exit(0)


if __name__ == "__main__":
    main()
