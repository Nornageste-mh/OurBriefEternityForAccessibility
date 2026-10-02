#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""播报去重键探针 —— 抽出 `_focus_key` + `_where` 的真源码来跑。

为什么要有它：
    0.0.1.1 那一版把「整片界面不朗读」写成了回归，根因**不是**某个函数算错了，
    而是**两种完全不同的情况拿到了同一个返回值**：

        · 「这个控件的位置我查不到」
        · 「这个控件的位置就是 (None, None)」

    两者一旦相同，所有查不到位置的控件**共用一个去重键** ⇒ 第一个念过之后，
    其余的都被自己的去重判据吞掉 ⇒ **焦点行在日志里刷，一行播报都没有**。
    实机日志原样是这个形状：

        [alt] 焦点=ImageButton 文本='开始游戏' 引擎队列=0
        [alt] 焦点=ImageButton 文本='继续游戏' 引擎队列=0
        [alt] 焦点=ImageButton 文本='读取游戏' 引擎队列=0
        （没有任何 [alt] 播报: 行，也没有任何 NVDA 调用）

    这类错误**在静默测试里长得像正常**：没有异常、没有报错、断言全过，
    只是不出声。所以只能靠一条专门的判据钉住它。

本探针验三件事：
    [1] `_where` 查不到位置时返回**哨兵**，而不是 `(None, None)`；
    [2] 两个「都查不到位置」的不同控件，去重键**必须不相等**
        （这就是那次事故的反面）；
    [3] 位置不同的控件键不相等、同一个控件键相等（不能因为修 [2] 就不去重了）。

用法：
    python tools/probe_focus_key.py
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


def extract_method(path, name):
    """抽出类方法 `def name(` 的整段源码（缩进去掉一级）。"""
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
    ded = "\n".join(l[indent:] if l.startswith(" " * indent) else l for l in body)
    return ded


print("=" * 72)
print("播报去重键探针 —— `_where` / `_focus_key` 的真源码")
print("=" * 72)

where_src = extract_method(SRC, "_where")
key_src = extract_method(SRC, "_focus_key")
print(f"抽出 `_where` {len(where_src.splitlines())} 行 + "
      f"`_focus_key` {len(key_src.splitlines())} 行（{os.path.relpath(SRC, REPO)}）\n")


class Probe(object):
    """把两个被测方法挂上来，其余一律用替身（不复制被测实现）。"""

    #: 与源码里同名同义：`_scan` 挂不上的控件，`_where` 要返回它
    _NO_WHERE = object()

    def __init__(self, loc=None, focus_list=None):
        self._loc = loc if loc is not None else {}
        self._focus_list = focus_list if focus_list is not None else []

    def _fake_focus_module(self):
        outer = self

        class _F(object):
            @property
            def focus_list(self):
                return outer._focus_list
        return _F()


ns = {"__name__": "probe", "renpy": None}
# `_where` 里 `import renpy.display.focus as _f` 需要一个可用替身：
# 用一个假的模块对象塞进 sys.modules，避免真的去导入引擎（真机才有 pygame）。
import types  # noqa: E402

probe = Probe()
fake_mod = types.ModuleType("renpy.display.focus")
fake_mod.focus_list = []


class _Renpy(types.ModuleType):
    pass


renpy_mod = _Renpy("renpy")
display_mod = _Renpy("renpy.display")
display_mod.focus = fake_mod
renpy_mod.display = display_mod
sys.modules["renpy"] = renpy_mod
sys.modules["renpy.display"] = display_mod
sys.modules["renpy.display.focus"] = fake_mod

exec(compile(where_src, "<_where>", "exec"), globals(), ns)
exec(compile(key_src, "<_focus_key>", "exec"), globals(), ns)
Probe._where = ns["_where"]
Probe._focus_key = ns["_focus_key"]


class Widget(object):
    """最简控件替身：可以随便挂属性（真机里引擎的 Displayable 也是普通对象）。"""

    def __init__(self, name, where=None, ordinal=None):
        self.name = name
        if where is not None:
            self._a11y_where = (lambda s=where[0], p=where[1]: (s, p))
        if ordinal is not None:
            self._a11y_ord = ordinal


p = Probe()

# ── 1) 查不到位置 -> 哨兵，不是 (None, None) ─────────────────────────
print("[1] 查不到位置时必须返回哨兵（不能与「位置就是 None」撞车）")
lonely = Widget("陌生控件")
got = p._where(lonely)
check("返回哨兵 _NO_WHERE", got is Probe._NO_WHERE, f"实得 {got!r}")

# ── 2) 两个都查不到位置的控件，去重键必须不相等 ──────────────────────
print("\n[2] ★ 事故的反面：都查不到位置的两个控件，键必须不相等")
a = Widget("控件A")
b = Widget("控件B")
ka, kb = p._focus_key(a, "控件A"), p._focus_key(b, "控件B")
check("A 与 B 的键不相等（否则 B 会被去重吞掉 ⇒ 静默）", ka != kb,
      f"ka={ka!r} kb={kb!r}")
check("同一文本、同一控件 -> 键相等（仍要能去重）",
      p._focus_key(a, "控件A") == ka)

# ── 3) 位置存在时的行为 ─────────────────────────────────────────────
print("\n[3] 位置正常时：位置不同 -> 键不同；位置相同 + 文本相同 -> 键相同")
w1 = Widget("一号", where=("main_menu", (100, 200)))
w2 = Widget("二号", where=("main_menu", (100, 300)))
w3 = Widget("三号", where=("main_menu", (100, 200)))
k1, k2, k3 = (p._focus_key(w, t) for w, t in ((w1, "一号"), (w2, "二号"), (w3, "三号")))
check("位置不同 -> 键不同", k1 != k2)
check("位置相同但文本不同 -> 键不同（不同控件不会被误去重）", k1 != k3)
check("键的内容就是 (文本, 界面名, 坐标)", k1 == ("一号", "main_menu", (100, 200)),
      f"实得 {k1!r}")

# ── 4) ① 现读焦点表那一级真的会生效 ─────────────────────────────────
print("\n[4] 焦点表现读（不依赖任何缓存）")


class _Focus(object):
    def __init__(self, widget, x, y, screen_name):
        self.widget = widget
        self.x = x
        self.y = y
        self.screen = type("S", (), {"screen_name": (screen_name, "tag")})()


fresh = Widget("刚建出来的控件（_scan 还没扫到它）")   # 没有任何缓存属性
fake_mod.focus_list = [_Focus(fresh, 533, 1002, "music")]
got = p._where(fresh)
check("现读焦点表拿到了坐标", got == ("music", (533, 1002)), f"实得 {got!r}")
check("此时不再返回哨兵", got is not Probe._NO_WHERE)
fake_mod.focus_list = []

print()
print("=" * 72)
print(f"结论：{'全部通过' if FAIL == 0 else str(FAIL) + ' 项不通过'}")
print("=" * 72)
raise SystemExit(0 if FAIL == 0 else 1)
