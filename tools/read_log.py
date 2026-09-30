#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只把补丁自己的日志行从 log.txt 里捞出来。

⚠ **本工具的输出含剧本原文**（`CfgDiagLog=True` 时 `[A11y朗读]` 行就是台词）。
按上游流水线 §6 P1 的 IP 红线：**不得入库、不得外传**，
只在本机排查时看，或者只把「必要的那几行」发给维护者。

用法：
    python tools/read_log.py                      # 默认读游戏的 log.txt
    python tools/read_log.py --path <log 路径>
    python tools/read_log.py --no-text            # 剔除含朗读内容的行（可外发）
    python tools/read_log.py --errors             # 只看错误与异常
"""

from __future__ import annotations

import argparse
import io
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_LOG = os.path.join(
    os.environ.get("ETERNITY_GAME_DIR", r"F:\Steam\steamapps\common\永恒与星辰与日常"),
    "log.txt")

#: 日志编码：Ren'Py 在 Windows 上按本地代码页写文件，
#: 而补丁写进去的是 UTF-8 字符串 —— 实测结果是 UTF-8 内容被当作单字节写入，
#: 用 utf-8 + replace 读回来即可（GBK 读会乱码）。
ENCODINGS = ("utf-8", "utf-8-sig", "gbk", "cp936", "latin-1")

ERROR_RE = re.compile(r"Traceback|Error|Exception|报错|异常|not a keyword")


def read_any(path):
    raw = open(path, "rb").read()
    best = None
    for enc in ENCODINGS:
        try:
            text = raw.decode(enc)
        except Exception:
            continue
        # 用「中文与 ASCII 是否都像样」来挑最优解码：
        # 乱码会带来大量替换字符或罕见符号。
        bad = text.count("\ufffd") + len(re.findall(r"[\u00c0-\u00ff]{4,}", text))
        if best is None or bad < best[0]:
            best = (bad, enc, text)
        if bad == 0:
            break
    if best is None:
        raise SystemExit(f"无法解码 {path}")
    return best[1], best[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=DEFAULT_LOG)
    ap.add_argument("--no-text", action="store_true",
                    help="剔除含朗读内容的行（输出可外发）")
    ap.add_argument("--errors", action="store_true", help="只看错误与异常")
    ap.add_argument("--tail", type=int, default=0, help="只看最后 N 行")
    args = ap.parse_args()

    if not os.path.exists(args.path):
        raise SystemExit(f"找不到日志：{args.path}")

    enc, text = read_any(args.path)
    lines = text.splitlines()
    print(f"# 日志: {args.path}")
    print(f"# 编码判定: {enc}   总行数: {len(lines)}")
    print()

    picked = []
    for l in lines:
        if args.errors:
            if ERROR_RE.search(l):
                picked.append(l)
            continue
        if "[A11y" not in l:
            continue
        if args.no_text and ("[A11y朗读]" in l or "root_tts" in l or "_tts=" in l):
            continue
        picked.append(l)

    if args.tail:
        picked = picked[-args.tail:]

    for l in picked:
        print(l[:400])

    print()
    print(f"# 命中 {len(picked)} 行")
    if not args.no_text and not args.errors:
        print("# ⚠ 以上可能含剧本原文 —— 按 IP 红线不得提交、不得外传。")
        print("#   要外发请加 --no-text。")


if __name__ == "__main__":
    raise SystemExit(main())
