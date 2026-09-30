#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线静态断言 —— 对应上游 A11yFramework 的 `tools/compile_check.ps1`。

上游那支脚本做的是：「编译 platform/ + contract/ 时**不引用 Assembly-CSharp**」，
用来机械证明「平台层没有游戏类型依赖」。

Ren'Py 这一侧没有「编译期不引用某程序集」这回事，所以本工具换成三条**可机械判定**的断言：

  断言 A（语法）  每个 `init python:` 块能被 CPython 的 ast 解析 ——
                  等价于「引擎加载时不会因语法错误炸掉」。
                  实测价值：本补丁开发期真正抓到过 NameError 与缩进/删行事故，
                  靠的都是这一条加上实机 log.txt。

  断言 B（分层）  `a11y_platform/` 下的文件**不得出现本作专有标识符**
                  （角色变量名、界面名、作品名……）。
                  这是上游「共享层绝不允许引用任何游戏类型」那条红线的落地。
                  本作的标识符清单在下面 GAME_TOKENS 里，逐作要改。

  断言 C（唯一出口）逐作层不得绕过重读缓冲区直接调后端 ——
                  对应上游 `tools/lint_repeat.ps1` 的静态断言。

  断言 D（键名）  凡出现在字符串字面量里的 `K_xxx` 都必须能被**玩家机器上的**
                  引擎键表解释 —— 写错一个键名会让游戏**完全起不来**
                  （`init_keymap()` 会对每个键名做 `eval`）。

  断言 E（无参）  ★★ 进 `renpy.Keymap` 的处理对象必须是**无参**可调用对象 ★★
                  `Keymap.event` 是 `run(action)`（无参）调用它的
                  （`behavior.py:559` -> `:411`），所以处理函数里
                  「读事件」等于**永久失效** —— 补丁的 F5 重读键
                  就这么白扔过一整轮，而日志上什么都看不出来。
                  这条断言就是要让那种错误**在提交前**就红。

用法：
    python tools/lint_patch.py                 # 检查 mod/game 下的全部文件
    python tools/lint_patch.py --dir <路径>
"""

from __future__ import annotations

import argparse
import ast
import glob
import io
import os
import re
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIR = os.path.join(REPO, "mod", "game")

#: 本作专有标识符 —— 平台层出现任何一个都算越界。
#: 依据：scripts/roles/role.rpy（角色变量）、scripts/screens/*（界面名）、
#: options.rpy（作品名与目录名）。逐作复用本工具时必须替换这一段。
GAME_TOKENS = [
    # 角色变量（role.rpy 实查，15 个 Character 定义）
    "tsa_", "tsb_", "tsc_", "fd_", "sy_", "syxm_", "xm_", "fwy_",
    "lxc_", "lxcxm_", "lxcsy_", "zfsn_", "yfsn_", "temp_", "temp_2",
    "rszg_", "tz_",
    # 本作界面名（scripts/screens/ 实查）
    "main_menu_extral", "screen_gallery", "stand_mode", "heroine_effect_screen",
    "screen_bubble",
    # 本作特有的持久化变量 / 控件脚本
    "stockings_color", "system_voice_shiyu", "system_voice_xingmi",
    "instant_display_read_text", "skip_after_choices", "auto_after_choices",
    "VirtualViewport", "PlayCharacterVoice", "MyAudioPositionValue",
    # 作品标识
    "OurBriefEternity", "永恒与星辰与日常",
    "林小凑", "时语", "星弥",
]

#: 逐作层不得直接调后端（必须走 A11yRepeat.say）
BACKEND_CALLS = [
    "A11yHost.speech.speak",
    "nvdaController_speakText",
    "Tolk_Output",
]

INIT_RE = re.compile(r"^init\s+(-?\d+)?\s*python\s*:\s*$")

#: `.rpy` **顶层**允许出现的语句关键字。
#:
#: 这条断言是**补上的**，起因是一次真实事故：`31_main_menu.rpy` 里把两个
#: Python 函数写成了裸的顶层 `def`，引擎直接拒绝解析整份脚本：
#:
#:     File "game/a11y_game/31_main_menu.rpy", line 50: expected statement.
#:       def _a11y_main_menu_items():
#:
#: 而当时的断言 A **只检查 `init python:` 块内部的语法**，块外一眼都没看，
#: 所以没拦住 —— 玩家打开游戏看到的是「解析脚本失败」的报错页。
#: 教训：安全网要盖住**整份文件的结构**，不能只盖住自己关心的那一小块。
#:
#: 允许的顶层形式（Ren'Py 官方语句）：
#:   screen / label / define / default / init / init python / python /
#:   image / transform / style / translate / menu / layeredimage / at /
#:   key / on / use / call / jump / return / $ / if / while / for / pass
TOP_LEVEL_RE = re.compile(
    r"^(?:"
    r"screen\b|label\b|define\b|default\b|init\b|python\b|image\b|transform\b|"
    r"style\b|translate\b|menu\b|layeredimage\b|at\b|key\b|on\b|use\b|call\b|"
    r"jump\b|return\b|if\b|elif\b|else\b|while\b|for\b|pass\b|\$|"
    r"#|@"
    r")"
)


def iter_rpy(root):
    for dirpath, _d, names in os.walk(root):
        for n in sorted(names):
            if n.endswith(".rpy"):
                yield os.path.join(dirpath, n)


def strip_comments_and_strings(text):
    """粗略剥掉 `#` 注释与字符串字面量，只留代码。

    用途：断言 I 要在**代码里**找 `A11yHost.X` 引用，而文档/日志字符串里
    顺口提一句（例如「上游 `contract/A11yHost.cs` 的对应物」）不该被算进去。
    不追求完备（Ren'Py 的 python 块就是普通 Python，这里够用），
    只求把注释与引号内的内容拿掉。
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "#":
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif c in "'\"":
            quote = c
            triple = text[i:i + 3] == quote * 3
            if triple:
                j = text.find(quote * 3, i + 3)
                i = n if j < 0 else j + 3
            else:
                j = i + 1
                while j < n:
                    if text[j] == "\\":
                        j += 2
                        continue
                    if text[j] == quote or text[j] == "\n":
                        break
                    j += 1
                i = j + 1
            out.append(' "" ')
        else:
            out.append(c)
            i += 1
    return "".join(out)


def check_encoding(files):
    """★ BOM / 编码自查 —— 这条是**因为一次自己制造的事故**加的。

    事故：我用 PowerShell 的 `Get-Content ... | Set-Content -Encoding UTF8`
    改一行版本号，结果
      · 读的时候按 GBK 解码 → 中文全变乱码；
      · 写的时候加了 UTF-8 BOM。
    于是 `.rpy` 首行变成 `\\ufeff# ...`，引擎直接报
    「顶层出现非 Ren'Py 语句」，**并把这份坏文件装进了游戏目录**
    （`errors.txt` 当场生成）。

    这条教训其实早写在仓库的陷阱清单里（「.ps1 与 .rpy 的编码」）——
    知道却再犯，说明**光靠记性不够，得让机器拦**。
    判据很简单：`.rpy` 不该有 BOM（Ren'Py 自己要的是无 BOM UTF-8）。
    """
    bad = 0
    for f in files:
        try:
            head = open(f, "rb").read(3)
        except Exception:
            continue
        if head == b"\xef\xbb\xbf":
            bad += 1
            print(f"  ✗ {os.path.relpath(f)} 带 UTF-8 BOM —— "
                  f"Ren'Py 会把首行当成非法语句（多为 PowerShell 改写所致）")
    return bad


def load_pygame_pool(game_python, game_dir):
    """拿引擎的 pygame 键表（用于断言 D）。

    做法：用**游戏自带的运行时 Python** 起一个子进程，让它把
    `renpy.pygame` 里所有 `K_` 开头的属性名打出来。
    这样校验用的就是**玩家机器的引擎**，而不是我这边的猜测。
    """
    if not game_python or not os.path.exists(game_python):
        return None
    code = (
        "import sys;sys.path.insert(0,sys.argv[1]);"
        "import renpy,renpy.pygame;"
        "print('\\n'.join(sorted(n for n in dir(renpy.pygame) if n.startswith('K_'))))"
    )
    try:
        out = subprocess.run([game_python, "-c", code, game_dir or ""],
                             capture_output=True, text=True, timeout=90)
    except Exception:
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return set(out.stdout.split())


def extract_init_blocks(path):
    """产出 (起始行号, 代码文本) 给每个 `init python:` 块。"""
    lines = io.open(path, encoding="utf-8").read().splitlines()
    i = 0
    while i < len(lines):
        if INIT_RE.match(lines[i]):
            j = i + 1
            body = []
            while j < len(lines):
                l = lines[j]
                if l.strip() and not l.startswith("    "):
                    break
                body.append(l[4:] if l.startswith("    ") else l)
                j += 1
            yield i + 1, "\n".join(body)
            i = j
        else:
            i += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--game-python", default=os.environ.get("ETERNITY_PYTHON"),
                    help="游戏自带的运行时 python.exe（用于键名校验）")
    ap.add_argument("--game-dir", default=os.environ.get(
        "ETERNITY_GAME_DIR", r"F:\Steam\steamapps\common\永恒与星辰与日常"))
    args = ap.parse_args()

    if not args.game_python:
        guess = os.path.join(args.game_dir, "lib", "py3-windows-x86_64", "python.exe")
        if os.path.exists(guess):
            args.game_python = guess

    files = list(iter_rpy(args.dir))
    if not files:
        print(f"没有找到 .rpy（目录: {args.dir}）")
        return 2

    fails = 0
    print("=" * 72)
    print(f"离线静态断言  目录: {args.dir}  文件数: {len(files)}")
    print("=" * 72)

    # ---------------- 断言 A0：文件编码（BOM）----------------
    print("\n[断言 A0] .rpy 不得带 BOM（PowerShell 改写的典型痕迹）")
    enc_bad = check_encoding(files)
    fails += enc_bad
    print(f"  {'编码干净' if enc_bad == 0 else str(enc_bad) + ' 个文件带 BOM'}")

    # ---------------- 断言 A：语法 ----------------
    print("\n[断言 A] init python 块语法")
    blocks = 0
    for f in files:
        rel = os.path.relpath(f, args.dir)
        for lineno, code in extract_init_blocks(f):
            blocks += 1
            try:
                ast.parse(code)
            except SyntaxError as e:
                fails += 1
                print(f"  ✗ {rel}:{lineno}  {e.msg}（块内第 {e.lineno} 行）")
    print(f"  {blocks} 个 init 块，{'全部通过' if fails == 0 else str(fails) + ' 处语法错误'}")

    # ---------------- 断言 A2：顶层结构 ----------------
    # 堵住「顶层裸 def」那一类 —— 引擎会直接报「解析脚本失败」，
    # 而断言 A 只看 init 块内部，盖不到。
    print("\n[断言 A2] .rpy 顶层只允许 Ren'Py 语句")
    top_bad = 0
    for f in files:
        rel = os.path.relpath(f, args.dir)
        lines = io.open(f, encoding="utf-8").read().splitlines()
        for n, line in enumerate(lines, 1):
            if not line.strip():
                continue
            # 只有**零缩进**的行才是顶层语句
            if line[0] in " \t":
                continue
            if not TOP_LEVEL_RE.match(line):
                top_bad += 1
                tok = line.strip().split("(")[0][:48]
                print(f"  ✗ {rel}:{n}  顶层出现非 Ren'Py 语句: {tok!r}")
    fails += top_bad
    print(f"  {'未发现顶层非法语句' if top_bad == 0 else str(top_bad) + ' 处非法顶层语句'}")

    # ---------------- 断言 B：分层 ----------------
    print("\n[断言 B] a11y_platform/ 不得出现本作专有标识符")
    platform = [f for f in files if os.sep + "a11y_platform" + os.sep in f]
    leak = 0
    for f in platform:
        rel = os.path.relpath(f, args.dir)
        text = io.open(f, encoding="utf-8").read()
        for tok in GAME_TOKENS:
            if tok in text:
                # 注释里引用依据是允许的？不 —— 上游的做法是平台层「一处都不许有」，
                # 但逐作依据写在注释里是可读性所需，因此这里只对**代码行**报错。
                for n, line in enumerate(text.splitlines(), 1):
                    if tok in line and not line.lstrip().startswith("#"):
                        leak += 1
                        print(f"  ✗ {rel}:{n}  出现本作标识符 {tok!r}")
    fails += leak
    print(f"  平台层 {len(platform)} 个文件，{'未越界' if leak == 0 else str(leak) + ' 处越界'}")

    # ---------------- 断言 C：唯一出口 ----------------
    print("\n[断言 C] 逐作层不得绕过重读缓冲区直呼后端")
    game = [f for f in files if os.sep + "a11y_game" + os.sep in f]
    direct = 0
    for f in game:
        rel = os.path.relpath(f, args.dir)
        for n, line in enumerate(io.open(f, encoding="utf-8").read().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for call in BACKEND_CALLS:
                if call in line:
                    direct += 1
                    print(f"  ✗ {rel}:{n}  直接调用 {call}（应走 A11yRepeat.say）")
    fails += direct
    print(f"  逐作层 {len(game)} 个文件，{'未绕过' if direct == 0 else str(direct) + ' 处绕过'}")

    # ---------------- 断言 D：键名必须存在 ----------------
    # 事故背景（实机复现，代价极大）：
    #   补丁在 keymap 里写 `K_KP_UP` / `K_KP_DOWN` / `K_KP_HOME` / `K_KP_END`，
    #   而 pygame 里**没有**这些名字。`renpy/display/behavior.py:231` 的
    #   `init_keymap()` 会对 keymap 里每个键名做 `eval`：
    #       check_code = eval("lambda ev : " + compile_event(keysym, True), globals())
    #   一个不存在的名字直接抛 AttributeError，而且发生在
    #   「初始化之后、游戏开始之前」—— **游戏完全无法启动**。
    # 所以：凡是出现在字符串字面量里的 `K_xxx`，都必须能在引擎的键表里找到。
    print("\n[断言 D] keymap 键名必须被引擎认识")
    key_literals = {}
    key_re = re.compile(r'"(K_[A-Z0-9_]+)"')
    for f in files:
        rel = os.path.relpath(f, args.dir)
        for n, line in enumerate(io.open(f, encoding="utf-8").read().splitlines(), 1):
            for m in key_re.finditer(line):
                key_literals.setdefault(m.group(1), []).append(f"{rel}:{n}")

    if not key_literals:
        print("  没有发现 K_* 字面量")
    else:
        pool = load_pygame_pool(args.game_python, args.game_dir)
        if pool is None:
            print(f"  ⚠ 拿不到引擎键表（--game-python 未给或执行失败），"
                  f"跳过校验；共 {len(key_literals)} 个键名未经验证")
        else:
            bad_keys = 0
            for k, where in sorted(key_literals.items()):
                if k not in pool:
                    bad_keys += 1
                    print(f"  ✗ 引擎不认识 {k}  —— 出现在 {', '.join(where[:3])}")
            fails += bad_keys
            print(f"  {len(key_literals)} 个键名，"
                  f"{'全部存在' if bad_keys == 0 else str(bad_keys) + ' 个不存在'}")

    # ---------------- 断言 E：Keymap 的值必须是无参可调用对象 ----------------
    # ★★ 事故背景（代价最大的一次：用户实机反馈「重读无效」）★★
    #
    #   `renpy.Keymap` 把字典的值当**无参可调用对象**执行：
    #
    #       renpy/display/behavior.py:550-565   Keymap.event
    #           for name, action in self.keymap.items():
    #               if map_event(ev, name):
    #                   rv = run(action)            # ← 没有参数
    #       renpy/display/behavior.py:384-411   run
    #           return action(*args, **kwargs)      # ← args 空
    #
    #   补丁第一版把处理函数写成 `def on_key(self, *args, **kwargs)` 并去读 `ev`，
    #   于是 `ev` 恒为 `None`、函数恒在开头早退 —— **那个键从装上那天起就是死的**，
    #   而日志里一行痕迹都没有（代码根本没跑到），排查时误以为是后端问题。
    #
    #   这条断言把「引擎是怎么调用它的」变成机械保证：
    #     1. 进 Keymap 的对象只能来自白名单（按字面写法核对）；
    #     2. 白名单里每个函数都必须在源码里以**无参**签名定义；
    #     3. `renpy.Keymap` 只允许用 `**binds` 构造（不许另起一处手写）。
    #
    #   同类的另一条（已由断言 D 覆盖）：键名写错会让游戏起不来。
    #   两条合起来就是「挂载点必须证明它真的能触发」的机械版。
    print("\n[断言 E] Keymap 的键处理对象必须是无参可调用对象")
    keymap_path = None
    for f in files:
        if os.path.basename(f) == "06_keymap.rpy":
            keymap_path = f
            break

    km_fail = 0
    if keymap_path is None:
        print("  ⚠ 没找到 06_keymap.rpy，跳过")
    else:
        km_text = io.open(keymap_path, encoding="utf-8").read()
        km_rel = os.path.relpath(keymap_path, args.dir)

        # 3) Keymap 只允许 _A11yKeymap(**binds) 这一种构造方式
        for c in re.findall(r"_A11yKeymap\(([^)]*)\)", km_text):
            if c.strip() != "**binds":
                km_fail += 1
                print(f"  ✗ {km_rel}  Keymap 构造方式非法: "
                      f"_A11yKeymap({c.strip()})（只允许 _A11yKeymap(**binds)）")

        # 1) 每个 binds[...] = [...] 的值都在白名单里
        #    ⚠ 数字那一条接受 `_A11yDigitAction(i)` 这种**循环变量**写法：
        #      闭包捕获的是「第几个数字」，仍然是无参对象。
        allowed_value = re.compile(
            r"^\[(?:A11yHost\.repeat\.on_key"
            r"|A11yHost\.keys\.on_backend_cycle"
            r"|A11yHost\.keys\.on_read_screen"
            r"|A11yHost\.keys\.on_diag"
            r"|_A11yDigitAction\(\w+\)"
            r"|_A11yNavAction\(-?1\))\]$")
        for n, line in enumerate(km_text.splitlines(), 1):
            m = re.match(r"^binds\[[^\]]+\]\s*=\s*(.+)$", line.strip())
            if not m:
                continue
            if not allowed_value.match(m.group(1).strip()):
                km_fail += 1
                print(f"  ✗ {km_rel}:{n}  binds 的值不在白名单里: {m.group(1).strip()}"
                      f"（Keymap 会无参调用它 —— 读事件 = 该键永久失效）")

        # 2) 白名单里的函数必须无参定义
        #    ⚠ 「带参数」的判据是 `self` **后面跟逗号**（`def on_key(self, ...)`）。
        #      第一版写成 `\(self\s*[,)]`，把合法的 `def on_key(self):`
        #      也一起报了出来 —— 安全网本身写错，比没有安全网更浪费时间。
        required = [
            (os.path.join("a11y_platform", "05_repeat.rpy"),
             r"^        def on_key\(self\):\s*$",
             r"def on_key\(self\s*,"),
            (os.path.join("a11y_platform", "06_keymap.rpy"),
             r"^        def on_backend_cycle\(self\):\s*$",
             r"def on_backend_cycle\(self\s*,"),
            (os.path.join("a11y_platform", "06_keymap.rpy"),
             r"^        def _act\(\):\s*$",
             r"def _act\([^)]"),
            (os.path.join("a11y_platform", "06_keymap.rpy"),
             r"^        def _nav_act\(\):\s*$",
             r"def _nav_act\([^)]"),
            (os.path.join("a11y_platform", "06_keymap.rpy"),
             r"^        def on_read_screen\(self\):\s*$",
             r"def on_read_screen\(self\s*,"),
            (os.path.join("a11y_platform", "06_keymap.rpy"),
             r"^        def on_diag\(self\):\s*$",
             r"def on_diag\(self\s*,"),
        ]
        for rel, good_re, bad_re in required:
            path = os.path.join(args.dir, rel)
            if not os.path.exists(path):
                km_fail += 1
                print(f"  ✗ 找不到 {rel}（无法核对无参签名）")
                continue
            t = io.open(path, encoding="utf-8").read()
            if not re.search(good_re, t, re.M):
                km_fail += 1
                print(f"  ✗ {rel}  没有找到无参签名 {good_re!r}")
            bad = re.search(bad_re, t)
            if bad:
                km_fail += 1
                print(f"  ✗ {rel}  出现带参数的处理函数签名 {bad.group(0)!r}"
                      f"（Keymap 不传参数，带参数 = 该键永久失效）")

        fails += km_fail
        print(f"  {'全部是无参调用对象' if km_fail == 0 else str(km_fail) + ' 处不合规'}")

    # ---------------- 断言 F：逐作层的「接线」必须在 ----------------
    # ★ 这条是**因为一次真实事故**加的：
    #   给 `22_uialt.rpy` 做批量改写时，把结尾那行
    #       A11yHost.UiAltFor = _a11y_ui_alt_for
    #   一起截掉了 —— 钩子从此再也不会被调用，而**当时所有断言照样通过**
    #   （契约层把 `UiAltFor` 默认成 None，是合法配置）。
    #   表现是：存档位的位号与时间、音声曲目的名字、立绘页的当前值
    #   全部静默失去文案 —— 而界面看上去「已经做完了」。
    #
    #   教训：**「注册语句」本身也需要断言**。它通常只有一行、
    #   看起来无关紧要，却决定了前面几百行是否生效 —— 是最容易被误删的地方。
    print("\n[断言 F] 逐作层的界面文案接线必须在")
    wire_fail = 0
    WIRES = [
        ("A11yHost.UiAltByImage =", "图片文案表"),
        ("A11yHost.UiAltByPos =", "位置文案表"),
        ("A11yHost.UiAltFor =", "兜底钩子（存档位/曲目/立绘当前值都靠它）"),
    ]
    game_text = ""
    for f in game:
        game_text += io.open(f, encoding="utf-8").read()
    for needle, what in WIRES:
        if needle not in game_text:
            wire_fail += 1
            print(f"  ✗ 没找到接线语句 {needle!r}（{what}）—— 那一部分会静默失效")
    # 再核一次「表不是空的」：图名字面量太少说明表被清空了
    n_lit = len(set(re.findall(r'"([^"]+\.(?:png|webp))"', game_text)))
    if n_lit < 30:
        wire_fail += 1
        print(f"  ✗ 逐作层的图名字面量只有 {n_lit} 条（应 ≥30）—— 文案表可能被清空了")
    fails += wire_fail
    print(f"  {'接线完整' if wire_fail == 0 else str(wire_fail) + ' 处缺失'}"
          f"（图名字面量 {n_lit} 条）")

    # ---------------- 断言 G：版本号必须与 git 标签一致 ----------------
    #
    # ⚠ 这条是**事故的产物**：整理那一版（标签 v0.0.0.5）我忘了改
    #   `A11yHost.PatchVersion`，于是**装进游戏的那份自称 0.0.0.4**。
    #   后果很实际 —— 维护者按日志里的版本号汇报「.4 没问题」，
    #   而从版本号上根本分不出他测的到底是 .4 还是那版"自称 .4"的整理版；
    #   我是靠**日志行为特征**（`[alt] 播报:` vs `兜底播报（引擎未报这一条）`）
    #   才分辨出来的。
    #
    #   版本号写进开屏播报与日志第一行，就是为了"按日志对账" ——
    #   那它就必须与标签严格一致。**人记不住，交给机器记。**
    print("\n[断言 G] PatchVersion 必须与当前提交的版本标签一致")
    g_fail = 0
    try:
        import subprocess
        root = os.path.dirname(os.path.abspath(args.dir))
        tag = subprocess.run(
            ["git", "-C", root, "describe", "--tags", "--exact-match", "HEAD"],
            capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        tag = ""
    if not re.fullmatch(r"v\d+(?:\.\d+)+", tag or ""):
        print(f"  --  当前提交没有版本标签（`{tag or '无'}`），跳过 —— "
              f"发布/打标签后请重跑一次")
    else:
        want = tag.lstrip("v")
        got = ""
        for f in iter_rpy(args.dir):
            if f.endswith("90_plugin.rpy"):
                m = re.search(r'A11yHost\.PatchVersion\s*=\s*"([^"]+)"',
                              io.open(f, encoding="utf-8").read())
                if m:
                    got = m.group(1)
        if got != want:
            g_fail += 1
            print(f"  ✗ 标签是 {tag}（应为 {want}），但代码里写的是 "
                  f"{got or '（找不到 PatchVersion）'} —— "
                  f"装进游戏的版本会与标签不符，日志就没法对账了")
        else:
            print(f"  OK  {tag} == PatchVersion {got}")
    fails += g_fail

    # ---------------- 断言 H：install.ps1 的文件清单必须与源文件一致 ----------------
    #
    # ⚠ 这条同样是**事故的产物**：`install.ps1` 用一份「文件名前缀」清单决定
    #   要删哪些旧 `.rpyc`。清单漏了哪个文件，那个文件的旧编译产物就永远留着，
    #   于是**改了源码没反应** —— 本项目为此卡过好几轮（`07_uinav` 那次、
    #   `08_uialt` 编号新加那次）。
    #   人会忘，清单会漂，所以让机器比对。
    print("\n[断言 H] install.ps1 的前缀清单必须覆盖全部补丁 .rpy")
    h_fail = 0
    try:
        inst = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "install.ps1"), encoding="utf-8-sig").read()
        m = re.search(r"\$OurPrefixes\s*=\s*@\((.*?)\)", inst, re.S)
        prefixes = set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()
        stems = set()
        for f in iter_rpy(args.dir):
            stems.add(os.path.basename(f)[:-4])
        missing = sorted(s for s in stems if s not in prefixes)
        extra = sorted(p for p in prefixes if p not in stems)
        if missing:
            h_fail += 1
            print("  ✗ 这些补丁文件不在 install.ps1 的清单里（旧 .rpyc 不会被清掉 ⇒ "
                  "改了没反应）：" + "、".join(missing))
        if extra:
            print("  --  清单里有已不存在的文件（无害，可删）：" + "、".join(extra))
        if not missing:
            print(f"  OK  {len(stems)} 个补丁文件全部在清单里")
    except Exception as e:
        h_fail += 1
        print(f"  ✗ 读 install.ps1 失败：{e}")
    fails += h_fail

    # ---------------- 断言 I：A11yHost 的每个属性都必须真的存在 ----------------
    #
    # ⚠ 这条是**在真 bug 上写出来的**：0.0.0.5 那次整理删掉了契约层的
    #   `CfgKeyCue` 字段，而 `key_cue()` 还在读它 —— 于是
    #       `AttributeError: type object 'A11yHost' has no attribute 'CfgKeyCue'`
    #   后果不是"提示音没了"这么轻：`05_repeat.rpy` 的 F5 在响提示音那一步抛出，
    #   **`self.repeat()` 永不执行**；F9 / F10 / Ctrl+Shift+I 的处理函数整段在
    #   try 里，异常被吞 ⇒ **四个键全部失灵，日志里只有一行 log_exc**。
    #
    #   这与「删常量漏了引用导致 init 链中断」是**同一类错误**：
    #   删定义时没查引用。`check_boot.py` 抓不到它（异常发生在按键那一刻，
    #   不在启动时），所以必须在静态层面拦。
    #
    #   判据：`.rpy` 里出现的每个 `A11yHost.X` 读操作，X 必须在契约类里定义过，
    #   或在某处被 `A11yHost.X = ...` 赋过值（逐作层就是靠赋值填空的）。
    print("\n[断言 I] A11yHost 的每个属性都必须有定义或赋值")
    i_fail = 0
    defined = set()
    assigned = set()
    referenced = set()

    contract = os.path.join(args.dir, "a11y_platform", "00_contract.rpy")
    ctext = ""
    if os.path.exists(contract):
        ctext = io.open(contract, encoding="utf-8").read()
        m = re.search(r"^    class A11yHost\b.*?(?=^    class |\Z)",
                      ctext, re.S | re.M)
        if m:
            body = m.group(0)
            for mm in re.finditer(r"^        ([A-Za-z_]\w*)\s*=", body, re.M):
                defined.add(mm.group(1))
            for mm in re.finditer(r"^        def ([A-Za-z_]\w*)", body, re.M):
                defined.add(mm.group(1))

    for f in iter_rpy(args.dir):
        raw = io.open(f, encoding="utf-8").read()
        # ⚠ 先剥掉注释与字符串字面量再找引用 —— 否则文档里提一句
        #   `contract/A11yHost.cs`（上游 C# 版的文件名）都会被当成属性读到。
        text = strip_comments_and_strings(raw)
        for mm in re.finditer(r"A11yHost\.([A-Za-z_]\w*)\s*=", text):
            assigned.add(mm.group(1))
        for mm in re.finditer(r"A11yHost\.([A-Za-z_]\w*)", text):
            referenced.add(mm.group(1))

    referenced -= assigned          # 赋值处不算「只读引用」

    unknown = sorted(n for n in (referenced | assigned | defined)
                     if n not in defined and n not in assigned)
    if unknown:
        i_fail += 1
        for n in unknown:
            print(f"  ✗ A11yHost.{n} 既没在契约类里定义，也没有被赋过值 —— "
                  f"读到它就会 AttributeError（按键那类代码会整段失效）")
    if not i_fail:
        print(f"  OK  {len(referenced)} 个被引用的属性全部有定义"
              f"（契约类定义 {len(defined)} 个，逐作层赋值 {len(assigned)} 个）")
    fails += i_fail

    # ---------------- 断言 J：.ps1 必须带 BOM（与 A0 正好相反）----------------
    #
    # ⚠ 这条同样是**事故的产物**，而且来得很快：改 `install.ps1` 的前缀清单时，
    #   我的编辑工具写出的是**无 BOM** 的 UTF-8 —— PowerShell 5.1 于是按 GBK
    #   解码中文注释，报 `Missing closing '}'` 之类的**语法错误**，
    #   安装脚本整个不执行（表现是"装了但还是老代码"，极难往编码上想）。
    #
    #   两类文件的规则**正好相反**，所以两条断言都要有：
    #       `.rpy`  → **不得**带 BOM（断言 A0，Ren'Py 会把首行当非法语句）
    #       `.ps1`  → **必须**带 BOM（断言 J，否则 PS 5.1 按 GBK 解码中文）
    print("\n[断言 J] .ps1 必须带 UTF-8 BOM（与 .rpy 规则相反）")
    j_fail = 0
    n_ps1 = 0
    for f in sorted(glob.glob(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "*.ps1"))):
        n_ps1 += 1
        if open(f, "rb").read(3) != b"\xef\xbb\xbf":
            j_fail += 1
            print(f"  ✗ {os.path.basename(f)} 没有 BOM —— PowerShell 5.1 会把中文"
                  f"注释按 GBK 解码，报语法错误、脚本整个不执行")
    fails += j_fail
    print(f"  {'全部带 BOM' if j_fail == 0 else str(j_fail) + ' 个文件缺 BOM'}"
          f"（共 {n_ps1} 个 .ps1）")

    print()
    print(f"结论：{'全部通过' if fails == 0 else str(fails) + ' 项不通过'}")
    print("=" * 72)
    return 0 if fails == 0 else 1

if __name__ == "__main__":
    raise SystemExit(main())
