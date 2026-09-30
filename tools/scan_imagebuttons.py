#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""界面控件扫描 —— 把 `.rpy` 里每个 `imagebutton` 压成一行「图片 / 坐标 / 动作」。

为什么要有它（无障碍补丁的常规作业）：
    Ren'Py 作品的控件几乎全是 `imagebutton`，而**字印在图上、代码里没有字**。
    要给它们补朗读文本，就必须先知道「哪个界面、第几行、用了哪张图、
    在什么坐标、点了会做什么」。逐份读源码又慢又费上下文，
    而这个信息是**纯机械可提取**的，所以固化成工具。

它只读**反编译出来的脚本**（`extracted/`），不碰游戏资源、不打印剧本正文，
所以输出可以直接贴进排查记录。

用法：
    python tools/scan_imagebuttons.py <文件或目录> [...]
    python tools/scan_imagebuttons.py extracted/scripts/scripts/screens/screen_gallery.rpy
"""

from __future__ import annotations

import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KEY_RE = re.compile(r"^\s*([A-Za-z_]+)\s+(.*)$")
WANT = ("idle", "hover", "insensitive", "selected_idle", "selected_hover",
        "action", "xpos", "ypos", "xysize", "alt", "text", "if", "for")


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def scan(path: str):
    lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
    out = []
    for i, line in enumerate(lines):
        s = line.strip()
        if s != "imagebutton:":
            continue
        base = indent_of(line)
        info = {"line": i + 1, "indent": base}
        j = i + 1
        while j < len(lines):
            cur = lines[j]
            if cur.strip() and indent_of(cur) <= base:
                break
            m = KEY_RE.match(cur)
            if m:
                k, v = m.group(1), m.group(2).strip()
                if k in WANT:
                    if k == "idle" and "idle" in info:
                        info["idle2"] = v
                    else:
                        info.setdefault(k, v)
            j += 1
        out.append(info)
    return out


def show(path: str):
    items = scan(path)
    if not items:
        return 0
    print("=" * 78)
    print(f"{os.path.basename(path)}   共 {len(items)} 个 imagebutton")
    print("=" * 78)
    for it in items:
        img = it.get("idle", "?")
        img = img.strip('"').split("/")[-1]
        pos = ""
        if "xpos" in it or "ypos" in it:
            pos = "(%s,%s)" % (it.get("xpos", "-"), it.get("ypos", "-"))
        act = it.get("action", "")
        act = act.strip()
        if len(act) > 58:
            act = act[:55] + "..."
        extra = ""
        if it.get("if"):
            extra = "  [if %s]" % it["if"][:40]
        print(f"  L{it['line']:<4} {pos:<14} {img:<46} {act}{extra}")
    print()
    return len(items)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    total = 0
    files = []
    for a in sys.argv[1:]:
        if os.path.isdir(a):
            for dp, _d, ns in os.walk(a):
                for n in sorted(ns):
                    if n.endswith(".rpy"):
                        files.append(os.path.join(dp, n))
        else:
            files.append(a)
    for f in files:
        total += show(f)
    print(f"合计 {total} 个 imagebutton（{len(files)} 个文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
