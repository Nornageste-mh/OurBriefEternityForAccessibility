#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线按键探针 —— 用**游戏自带的运行时 Python**直接验证 Ren'Py 的 keymap 机制。

为什么要它（这是本补丁最贵的一次返工）：
    补丁的 F5 重读键一连几个版本「装了但永远不响」，而取证文件里
    **一行痕迹都没有** —— 因为处理函数在第一行就早退了。
    根因是引擎的调用约定：

        renpy/display/behavior.py:550-565   Keymap.event
            for name, action in self.keymap.items():
                if map_event(ev, name):
                    rv = run(action)            # ← 无参数
        renpy/display/behavior.py:384-411   run
            return action(*args, **kwargs)      # ← args 空

    这类「约定型」错误靠读注释是防不住的（注释写错了就一起错），
    所以本探针把它变成**可重复执行的事实核对**：
    每次改按键相关代码后跑一遍，比让读屏用户重开一次游戏便宜得多。

本探针不启动游戏、不加载剧本、不开窗口，也不打印任何剧本原文。

用法：
    <游戏>\\lib\\py3-windows-x86_64\\python.exe tools\\probe_keymap.py
    （或设置 ETERNITY_GAME_DIR 后用自己的 python 跑；
      注意必须用**游戏自带的** python —— pygame 在里面）
"""

from __future__ import annotations

import os
import sys

GAME_DIR = os.environ.get(
    "ETERNITY_GAME_DIR", r"F:\Steam\steamapps\common\永恒与星辰与日常")
sys.path.insert(0, GAME_DIR)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FAIL = 0


def check(label, ok, detail=""):
    global FAIL
    mark = "OK  " if ok else "✗✗✗ "
    if not ok:
        FAIL += 1
    print(f"  {mark}{label}" + (f"   {detail}" if detail else ""))
    return ok


print("=" * 72)
print("离线按键探针 —— Ren'Py keymap 机制核对")
print("=" * 72)
print(f"python   : {sys.version.split()[0]}")
print(f"game dir : {GAME_DIR}")

import renpy  # noqa: E402

print(f"renpy    : {renpy.version_tuple}  ({renpy.version})")

# ---------------------------------------------------------------- 导入稳定化
# ⚠ 本作**没有**独立的 pygame 包：Ren'Py 8 用自带 shim `renpy.pygame`
#   （`behavior.py:32` 就是 `import renpy.pygame as pygame`），
#   直接 `import pygame` 会 ModuleNotFoundError —— 踩过。
# ⚠ 也不能直接 `import renpy.pygame`：`renpy/__init__.py` 的导入块是有
#   **严格先后依赖**的，少跑一步就撞
#   `AttributeError("module 'renpy' has no attribute 'object'")` —— 也踩过。
#   所以复用引擎自己那份有序导入清单，反复迭代到稳定为止。
import re  # noqa: E402

INIT_PY = os.path.join(GAME_DIR, "renpy", "__init__.py")
_src = open(INIT_PY, encoding="utf-8").read()
seeds = list(dict.fromkeys(re.findall(
    r"^\s+import ((?:renpy\.[A-Za-z_][\w.]*)|six|pygame)\s*$", _src, re.M)))
pending = list(seeds)
_rounds = 0
while pending and _rounds < 12:
    _rounds += 1
    still = []
    for name in pending:
        try:
            __import__(name)
        except Exception:
            still.append(name)
    if len(still) == len(pending):
        break
    pending = still
print(f"导入稳定化: {len(seeds)} 个种子, {_rounds} 轮, 剩 {len(pending)} 个未成功")

import renpy.pygame as pygame  # noqa: E402

import renpy.display.behavior as B  # noqa: E402
import renpy.display.core as C  # noqa: E402

KEYDOWN = pygame.KEYDOWN
KC = pygame.constants

print(f"pygame   : renpy.pygame shim (KEYDOWN={KEYDOWN})")
print()


class Ev(object):
    """最小按键事件替身。

    刻意**不**用 pygame 的 Event 类型：`map_event` 只看
    `type / key / unicode / mod / repeat` 五个属性
    （`compile_event` 拼出来的表达式就读这几个），
    用替身既够用，也不受 pygame 事件 API 变化影响。
    """

    def __init__(self, key, unicode="", mod=0, repeat=False):
        self.type = KEYDOWN
        self.key = key
        self.unicode = unicode
        self.mod = mod
        self.repeat = repeat

# ══════════════════════════════════════════════════════════════════
# 1) 引擎的调用约定：`run(action)` 到底传了几个参数？
# ══════════════════════════════════════════════════════════════════
print("[1] 调用约定：`run(action)` 传给 action 的参数个数")
seen = []


def _spy(*args, **kwargs):
    seen.append((args, kwargs))


B.run(_spy)
check("B.run(fn) 调用 fn 时**一个参数都不传**", seen and seen[0] == ((), {}),
      f"实收 args={seen[0][0] if seen else None} kwargs={seen[0][1] if seen else None}")

src = ""
try:
    import inspect
    src = inspect.getsource(B.Keymap.event)
except Exception as e:
    print(f"  ⚠ 取不到 Keymap.event 源码: {type(e).__name__}")

if src:
    has_noarg = "run(action)" in src.replace(" ", "").replace("run( action )", "run(action)")
    check("Keymap.event 里写的是 `run(action)`（无参数）", has_noarg)
    print("       —— 结论：**进 Keymap 的处理函数必须是无参可调用对象**。")
    print("          写成 `def on_key(self, ev)` 并读 ev 的，等于该键永久失效。")
print()

# ══════════════════════════════════════════════════════════════════
# 2) compile_event / map_event：键名能不能被引擎解释
# ══════════════════════════════════════════════════════════════════
print("[2] 键名解析（`compile_event`，`init_keymap()` 就是靠它）")
old_dev = renpy.config.developer
renpy.config.developer = True          # 让非法名字**抛异常**而不是静默变 (False)

GOOD = ["K_F5", "K_F9", "K_F6", "1", "9", "K_KP1", "ctrl_shift_K_r", "alt_K_RETURN"]
BAD = ["K_KP_UP", "K_KP_HOME", "K_FOO", "not_a_key"]

for spec in GOOD:
    try:
        B.compile_event(spec, True)
        check(f"合法键名被接受: {spec!r}", True)
    except Exception as e:
        check(f"合法键名被接受: {spec!r}", False, f"{type(e).__name__}: {e}")

for spec in BAD:
    try:
        B.compile_event(spec, True)
        check(f"非法键名被拒绝: {spec!r}", False, "居然解析通过了 —— 过滤器会漏掉它")
    except Exception:
        check(f"非法键名被拒绝: {spec!r}", True)

renpy.config.developer = old_dev
print()

# ══════════════════════════════════════════════════════════════════
# 3) 端到端：注册一个补丁键名，再造一个真事件去匹配
# ══════════════════════════════════════════════════════════════════
print("[3] 端到端：注册 A11yReread = ['K_F5'] 后，F5 事件能不能命中")
renpy.config.keymap["A11yReread"] = ["K_F5"]
renpy.config.keymap["A11yChoiceDigit1"] = ["1", "K_KP1"]
B.event_cache.pop("A11yReread", None)
B.event_cache.pop("A11yChoiceDigit1", None)
B.init_keymap()


def keydown(key, unicode="", mod=0, repeat=False):
    return Ev(key, unicode=unicode, mod=mod, repeat=repeat)


f5 = keydown(KC.K_F5)
ev_f9 = keydown(KC.K_F9)
ev_1 = keydown(KC.K_1, unicode="1")
ev_shift_f5 = keydown(KC.K_F5, mod=KC.KMOD_SHIFT)

check("F5 命中 A11yReread", B.map_event(f5, "A11yReread"))
check("F9 不命中 A11yReread", not B.map_event(ev_f9, "A11yReread"))
# ⚠ 实测事实：**普通键名不排除 Shift**。
#   `compile_event` 只在键名里**明写** `shift` / `noshift` 时才管 Shift
#   （behavior.py:162-167），`K_F5` 因此对「F5」和「Shift+F5」都成立。
#   这不算问题（多一个组合键也能重读），但要写下来 ——
#   免得以后看到「Shift+F5 也重读」又当成 bug 查一轮。
check("Shift+F5 命中也算命中（普通键名不管 Shift，实查如此）",
      B.map_event(ev_shift_f5, "A11yReread"))
check("显式 noshift_K_F5 才排除 Shift",
      not B.map_event(ev_shift_f5, ["noshift_K_F5"]) and B.map_event(f5, ["noshift_K_F5"]))
check("数字 1 命中 A11yChoiceDigit1", B.map_event(ev_1, "A11yChoiceDigit1"))
check("F5 不命中 A11yChoiceDigit1", not B.map_event(f5, "A11yChoiceDigit1"))
print()

# ══════════════════════════════════════════════════════════════════
# 4) 真造一个 Keymap，走一遍 `Keymap.event`
# ══════════════════════════════════════════════════════════════════
print("[4] 真 Keymap 事件分发（用补丁实际导入的那个类）")


class _DummyStyle(object):
    """只为绕开「离线环境下样式系统未初始化」。

    事件分发逻辑本身**完全走引擎原版** —— 这里换掉的只是
    `self.style.activate_sound` 这一个读取（探针里不播声音）。
    """

    activate_sound = None


class _ProbeKeymap(B.Keymap):
    """绕开「离线环境下样式系统未初始化」：`Keymap.event` 里唯一碰样式的地方
    就是 `self.style.activate_sound`。`Displayable.__init__` 会写 `self.style = ...`，
    所以还必须带一个 setter（第一版忘了，直接 `AttributeError: no setter`）。"""

    @property
    def style(self):
        return _DummyStyle()

    @style.setter
    def style(self, value):
        pass


try:
    import renpy.exports as _ex
    _ex.play = lambda *a, **k: None      # 探针不播按键音
except Exception:
    pass


def dispatch(km, ev):
    """跑一次 `Keymap.event`；命中时引擎抛 `IgnoreEvent` 是**正常**的。"""
    try:
        km.event(ev, 0, 0, 0)
    except Exception as e:
        if isinstance(e, C.IgnoreEvent):
            return "captured"
        raise
    return "passed"


try:
    hits = []
    km = _ProbeKeymap(A11yReread=[lambda: hits.append("hit")])
    r = dispatch(km, f5)
    check("无参处理函数被 Keymap 调用（补丁现在的写法）",
          hits == ["hit"] and r == "captured", f"hits={hits} r={r}")
    check("非绑定的键不会触发", (dispatch(_ProbeKeymap(
        A11yReread=[lambda: hits.append("bad")]), ev_f9), hits == ["hit"])[1])

    # 反向证明：旧写法收到的就是 None —— 于是 `ev is None -> return` 必然早退
    got = []
    km2 = _ProbeKeymap(A11yReread=[lambda ev=None: got.append(ev)])
    dispatch(km2, f5)
    check("依赖 ev 的处理函数收到的 ev 是 None（旧写法必然早退）",
          got == [None], f"got={got}")
    print("       —— 这就是「重读无效」的机制：旧写法第一行就 return 了。")

    # 再反向一层：把参数写成**必填**位置参数，会当场 TypeError ——
    # 说明这类错误不会「静默」，而是会在事件分发里炸出来。
    try:
        dispatch(_ProbeKeymap(A11yReread=[lambda ev: None]), f5)
        check("必填位置参数的处理函数会当场报错（不会静默）", False,
              "居然没报错 —— 与引擎源码不符，需要重新核对")
    except TypeError as e:
        check("必填位置参数的处理函数会当场 TypeError（不会静默）", True, str(e)[:70])
except Exception as e:
    print(f"  ⚠ 第 4 步跑不动（{type(e).__name__}: {e}）—— 跳过；"
          f"第 1-3 步已足够定论。")
print()

print("=" * 72)
print(f"结论：{'全部通过' if FAIL == 0 else str(FAIL) + ' 项不通过'}")
print("=" * 72)
raise SystemExit(0 if FAIL == 0 else 1)
