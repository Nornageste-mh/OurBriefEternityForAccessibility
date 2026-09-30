#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""序号逻辑探针 —— 直接抽出 `.rpy` 里的 `_A11yOrdinals` 源码来跑。

为什么要有它：
    这段逻辑决定「**这是第几个存档位 / 第几行曲目 / 立绘第几行**」。
    算错了不是「少报」，而是**报错位号** —— 玩家听着「存档位 3」按下去，
    覆盖掉的却是第 5 位。这是本补丁里后果最重的一类错误。

    所以它不能只靠「我看了一遍觉得对」：
      · 探针把 `a11y_platform/08_uialt.rpy` 里那段**真源码**抽出来 exec，
        测的是**将要上机运行的那段代码**，不是它的复制品；
      · 喂进去的是**合成的屏幕布局**（网格、列表、多列、乱序输入），
        覆盖所有真实界面的形状。

用法：
    python tools/probe_ordinal.py
"""

from __future__ import annotations

import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "mod", "game", "a11y_platform", "08_uialt.rpy")

FAIL = 0


def check(label, ok, detail=""):
    global FAIL
    if not ok:
        FAIL += 1
    print(f"  {'OK  ' if ok else '✗✗✗ '}{label}" + (f"   {detail}" if detail else ""))


def extract_func(path, name):
    """从 .rpy 里抽出 `def name(...)` 的整段源码。

    判据：从 `def name(` 那一行开始，到**同缩进的下一个 def / class / init** 为止。
    这样抽出来的是引擎将要执行的那段文本本身。
    """
    lines = open(path, encoding="utf-8").read().split("\n")
    start = None
    for i, l in enumerate(lines):
        if re.match(r"^\s*def %s\(" % re.escape(name), l):
            start = i
            break
    if start is None:
        raise SystemExit(f"在 {path} 里找不到 def {name}(")
    indent = len(lines[start]) - len(lines[start].lstrip(" "))
    body = [lines[start]]
    for l in lines[start + 1:]:
        if l.strip() and (len(l) - len(l.lstrip(" "))) <= indent:
            break
        body.append(l)
    return "\n".join(body)


print("=" * 72)
print("序号逻辑探针 —— `_A11yOrdinals` 的真源码 + 合成布局")
print("=" * 72)

src = extract_func(SRC, "_A11yOrdinals")
print(f"抽出 {len(src.splitlines())} 行源码（{os.path.relpath(SRC, REPO)}）\n")

# 抽出来的是 4 空格缩进的块内代码：去掉一级缩进后 exec
dedented = "\n".join(l[4:] if l.startswith("    ") else l for l in src.split("\n"))
ns = {}
exec(compile(dedented, "<A11yOrdinals>", "exec"), ns)
ordinals = ns["_A11yOrdinals"]

# ── 1) 存读档的 4×3 网格 ────────────────────────────────────────────
print("[1] 存读档 12 个格子（grid 4 3，按行填）")
# 真实几何：x = 208 + col*549, y = 202 + row*340；这里**故意用乱序输入**，
# 而且刻意把每个按钮的 y 加 23（模拟「按钮比格子矮」那种偏移），
# 证明序号只依赖先后、不依赖数值。
entries = []
for r in range(3):
    for c in range(4):
        wid = f"slot{r * 4 + c}"
        entries.append(("file_slots", "empty.png", 208 + c * 549, 202 + r * 340 + 23, wid))
import random
shuffled = entries[:]
random.Random(7).shuffle(shuffled)
ord_map = ordinals(shuffled)
got = {wid: ord_map[wid][0] for wid in (e[4] for e in entries)}
want = {f"slot{i}": i for i in range(12)}
check("12 个格子按行排出的名次 = 存档位号-1", got == want,
      "" if got == want else f"实得 {got}")
check("总数正确", all(ord_map[f"slot{i}"][1] == 12 for i in range(12)))

# ── 2) 音声曲目列表（单列 5 行）───────────────────────────────────────
print("\n[2] 音声曲目列表（vbox 单列 5 行）")
rows = [("music", "list.png", 141, 225 + i * 199, f"row{i}") for i in range(5)]
m = ordinals(rows[::-1])
check("5 行按 y 排出的名次 = 行号", [m[f"row{i}"][0] for i in range(5)] == [0, 1, 2, 3, 4])

# ── 3) 立绘六行 × 两个方向（两张不同的图）─────────────────────────────
print("\n[3] 立绘 6 行 × 左右两个小三角（两张图各自成组）")
st = []
for i in range(6):
    y = 726 + i * 82
    st.append(("stand_mode", "left.png", 0, y, f"L{i}"))
    st.append(("stand_mode", "right.png", 95, y, f"R{i}"))
m = ordinals(st)
check("左三角 6 个 → 名次 = 行号", [m[f"L{i}"][0] for i in range(6)] == list(range(6)))
check("右三角 6 个 → 名次 = 行号", [m[f"R{i}"][0] for i in range(6)] == list(range(6)))
check("两组互不干扰（总数各 6）",
      all(m[f"L{i}"][1] == 6 and m[f"R{i}"][1] == 6 for i in range(6)))

# ── 4) 同一行里横向排列（页签）→ 按 x 排 ─────────────────────────────
print("\n[4] 同一行的横向页签（y 相同，按 x 排）")
tabs = [("gallery", "page.png", 246 + i * 60, 1267, f"t{i}") for i in range(5)]
m = ordinals(tabs[::-1])
check("y 相同时按 x 定先后", [m[f"t{i}"][0] for i in range(5)] == [0, 1, 2, 3, 4])

# ── 5) 不同界面 / 不同图互不影响 ─────────────────────────────────────
print("\n[5] 界面与图各自分组")
mix = [
    ("a", "x.png", 0, 0, "a1"), ("a", "x.png", 0, 10, "a2"),
    ("b", "x.png", 0, 0, "b1"),
    ("a", "y.png", 0, 0, "a3"),
]
m = ordinals(mix)
check("同名图但不同界面 → 分开计数", m["a1"] == (0, 2) and m["a2"] == (1, 2) and m["b1"] == (0, 1))
check("不同图分开计数", m["a3"] == (0, 1))

# ── 6) 缺坐标 / 缺键 ⇒ 跳过（宁可没有，也不要瞎排）────────────────────
print("\n[6] 缺坐标或缺键时跳过")
m = ordinals([
    ("a", "x.png", None, 0, "n1"),
    ("a", "x.png", 0, None, "n2"),
    ("a", None, 0, 0, "n3"),
    ("a", "x.png", 0, 0, "ok"),
])
check("缺坐标/缺键的项不出现在结果里",
      set(m.keys()) == {"ok"} and m["ok"] == (0, 1), f"实得 {m}")

print()
print("=" * 72)
print(f"结论：{'全部通过' if FAIL == 0 else str(FAIL) + ' 项不通过'}")
print("=" * 72)
raise SystemExit(0 if FAIL == 0 else 1)
