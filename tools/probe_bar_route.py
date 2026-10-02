#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""滑杆路由探针 —— 抽出 `_real_text` 的真源码，验证 **Bar 会不会被送去查表**。

为什么要有它（实机事故）：
    滑杆在游戏里念成 `Barbar` / `asmr volumebar`。查下去发现 `_real_text` 的
    第 ③ 级门口写的是

        if isinstance(w, _b.Button):
            txt = self._table_text(w, screen, pos)

    而 `_table_text` 里**本来就有** Bar 分支（`isinstance(w, _b.Bar) -> _bar_text`）
    —— 但 `Bar` 不是 `Button`，整段被跳过，滑杆永远走不到查表，
    直接落到第 ② 级念出引擎拼的 `value.alt` + 「栏」。

    上一版我在 `_bar_text` 里认真修了名字取法，**改的是一个走不到的函数**。
    教训：**「函数改对了」不等于「它会被调用」** —— 门口那道类型判据
    也是被改逻辑的一部分，必须一起验。

本探针只验**路由**（Bar/Button 的文本分别从哪一级来），
`_bar_text` 的取名逻辑不在这里重复（它有自己的输入输出，改坏了这一条也看得出来）。

用法：
    python tools/probe_bar_route.py
"""

from __future__ import annotations

import os
import re
import sys
import types

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


print("=" * 72)
print("滑杆路由探针 —— `_real_text` 的真源码")
print("=" * 72)

src = extract_method(SRC, "_real_text")
print(f"抽出 {len(src.splitlines())} 行源码（{os.path.relpath(SRC, REPO)}）\n")


# ── 假的引擎模块：只提供 `_real_text` 用到的两个类型 ──────────────────
class Bar(object):
    """替身：`_tts_all` 返回引擎那一串（`value.alt` + 名字），用来暴露「走了 ②」。"""

    def _tts_all(self, raw=False):
        return "Barbar"                       # 引擎真实输出（实机日志原文）

    class style:
        alt = None


class Button(object):
    """替身：`_tts_all` 返回空 —— 模拟「没有文字子节点、没有 alt」的图片按钮。

    这类按钮必须落到第 ③ 级查表（补丁的文案表就是为它们准备的）。
    """

    def _tts_all(self, raw=False):
        return ""

    class style:
        alt = None


class TalkativeButton(object):
    """替身：`_tts_all` 有内容 —— 模拟 textbutton 与 preference 按钮。

    引擎/控件自己拼得出文本时**就该用它**（补丁的文档化次序 ② 在 ③ 之前）。
    """

    def _tts_all(self, raw=False):
        return "按钮自己拼的文本"

    class style:
        alt = None


class SayBehavior(object):
    pass


class DismissBehavior(object):
    pass


class Null(object):
    pass


fake_behavior = types.ModuleType("renpy.display.behavior")
fake_behavior.Bar = Bar
fake_behavior.Button = Button
fake_behavior.TalkativeButton = TalkativeButton
fake_behavior.SayBehavior = SayBehavior
fake_behavior.DismissBehavior = DismissBehavior
fake_layout = types.ModuleType("renpy.display.layout")
fake_layout.Null = Null
renpy_mod = types.ModuleType("renpy")
display_mod = types.ModuleType("renpy.display")
renpy_mod.display = display_mod
display_mod.behavior = fake_behavior
display_mod.layout = fake_layout
sys.modules["renpy"] = renpy_mod
sys.modules["renpy.display"] = display_mod
sys.modules["renpy.display.behavior"] = fake_behavior
sys.modules["renpy.display.layout"] = fake_layout


class Harness(object):
    def __init__(self):
        self.bar_calls = []
        self.table_calls = []

    # ---- 被测方法依赖的两处替身（记录「有没有被走到」）----
    def _silent_widget(self, w):
        return False

    def _table_text(self, w, screen, pos):
        self.table_calls.append(type(w).__name__)
        if isinstance(w, Bar):
            return "音声音量 60%"            # 模拟 `_bar_text` 的产出
        return "按钮名"

    def _state_suffix(self, w):
        return ""

    @staticmethod
    def _drop_bare_state(t):
        return (t or "").strip()


ns = {}
exec(compile(src, "<_real_text>", "exec"), ns)
Harness._real_text = ns["_real_text"]

h = Harness()
bar_txt = h._real_text(Bar(), "music", (2062, 1095))
print(f"[1] 滑杆的文本 = {bar_txt!r}")
check("Bar 被送去查表（拿到 `_bar_text` 的名字 + 百分比）",
      bar_txt == "音声音量 60%", f"实得 {bar_txt!r}")
check("走到查表的是 Bar", h.table_calls == ["Bar"], f"实得 {h.table_calls}")

h2 = Harness()
btn_txt = h2._real_text(Button(), "main_menu", (100, 200))
print(f"\n[2] 空 `_tts_all` 的图片按钮 = {btn_txt!r}")
check("落到查表（拿到表里的名字）", btn_txt == "按钮名", f"实得 {btn_txt!r}")
check("走到查表的是 Button", h2.table_calls == ["Button"], f"实得 {h2.table_calls}")

h2b = Harness()
talk = h2b._real_text(TalkativeButton(), "preferences", (403, 279))
print(f"\n[2b] `_tts_all` 有内容的按钮 = {talk!r}")
check("② 仍然优先（textbutton / preference 按钮靠这条）",
      talk == "按钮自己拼的文本", f"实得 {talk!r}")
check("这条**不该**去查表", h2b.table_calls == [], f"实得 {h2b.table_calls}")

print("\n[3] 百分比取法（三条，全部来自实机探针打出来的接口）")
ns2 = {}
pct_src = extract_method(SRC, "_bar_pct")
exec(compile(pct_src, "<_bar_pct>", "exec"), ns2)
_bar_pct = ns2["_bar_pct"]


class _Adj(object):
    def __init__(self, lo, hi, v):
        self.min, self.max, self.value = lo, hi, v


class _PosValue(object):
    """本作 `MyAudioPositionValue`：只有秒数与总长，没有 min/max。"""

    def __init__(self, cur, total):
        self.cur, self.total = cur, total
        self.adjustment = _Adj(None, None, cur)      # 实机：value 是**秒数**

    def get_pos_duration(self):
        return (self.cur, self.total)


class _RangeValue(object):
    """普通范围滑杆：adjustment 带 min/max。"""

    def __init__(self, lo, hi, v):
        self.adjustment = _Adj(lo, hi, v)


class _MixerValue(object):
    """`MixerValue`：`get_volume()` 返回 0~1。"""

    def __init__(self, v):
        self.v = v

    def get_volume(self):
        return self.v


check("播放进度 30/120 秒 -> 25%", _bar_pct(_PosValue(30, 120)) == 25,
      f"实得 {_bar_pct(_PosValue(30, 120))}")
check("总长 0 时不得除零、也不编数值", _bar_pct(_PosValue(5, 0)) is None)
check("范围滑杆 0..1、值 0.6 -> 60%", _bar_pct(_RangeValue(0.0, 1.0, 0.6)) == 60,
      f"实得 {_bar_pct(_RangeValue(0.0, 1.0, 0.6))}")
check("无 min/max 的范围滑杆 -> None（不编）", _bar_pct(_RangeValue(None, None, 5)) is None)
check("音量 0.32 -> 32%", _bar_pct(_MixerValue(0.32)) == 32,
      f"实得 {_bar_pct(_MixerValue(0.32))}")
check("什么都没有的值对象 -> None", _bar_pct(object()) is None)

print("\n[4] 回归：确认「只放 Button」的旧写法会漏掉 Bar")
h3 = Harness()
old_gate = isinstance(Bar(), (Button,))    # 旧写法 = 只判 Button
check("旧写法下 Bar 进不了查表（so 滑杆必落到 ② 的 `Barbar`）",
      old_gate is False and Bar()._tts_all() == "Barbar")

print()
print("=" * 72)
print(f"结论：{'全部通过' if FAIL == 0 else str(FAIL) + ' 项不通过'}")
print("=" * 72)
raise SystemExit(0 if FAIL == 0 else 1)
