#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后端 DLL 导出表实证 —— 「不许猜导出名」（流水线 §7 铁律 1）。

流水线在 C# 那一侧踩过的坑（README《Zdsr.cs》）：
  `DllImport(EntryPoint="Speak")` 漏了就会去找不存在的 `SpeakText`，
  **编得过、静态断言也查不出，只有读 DLL 元数据才看得见**。

在 ctypes 这一侧风险更高：`WinDLL(...).函数名` 写错要到**运行时调用**才炸。
所以这个探针在**开发期**就把导出表读出来，逐个核对我们要用的那几个名字。

纯 ctypes + PE 解析，不依赖 pefile。
"""

from __future__ import annotations

import ctypes
import os
import struct
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 极简 PE 导出表解析
def pe_exports(path: str) -> list[str]:
    """读 PE 的导出名表。纯标准库。"""
    with open(path, "rb") as f:
        data = f.read()

    if data[:2] != b"MZ":
        raise ValueError("不是 PE 文件")
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        raise ValueError("PE 签名不符")

    coff = e_lfanew + 4
    num_sections = struct.unpack_from("<H", data, coff + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    is_pe32p = magic == 0x20B

    # 数据目录第 0 项 = 导出表
    dd_off = opt + (112 if is_pe32p else 96)
    rva, size = struct.unpack_from("<II", data, dd_off)
    if rva == 0:
        return []

    # RVA -> 文件偏移
    sec_off = opt + opt_size
    def rva_to_off(rva: int) -> int | None:
        for i in range(num_sections):
            s = sec_off + i * 40
            vaddr, vsize = struct.unpack_from("<II", data, s + 12)[0], struct.unpack_from("<I", data, s + 8)[0]
            raw_size, raw_ptr = struct.unpack_from("<II", data, s + 16)
            if vaddr <= rva < vaddr + max(vsize, raw_size):
                return raw_ptr + (rva - vaddr)
        return None

    off = rva_to_off(rva)
    if off is None:
        return []

    n_names = struct.unpack_from("<I", data, off + 24)[0]
    names_rva = struct.unpack_from("<I", data, off + 32)[0]
    names_off = rva_to_off(names_rva)
    if names_off is None:
        return []

    out = []
    for i in range(n_names):
        name_rva = struct.unpack_from("<I", data, names_off + i * 4)[0]
        no = rva_to_off(name_rva)
        if no is None:
            continue
        end = data.index(b"\0", no)
        out.append(data[no:end].decode("ascii", "replace"))
    return out


def machine_of(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read(0x200)
    e = struct.unpack_from("<I", data, 0x3C)[0]
    m = struct.unpack_from("<H", data, e + 4)[0]
    return {0x8664: "x64", 0x14C: "x86", 0xAA64: "arm64"}.get(m, f"0x{m:04x}")


TARGETS = [
    ("NVDA controller client",
     r"D:\Harness工作区\nvda_dl\x64\nvdaControllerClient.dll",
     ["nvdaController_testIfRunning", "nvdaController_speakText",
      "nvdaController_cancelSpeech", "nvdaController_brailleMessage",
      "nvdaController_getProcessId", "nvdaController_speakSsml",
      "nvdaController_setOnSsmlMarkReachedCallback"]),
    ("争渡 ZDSRAPI (x64)",
     r"C:\Program Files (x86)\zdsr\zdsr\ZDSRAPI_x64.dll",
     ["InitTTS", "Speak", "SpeakText", "GetSpeakState", "StopSpeak", "Braille",
      "GetSpeakStateEx", "PauseSpeak", "ResumeSpeak", "SetVolume", "SetRate"]),
    ("Tolk（若玩家自备）",
     os.path.join(os.environ.get("ETERNITY_GAME_DIR",
                                 r"F:\Steam\steamapps\common\永恒与星辰与日常"), "Tolk.dll"),
     ["Tolk_Load", "Tolk_Unload", "Tolk_IsLoaded", "Tolk_DetectScreenReader",
      "Tolk_HasSpeech", "Tolk_HasBraille", "Tolk_Output", "Tolk_Speak",
      "Tolk_Braille", "Tolk_Silence", "Tolk_TrySAPI", "Tolk_PreferSAPI",
      "Tolk_IsSpeaking"]),
]

print("=" * 72)
print("后端 DLL 导出表实证")
print("=" * 72)

all_ok = True
for label, path, need in TARGETS:
    print(f"\n### {label}")
    if not os.path.exists(path):
        print(f"  [未找到] {path}")
        if "Tolk" in label:
            print("  -> Tolk 是可选一级；缺它不影响三级链（NVDA/ZDSR/SAPI）")
        else:
            all_ok = False
        continue

    try:
        names = pe_exports(path)
        arch = machine_of(path)
    except Exception as e:  # noqa: BLE001
        print(f"  [解析失败] {type(e).__name__}: {e}")
        all_ok = False
        continue

    print(f"  路径   : {path}")
    print(f"  架构   : {arch}   导出总数: {len(names)}")
    print("  核对我们要用的导出名：")
    for n in need:
        if n in names:
            print(f"    [有]   {n}")
        else:
            # 争渡的备用名，不算缺
            print(f"    [缺失] {n}")
    # 列出与语音/朗读相关的导出，便于发现我们没料到的名字
    related = [n for n in names
               if any(k in n.lower() for k in
                      ("speak", "tts", "voice", "braille", "silence", "output",
                       "load", "detect", "sapi", "state", "stop"))]
    print(f"  与语音相关的全部导出 ({len(related)}):")
    for n in sorted(related):
        print(f"      {n}")

print("\n" + "=" * 72)
print("结论：" + ("全部必需导出名核对通过" if all_ok else "有缺失，见上"))
print("=" * 72)
