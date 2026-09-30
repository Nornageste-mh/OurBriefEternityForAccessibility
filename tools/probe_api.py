#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线 API 探针 —— 用游戏自带运行时 Python 直接 import renpy，把「猜」变成「看」。

为什么不能 `import renpy.config` 就完事：
`renpy/config.py` 在**模块级**就引用了 `renpy.error.TracebackException`，
而 `renpy/__init__.py` 里的导入块（约 373–568 行）是有严格先后依赖的。
所以本探针**复用引擎自己的那份导入清单**，反复迭代到稳定为止
（无依赖环，必然收敛），而不是自己手写一个脆弱的子集。

不启动游戏、不加载剧本、不开窗口。
只打印类型 / 签名 / 默认值 —— **不打印任何剧本原文**（流水线 §6 P1 IP 红线）。
"""

from __future__ import annotations

import inspect
import os
import re
import sys

GAME_DIR = os.environ.get("ETERNITY_GAME_DIR",
                          r"F:\Steam\steamapps\common\永恒与星辰与日常")
sys.path.insert(0, GAME_DIR)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

print("=" * 72)
print("离线 API 探针 —— Ren'Py 引擎事实核查")
print("=" * 72)
print(f"python     : {sys.version.split()[0]} ({sys.implementation.name})")
print(f"game dir   : {GAME_DIR}")

import renpy  # noqa: E402

print(f"renpy      : {renpy.version_tuple}   ({renpy.version})")

# ---------------------------------------------------------------- 导入稳定化
INIT_PY = os.path.join(GAME_DIR, "renpy", "__init__.py")
src = open(INIT_PY, encoding="utf-8").read()
# 抓 `    import renpy.xxx` / `    import six` 这种缩进导入行
seeds = re.findall(r"^\s+import ((?:renpy\.[A-Za-z_][\w.]*)|six|pygame)\s*$", src, re.M)
seeds = list(dict.fromkeys(seeds))

pending = list(seeds)
failed: dict[str, str] = {}
rounds = 0
while pending and rounds < 12:
    rounds += 1
    still = []
    for name in pending:
        try:
            __import__(name)
        except Exception as e:  # noqa: BLE001
            still.append(name)
            failed[name] = f"{type(e).__name__}: {e}"
    if len(still) == len(pending):
        break
    pending = still

print(f"导入稳定化: {len(seeds)} 个种子模块, {rounds} 轮, "
      f"剩 {len(pending)} 个未成功")
if pending:
    for n in pending[:8]:
        print(f"  [未导入] {n}: {failed.get(n,'')[:110]}")


def check(label, obj, attr):
    try:
        val = getattr(obj, attr)
    except AttributeError:
        print(f"  [缺失] {label}.{attr}")
        return None
    except Exception as e:  # noqa: BLE001
        print(f"  [异常] {label}.{attr} -> {type(e).__name__}: {e}")
        return None
    if callable(val):
        try:
            sig = str(inspect.signature(val))
        except (TypeError, ValueError):
            sig = "(?)"
        print(f"  [有]   {label}.{attr}{sig}")
    else:
        r = repr(val)
        print(f"  [有]   {label}.{attr} = {r[:90]}{' …' if len(r) > 90 else ''}")
    return val


def section(n, title):
    print(f"\n--- {n}. {title} ---")


try:
    import renpy.config as C
except Exception as e:  # noqa: BLE001
    print(f"致命: 无法 import renpy.config: {e}")
    raise SystemExit(2)

section(1, "self-voicing / TTS 出口（补丁要挂的地方）")
try:
    import renpy.display.tts as T
    for a in ("tts_function", "tts_substitutions", "tts_voice", "tts_queue",
              "tts_voice_channels", "self_voicing"):
        check("config", C, a)
    for a in ("speak", "displayable", "stop_tts", "is_active", "tick", "set_root",
              "speak_extra_alt", "TTSDone", "TTSRoot", "default_tts_function",
              "apply_substitutions"):
        check("tts", T, a)
except Exception as e:  # noqa: BLE001
    print(f"  [异常] import renpy.display.tts -> {type(e).__name__}: {e}")

section(2, "无障碍 / 描述性文本 config")
for a in ("self_voicing", "tts_voice", "accessibility_menu", "nw_voice",
          "descriptive_text_character", "say_menu", "alt", "default_afm_time",
          "rollback_enabled", "keymap"):
    check("config", C, a)

section(3, "config 里影响「补丁能否叠加」的字段")
for a in ("script_version", "save_version", "searchpath", "gamedir", "basedir",
          "renpy_base", "archives", "compile_cache_size", "autoreload",
          "developer", "auto_voice", "voice_filename_format", "has_voice",
          "voice_sustain", "tts_queue"):
    check("config", C, a)

section(4, "显示层 / 焦点（导航播报的依据）")
try:
    import renpy.display.focus as F
    for a in ("get_focused", "focus_list", "set_focused", "take_focus",
              "focus_coordinates"):
        check("focus", F, a)
except Exception as e:  # noqa: BLE001
    print(f"  [异常] focus -> {e}")

section(5, "exports 里可供挂钩的 API")
try:
    import renpy.exports as E
    for a in ("speak", "notify", "get_say_attributes", "get_say_image_tag",
              "get_screen", "get_widget", "restart_interaction", "is_seen",
              "get_voice_info", "get_side_image", "get_voice_info",
              "current_screen", "get_displayable"):
        check("exports", E, a)
except Exception as e:  # noqa: BLE001
    print(f"  [异常] exports -> {e}")

section(6, "音频通道 / 语音")
try:
    import renpy.audio.music as M
    for a in ("get_playing", "register_channel", "get_channel", "is_music_playing"):
        check("music", M, a)
except Exception as e:  # noqa: BLE001
    print(f"  [异常] music -> {e}")

section(7, "说话人与 say 语句")
try:
    import renpy.character as CH
    check("character", CH, "Character")
    check("character", CH, "ADVCharacter")
    check("character", CH, "NVLCharacter")
    check("character", CH, "Say")
except Exception as e:  # noqa: BLE001
    print(f"  [异常] character -> {e}")

section(8, "text displayable 的 TTS 出口（决定「读什么」）")
try:
    import renpy.text.text as TT
    check("text", TT, "Text")
    print("  说明: Text._tts_all 是 self-voicing 取文本的入口之一")
except Exception as e:  # noqa: BLE001
    print(f"  [异常] text -> {e}")

section(9, "Windows 默认 TTS 路径（确认「不认识 NVDA」）")
if renpy.windows:
    say_vbs = os.path.join(os.path.dirname(sys.executable), "say.vbs")
    print(f"  say.vbs    : {say_vbs}")
    print(f"  存在       : {os.path.exists(say_vbs)}")
    print("  默认 tts_function 在 Windows 上 = wscript say.vbs -> SAPI 默认语音，")
    print("  **不认识正在运行的 NVDA / 争渡** —— 这正是后端链不能被省掉的理由。")

section(10, "ctypes 可用性（后端链 NVDA/ZDSR/SAPI 全依赖它）")
import ctypes  # noqa: E402
print(f"  ctypes        : OK")
print(f"  windll        : {hasattr(ctypes, 'windll')}")
print(f"  WINFUNCTYPE   : {hasattr(ctypes, 'WINFUNCTYPE')}")
print(f"  OleDLL        : {hasattr(ctypes, 'OleDLL')}")
print(f"  cdll          : {hasattr(ctypes, 'cdll')}")

section(11, "本机读屏后端可用性预检")
for label, paths in [
    ("NVDA controller client", [
        os.path.join(GAME_DIR, "nvdaControllerClient64.dll"),
        r"D:\Harness工作区\nvda_dl\x64\nvdaControllerClient.dll",
        r"D:\Harness工作区\meikong-a11y\mod\package\BepInEx\plugins\nvdaControllerClient.dll",
    ]),
    ("争渡 ZDSRAPI_x64", [r"C:\Program Files (x86)\zdsr\zdsr\ZDSRAPI_x64.dll"]),
    ("Tolk", [os.path.join(GAME_DIR, "Tolk.dll")]),
]:
    hit = next((p for p in paths if os.path.exists(p)), None)
    print(f"  {label:<24} {'命中: ' + hit if hit else '未找到'}")

section(12, "脚本编译 / 校验入口（离线跑补丁的语法与语义检查）")
try:
    import renpy.parser as PA
    for a in ("parse", "parse_file"):
        check("parser", PA, a)
except Exception as e:  # noqa: BLE001
    print(f"  [异常] parser -> {e}")

print("\n" + "=" * 72)
print("探针完成")
print("=" * 72)
