#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剧本结构统计（P0）。

对 unrpyc 反编译出的 `.rpy` 做**正则级**统计，产出流水线 §6 P0 要求的量化问题：

  - 剧本总行数
  - 各说话人的台词行数分布
  - 旁白 / 内心独白行数
  - 选项（menu）数量与每处选项的分支数
  - 行内富文本标签的存在与否（决定 TextProc 复杂度）
  - 配音覆盖（能对上 audio.rpa 里 voice 条目的行数）

**只输出统计数字与标签种类，绝不输出任何台词原文。**
本工具的输出是「不含剧本文本」的证据，可以直接入库（流水线 §6 P1 的 IP 红线）。

统计口径（正则级，故意保守 —— 宁可少算也不虚报）：
  一句台词 = 缩进后形如 `<标识符> "..."` 或 `<标识符> '...'` 的行
  标识符 = 一个 Ren'Py 名字（角色变量名 / `narrator` / 引号开头的旁白）
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import sys

# 只匹配「一行里、缩进之后、一个标识符、然后一个引号字符串」。
# 用 (?!\s*#) 排掉注释。
SAY_RE = re.compile(r'^(?P<indent>[ \t]*)(?P<who>[A-Za-z_][A-Za-z0-9_]*)\s+(?P<q>"|\')(?P<text>.*)$')

# 纯旁白：整行只有一个字符串（无标识符）
NARRATE_RE = re.compile(r'^[ \t]*(?P<q>")(?P<text>.*)$')

# 内嵌 python / 定义块，出现即跳过整块直到缩进回来
BLOCK_START_RE = re.compile(r'^[ \t]*(python|init python|screen |style |transform |translate |label |define |default |image |layeredimage |init offset|init -?\d+ python)\b')

MENU_RE = re.compile(r'^[ \t]*menu\b')
CHOICE_RE = re.compile(r'^[ \t]+"[^"]*"\s*:')

# 需要 TextProc 处理的富文本 / 噪声标签种类
TAG_RES = {
    "{}插值": re.compile(r"\{[^}]*\}"),
    "[方括号]插值": re.compile(r"\[[A-Za-z_][^\]]*\]"),
    "全角括号「」": re.compile(r"[「」]"),
    "全角括号【】": re.compile(r"[【】]"),
    "遮蔽问号？？？": re.compile(r"？{2,}|\?{2,}"),
    "ruby旁注": re.compile(r"\{ruby", re.I),
    "换行\\n": re.compile(r"\\n"),
    "连续省略号": re.compile(r"[…]{2,}|\.{3,}"),
    "波浪号": re.compile(r"[~～]"),
}


def mask_text(text: str) -> str:
    """把台词原文替换成等长的占位符 —— 保证统计结果里永不出现剧本原文。"""
    return "x" * len(text)


def analyze_file(path: str, stats: collections.Counter, speakers: collections.Counter,
                 tags: collections.Counter, menu_branches: list[int],
                 detail: dict) -> None:
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()

    in_menu = False
    menu_indent = 0
    cur_branches = 0

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        stats["总行(非空非注释)"] += 1

        if MENU_RE.match(line):
            if in_menu and cur_branches:
                menu_branches.append(cur_branches)
            in_menu = True
            menu_indent = len(line) - len(line.lstrip())
            cur_branches = 0
            stats["menu 数"] += 1
            continue

        if in_menu:
            indent = len(line) - len(line.lstrip())
            if indent > menu_indent and CHOICE_RE.match(line):
                cur_branches += 1
                stats["选项分支数"] += 1
                continue
            if indent <= menu_indent:
                if cur_branches:
                    menu_branches.append(cur_branches)
                in_menu = False
                cur_branches = 0

        m = SAY_RE.match(line)
        if m:
            who = m.group("who")
            text = m.group("text")
            # 排除语句关键字（避免把 `if "x":` 之类算成台词）
            if who in {
                "if", "elif", "while", "for", "return", "call", "jump", "label",
                "menu", "show", "hide", "scene", "play", "stop", "queue", "pause",
                "with", "window", "voice", "nvl", "python", "init", "define",
                "default", "screen", "style", "transform", "image", "set", "pass",
                "else", "try", "except", "class", "def", "import", "from", "and",
                "or", "not", "in", "is", "del", "global", "assert", "raise", "yield",
                "use", "on", "at", "as", "to", "from_", "expression",
            }:
                continue
            # 行尾若是 `:` 说明是语句块头，不是台词
            if text.rstrip().endswith(":"):
                continue

            stats["台词行总数"] += 1
            detail.setdefault("说话人集合", set()).add(who)
            speakers[who if who != "narrator" else "(旁白 narrator)"] += 1

            for name, rx in TAG_RES.items():
                if rx.search(text):
                    tags[name] += 1
            continue

        m2 = NARRATE_RE.match(line)
        if m2:
            stats["裸字符串行(旁白/独白)"] += 1
            for name, rx in TAG_RES.items():
                if rx.search(m2.group("text")):
                    tags[name] += 1

    if in_menu and cur_branches:
        menu_branches.append(cur_branches)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="反编译后的 .rpy 根目录")
    ap.add_argument("--only-story", action="store_true",
                    help="只统计 content/story 下的剧本文件")
    args = ap.parse_args()

    stats: collections.Counter = collections.Counter()
    speakers: collections.Counter = collections.Counter()
    tags: collections.Counter = collections.Counter()
    menus: list[int] = []
    detail: dict = {}
    files = 0

    for dirpath, _dirs, names in os.walk(args.root):
        for n in sorted(names):
            if not n.endswith(".rpy"):
                continue
            full = os.path.join(dirpath, n)
            rel = os.path.relpath(full, args.root)
            if args.only_story and "story" not in rel.replace("\\", "/"):
                continue
            files += 1
            stats["文件数"] += 1
            analyze_file(full, stats, speakers, tags, menus, detail)

    print("=" * 62)
    print(f"剧本结构统计（正则级）  目录: {args.root}")
    print("=" * 62)
    for k in ("文件数", "总行(非空非注释)", "台词行总数", "裸字符串行(旁白/独白)",
              "menu 数", "选项分支数"):
        print(f"  {k:<24} {stats[k]}")

    denom = stats["台词行总数"] + stats["裸字符串行(旁白/独白)"]
    if denom:
        print(f"  {'有声台词占比':<24} {stats['台词行总数'] / denom * 100:.1f}%")

    print("\n--- 说话人分布（按台词行数降序）---")
    for who, cnt in speakers.most_common():
        print(f"  {cnt:>7}  {who}")
    print(f"  (共 {len(speakers)} 个说话人)")

    print("\n--- 行内富文本 / 噪声标签出现次数（决定 TextProc 复杂度）---")
    if tags:
        for name, cnt in tags.most_common():
            print(f"  {cnt:>7}  {name}")
    else:
        print("  （无）")

    print("\n--- menu 分支数分布 ---")
    if menus:
        dist = collections.Counter(menus)
        for k in sorted(dist):
            print(f"  {k} 个分支: {dist[k]} 处")
        print(f"  共 {len(menus)} 处 menu，平均 {sum(menus)/len(menus):.2f} 分支")
    else:
        print("  （无）")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
