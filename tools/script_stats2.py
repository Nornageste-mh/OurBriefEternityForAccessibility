#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剧本结构统计（P0）—— 第二版，口径收紧。

第一版的教训：正则级匹配会把 `screen` 块里的样式属性
（`idle` / `hover` / `selected_idle` / `add` / `color` / `font` …）
误判成说话人，于是「说话人分布」里混进了 8 个不是人的东西。

第二版修正口径：
  1. **跳过整个 `screen` / `style` / `transform` / `init python` / `python` 块**
     （按缩进回退判定块结束）—— 这些块里的字符串绝大多数不是台词。
  2. 说话人标识符必须**以 `_` 结尾**，或就是 `narrator` / 已知的 Ren'Py 内置。
     本作的角色变量全部是 `xx_` 形态（role.rpy 实查：15 个 Character 定义，
     14 个以 `_` 结尾 + `temp_2`）。
  3. `voice_tag` 等关键字单独列白名单排除。

**只输出统计数字与标签种类，绝不输出任何台词原文**（流水线 §6 P1 IP 红线）。
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SAY_RE = re.compile(r'^(?P<indent>[ \t]*)(?P<who>[A-Za-z_][A-Za-z0-9_]*)[ \t]+(?P<q>")(?P<text>.*)$')
NARRATE_RE = re.compile(r'^[ \t]*(?P<q>")(?P<text>.*)$')

# 这些块里的一切都不统计（里面是界面/样式/工具代码，不是剧本）
BLOCK_RE = re.compile(
    r'^[ \t]*(?:screen|style|transform|init[ \t]+python|init[ \t]+-?\d+[ \t]+python|'
    r'python|translate|layeredimage|image|define|default|layeredimage)\b'
)

MENU_RE = re.compile(r'^[ \t]*menu\b')
CHOICE_RE = re.compile(r'^[ \t]+"[^"]*"[ \t]*:')

# Ren'Py 的内置说话人 / 非角色标识符
BUILTIN_WHO = {"narrator", "say", "extend", "voice", "nvl", "centered", "vcentered"}

# 明确不是说话人的关键字（第二道保险）
NOT_WHO = {
    "if", "elif", "else", "while", "for", "return", "call", "jump", "label",
    "menu", "show", "hide", "scene", "play", "stop", "queue", "pause", "with",
    "window", "python", "init", "define", "default", "screen", "style",
    "transform", "image", "set", "pass", "try", "except", "class", "def",
    "import", "from", "and", "or", "not", "in", "is", "del", "global",
    "assert", "raise", "yield", "use", "on", "at", "as", "to", "expression",
    "voice_tag", "what_prefix", "what_suffix", "image", "who", "kind",
}

TAG_RES = {
    "{}插值": re.compile(r"\{[^{}]*\}"),
    "[方括号]插值": re.compile(r"\[[A-Za-z_][^\]]*\]"),
    "全角引号「」": re.compile(r"[「」]"),
    "全角括号【】": re.compile(r"[【】]"),
    "遮蔽问号(？？？)": re.compile(r"？{2,}"),
    "换行转义\\n": re.compile(r"\\n"),
    "连续省略号": re.compile(r"[…]{2,}|\.{3,}"),
}


def analyze_file(path, S, speakers, tags, menus, stats_by_file):
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw_lines = fh.readlines()

    skip_until_indent = None  # 块跳过的目标缩进
    in_menu = False
    menu_indent = 0
    cur = 0
    f_say = f_narr = 0

    def close_menu():
        nonlocal cur, in_menu
        if in_menu and cur:
            menus.append(cur)
        cur = 0
        in_menu = False

    for raw in raw_lines:
        line = raw.rstrip("\n")
        st = line.strip()
        if not st or st.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())

        # 块跳过
        if skip_until_indent is not None:
            if indent > skip_until_indent:
                continue
            skip_until_indent = None

        if BLOCK_RE.match(line):
            skip_until_indent = indent
            continue

        S["总行(有效)"] += 1

        if MENU_RE.match(line):
            close_menu()
            in_menu = True
            menu_indent = indent
            S["menu 数"] += 1
            continue

        if in_menu:
            if indent > menu_indent and CHOICE_RE.match(line):
                cur += 1
                S["选项分支数"] += 1
                continue
            if indent <= menu_indent:
                close_menu()

        m = SAY_RE.match(line)
        if m:
            who = m.group("who")
            text = m.group("text")
            if who in NOT_WHO or text.rstrip().endswith(":"):
                continue
            # 口径：说话人必须是 `xx_` 形态或内置
            if not (who.endswith("_") or who in BUILTIN_WHO):
                continue
            f_say += 1
            S["台词行(带说话人)"] += 1
            speakers[who if who not in BUILTIN_WHO else f"(旁白 {who})"] += 1
            for name, rx in TAG_RES.items():
                if rx.search(text):
                    tags[name] += 1
            continue

        m2 = NARRATE_RE.match(line)
        if m2:
            f_narr += 1
            S["旁白/独白行"] += 1
            for name, rx in TAG_RES.items():
                if rx.search(m2.group("text")):
                    tags[name] += 1

    close_menu()
    stats_by_file[path] = (f_say, f_narr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--subdir", default=None, help="只统计路径含该子串的文件，可重复", action="append")
    ap.add_argument("--by-file", action="store_true", help="逐文件列出（只列数字，不含原文）")
    args = ap.parse_args()

    S = collections.Counter()
    speakers = collections.Counter()
    tags = collections.Counter()
    menus = []
    per_file = {}

    for dirpath, _d, names in os.walk(args.root):
        for n in sorted(names):
            if not n.endswith(".rpy"):
                continue
            full = os.path.join(dirpath, n)
            rel = os.path.relpath(full, args.root).replace("\\", "/")
            if args.subdir and not any(s in rel for s in args.subdir):
                continue
            S["文件数"] += 1
            analyze_file(full, S, speakers, tags, menus, per_file)

    print("=" * 64)
    print(f"剧本结构统计 v2   目录: {args.root}")
    if args.subdir:
        print(f"过滤: {args.subdir}")
    print("=" * 64)
    for k in ("文件数", "总行(有效)", "台词行(带说话人)", "旁白/独白行",
              "menu 数", "选项分支数"):
        print(f"  {k:<22} {S[k]}")

    denom = S["台词行(带说话人)"] + S["旁白/独白行"]
    if denom:
        print(f"  {'带说话人台词占比':<22} {S['台词行(带说话人)']/denom*100:.1f}%")
        print(f"  {'剧情文本总行数':<22} {denom}")

    print("\n--- 说话人分布 ---")
    for who, cnt in speakers.most_common():
        print(f"  {cnt:>6}  {who}")
    print(f"  (共 {len(speakers)} 个)")

    print("\n--- 行内富文本/噪声标签（决定 TextProc 复杂度）---")
    for name, cnt in tags.most_common():
        print(f"  {cnt:>6}  {name}")
    if not tags:
        print("  （无）")

    print("\n--- menu 分支分布 ---")
    if menus:
        dist = collections.Counter(menus)
        for k in sorted(dist):
            print(f"  {k} 分支 × {dist[k]} 处")
        print(f"  共 {len(menus)} 处")
    else:
        print("  （无）")

    if args.by_file:
        print("\n--- 逐文件（台词/旁白）---")
        for p, (a, b) in sorted(per_file.items(), key=lambda kv: -(kv[1][0] + kv[1][1])):
            if a + b == 0:
                continue
            print(f"  {a:>5} / {b:>5}   {os.path.relpath(p, args.root)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
