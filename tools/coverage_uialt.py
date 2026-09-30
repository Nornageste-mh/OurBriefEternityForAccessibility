#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""控件覆盖率核对 —— 反编译脚本里的每个 `imagebutton` 图，是否已有朗读文案。

为什么需要它（而不是靠人记）：
    无障碍补丁的「还差哪些控件」是个**纯粹的集合差**问题：
        脚本里出现过的 idle 图  −  逐作层表里写过的图  −  钩子/位置表覆盖的
    靠人记必然漏，而漏掉的控件在实机上表现是**安静**，最难发现。
    所以把它做成一条命令，发布前跑一次，输出就是待办清单。

用法：
    python tools/coverage_uialt.py
    python tools/coverage_uialt.py --screens extracted/scripts/scripts/screens \
                                   --table mod/game/a11y_game/22_uialt.rpy
"""

from __future__ import annotations

import argparse
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEF_SCREENS = os.path.join(REPO, "extracted", "scripts", "scripts", "screens")
DEF_MORE = [os.path.join(REPO, "extracted", "scripts", "scripts")]
DEF_TABLE = os.path.join(REPO, "mod", "game", "a11y_game", "22_uialt.rpy")

#: 只匹配**独立**的 `idle`，不能把 `selected_idle` / `hover_idle` 也算进来。
#:
#: ⚠ 这条是踩出来的：第一版用 `idle\s+"..."`，于是 `selected_idle "..._confim.png"`
#: 全部被当成 idle —— 覆盖率报告里凭空多出四十条「缺文案」，
#: 而它们其实是**同一个按钮的选中态图**，idle 那条早就写进表里了。
IDLE_RE = re.compile(r'(?<![_a-zA-Z])idle\s+"([^"]+)"')
IDLE_FMT_RE = re.compile(r'(?<![_a-zA-Z])idle\s+"([^"]*?)\{\}[^"]*"\.format')
LITERAL_RE = re.compile(r'"([^"]*\.(?:png|webp|jpg|jpeg))"')

#: 补丁**整屏覆盖**掉的界面：原版那些 imagebutton 不会被实例化，
#: 所以不需要（也不该）给它们写文案 —— 文案写在本补丁的覆盖版里。
#: 依据：`a11y_game/31_main_menu.rpy`（screen main_menu）与
#:       `a11y_game/30_choice.rpy`（screen choice）。
OVERRIDDEN_FILES = {"screen_main_menu.rpy", "screen_choice.rpy"}

#: 由**位置表**覆盖的图：表是按坐标写的，报告工具看不出对应关系，
#: 所以逐作层用 `A11Y_POS_IMAGES` 显式声明（**不在这里再维护一份**，
#: 免得两处清单漂移 —— 这条本身就是「单一来源」纪律的应用）。
POS_IMAGES_BLOCK = re.compile(r"A11Y_POS_IMAGES\s*=\s*\[(.*?)\]", re.S)


def pos_covered_images(table_path):
    txt = open(table_path, encoding="utf-8", errors="replace").read()
    m = POS_IMAGES_BLOCK.search(txt)
    if not m:
        return set()
    return {v.replace("\\", "/").rsplit("/", 1)[-1]
            for v in LITERAL_RE.findall(m.group(1))}

#: 由**钩子**按位置/序号给文案（不在表里出现也属已覆盖）。
HOOK_COVERED = {
    "sl_data_img_bg_empty.png",       # 存读档格子：按网格几何反推位号
    "extra_audio_list_bg_normal.png",  # 音声曲目：按行高反推行号
}


def scan_images(screens_dir):
    found = {}
    for dp, _d, ns in os.walk(screens_dir):
        for n in sorted(ns):
            if not n.endswith(".rpy"):
                continue
            if n in OVERRIDDEN_FILES:
                continue          # 补丁整屏覆盖掉了，原版控件不会出现
            p = os.path.join(dp, n)
            for i, line in enumerate(
                    open(p, encoding="utf-8", errors="replace").read().split("\n"), 1):
                # ⚠ 先判**循环生成**那一类再判普通 idle：`idle "…{}….png".format(i)`
                #   同样满足普通 idle 的形状，第一版因此把它当成一个**带花括号的
                #   图名**，前缀匹配就走不到了（永远差最后一条）。
                mfmt = IDLE_FMT_RE.search(line)
                if mfmt:
                    pre = mfmt.group(1).replace("\\", "/").rsplit("/", 1)[-1]
                    found.setdefault("<前缀: %s>" % pre, []).append(f"{n}:{i}")
                    continue
                m = IDLE_RE.search(line)
                if m:
                    img = m.group(1).replace("\\", "/").rsplit("/", 1)[-1]
                    found.setdefault(img, []).append(f"{n}:{i}")
    return found


def table_keys(table_path):
    txt = open(table_path, encoding="utf-8", errors="replace").read()
    keys = set()
    for m in LITERAL_RE.finditer(txt):
        v = m.group(1).replace("\\", "/")
        keys.add(v.rsplit("/", 1)[-1])
    return keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--screens", default=DEF_SCREENS)
    ap.add_argument("--table", default=DEF_TABLE)
    args = ap.parse_args()

    found = scan_images(args.screens)
    keys = table_keys(args.table)
    pos_keys = pos_covered_images(args.table)
    print("=" * 72)
    print(f"界面目录: {os.path.relpath(args.screens, REPO)}")
    print(f"文案表  : {os.path.relpath(args.table, REPO)}")
    print("=" * 72)
    print(f"脚本里出现的 idle 图：{len(found)} 种    "
          f"图片表：{len(keys)} 种    位置表声明：{len(pos_keys)} 种\n")

    missing = []
    for img, where in sorted(found.items()):
        if img in keys or img in HOOK_COVERED or img in pos_keys:
            continue
        # 循环生成的：表里有**同前缀**的条目就算覆盖
        if img.startswith("<前缀: ") and img.endswith(">"):
            # ⚠ 记得把标记的收尾 `>` 也去掉 —— 第一版只切了开头，
            #   于是前缀变成 `general_menu_page_>`，匹配永远不成立。
            pre = img[len("<前缀: "):-1]
            if any(k.startswith(pre) for k in keys):
                continue
            if any(v.startswith(pre) for v in pos_keys):
                continue
        missing.append((img, where))

    if not missing:
        print("✅ 全部 imagebutton 都已有朗读文案（表 或 钩子）")
        return 0
    print(f"⚠ 还有 {len(missing)} 种图没有文案：")
    for img, where in missing:
        print(f"  - {img:52s} {', '.join(where[:3])}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
