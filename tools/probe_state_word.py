#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态词筛子探针 —— 直接抽出 `.rpy` 里的 `_drop_bare_state` 源码来跑。

为什么要有它：
    引擎会在 `Button._tts_all` 的**返回值尾巴上追加**一个状态词
    （`renpy/display/behavior.py:1199-1205`）：

        if self.style.prefix.startswith("selected_") and (self.style.alt == self.style._hover_alt()):
            rv += " selected" if raw else " " + renpy.minstore.__("selected")

    本作一大批图片开关都用 `selected_idle`（音声曲目、存读档页签、设置里的
    单选按钮…），它们的 `style.alt` 又不等于 `_hover_alt()`，于是**整串**就是
    一个 `selected`。那不是控件的名字，是它的状态 —— 读屏用户听到「selected」
    等于什么都没听到。

    实机故障（用户反馈「音声播放界面按方向键朗读抽搐」）的日志原文：

        [alt] 焦点=ImageButton 文本='selected'

    修法是：把这个裸状态词判成「没有名字」，让流程继续走到**查表那一级**
    （那里才有「音声 05 主题曲 永恒星辰下的日常」这种真名字）。

    这段逻辑一旦错，会有两种坏结果，所以必须离线钉住：
      · 筛得太狠  -> 把「跳过没见过的」这种**名字里带状态词**的文本砍坏
                     （引擎 `"跳过没见过的 [text] selected"` 就是这一类）；
      · 筛得不够  -> `selected` 继续当名字念，故障原地复现。

用法：
    python tools/probe_state_word.py
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


def extract_method(path, name, order=0):
    """抽出类方法 `def name(` 的整段源码（`order` 指定取第几个同名方法）。"""
    lines = open(path, encoding="utf-8").read().split("\n")
    hits = [i for i, l in enumerate(lines)
            if re.match(r"^\s*def %s\(" % re.escape(name), l)]
    if not hits:
        raise SystemExit(f"在 {path} 里找不到 def {name}(")
    start = hits[order]
    indent = len(lines[start]) - len(lines[start].lstrip(" "))
    body = [lines[start]]
    for l in lines[start + 1:]:
        if l.strip() and (len(l) - len(l.lstrip(" "))) <= indent:
            break
        body.append(l)
    return "\n".join(body)


def extract_literal(path, name):
    """抽出 `name = {...}` 这类字面量赋值（同样取真源码）。"""
    lines = open(path, encoding="utf-8").read().split("\n")
    for i, l in enumerate(lines):
        if re.match(r"^\s*%s\s*=" % re.escape(name), l):
            indent = len(l) - len(l.lstrip(" "))
            body = [l.strip()]
            for l2 in lines[i + 1:]:
                if l2.strip() and (len(l2) - len(l2.lstrip(" "))) <= indent:
                    break
                body.append(l2.strip() if l2.strip() else l2)
            return "\n".join(body)
    raise SystemExit(f"在 {path} 里找不到 {name} =")


print("=" * 72)
print("状态词筛子探针 —— `_drop_bare_state` 的真源码")
print("=" * 72)

src = extract_method(SRC, "_drop_bare_state")
words = extract_literal(SRC, "_A11Y_BARE_STATE_WORDS")
print(f"抽出 {len(src.splitlines())} 行方法 + 1 行词表（{os.path.relpath(SRC, REPO)}）\n")


class _Probe(object):
    """只把被测方法挂上去 —— 不复制它的实现。"""


ns = {"_A11Y_BARE_STATE_WORDS": eval(words.split("=", 1)[1].strip())}
exec(compile("\n".join(
    l[8:] if l.startswith(" " * 8) else l for l in src.split("\n")
), "<_drop_bare_state>", "exec"), ns)
_Probe._drop_bare_state = staticmethod(ns["_drop_bare_state"])
drop = _Probe._drop_bare_state

print(f"词表来自源码：{ns['_A11Y_BARE_STATE_WORDS']}\n")


def engine_tts_all(base, selected_prefix, alt, hover_alt, raw=True):
    """引擎 `Button._tts_all` 的**判据**（behavior.py:1199-1205）的忠实复刻。

    只复刻那两行判据本身 —— 本探针要验的是「筛子能不能吃掉引擎追加的那截」，
    而不是引擎怎么拼前半段（前半段在真机上由 `_tts_common` 给出）。
    """
    rv = base
    if selected_prefix and (alt == hover_alt):
        rv += " selected" if raw else " selected"
    return rv


# ── 1) 实机那一串：空 alt 的图片开关 ────────────────────────────────
print("[1] 实机原文：`焦点=ImageButton 文本='selected'`")
# `_tts_common` 对**空 alt** 的图片按钮返回空串（引擎行为），所以整串就是追加的那截。
raw = engine_tts_all("", True, "", "", raw=True)
check("引擎确实会拼出裸 'selected'（复刻判据）", raw.strip() == "selected", f"实得 {raw!r}")
check("筛子把它判成空（=没名字，继续查表）", drop(raw) == "", f"实得 {drop(raw)!r}")

# ── 2) 有名字的按钮：状态词在尾巴上 ────────────────────────────────
print("\n[2] 名字 + 状态词（只砍尾巴）")
for base, want in [
    ("暂停或继续播放", "暂停或继续播放"),
    ("音声 05 主题曲 永恒星辰下的日常", "音声 05 主题曲 永恒星辰下的日常"),
    ("跳过没见过的", "跳过没见过的"),
]:
    got = drop(engine_tts_all(base, True, base, None, raw=True))
    check(f"{base!r} -> {want!r}", got == want, f"实得 {got!r}")

# ── 3) 不该被误伤的文本 ────────────────────────────────────────────
print("\n[3] 不能误伤：名字里含状态词、或状态词不是独立词")
for text, want in [
    ("", ""),
    ("   ", ""),
    ("selected files", "selected files"),   # 状态词在**开头**，不是尾巴
    ("selectedness", "selectedness"),       # 只是前缀，不是独立词
    ("我的selected", "我的selected"),        # 前面**没有空白**，不是独立词
    ("确定", "确定"),
    ("未知控件（ImageButton）", "未知控件（ImageButton）"),
]:
    got = drop(text)
    check(f"{text!r} 原样保留", got == want, f"实得 {got!r}")

# ── 4) 中文界面下的同义词 ──────────────────────────────────────────
print("\n[4] 中文界面：同一串被翻译成「选定」")
for t in ("选定", "已选定"):
    check(f"裸 {t!r} 判空", drop(t) == "", f"实得 {drop(t)!r}")
check("「已选定」作为尾巴也被砍",
      drop("全屏 已选定") == "全屏", f"实得 {drop('全屏 已选定')!r}")

# ── 5) 假修复回归：只筛 ① 不够 ─────────────────────────────────────
print("\n[5] 回归：确认「只筛 style.alt」是假修复")
# 模拟旧写法：只在 ① 层筛，② 层原样返回
base = engine_tts_all("", True, "", "", raw=True)
old_style_alt_filtered = ""            # ① 被筛掉
old_level2_return = base               # ② 原样返回 -> 又变回 selected
check("旧写法会把 'selected' 从 ② 带回来（故必须在 ② 也筛）",
      old_level2_return.strip() == "selected" and drop(old_level2_return) == "",
      f"② 原样 {old_level2_return.strip()!r} -> 筛后 {drop(old_level2_return)!r}")

print()
print("=" * 72)
print(f"结论：{'全部通过' if FAIL == 0 else str(FAIL) + ' 项不通过'}")
print("=" * 72)
raise SystemExit(0 if FAIL == 0 else 1)
