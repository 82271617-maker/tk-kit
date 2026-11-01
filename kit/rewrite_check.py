#!/usr/bin/env python3
"""rewrite_check — 校验文案三步的硬规则：行数一致 / 无标点 / 缩减≥30%

用法：python rewrite_check.py <03-文案/<id> 目录>
退出码 0 = 全过；1 = 有不合格项
"""
import sys, re, pathlib

PUNCT = re.compile(r"[，。！？、：；""''（）()…—,.!?;:]")

def lines(p):
    return [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

def main():
    if len(sys.argv) < 2:
        print("用法: rewrite_check.py <目录>"); return 2
    d = pathlib.Path(sys.argv[1])
    f1, f2, f3 = d/"01-英文稿.txt", d/"02-中文稿.txt", d/"03-调整稿.txt"
    miss = [f.name for f in (f1, f2, f3) if not f.exists()]
    if miss:
        print(f"缺文件: {', '.join(miss)}"); return 1
    L1, L2, L3 = lines(f1), lines(f2), lines(f3)
    ok = True
    print(f"行数  01={len(L1)}  02={len(L2)}  03={len(L3)}")
    if not (len(L1) == len(L2) == len(L3)):
        print("✗ 行数不一致（时间轴会错位）"); ok = False
    else:
        print("✓ 行数一致")
    for name, L in (("02", L2), ("03", L3)):
        bad = [(i+1, l) for i, l in enumerate(L) if PUNCT.search(l)]
        if bad:
            print(f"✗ {name} 混入标点: {bad[:3]}"); ok = False
        else:
            print(f"✓ {name} 无标点")
    c2, c3 = sum(map(len, L2)), sum(map(len, L3))
    cut = (1 - c3/c2) * 100 if c2 else 0
    print(f"字数  02={c2}  03={c3}  缩减 {cut:.1f}%")
    if cut < 30:
        print("✗ 缩减不足 30%"); ok = False
    else:
        print("✓ 缩减达标")
    # 发布文案（可选，存在就校验）
    cap = d/"发布文案.txt"
    if cap.exists():
        cl = [x for x in cap.read_text(encoding="utf-8").splitlines() if x.strip()]
        if len(cl) < 3:
            print("✗ 发布文案不足 3 行（标题/正文/标签）"); ok = False
        else:
            tags = re.findall(r"#[^\s#]+", cl[2])
            need = {"#速報", "#news"}
            miss_tag = need - set(tags)
            print(f"标题 {len(cl[0])} 字 | 正文 {len(cl[1])} 字 | 标签 {len(tags)} 个")
            if len(tags) > 5:
                print(f"✗ 标签超过 5 个: {tags}"); ok = False
            elif miss_tag:
                print(f"✗ 缺必需标签: {miss_tag}"); ok = False
            else:
                print("✓ 标签 ≤5 且含 #速報 #news")
    else:
        print("· 发布文案.txt 未生成（可选）")
    print("结论:", "全部通过" if ok else "不合格")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
