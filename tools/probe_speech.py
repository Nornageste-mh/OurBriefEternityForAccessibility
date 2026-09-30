#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""朗读后端调度探针 —— 抽出 `A11ySpeech` 的真源码，用假后端跑一遍。

为什么要有它（一次**说错话**的事故）：
    实机上开屏播报说「没有可用的朗读后端，请确认读屏软件正在运行」——
    而那句话**正是被读屏念出来的**。自相矛盾。

    根因：`set_mode()` 会经 `set_pinned("")` 把 `_active` 清成 None
    （意思是「下次发声重新挑」），`speak()` 确实会重挑，
    而 `backend_name()` 只会照实报「没有」——
    **同一个状态，两个接口的解读不一致**。

    这类 bug 的特点是：只在「先查询、后执行」的调用顺序下暴露，
    而且暴露方式是「说出自相矛盾的话」，非常容易被当成「读屏坏了」。

    所以这里把它钉成一条测试：`set_mode("")` 之后，
    `backend_name()` **必须仍能报出后端**。

用法：
    python tools/probe_speech.py
"""

from __future__ import annotations

import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "mod", "game", "a11y_platform", "01_speech.rpy")

FAIL = 0


def check(label, ok, detail=""):
    global FAIL
    if not ok:
        FAIL += 1
    print(f"  {'OK  ' if ok else '✗✗✗ '}{label}" + (f"   {detail}" if detail else ""))


def extract_block(path, header_re):
    """抽出一段**缩进块**（class/def）的源码文本。

    判据：从匹配到的那一行起，到**缩进回到同级或更少**的下一行为止。
    抽出来的是引擎将要执行的那段文本，不是复制品。
    """
    lines = open(path, encoding="utf-8").read().split("\n")
    start = None
    for i, l in enumerate(lines):
        if re.match(header_re, l):
            start = i
            break
    if start is None:
        raise SystemExit(f"在 {path} 里找不到 {header_re}")
    indent = len(lines[start]) - len(lines[start].lstrip(" "))
    body = [lines[start]]
    for l in lines[start + 1:]:
        if l.strip() and (len(l) - len(l.lstrip(" "))) <= indent:
            break
        body.append(l)
    return "\n".join(body)


class FakeHost(object):
    """`A11yHost` 的替身：只提供日志接口（探针里不写文件，攒起来看）。"""

    def __init__(self):
        self.logs = []

    def log(self, msg):
        self.logs.append(str(msg))

    def log_exc(self, msg):
        self.logs.append("EXC " + str(msg))


class FakeBackend(object):
    def __init__(self, name, ok=True, reason="就绪"):
        self.name = name
        self._ok = ok
        self._why = reason
        self.spoken = []
        self.inited = False

    def init(self):
        self.inited = True

    def available(self):
        return self._ok

    def reason(self):
        return self._why

    def speak(self, text, interrupt=True):
        if not self._ok:
            raise RuntimeError("不可用")
        self.spoken.append((text, interrupt))

    def stop(self):
        pass


print("=" * 72)
print("朗读后端调度探针 —— `A11ySpeech` 真源码 + 假后端")
print("=" * 72)

src = extract_block(SRC, r"^\s*class A11ySpeech\(object\):")
print(f"抽出 {len(src.splitlines())} 行源码（{os.path.relpath(SRC, REPO)}）\n")
dedented = "\n".join(l[4:] if l.startswith("    ") else l for l in src.split("\n"))

host = FakeHost()
ns = {"A11yHost": host}
exec(compile(dedented, "<A11ySpeech>", "exec"), ns)
A11ySpeech = ns["A11ySpeech"]


def new_speech(ok_nvda=True, ok_sapi=True):
    s = A11ySpeech()
    # 跳过 register_builtin（它要 A11yTolkBackend 等真实后端类，探针自带假的）
    s._registered = True
    nvda = FakeBackend("NVDA", ok_nvda)
    sapi = FakeBackend("SAPI(引擎同款)", ok_sapi)
    s.register(nvda)
    s.register(sapi)
    s.init()
    return s, nvda, sapi


# ── 1) 初始化后能报出后端 ─────────────────────────────────────────
print("[1] init() 之后")
s, nvda, sapi = new_speech()
check("backend_name() = NVDA（链首）", s.backend_name() == "NVDA", f"实得 {s.backend_name()!r}")
check("两个后端都被 init 过", nvda.inited and sapi.inited)

# ── 2) ★ 回归点：set_mode("") 之后仍然能报出后端 ★ ──────────────────
print("\n[2] ★ set_mode('') 之后（这就是实机说错话的那一步）")
s.set_mode("")
check("backend_name() 仍能报出后端（不能是「(无)」）",
      s.backend_name() not in ("(无)", "", None), f"实得 {s.backend_name()!r}")
check("mode_label() 带上实际后端", "NVDA" in s.mode_label(), f"实得 {s.mode_label()!r}")
check("此时 speak() 也能出声", s.speak("测试") and nvda.spoken, f"nvda.spoken={nvda.spoken}")

# ── 3) 档位轮换 ──────────────────────────────────────────────────
print("\n[3] F9 档位轮换")
seen = []
s2, _n, _p = new_speech()
for _ in range(len(A11ySpeech.CfgModes)):
    seen.append(s2.cycle_mode())
check("轮换一周正好回到起点", len(set(seen)) == len(A11ySpeech.CfgModes),
      f"实得 {seen}")

# ── 4) 钉死某个后端 ──────────────────────────────────────────────
print("\n[4] 钉死到「引擎同款」")
s3, n3, p3 = new_speech()
s3.set_mode("SAPI(引擎同款)")
check("backend_name() 跟着变", s3.backend_name() == "SAPI(引擎同款)", f"实得 {s3.backend_name()!r}")
s3.speak("只走 SAPI")
check("只走了 SAPI，没走 NVDA", p3.spoken and not n3.spoken,
      f"sapi={p3.spoken} nvda={n3.spoken}")

# ── 5) 名字写错 ⇒ 退回自动，而不是整局哑掉 ────────────────────────
print("\n[5] 配置里后端名写错")
s4, n4, p4 = new_speech()
s4.set_mode("拼错的名字")
check("没有停在「没有后端」", s4.backend_name() not in ("(无)", ""), f"实得 {s4.backend_name()!r}")
check("写了 Warning（不静默）", any("不认识的后端名" in x for x in host.logs),
      f"日志尾部 {host.logs[-2:]}")

# ── 6) 链首不可用时降级 ──────────────────────────────────────────
print("\n[6] NVDA 不可用时降级到下一个")
s5, n5, p5 = new_speech(ok_nvda=False)
check("退化到 SAPI(引擎同款)", s5.backend_name() == "SAPI(引擎同款)", f"实得 {s5.backend_name()!r}")
s5.speak("降级")
check("确实由 SAPI 出声", p5.spoken and not n5.spoken)

# ── 7) 全灭时返回失败，而不是抛异常 ──────────────────────────────
print("\n[7] 所有后端都不可用")
s6, _a, _b = new_speech(ok_nvda=False, ok_sapi=False)
check("backend_name() 报「(无)」", s6.backend_name() == "(无)", f"实得 {s6.backend_name()!r}")
check("speak() 返回 False 而不抛异常", s6.speak("没人听") is False)

# ── 8) 「两者」档 ────────────────────────────────────────────────
print("\n[8] 「两者同时」档")
s7, n7, p7 = new_speech()
s7.set_mode("两者")
ok = s7.speak("两边都念")
check("两路都被调用", ok and n7.spoken and p7.spoken, f"nvda={n7.spoken} sapi={p7.spoken}")
check("backend_name() 报出两路", "NVDA" in s7.backend_name() and "SAPI" in s7.backend_name(),
      f"实得 {s7.backend_name()!r}")

print()
print("=" * 72)
print(f"结论：{'全部通过' if FAIL == 0 else str(FAIL) + ' 项不通过'}")
print("=" * 72)
raise SystemExit(0 if FAIL == 0 else 1)
