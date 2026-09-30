#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NVDA 打断竞态 A/B 对照实验（不开游戏）。

背景（实机取证）：
    浏览器/游戏里的取证文件显示，补丁把下面这些**都成功送给了 NVDA**
    （`nvdaController_speakText` 返回 0）：
        [A11y果] OK backend=NVDA text='主菜单。开始游戏，……'
        [A11y果] OK backend=NVDA text='1．开始游戏'
    但用户**一句都没听到**；而同样长度的开屏播报却听得到。

    两者的差别只在**时机**：开屏播报发生在界面还没起来时，
    菜单播报发生在界面活跃、主循环高频运行时。

本脚本把那个差别拆成可控变量，用**完全相同的文本**做 A/B：
    A. 单次长句（对照组：应当听得到）
    B. 先长句，再在它还没读完时连发短句（每次先 cancelSpeech）
       —— 复现「菜单导航」的时序
    C. 同 B，但不 cancelSpeech（只排队）
    D. 高频连发（模拟每帧都播报）

判读：
    · B 听不到、C 听得到 → 确认是「cancelSpeech 打断竞态」，
      补丁应在**界面活跃期**改为排队（不打断）。
    · B、C 都听不到 → 与打断无关，问题在调用线程或 NVDA 会话。
    · 全部听得到 → 宿主复现不出来，必须回到游戏里带更细的日志查。

用法：
    python tools/probe_nvda_race.py
"""

from __future__ import annotations

import ctypes
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DLL_CANDIDATES = [
    r"F:\Steam\steamapps\common\永恒与星辰与日常\nvdaControllerClient64.dll",
    r"D:\Harness工作区\eternity-a11y\mod\nvdaControllerClient64.dll",
    r"D:\Harness工作区\nvda_dl\x64\nvdaControllerClient.dll",
]

#: 与实机取证文件里**完全一致**的文本
LONG = "主菜单。开始游戏，继续游戏，读取游戏，系统设置，特殊模式（尚未解锁），退出游戏。按方向键移动，回车键确认。"
SHORT = ["1．开始游戏", "2．继续游戏", "3．读取游戏", "4．系统设置"]


def main() -> int:
    dll = next((p for p in DLL_CANDIDATES if os.path.exists(p)), None)
    if dll is None:
        print("找不到 nvdaControllerClient64.dll")
        return 2

    lib = ctypes.WinDLL(dll)
    lib.nvdaController_testIfRunning.argtypes = []
    lib.nvdaController_testIfRunning.restype = ctypes.c_int
    lib.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
    lib.nvdaController_speakText.restype = ctypes.c_int
    lib.nvdaController_cancelSpeech.argtypes = []
    lib.nvdaController_cancelSpeech.restype = ctypes.c_int

    rc = lib.nvdaController_testIfRunning()
    print("=" * 74)
    print("NVDA 打断竞态 A/B 对照")
    print("=" * 74)
    print(f"dll={dll}")
    print(f"testIfRunning -> {rc} ({'在跑' if rc == 0 else '未运行'})")
    if rc != 0:
        return 1
    print()

    def speak(text, interrupt):
        if interrupt:
            lib.nvdaController_cancelSpeech()
        return lib.nvdaController_speakText(text)

    # ---------------- A：单次长句（对照）----------------
    print("--- A 单次长句（对照：这一句应当听得到）---")
    print(f"  speak -> {speak(LONG, False)}")
    input("  >>> 听完了按回车继续…")

    # ---------------- B：长句后 0.5 秒插短句，每次打断 ----------------
    print("\n--- B 长句 +0.5s 短句（每次 cancelSpeech）——模拟菜单导航 ---")
    print(f"  长句 speak -> {speak(LONG, False)}")
    time.sleep(0.5)
    for s in SHORT:
        print(f"  {s}  speak -> {speak(s, True)}")
        time.sleep(0.6)
    input("  >>> 你听到几句？（期望：只听到一两个碎片，或什么都没有）按回车继续…")

    # ---------------- C：同 B，但不打断 ----------------
    print("\n--- C 长句 +0.5s 短句（不打断，只排队）---")
    print(f"  长句 speak -> {speak(LONG, False)}")
    time.sleep(0.5)
    for s in SHORT:
        print(f"  {s}  speak -> {speak(s, False)}")
        time.sleep(0.6)
    input("  >>> 你听到几句？（期望：长句 + 四句短句都在）按回车继续…")

    # ---------------- D：高频连发 ----------------
    print("\n--- D 高频连发（50 次，不打断）---")
    n = 0
    for i in range(50):
        n += 1
        speak("%d．测试" % (i + 1), False)
    print(f"  已连发 {n} 次")
    input("  >>> 听到了多少个数字？按回车结束…")

    print("\n" + "=" * 74)
    print("判读表：")
    print("  B 听不到而 C 听得到  -> 打断竞态，补丁在界面活跃期应改为排队")
    print("  B 与 C 都听不到      -> 与打断无关，需查调用线程 / NVDA 会话")
    print("  全部听得到           -> 宿主复现不出，需回游戏加更细的日志")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
