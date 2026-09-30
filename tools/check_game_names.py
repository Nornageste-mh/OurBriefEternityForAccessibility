#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""游戏侧名字核对 —— 补丁引用的每个「本作的名字」是否真的存在。

为什么需要它：
    补丁引用的都是**游戏侧的 store 变量与函数**（`data_group`、
    `asmr_track_names`、`is_asmr_track_unlocked` …）。
    Python 里读一个不存在的属性通常是异常，而这些地方**全都包在
    try/except 里**（补丁绝不能因为读不到一个变量就把游戏拖垮）——
    于是名字写错的后果不是报错，而是**静默退化成"没有文案"**：
    玩家听到的是安静，维护者看到的日志是「未识别」，
    两边都以为「还没做」，其实是**做错了**。

    所以把「这些名字存在吗」变成一条命令。名字清单在下面 `NEEDED` 里，
    每条都写明**它撑起哪个功能** —— 哪天游戏更新改了名，这条会先红。

用法：
    python tools/check_game_names.py
    python tools/check_game_names.py --scripts extracted/scripts/scripts
"""

from __future__ import annotations

import argparse
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEF_SCRIPTS = os.path.join(REPO, "extracted", "scripts", "scripts")

#: (名字, 它撑起什么, 期望最先出现在哪个文件里 —— 只用于提示)
NEEDED = [
    ("persistent._file_page", "存读档槽位名的页号（`FilePage` 会改它）", "00action_file"),
    ("renpy.slot_mtime", "存档位是空还是有存档（引擎 API）", "renpy/loadsave.py"),
    ("asmr_track_files", "音声曲目总数（决定列表有几行）", "music.rpy"),
    ("asmr_track_names", "音声曲目的短名（「音声 01」）", "music.rpy"),
    ("asmr_track_titles", "音声曲目的正式标题", "music.rpy"),
    ("asmr_track_unlock_hints", "未解锁曲目显示什么（照画面念）", "music.rpy"),
    ("is_asmr_track_unlocked", "哪些曲目已解锁（决定行号→曲目号）", "music.rpy"),
    ("data_group", "立绘页六行的当前取值", "stand_mode.rpy"),
    ("data_group_max", "立绘页每行的取值范围（核对行数=6）", "stand_mode.rpy"),
    ("persistent.gallery_unlocked", "主菜单「特殊模式」是否解锁", "options.rpy"),
    ("gallery_groups", "画廊的 CG 分组（决定分页数）", "screen_gallery.rpy"),
    ("movie_items", "画廊的影片清单", "screen_gallery.rpy"),
    ("is_mov_unlocked", "哪些影片已解锁", "screen_gallery.rpy"),
]


def iter_text(root):
    for dp, _d, ns in os.walk(root):
        for n in sorted(ns):
            if n.endswith((".rpy", ".rpym")):
                p = os.path.join(dp, n)
                try:
                    yield p, open(p, encoding="utf-8", errors="replace").read()
                except Exception:
                    continue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scripts", default=DEF_SCRIPTS)
    ap.add_argument("--game-dir", default=os.environ.get(
        "ETERNITY_GAME_DIR", r"F:\Steam\steamapps\common\永恒与星辰与日常"))
    args = ap.parse_args()

    print("=" * 72)
    print("游戏侧名字核对")
    print(f"脚本目录: {os.path.relpath(args.scripts, REPO)}")
    print("=" * 72)

    blobs = {}
    if os.path.isdir(args.scripts):
        for p, t in iter_text(args.scripts):
            blobs[p] = t
    # 引擎侧的（`renpy.slot_mtime`）也一并搜：游戏目录里带着引擎源码
    if os.path.isdir(args.game_dir):
        for p, t in iter_text(os.path.join(args.game_dir, "renpy")):
            blobs[p] = t

    if not blobs:
        print("⚠ 一个脚本都没读到 —— 先用 tools/rpa.py 解出剧本，或改 --scripts")
        return 2

    miss = 0
    for name, why, hint in NEEDED:
        pat = re.compile(r"\b%s\b" % re.escape(name.split(".")[-1]))
        hit = None
        for p, t in blobs.items():
            if pat.search(t):
                hit = os.path.relpath(p, REPO)
                break
        if hit:
            print(f"  OK   {name:28s} {why}")
        else:
            miss += 1
            print(f"  ✗✗✗  {name:28s} **找不到** —— {why}（期望在 {hint}）")

    # 立绘六行：顺带核一下行数与标签数是否一致
    dg = None
    for p, t in blobs.items():
        m = re.search(r"define\s+data_group\s*=\s*\[([^\]]*)\]", t)
        if m:
            dg = [x.strip() for x in m.group(1).split(",") if x.strip()]
            break
    if dg is not None:
        n = len(dg)
        ok = (n == 6)
        if not ok:
            miss += 1
        print(f"  {'OK  ' if ok else '✗✗✗ '} 立绘行数 = {n}"
              f"（逐作层 `_STAND_GROUPS` 有 6 条标签，必须相等）")

    print()
    print(f"结论：{'全部存在' if miss == 0 else str(miss) + ' 个名字有问题'}")
    print("=" * 72)
    return 0 if miss == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
