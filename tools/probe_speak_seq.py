#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""连续朗读复现实验 —— 不开游戏，直接打 NVDA 后端。

为什么需要它：用户反馈「开屏第一句听得到，之后全哑，而且像被打断」。
补丁的朗读出口每次都先 `cancelSpeech()` 再 `speakText()`，
所以第一嫌疑人是**打断与朗读之间的竞态**。

本脚本把那个调用序列原样复现出来，并用三种节奏各念三句：
    A. interrupt=True  （当前实现：每次先 cancel）
    B. interrupt=False （不打断，交给读屏排队）
    C. 只 cancel 一次，之后不打断

每种节奏都把每个调用的返回码打出来 ——
返回码本身就是判据（0 = 成功排队）。

用法：
    python tools/probe_speak_seq.py            # 需要 NVDA 正在运行
    python tools/probe_speak_seq.py --wait 2.0 # 每句之间等更久
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DLL_CANDIDATES = [
    r"D:\Harness工作区\eternity-a11y\mod\nvdaControllerClient64.dll",
    r"D:\Harness工作区\nvda_dl\x64\nvdaControllerClient.dll",
]

PHRASES = [
    "第一句，测试连续朗读。",
    "第二句，如果你听到这句，说明不是打断竞态。",
    "第三句，三句都听到就是完全正常。",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=float, default=3.0, help="每句之间等待秒数")
    args = ap.parse_args()

    dll = next((p for p in DLL_CANDIDATES if os.path.exists(p)), None)
    if dll is None:
        print("找不到 nvdaControllerClient64.dll，无法测试。")
        return 2

    print("=" * 72)
    print("连续朗读复现实验")
    print("=" * 72)
    print(f"dll  : {dll}")

    lib = ctypes.WinDLL(dll)
    lib.nvdaController_testIfRunning.argtypes = []
    lib.nvdaController_testIfRunning.restype = ctypes.c_int
    lib.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
    lib.nvdaController_speakText.restype = ctypes.c_int
    lib.nvdaController_cancelSpeech.argtypes = []
    lib.nvdaController_cancelSpeech.restype = ctypes.c_int

    rc = lib.nvdaController_testIfRunning()
    print(f"testIfRunning -> {rc}  ({'NVDA 在跑' if rc == 0 else 'NVDA 未运行'})")
    if rc != 0:
        print("\n请先启动 NVDA 再跑本脚本。")
        return 1

    def seq(label, interrupts):
        print(f"\n--- 节奏 {label} ---")
        for i, phrase in enumerate(PHRASES):
            use_interrupt = interrupts[i] if i < len(interrupts) else interrupts[-1]
            if use_interrupt:
                c = lib.nvdaController_cancelSpeech()
                print(f"  句{i+1} cancelSpeech -> {c}")
            s = lib.nvdaController_speakText(phrase)
            print(f"  句{i+1} speakText    -> {s}   interrupt={use_interrupt}")
            time.sleep(args.wait)

    # A. 当前实现：每次都打断
    seq("A 每次打断（当前实现）", [True, True, True])
    # B. 完全不打断
    seq("B 完全不打断", [False, False, False])
    # C. 只打断一次
    seq("C 只在开头打断一次", [True, False, False])

    print("\n" + "=" * 72)
    print("怎么判读：")
    print("  · 三种节奏都能听到三句 → 打断不是主因，问题在游戏侧的调用时机")
    print("  · 只有 B / C 能听到三句   → 确认是打断竞态，补丁应默认不打断")
    print("  · 三种都只听到第一句、返回码却都是 0")
    print("      → 读屏端在一次之后不再接受（可能是同一句被判重复，或控件被游戏抢走）")
    print("  · 返回码非 0            → 后端调用本身有问题，把这一段发我")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
