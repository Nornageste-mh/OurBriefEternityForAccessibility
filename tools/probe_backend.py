#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后端发声实测 —— 独立宿主，不依赖游戏与 Ren'Py。

对应流水线里的 `tools/zdsr-probe/`：把「后端不出声」拆成
「我们代码的问题」还是「环境/授权的问题」。

它会依次试 NVDA / 争渡 / SAPI，各自打印**判据返回值**，最后实际出声一句中文。
判据严格照抄流水线 README 的结论：
  - 争渡的判据是 `GetSpeakState`（3/4 才算读屏在跑），**不是** `InitTTS` 的返回值
    （实测读屏没启动时 InitTTS 照样返回 0）
  - SAPI 初始化时**先读 rate/volume 验证 vtable 槽位** —— 错一位当场露馅

用法：
    python tools/probe_backend.py            # 只探不发声
    python tools/probe_backend.py --speak    # 真的出声（需要读屏在跑）
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NVDA_DLL_CANDIDATES = [
    r"D:\Harness工作区\nvda_dl\x64\nvdaControllerClient.dll",
    r"D:\Harness工作区\meikong-a11y\mod\package\BepInEx\plugins\nvdaControllerClient.dll",
]
ZDSR_DLL_CANDIDATES = [
    r"C:\Program Files (x86)\zdsr\zdsr\ZDSRAPI_x64.dll",
    r"C:\Program Files\zdsr\zdsr\ZDSRAPI_x64.dll",
]

PROBE_TEXT = "无障碍后端测试，如果你听到这句话，说明朗读通路是通的。"


def first_existing(paths):
    return next((p for p in paths if os.path.exists(p)), None)


# ------------------------------------------------------------------ NVDA
def try_nvda(speak: bool) -> str:
    print("\n### NVDA controller client")
    dll = first_existing(NVDA_DLL_CANDIDATES)
    if not dll:
        print("  [跳过] 未找到 nvdaControllerClient.dll")
        return "missing"
    print(f"  dll: {dll}")

    try:
        lib = ctypes.WinDLL(dll)
        test = lib.nvdaController_testIfRunning
        test.restype = ctypes.c_int
        speak_text = lib.nvdaController_speakText
        speak_text.argtypes = [ctypes.c_wchar_p]
        speak_text.restype = ctypes.c_int
        cancel = lib.nvdaController_cancelSpeech
        cancel.restype = ctypes.c_int
    except Exception as e:  # noqa: BLE001
        print(f"  [失败] 加载/取符号: {type(e).__name__}: {e}")
        return "error"

    rc = test()
    print(f"  nvdaController_testIfRunning() -> {rc}"
          f"   ({'NVDA 在跑' if rc == 0 else 'NVDA 未运行/不可达'})")
    if rc != 0:
        return "not_running"

    if speak:
        rc2 = speak_text(PROBE_TEXT)
        print(f"  nvdaController_speakText(...) -> {rc2}"
              f"   ({'已排队' if rc2 == 0 else '失败'})")
        time.sleep(0.3)
        return "ok" if rc2 == 0 else "error"
    print("  (--speak 未指定，不实际发声)")
    return "ok"


# ------------------------------------------------------------------ 争渡
def try_zdsr(speak: bool) -> str:
    print("\n### 争渡 ZDSRAPI")
    dll = first_existing(ZDSR_DLL_CANDIDATES)
    if not dll:
        print("  [跳过] 未找到 ZDSRAPI_x64.dll")
        return "missing"
    print(f"  dll: {dll}")

    try:
        lib = ctypes.WinDLL(dll)
        init = lib.InitTTS
        init.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        init.restype = ctypes.c_int
        speak_fn = lib.Speak
        speak_fn.argtypes = [ctypes.c_wchar_p, ctypes.c_bool]
        speak_fn.restype = ctypes.c_int
        state = lib.GetSpeakState
        state.restype = ctypes.c_int
        stop = lib.StopSpeak
        stop.restype = ctypes.c_int
    except Exception as e:  # noqa: BLE001
        print(f"  [失败] 加载/取符号: {type(e).__name__}: {e}")
        return "error"

    rc_init = init("", "")
    print(f"  InitTTS(...) -> {rc_init}   (0=成功/已初始化, 1=失败, 3=同进程已初始化)")

    # ★ 判据是 GetSpeakState，不是 InitTTS 的返回值
    rc_state = state()
    state_meaning = {0: "未初始化", 1: "就绪", 2: "读屏没有运行或没有授权",
                     3: "正在朗读", 4: "朗读暂停"}.get(rc_state, "未知")
    print(f"  GetSpeakState() -> {rc_state}   ({state_meaning})")

    usable = rc_state in (1, 3, 4)
    print(f"  判据: rc_state in (1,3,4) -> {usable}")

    if not usable:
        print("  => 争渡这一级不可用，应按流水线**顺降到 SAPI/NVDA**，"
              "而不是继续调用")
        return "not_usable"

    if speak:
        rc2 = speak_fn(PROBE_TEXT, True)
        print(f"  Speak(...) -> {rc2}")
        time.sleep(0.3)
        return "ok" if rc2 == 0 else "error"
    return "ok"


# ------------------------------------------------------------------ SAPI
CLSID_SpVoice = "{96749377-3391-11d2-9ee3-00c04f797396}"
IID_ISpVoice = "{6c44df74-72b9-4992-a1ec-ef996e0422d4}"

# 已实机验证的 vtable 槽位（流水线 README《Sapi.cs》）
VT = {
    "QueryInterface": 0, "AddRef": 1, "Release": 2,
    "SetRate": 28, "GetRate": 29, "SetVolume": 30, "GetVolume": 31,
    "Speak": 20, "WaitUntilDone": 32,
}
SPF_ASYNC = 1
SPF_PURGEBEFORESPEAK = 2


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


def guid_from_string(s: str) -> GUID:
    s = s.strip("{}")
    p = s.split("-")
    g = GUID()
    g.Data1 = int(p[0], 16)
    g.Data2 = int(p[1], 16)
    g.Data3 = int(p[2], 16)
    tail = bytes.fromhex(p[3] + p[4])
    for i, b in enumerate(tail):
        g.Data4[i] = b
    return g


def try_sapi(speak: bool) -> str:
    print("\n### Windows SAPI 5 (ISpVoice, 纯 ctypes + vtable)")
    try:
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
        p = ctypes.c_void_p()
        clsid = guid_from_string(CLSID_SpVoice)
        iid = guid_from_string(IID_ISpVoice)
        hr = ole32.CoCreateInstance(
            ctypes.byref(clsid), None, 0x17,  # CLSCTX_ALL
            ctypes.byref(iid), ctypes.byref(p))
        if hr != 0:
            print(f"  CoCreateInstance -> 0x{hr & 0xFFFFFFFF:08X}  失败")
            return "error"
        print(f"  CoCreateInstance -> S_OK, ISpVoice* = {p.value:#x}")

        vtbl = ctypes.cast(p, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]

        def slot(i):
            return ctypes.cast(vtbl[i], ctypes.c_void_p).value

        # ★ 先读 rate/volume 验证 vtable 槽位 —— 错一位当场露馅
        GetRate = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                     ctypes.POINTER(ctypes.c_long))(slot(VT["GetRate"]))
        GetVolume = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_ushort))(slot(VT["GetVolume"]))
        rate = ctypes.c_long()
        vol = ctypes.c_ushort()
        hr1 = GetRate(p, ctypes.byref(rate))
        hr2 = GetVolume(p, ctypes.byref(vol))
        print(f"  GetRate()   -> hr=0x{hr1 & 0xFFFFFFFF:08X} rate={rate.value}")
        print(f"  GetVolume() -> hr=0x{hr2 & 0xFFFFFFFF:08X} volume={vol.value}")
        slots_ok = (hr1 == 0 and hr2 == 0 and 0 <= vol.value <= 100)
        print(f"  vtable 槽位自检: {'通过' if slots_ok else '**不通过**（别信后面的朗读）'}")
        if not slots_ok:
            return "error"

        if speak:
            Speak = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                       ctypes.c_wchar_p, ctypes.c_ulong)(slot(VT["Speak"]))
            hr3 = Speak(p, PROBE_TEXT, SPF_ASYNC | SPF_PURGEBEFORESPEAK)
            print(f"  Speak(SPF_ASYNC|SPF_PURGEBEFORESPEAK) -> hr=0x{hr3 & 0xFFFFFFFF:08X}")
            time.sleep(1.0)
        return "ok"
    except Exception as e:  # noqa: BLE001
        print(f"  [失败] {type(e).__name__}: {e}")
        return "error"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--speak", action="store_true", help="实际出声（默认只探不发）")
    args = ap.parse_args()

    print("=" * 72)
    print("后端发声实测（独立宿主）")
    print("=" * 72)
    print(f"实际发声: {args.speak}")

    results = {
        "NVDA": try_nvda(args.speak),
        "ZDSR": try_zdsr(args.speak),
        "SAPI": try_sapi(args.speak),
    }

    print("\n" + "=" * 72)
    print("汇总（按流水线后端链次序 NVDA -> ZDSR -> SAPI）")
    for k, v in results.items():
        mark = {"ok": "可用", "not_running": "读屏未运行", "not_usable": "接口报不可用",
                "missing": "dll 缺失", "error": "错误"}.get(v, v)
        print(f"  {k:<6} {v:<14} {mark}")
    usable = [k for k, v in results.items() if v == "ok"]
    print(f"\n可用后端: {usable if usable else '（无）'}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
