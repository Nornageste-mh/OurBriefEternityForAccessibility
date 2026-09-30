#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动证据核对 —— 跑完引擎 lint 之后，检查日志里**该出现的正向行是否都在**。

为什么需要它（一次真实事故）：
    清理死代码时我删掉了一个常量的定义，却漏掉一处引用，
    于是 `init` 抛 `NameError`、**init 链中断** —— 后面的按键层与播报层
    全部没有执行。而当时我的检查只有两条：`exit code` 与 `errors.txt`，
    **两条都通过**（Ren'Py 的 lint 把异常写进日志却仍以 0 退出）。

    同一个坑这一轮之前已经踩过一次：兜底播报"改了三版都没区别"，
    也是因为代码根本没跑，而日志里既没有成功记录、也没有失败记录。

    所以：**验证不能只看"没报错"，要看"该出现的东西出现了没有"**。
    这就是本脚本存在的理由 —— 它检查的是正向证据。

用法：
    python tools/check_boot.py            # 默认读游戏目录的 log.txt
    python tools/check_boot.py --log <路径>
"""

from __future__ import annotations

import argparse
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_LOG = r"F:\Steam\steamapps\common\永恒与星辰与日常\log.txt"

#: (正向证据，为什么它重要)
EVIDENCE = [
    ("契约: 游戏=", "契约层初始化"),
    ("已接管 config.tts_function", "朗读出口接管"),
    ("后端结论:", "朗读后端探测"),
    ("A11yRenpy 已启动", "适配层启动"),
    ("已登记重读键", "重读键登记"),
    ("已插入按键层", "★ 按键层插入（它没出现 ⇒ init 链断过）"),
    ("已登记线性导航键 A11yNavUp", "线性导航键登记"),
    ("无配音角色推导:", "★ 无配音角色推导（它管主角台词会不会被吞）"),
]

#: 出现即算失败（异常痕迹）
BAD = ["Traceback", "NameError", "AttributeError", "登记键盘绑定失败",
       "alt 注入扫描异常", "控件扫描异常", "未接管"]

#: 正向证据，但不是每次都必然出现（只提示，不算失败）
SOFT = ["[alt] 心跳"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=DEFAULT_LOG)
    args = ap.parse_args()

    if not os.path.exists(args.log):
        print(f"找不到日志：{args.log}")
        return 2
    text = open(args.log, "rb").read().decode("utf-8", errors="replace")
    lines = text.splitlines()

    print("=" * 72)
    print("启动证据核对：", args.log)
    print("=" * 72)

    miss = 0
    for needle, why in EVIDENCE:
        if any(needle in l for l in lines):
            print(f"  OK   {why}")
        else:
            miss += 1
            print(f"  ✗✗✗  {why}  —— 没找到 {needle!r}")

    print()
    bad = 0
    for needle in BAD:
        hit = [l for l in lines if needle in l]
        if hit:
            bad += 1
            print(f"  ✗✗✗  日志里有异常痕迹 {needle!r}：{hit[0][:120]}")
            for l in hit[1:4]:
                print(f"        {l[:120]}")

    for needle in SOFT:
        if any(needle in l for l in lines):
            print(f"  OK   {needle}（本层跑过）")
        else:
            print(f"  --   {needle} 未出现（lint 不跑交互，属正常）")

    print()
    ok = (miss == 0 and bad == 0)
    print(f"结论：{'启动证据齐全' if ok else str(miss + bad) + ' 项不合格'}")
    print("=" * 72)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
