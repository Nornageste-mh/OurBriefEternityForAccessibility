#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""播报时间窗探针 —— 抽出 `_announce` 的真源码来跑。

为什么要有它：
    「按方向键朗读抽搐」先后有**两个**成因，第二个是位置键挡不住的：

        [alt] 播报: 开始游戏      ← 0.5 秒内 11 次，每次都真的调了 NVDA
        [alt] 播报: 开始游戏
        （…×11，间隔 30~80 ms）

    主菜单有动画 ⇒ 引擎每帧重建焦点表、坐标跟着动 ⇒ 按「位置键」判断
    「还是不是同一个控件」在动画界面上**恒为假**。唯一稳定的是文案本身，
    所以最后一道去重必须按文案 + 时间窗（`SAY_DEDUP_WINDOW`）。

    ⚠ 上一版的教训是**只验了一个方向**：只验「不该重复的还重不重复」，
    于是把「去重过头 = 全哑」当成了修好。本探针**两个方向都验**：

      方向一（防抽搐）：同一句在窗口内反复进来 -> **只念一次**；
      方向二（防静默）：不同句、以及窗口之外的同句 -> **必须照念**。

用法：
    python tools/probe_say_window.py
"""

from __future__ import annotations

import os
import re
import sys
import time as _time

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


def extract_method(path, name):
    lines = open(path, encoding="utf-8").read().split("\n")
    hits = [i for i, l in enumerate(lines)
            if re.match(r"^\s*def %s\(" % re.escape(name), l)]
    if not hits:
        raise SystemExit(f"在 {path} 里找不到 def {name}(")
    start = hits[0]
    indent = len(lines[start]) - len(lines[start].lstrip(" "))
    body = [lines[start]]
    for l in lines[start + 1:]:
        if l.strip() and (len(l) - len(l.lstrip(" "))) <= indent:
            break
        body.append(l)
    return "\n".join(l[indent:] if l.startswith(" " * indent) else l for l in body)


def extract_class_attr(path, name):
    """抽出类属性 `NAME = <字面量>`（例如 `SAY_DEDUP_WINDOW = 0.9`）。"""
    m = re.search(r"^\s*%s\s*=\s*([0-9.]+)\s*$" % re.escape(name),
                  open(path, encoding="utf-8").read(), re.M)
    if not m:
        raise SystemExit(f"在 {path} 里找不到 {name}")
    return float(m.group(1))


print("=" * 72)
print("播报时间窗探针 —— `_announce` 的真源码（双向验证）")
print("=" * 72)

src = extract_method(SRC, "_announce")
WINDOW = extract_class_attr(SRC, "SAY_DEDUP_WINDOW")
print(f"抽出 {len(src.splitlines())} 行源码；SAY_DEDUP_WINDOW = {WINDOW}（同源于源码）\n")


class _Repeat(object):
    def __init__(self):
        self.spoken = []

    def say(self, text, interrupt=None, record=True):
        self.spoken.append(text)
        return True


class _Rpy(object):
    last_sink_text = None


class _Host(object):
    def __init__(self):
        self.repeat = _Repeat()
        self.rpy = _Rpy()
        self.log = []

    def said(self, s):
        self.log.append(s)


class Harness(object):
    """只挂被测方法；`_where` 用**可控的**位置，`_focus_key` 用真源码。"""

    _NO_WHERE = object()
    SAY_DEDUP_WINDOW = WINDOW

    def __init__(self, host):
        self.host = host
        self._said_last = (None, None)
        self._said_text = None
        self._said_at = 0.0
        self._positions = {}      # name -> (screen, pos)

    def _where(self, w):
        return self._positions.get(w, self._NO_WHERE)

    def _focus_key(self, w, text):
        where = self._where(w)
        if where is self._NO_WHERE:
            return (text, "__nopos__", id(w))
        return (text, where[0], where[1])


ns = {"A11yHost": None, "time": _time}
host = _Host()
ns["A11yHost"] = host
exec(compile(src, "<_announce>", "exec"), ns)
Harness._announce = ns["_announce"]

h = Harness(host)
h._positions["a"] = ("main_menu", (100, 200))
h._positions["b"] = ("main_menu", (100, 300))

# ── 方向一：同一句在窗口内反复进来，只念一次 ─────────────────────────
print("[1] 防抽搐：同一句在窗口内反复进来 -> 只念一次")
for _ in range(11):
    h._announce("a", "开始游戏")
spoke = list(host.repeat.spoken)
check("11 次调用只出声 1 次", len(spoke) == 1, f"实得 {len(spoke)} 次：{spoke}")

# ── 关键：位置变了也必须只念一次（动画界面就是这样）──────────────────
print("\n[2] 位置变了、文案没变 -> 仍然只念一次（动画界面的真实形状）")
host.repeat.spoken.clear()
h2 = Harness(host)
for i in range(11):
    h2._positions["w%d" % i] = ("main_menu", (100, 200 + i))   # 每帧坐标都动
    h2._announce("w%d" % i, "开始游戏")
check("位置每帧都变、仍是 1 次", len(host.repeat.spoken) == 1,
      f"实得 {len(host.repeat.spoken)} 次")

# ── 方向二：不同文案必须照念（防静默）──────────────────────────────
print("\n[3] 防静默：不同文案必须照念（导航靠这条）")
host.repeat.spoken.clear()
h3 = Harness(host)
for i, txt in enumerate(["开始游戏", "继续游戏", "读取游戏", "系统设置", "特殊模式", "退出游戏"]):
    h3._positions["m%d" % i] = ("main_menu", (100, 200 + i * 50))
    h3._announce("m%d" % i, txt)
check("六项全部出声", len(host.repeat.spoken) == 6,
      f"实得 {len(host.repeat.spoken)} 次：{host.repeat.spoken}")

# ── 方向二（续）：窗口之外的同句必须再念（玩家又走回来了）────────────
print("\n[4] 防静默：窗口之外再回到同一项 -> 必须再念")
host.repeat.spoken.clear()
h4 = Harness(host)
h4._positions["x"] = ("main_menu", (100, 200))
h4._announce("x", "开始游戏")
h4._said_at -= (WINDOW + 0.1)          # 让窗口过期（等价于真的过了这么久）
h4._announce("x", "开始游戏")
check("窗口外再念一次", len(host.repeat.spoken) == 2,
      f"实得 {len(host.repeat.spoken)} 次")

# ── 方向二（续）：引擎已经念过的那条本层让位，但**不刷新窗口** ────────
print("\n[5] 让位的那条不得占用窗口（否则会把后面真该念的挤掉）")
host.repeat.spoken.clear()
h5 = Harness(host)
h5._positions["y"] = ("main_menu", (100, 200))
host.rpy.last_sink_text = "开始游戏"          # 模拟引擎刚报过这一条
h5._announce("y", "开始游戏")
check("让位：不出声", len(host.repeat.spoken) == 0)
host.rpy.last_sink_text = None               # 引擎这条已经过去
h5._announce("y", "开始游戏")
check("随后同句仍能念出来（窗口未被让位占用）", len(host.repeat.spoken) == 1,
      f"实得 {len(host.repeat.spoken)} 次")

print()
print("=" * 72)
print(f"结论：{'全部通过' if FAIL == 0 else str(FAIL) + ' 项不通过'}")
print("=" * 72)
raise SystemExit(0 if FAIL == 0 else 1)
