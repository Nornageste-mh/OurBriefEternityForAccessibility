#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""朗读后端调度探针 —— 抽出 `A11ySpeech` 的真源码，用假后端跑一遍。

为什么要有它（一次**说错话**的事故）：
    实机上开屏播报说「没有可用的朗读后端，请确认读屏软件正在运行」——
    而那句话**正是被读屏念出来的**。自相矛盾。

    根因：`set_mode()` 会经 `set_pinned("")` 把 `_active` 清成 None
    （意思是「下次发声重新挑」），`speak()` 确实会重挑，
    而 `backend_name()` 只会照实报「没有」——
    **同一个状态，两个接口的解读不一致**。

    这类 bug 的特点是：只在「先查询、后执行」的调用顺序下暴露，
    而且暴露方式是「说出自相矛盾的话」，非常容易被当成「读屏坏了」。

    所以这里把它钉成一条测试：`set_mode("")` 之后，
    `backend_name()` **必须仍能报出后端**。

0.0.1.6 追加的三件事（ZDSR 接入链上第三级之后）：
    · **四级链序**：Tolk(可选) -> NVDA -> ZDSR -> SAPI(引擎同款)，
      逐级设成不可用，看它是不是**一级一级**顺降（而不是跳过或抛异常）；
    · **ZDSR 能被配置钉死**：`set_mode("ZDSR")` 后只有 ZDSR 被调用；
    · **真源码静态核对 + 真 DLL 活体检查**：类在不在、握手形状对不对、
      可用判据是不是只认 `GetSpeakState() in (3,4)`（**绝不看 `Speak()` 的返回值**），
      以及拿本机真的 `ZDSRAPI_x64.dll` 跑一遍判据（只调 `InitTTS` / `GetSpeakState`，
      **不调 `Speak`**，所以不会出声、也不会启动读屏；找不到 dll 就跳过）。

0.0.1.6 追加的后端切换键（第 14、15 组）：
    · **只停在可用的后端上**：固定顺序 自动 -> Tolk -> NVDA -> 争渡 -> SAPI -> 回自动，
      不可用的**跳过并念出跳过了谁**（含「没注册」与「注册了但判据不过」两种）；
    · **播报走新后端**：切完返回的是一整句「语音后端：争渡读屏…」，
      由按键层用 `A11yHost.repeat.say`（= 平台层唯一出口）念出去；
    · **跨启动记住**：选中档位写进 `A11yHost.remember`（引擎 persistent），
      下次启动由 `boot_mode()` 读回来，而**配置里写死的档位优先于它**；
    · **键名支持人话写法**：`"Alt+Shift+F9"` -> `"alt_shift_K_F9"`
      （抽 `06_keymap.rpy` 的 `_A11yKeySpec` 真源码来跑，不是探针里抄一份）。

用法：
    python tools/probe_speech.py
"""

from __future__ import annotations

import ast
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "mod", "game", "a11y_platform", "01_speech.rpy")
KM = os.path.join(REPO, "mod", "game", "a11y_platform", "06_keymap.rpy")
CONTRACT = os.path.join(REPO, "mod", "game", "a11y_platform", "00_contract.rpy")
PLUGIN = os.path.join(REPO, "mod", "game", "a11y_game", "90_plugin.rpy")

#: 真 dll 的默认位置（争渡读屏安装目录，官方文档写的就是这里）。
#: 找不到时活体检查跳过 —— 探针必须在没装争渡的机器上也能跑完。
ZDSR_DLL = r"C:\Program Files (x86)\zdsr\zdsr\ZDSRAPI_x64.dll"

#: `GetSpeakState()` 的**全部**官方返回码 → 人话。
#: ⚠ 后端源码里的 `STATE_WHY` 只登记「不可用」的那几个（它的 `_why` 只在那条分支上
#: 用它），所以**不能拿它印 3/4** —— 那会印出「未知」，而 3/4 的含义恰恰是文档里
#: 写得最清楚的两个。这里另存一份完整表，并**交叉核对**后端那份（见第 13 组）。
ZDSR_STATE_MEANING = {
    1: "版本不匹配",
    2: "争渡读屏没有运行或没有授权",
    3: "正在朗读",
    4: "没有朗读",
    8: "命令没有成功送达",
    9: "独立通道尚未就绪",
}

FAIL = 0


def check(label, ok, detail=""):
    global FAIL
    if not ok:
        FAIL += 1
    print(f"  {'OK  ' if ok else '✗✗✗ '}{label}" + (f"   {detail}" if detail else ""))


def extract_block(path, header_re):
    """抽出一段**缩进块**（class/def）的源码文本。

    判据：从匹配到的那一行起，到**缩进回到同级或更少**的下一行为止。
    抽出来的是引擎将要执行的那段文本，不是复制品。
    """
    lines = open(path, encoding="utf-8").read().split("\n")
    start = None
    for i, l in enumerate(lines):
        if re.match(header_re, l):
            start = i
            break
    if start is None:
        raise SystemExit(f"在 {path} 里找不到 {header_re}")
    indent = len(lines[start]) - len(lines[start].lstrip(" "))
    body = [lines[start]]
    for l in lines[start + 1:]:
        if l.strip() and (len(l) - len(l.lstrip(" "))) <= indent:
            break
        body.append(l)
    return "\n".join(body)


def dedent4(src):
    """`init python:` 块里的类是 4 空格缩进的，抽出来要退掉那一级才能 exec。"""
    return "\n".join(l[4:] if l.startswith("    ") else l for l in src.split("\n"))


def extract_init_block(path, init_re):
    """抽出一个 `init <n> python:` 块的**整段源码**（去掉那一级缩进）。

    判据与 `tools/lint_patch.py` 的 `extract_init_blocks` 一致：从匹配行开始，
    到下一行**不在块内**（非空且不缩进）为止。
    """
    lines = open(path, encoding="utf-8").read().split("\n")
    start = None
    for i, l in enumerate(lines):
        if re.match(init_re, l):
            start = i
            break
    if start is None:
        raise SystemExit(f"在 {path} 里找不到 {init_re}")
    body = []
    for l in lines[start + 1:]:
        if l.strip() and not l.startswith("    "):
            break
        body.append(l[4:] if l.startswith("    ") else l)
    return "\n".join(body)


def grab_defs(path, init_re, names):
    """从 `init python:` 块里按名字取出**真源码片段**（用 ast 定位，不靠缩进猜）。

    为什么这里不能用 `extract_block`：要取的是「两个模块级字典 + 一个函数」三块
    **互不相邻**的定义，而 `extract_block` 的判据是「一直读到缩进回到同级」——
    取到字典的 `}` 那一行就断了（少了那个 `}` 直接 SyntaxError）。
    ast 拿到的仍然是**引擎将要执行的那段文本**（`ast.get_source_segment`），
    与 `extract_block` 一样是真源码，只是定位更稳。
    """
    tree = ast.parse(extract_init_block(path, init_re))
    src = extract_init_block(path, init_re)
    out = {}
    for node in tree.body:
        cand = []
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            cand.append(node.name)
        for t in getattr(node, "targets", []) or []:
            if isinstance(t, ast.Name):
                cand.append(t.id)
        for n in cand:
            if n in names:
                out[n] = ast.get_source_segment(src, node)
    missing = [n for n in names if n not in out]
    if missing:
        raise SystemExit(f"在 {path} 的 {init_re} 块里找不到 {missing}")
    return out


class FakeHost(object):
    """`A11yHost` 的替身：日志接口 + **跨启动记忆**（探针里不写文件，攒起来看）。

    `mem` 就是引擎那一侧 `persistent` 的替身：`recall` / `remember` 的语义要与
    `00_contract.rpy` 一致 —— **读不到就返回 default，写失败也不抛**。
    """

    #: 契约层的默认值（`boot_mode()` 会读它）
    CfgSpeechBackend = ""

    def __init__(self):
        self.logs = []
        self.mem = {}

    def log(self, msg):
        self.logs.append(str(msg))

    def log_exc(self, msg):
        self.logs.append("EXC " + str(msg))

    def diag(self, msg):
        self.logs.append("DIAG " + str(msg))

    def recall(self, key, default=None):
        return self.mem.get(key, default)

    def remember(self, key, value):
        self.mem[key] = value
        return True


class FakeBackend(object):
    def __init__(self, name, ok=True, reason=None):
        self.name = name
        self._ok = ok
        self._why = reason if reason is not None else ("就绪" if ok else "测试用：判定不可用")
        self.spoken = []
        self.inited = False

    def init(self):
        self.inited = True

    def available(self):
        return self._ok

    def reason(self):
        return self._why

    def speak(self, text, interrupt=True):
        if not self._ok:
            raise RuntimeError("不可用")
        self.spoken.append((text, interrupt))

    def stop(self):
        pass


print("=" * 72)
print("朗读后端调度探针 —— `A11ySpeech` 真源码 + 假后端")
print("=" * 72)

src = extract_block(SRC, r"^\s*class A11ySpeech\(object\):")
print(f"抽出 {len(src.splitlines())} 行源码（{os.path.relpath(SRC, REPO)}）\n")
dedented = dedent4(src)

host = FakeHost()
ns = {"A11yHost": host}
exec(compile(dedented, "<A11ySpeech>", "exec"), ns)
A11ySpeech = ns["A11ySpeech"]


def new_speech(ok_nvda=True, ok_zdsr=True, ok_sapi=True, with_tolk=False, ok_tolk=True):
    """建一个**只注册假后端**的 `A11ySpeech`，返回 `(调度器, 后端字典)`。

    后端名与真源码里的 `name` 类属性逐字一致（`"SAPI(引擎同款)"` 这种带括号的
    也要照抄）—— 因为 `set_mode()` 的白名单核对就是按名字做的，
    名字不一致的「假后端」验证不了真行为（这正是本探针要防的那类假验证）。

    `with_tolk=True` 时按真实链序把 Tolk 也注册到链首（真源码里它是
    「探测到才注册」的可选一级，探针里用开关模拟探测结果）。
    """
    s = A11ySpeech()
    # 跳过 register_builtin（它要 A11yTolkBackend 等真实后端类，探针自带假的）
    s._registered = True
    order = []
    if with_tolk:
        order.append(("Tolk", ok_tolk))
    order += [("NVDA", ok_nvda), ("ZDSR", ok_zdsr), ("SAPI(引擎同款)", ok_sapi)]
    b = {}
    for name, ok in order:
        b[name] = FakeBackend(name, ok)
        s.register(b[name])
    s.init()
    return s, b


# ── 1) 初始化后能报出后端 ─────────────────────────────────────────
print("[1] init() 之后")
s, b = new_speech()
check("backend_name() = NVDA（链首）", s.backend_name() == "NVDA", f"实得 {s.backend_name()!r}")
check("注册的后端都被 init 过", all(x.inited for x in b.values()))

# ── 2) ★ 回归点：set_mode("") 之后仍然能报出后端 ★ ──────────────────
print("\n[2] ★ set_mode('') 之后（这就是实机说错话的那一步）")
s.set_mode("")
check("backend_name() 仍能报出后端（不能是「(无)」）",
      s.backend_name() not in ("(无)", "", None), f"实得 {s.backend_name()!r}")
check("mode_label() 带上实际后端", "NVDA" in s.mode_label(), f"实得 {s.mode_label()!r}")
check("此时 speak() 也能出声", s.speak("测试") and b["NVDA"].spoken, f"nvda={b['NVDA'].spoken}")

# ── 3) 档位轮换 ──────────────────────────────────────────────────
print("\n[3] 后端切换键的轮换表")
seen = []
s2, _b2 = new_speech(with_tolk=True)          # 四路都可用 ⇒ 五档全都能停
for _ in range(len(A11ySpeech.CfgModes)):
    seen.append(s2.cycle_backend())
# 注意起点：配置是「自动」时，起点按**实际选中的后端**算（这里是链首 Tolk），
# 所以第一下落到 NVDA，而不是原地切到 Tolk（原地切 = 玩家以为键没生效）。
check("从「自动（实际落在 Tolk）」出发轮换一周：NVDA → 争渡 → SAPI → 自动 → NVDA",
      seen == ["语音后端：NVDA", "语音后端：争渡读屏", "语音后端：引擎同款 SAPI",
               "语音后端：自动（Tolk）", "语音后端：NVDA"], f"实得 {seen}")
check("每一档都停到了不同的落点（除回到起点那一档）",
      len(set(seen)) == len(A11ySpeech.CfgModes) - 1 or len(set(seen)) == len(A11ySpeech.CfgModes),
      f"实得 {seen}")
check("轮换表 = 维护者的固定顺序（自动 / Tolk / NVDA / ZDSR / SAPI）",
      list(A11ySpeech.CfgModes) == ["", "Tolk", "NVDA", "ZDSR", "SAPI(引擎同款)"],
      f"实得 {A11ySpeech.CfgModes}")
check("播报里用的是中文名「争渡读屏」而不是类名 ZDSR",
      any("语音后端：争渡读屏" in x for x in seen), f"实得 {seen}")

# ── 4) 钉死某个后端 ──────────────────────────────────────────────
print("\n[4] 钉死到「引擎同款」")
s3, b3 = new_speech()
s3.set_mode("SAPI(引擎同款)")
check("backend_name() 跟着变", s3.backend_name() == "SAPI(引擎同款)", f"实得 {s3.backend_name()!r}")
s3.speak("只走 SAPI")
check("只走了 SAPI，没走 NVDA", b3["SAPI(引擎同款)"].spoken and not b3["NVDA"].spoken,
      f"sapi={b3['SAPI(引擎同款)'].spoken} nvda={b3['NVDA'].spoken}")

# ── 5) 名字写错 ⇒ 退回自动，而不是整局哑掉 ────────────────────────
print("\n[5] 配置里后端名写错")
s4, _b4 = new_speech()
s4.set_mode("拼错的名字")
check("没有停在「没有后端」", s4.backend_name() not in ("(无)", ""), f"实得 {s4.backend_name()!r}")
check("写了 Warning（不静默）", any("不认识的后端名" in x for x in host.logs),
      f"日志尾部 {host.logs[-2:]}")

# ── 6) 链首不可用时降级 ──────────────────────────────────────────
print("\n[6] NVDA 不可用时降级到下一级（ZDSR）")
s5, b5 = new_speech(ok_nvda=False)
check("退化到 ZDSR", s5.backend_name() == "ZDSR", f"实得 {s5.backend_name()!r}")
s5.speak("降级")
check("确实由 ZDSR 出声", b5["ZDSR"].spoken and not b5["NVDA"].spoken,
      f"zdsr={b5['ZDSR'].spoken} nvda={b5['NVDA'].spoken}")

# ── 7) 全灭时返回失败，而不是抛异常 ──────────────────────────────
print("\n[7] 所有后端都不可用")
s6, _b6 = new_speech(ok_nvda=False, ok_zdsr=False, ok_sapi=False)
check("backend_name() 报「(无)」", s6.backend_name() == "(无)", f"实得 {s6.backend_name()!r}")
check("speak() 返回 False 而不抛异常", s6.speak("没人听") is False)

# ── 8) 「两者」档 ────────────────────────────────────────────────
print("\n[8] 「两者同时」档")
s7, b7 = new_speech()
s7.set_mode("两者")
ok = s7.speak("两边都念")
check("三路都被调用", ok and b7["NVDA"].spoken and b7["ZDSR"].spoken
      and b7["SAPI(引擎同款)"].spoken,
      f"nvda={b7['NVDA'].spoken} zdsr={b7['ZDSR'].spoken} sapi={b7['SAPI(引擎同款)'].spoken}")
check("backend_name() 报出各路", "NVDA" in s7.backend_name() and "SAPI" in s7.backend_name(),
      f"实得 {s7.backend_name()!r}")

# ── 9) ★ 四级链序：Tolk(可选) -> NVDA -> ZDSR -> SAPI ★ ────────────
#     每一级都用**新建的**调度器验（`_pick()` 只升不降，`_active` 不会因为
#     假后端事后改可用性而重挑 —— 那是刻意的设计，探针要顺着它写）。
print("\n[9] ★ 四级链序：Tolk(可选) -> NVDA -> ZDSR -> SAPI(引擎同款)")
s8, _b8 = new_speech(with_tolk=True)
check("四路都可用 ⇒ 停在链首 Tolk", s8.backend_name() == "Tolk", f"实得 {s8.backend_name()!r}")
s9, _b9 = new_speech(with_tolk=True, ok_tolk=False)
check("Tolk 不可用 ⇒ NVDA", s9.backend_name() == "NVDA", f"实得 {s9.backend_name()!r}")
s10, _b10 = new_speech(ok_nvda=False)
check("NVDA 不可用 ⇒ ZDSR", s10.backend_name() == "ZDSR", f"实得 {s10.backend_name()!r}")
s11, b11 = new_speech(ok_nvda=False, ok_zdsr=False)
check("ZDSR 不可用 ⇒ SAPI(引擎同款)", s11.backend_name() == "SAPI(引擎同款)",
      f"实得 {s11.backend_name()!r}")
s11.speak("一路顺降")
check("最后确实由 SAPI 出声、ZDSR 一次没被调用",
      b11["SAPI(引擎同款)"].spoken and not b11["ZDSR"].spoken,
      f"sapi={b11['SAPI(引擎同款)'].spoken} zdsr={b11['ZDSR'].spoken}")

# ── 10) ★ 不可用的 ZDSR 必须顺降到 SAPI（不抛异常、不静默）★ ────────
print("\n[10] ★ ZDSR 不可用 ⇒ 顺降（这是「未授权也能返回 0」那个坑的回归点）")
s12, b12 = new_speech(ok_nvda=False, ok_zdsr=False)
check("backend_name() = SAPI(引擎同款)", s12.backend_name() == "SAPI(引擎同款)",
      f"实得 {s12.backend_name()!r}")
check("speak() 返回 True，且只走了 SAPI",
      s12.speak("ZDSR 不在") and b12["SAPI(引擎同款)"].spoken and not b12["ZDSR"].spoken,
      f"sapi={b12['SAPI(引擎同款)'].spoken} zdsr={b12['ZDSR'].spoken}")
check("verdict() 里 ZDSR 那一栏给的是**人话原因**（reason() 没抛异常）",
      "ZDSR=测试用：判定不可用" in s12.verdict(), f"实得 {s12.verdict()!r}")

# ── 11) 钉死 ZDSR ────────────────────────────────────────────────
print("\n[11] 把后端钉死成 ZDSR（配置 CfgSpeechBackend = \"ZDSR\" / F9 切到 ZDSR）")
s13, b13 = new_speech()
s13.set_mode("ZDSR")
check("set_mode('ZDSR') 被接受（白名单按已注册后端名动态生成）",
      s13.backend_name() == "ZDSR", f"实得 {s13.backend_name()!r}")
check("mode_label() 报 ZDSR", "ZDSR" in s13.mode_label(), f"实得 {s13.mode_label()!r}")
s13.speak("只走 ZDSR")
check("只有 ZDSR 被调用",
      b13["ZDSR"].spoken and not b13["NVDA"].spoken and not b13["SAPI(引擎同款)"].spoken,
      f"nvda={b13['NVDA'].spoken} zdsr={b13['ZDSR'].spoken} sapi={b13['SAPI(引擎同款)'].spoken}")

# ── 12) ZDSR 后端的静态核对（真源码，不是探针里的复制品）────────────
print("\n[12] `A11yZdsrBackend` 静态核对（从 01_speech.rpy 抽真源码）")
zdsr_src = extract_block(SRC, r"^\s*class A11yZdsrBackend\(object\):")
check('类属性 name = "ZDSR"（与 CfgModes / 配置写法一致）',
      re.search(r'^\s*name = "ZDSR"\s*$', zdsr_src, re.M) is not None)
check("握手形状是 InitTTS(0, None, False)（官方：读屏通道 / NULL / 按键不打断）",
      re.search(r"InitTTS\(\s*0\s*,\s*None\s*,\s*False\s*\)", zdsr_src) is not None)
check("★ 可用性判据只认 self._state in (3, 4)（GetSpeakState）",
      re.search(r"self\._state\s+in\s+\(\s*3\s*,\s*4\s*\)", zdsr_src) is not None)
check("★ 没有把 Speak() 的返回值当可用判据（未授权时它同样返回 0）",
      re.search(r"Speak\([^)]*\)\s*==\s*0", zdsr_src) is None)
check("speak() 在 rc != 0 时抛异常（与 NVDA 后端同一套语义）",
      re.search(r'raise RuntimeError\("ZDSR Speak rc=', zdsr_src) is not None)
i_nvda = src.find("self.register(A11yNvdaBackend())")
i_zdsr = src.find("self.register(A11yZdsrBackend())")
i_sapi = src.find("self.register(A11ySayVbsBackend())")
check("register_builtin 里 NVDA -> ZDSR -> SAPI 的注册次序成立（顺序即优先级）",
      -1 < i_nvda < i_zdsr < i_sapi, f"位置 {i_nvda} / {i_zdsr} / {i_sapi}")

# ── 13) 真 DLL 活体检查（只读：只调 InitTTS / GetSpeakState，**不调 Speak**）──
print("\n[13] 真 ZDSRAPI_x64.dll 活体检查（走 A11yZdsrBackend 真源码；不发声、不启动读屏）")
if not os.path.exists(ZDSR_DLL):
    print(f"  --  未找到 {ZDSR_DLL}（本机没装争渡）—— 跳过，不计失败")
else:
    print(f"  dll: {ZDSR_DLL}")
    print("  （争渡的 dll 每次 InitTTS 会往 stdout 写一行 `--------------InitTTS rt = N`，")
    print("    那是它自己的输出，不是本探针打印的 —— 见到别当成乱码）")

    class _StubNvda(object):
        """只补 `A11yZdsrBackend._candidate_dirs()` 复用的那个兜底目录函数。

        （活体检查关心的是「官方目录能不能找到 dll」与「判据怎么判」，
        兜底目录这里不参与，给空表即可；这样也能让探针在非 Windows 上被 import。）
        """

        @staticmethod
        def _candidate_dirs():
            return []

    zhost = FakeHost()
    zns = {"A11yHost": zhost, "A11yNvdaBackend": _StubNvda}
    exec(compile(dedent4(zdsr_src), "<A11yZdsrBackend>", "exec"), zns)
    Zdsr = zns["A11yZdsrBackend"]

    z = Zdsr()
    z.init()
    check("dll 能按绝对路径加载并绑好四个导出", z._lib is not None, f"结论 {z.reason()!r}")
    if z._lib is None:
        print(f"    （加载失败原因：{z.reason()}）")
    else:
        print(f"    loaded_from   : {z.loaded_from}")
        print(f"    盲文导出      : {'有' if z._has_braille else '无'}")
        print(f"    InitTTS rc    : {z._init_rc}"
              f"（握手{'成功' if z._handshake_ok else '失败：' + str(z._init_why)}）")
        z._read_state()                 # 强制刷新一次，别拿 init 时的缓存下结论
        rc = z._state
        avail = z.available()
        print(f"    GetSpeakState : {rc}"
              f"（{ZDSR_STATE_MEANING.get(rc, '未知返回码')}）")
        print(f"    available()   : {avail}")
        print(f"    reason()      : {z.reason()!r}")
        check("后端源码里的 STATE_WHY 与官方文档逐条一致（探针另存一份做交叉核对）",
              all(ZDSR_STATE_MEANING.get(k) == v for k, v in Zdsr.STATE_WHY.items()),
              f"后端 {Zdsr.STATE_WHY}")
        check("★ 可用判据 == (GetSpeakState() in (3,4)) —— 不看 Speak() 的返回值",
              avail == (rc in (3, 4)), f"available={avail} state={rc}")
        check("reason() 不抛异常且给出非空人话", isinstance(z.reason(), str) and z.reason() != "",
              f"实得 {z.reason()!r}")
        if rc == 2:
            check("未运行/未授权时判为**不可用**（不是「自称可用」）", avail is False)
        # verdict() 对 reason() 没有 try —— 真后端接进去也要能拼出整行
        s14 = A11ySpeech()
        s14._registered = True
        s14.register(z)
        v = s14.verdict()
        print(f"    verdict()     : {v}")
        check("verdict() 能把 ZDSR 的结论拼进一行（reason() 不打断这行日志）",
              "ZDSR=" in v)
        print(f"    A11yHost 日志 : {zhost.logs}")

# ── 14) ★ 后端切换键：只停在**当前可用**的后端上，跳过的要念出来 ────────
print("\n[14] ★ 后端切换键：固定顺序 + 跳过不可用 + 跳过谁要念出来 + 跨启动记住")

# (a) 四路都可用 ⇒ 起点按「自动实际落在的 Tolk」算，第一下就换到 NVDA
s14, _b14 = new_speech(with_tolk=True)
host.mem.clear()
host.CfgSpeechBackend = ""
modes14 = []
for _ in range(len(A11ySpeech.CfgModes)):
    s14.cycle_backend()
    modes14.append(s14._mode)
check("四路都可用 ⇒ （自动落在 Tolk）NVDA -> 争渡 -> SAPI -> 自动 -> NVDA",
      modes14 == ["NVDA", "ZDSR", "SAPI(引擎同款)", "", "NVDA"], f"实得 {modes14}")

# (b) Tolk 没注册（绝大多数机器的真实情况：玩家没有自备 Tolk.dll）
#     ⇒ 自动实际落在 NVDA，第一下应当**直接换到争渡**（而不是原地不动）
s15, _b15 = new_speech()
line15 = s15.cycle_backend()
check("Tolk 没注册 ⇒ 自动落在 NVDA，第一下就换到争渡读屏（不是原地停在 NVDA）",
      s15._mode == "ZDSR", f"实得 {s15._mode!r}")
check("这一路没有需要跳过的东西，播报里就不该出现「已跳过」",
      "已跳过" not in line15 and line15.startswith("语音后端：争渡读屏"), f"实得 {line15!r}")

# (c) 只有 SAPI 可用：这一路要**真的经过**三个不可用档，跳过要逐个念出来；
#     同时验证「已经在自动上时不再切回自动（空转）」这条规则
s16, _b16 = new_speech(ok_nvda=False, ok_zdsr=False)
line16 = s16.cycle_backend()
check("只有 SAPI 可用 ⇒ 跳过 未接入的 Tolk / 不可用的 NVDA 与争渡，停在 SAPI",
      s16._mode == "SAPI(引擎同款)", f"实得 {s16._mode!r}")
check("三个被跳过的都念出来，且理由分开（未接入 / 不可用）",
      "已跳过" in line16 and "未接入" in line16 and line16.count("不可用") >= 2,
      f"实得 {line16!r}")
check("落在 SAPI 时播报的就是它", line16.startswith("语音后端：引擎同款 SAPI"),
      f"实得 {line16!r}")
line16b = s16.cycle_backend()
check("再按一下：从钉死的 SAPI 出发，「自动」是有效落点（取消钉死）",
      s16._mode == "" and line16b.startswith("语音后端：自动"), f"实得 {s16._mode!r} / {line16b!r}")
line16c = s16.cycle_backend()
check("第三次：已经在自动上 ⇒ 不再切回自动（空转跳过），而是钉回可用的 SAPI",
      s16._mode == "SAPI(引擎同款)", f"实得 {s16._mode!r} / {line16c!r}")

# (d) 从中间档出发 + 绕过不可用的兜底档
s17, _b17 = new_speech(ok_nvda=False, ok_sapi=False)
s17.set_mode("ZDSR")
line17 = s17.cycle_backend()
check("从争渡读屏出发、SAPI 不可用 ⇒ 跳过 SAPI 回到自动", s17._mode == "",
      f"实得 {s17._mode!r}")
check("绕过的兜底档也要念出来", "已跳过 引擎同款 SAPI：不可用" in line17,
      f"实得 {line17!r}")

# (e) 全灭：不能停在任何一个不可用的后端上，也要如实说没有可用后端
s18, _b18 = new_speech(ok_nvda=False, ok_zdsr=False, ok_sapi=False)
line18 = s18.cycle_backend()
check("所有后端都不可用 ⇒ 停在「自动」并如实报「无可用后端」",
      s18._mode == "" and "无可用后端" in line18, f"实得 {s18._mode!r} / {line18!r}")
check("四个档位（未接入 + 三个不可用）一个不落地念出来",
      line18.count("：") == 5, f"实得 {line18!r}")

# (f) 落盘 + 下次启动沿用。用「只有争渡可用」的机器形态：从自动（落在争渡）出发，
#     SAPI 不可用 ⇒ 一路跳回争渡并**钉死**它（这就是「开着 NVDA 想听争渡」那一类场景）
host.mem.clear()
host.CfgSpeechBackend = ""
s19, b19 = new_speech(ok_nvda=False, ok_sapi=False)
line19 = s19.cycle_backend()
check("只有争渡可用 ⇒ 钉死在争渡读屏（其余三档都被跳过）",
      s19._mode == "ZDSR", f"实得 {s19._mode!r} / {line19!r}")
check("选中的档位写进 persistent（跨启动读得回来）",
      host.mem.get("a11y_speech_backend") == "ZDSR", f"实得 {host.mem}")
check("配置面同步（日志/现场快照立刻跟上）",
      host.CfgSpeechBackend == "ZDSR", f"实得 {host.CfgSpeechBackend!r}")

# 播报必须走**刚选中**的那个后端（否则玩家听不出切没切过去）
s19.speak("语音后端：争渡读屏")
check("播报走的是刚选中的后端（只有争渡被调用，NVDA/SAPI 一次没碰）",
      len(b19["ZDSR"].spoken) == 1 and not b19["NVDA"].spoken
      and not b19["SAPI(引擎同款)"].spoken,
      f"zdsr={b19['ZDSR'].spoken} nvda={b19['NVDA'].spoken} "
      f"sapi={b19['SAPI(引擎同款)'].spoken}")

s20, _b20 = new_speech(ok_nvda=False)          # 相当于「下一次启动」
s20.boot_mode()
check("下次启动沿用玩家上次选的档位（不再退回自动）", s20._mode == "ZDSR",
      f"实得 {s20._mode!r}")

# (g) 配置里写死的档位优先于记忆（排查时不能被上一次按键顶掉）
host.CfgSpeechBackend = "SAPI(引擎同款)"
s21, _b21 = new_speech()
s21.boot_mode()
check("配置里写死的档位**优先于**记忆（排查手段必须压得住记忆）",
      s21._mode == "SAPI(引擎同款)", f"实得 {s21._mode!r}")

# (h) 记忆里的后端已经用不了（例如玩家把 Tolk.dll 删了）
host.mem["a11y_speech_backend"] = "Tolk"
host.CfgSpeechBackend = ""
s22, _b22 = new_speech()                       # 没注册 Tolk
s22.boot_mode()
check("记忆里的后端已经用不了 ⇒ 退回自动 + 一行 Warning（不是整局哑掉）",
      s22._mode == "" and any("不认识的后端名" in x for x in host.logs),
      f"实得 {s22._mode!r}")

# (i) 「两者」不占按键档位，但配置仍然能用 —— 能力没少，只是换了个入口
s23, _b23 = new_speech()
s23.set_mode("两者")
check("「两者」不在轮换表里，但配置档仍然有效（且播报名是中文）",
      "两者" not in A11ySpeech.CfgModes and s23._mode == "两者"
      and s23.mode_display().startswith("两者同时"),
      f"实得 {A11ySpeech.CfgModes} / {s23._mode!r} / {s23.mode_display()!r}")

# ── 15) ★ 键名写法（抽 06_keymap.rpy 的真源码来跑）────────────────────
print("\n[15] ★ 后端切换键的键名写法与接线（从 06_keymap.rpy 抽真源码）")
km_ns = {}
for _name, _code in grab_defs(
        KM, r"^init 1200 python:",
        ["_A11Y_MOD_ALIASES", "_A11Y_KEY_ALIASES", "_A11yKeySpec",
         "_A11yKeySpecs"]).items():
    exec(compile(_code, f"<{_name}>", "exec"), km_ns)
KeySpec = km_ns["_A11yKeySpec"]
KeySpecs = km_ns["_A11yKeySpecs"]

#: (人话写法, 引擎写法)。表里每一对都按「引擎真认不认」在 probe_keymap.py 里
#: 走过一遍 `compile_event` —— 这里先保证转换规则本身是对的。
CASES = [
    ("F9", "K_F9"),
    ("K_F9", "K_F9"),
    ("Alt+Shift+F9", "alt_shift_K_F9"),
    ("Shift+Alt+F9", "shift_alt_K_F9"),        # 修饰词顺序无意义（引擎是 set）
    ("Ctrl+R", "ctrl_K_r"),                    # 引擎里字母只有小写那份（实查）
    ("ctrl_shift_K_r", "ctrl_shift_K_r"),      # 引擎写法原样透传
    ("Alt+Win+F9", "alt_meta_K_F9"),           # Win/Super/Command 都映射到 meta
    ("Enter", "K_RETURN"),
    ("Alt+PageUp", "alt_K_PAGEUP"),
]
for raw, want in CASES:
    got = KeySpec(raw)
    check(f"{raw!r} -> {want!r}", got == want, f"实得 {got!r}")

check("不认识的修饰键**原样返回**（交给引擎判，绝不硬塞进 keymap）",
      KeySpec("Hyper+F9") == "Hyper+F9", f"实得 {KeySpec('Hyper+F9')!r}")
check("不认识的键名**原样返回**", KeySpec("Alt+Foo") == "Alt+Foo",
      f"实得 {KeySpec('Alt+Foo')!r}")
check("空值与 None 都不炸（配置写空不能把游戏弄起不来）",
      KeySpec("") == "" and KeySpec(None) == "")

check("键位配置漏写方括号（写成字符串）也认 —— 否则会按字符拆成一个都不合法",
      KeySpecs("Alt+Shift+F9") == ["alt_shift_K_F9"], f"实得 {KeySpecs('Alt+Shift+F9')!r}")
check("未配置时用默认键（`_A11yKeySpecs(None, [\"K_F9\"])` -> [\"K_F9\"]）",
      KeySpecs(None, ["K_F9"]) == ["K_F9"], f"实得 {KeySpecs(None, ['K_F9'])!r}")
check("正常写法（列表）逐条转换",
      KeySpecs(["K_F9", "Alt+Shift+F9"]) == ["K_F9", "alt_shift_K_F9"],
      f"实得 {KeySpecs(['K_F9', 'Alt+Shift+F9'])!r}")

km_text = open(KM, encoding="utf-8").read()
check("切换键读的是配置 `CfgBackendCycleKey`（不再写死 K_F9）",
      "A11yHost.CfgBackendCycleKey" in km_text)
check("登记前仍然过引擎自己的解析器（`_A11yValidSpecs`）",
      "_A11yValidSpecs(_A11yKeySpecs(" in km_text)
check("只登记在补丁自己的 Keymap 层上（没有自己监听原始按键、不抢游戏事件流）",
      'config.keymap["A11yBackendCycle"] = cyc' in km_text
      and "pygame.event" not in km_text)
check("处理函数仍然是无参可调用对象（断言 E 的不变量）",
      'binds["A11yBackendCycle"] = [A11yHost.keys.on_backend_cycle]' in km_text)
check("播报走平台层唯一出口 repeat.say（这样才是用**新后端**念出来的）",
      "A11yHost.repeat.say(line, interrupt=True, record=False)" in km_text)

c_text = open(CONTRACT, encoding="utf-8").read()
p_text = open(PLUGIN, encoding="utf-8").read()
check('契约层定义了 CfgBackendCycleKey，默认 ["K_F9"]',
      re.search(r'CfgBackendCycleKey = \["K_F9"\]', c_text) is not None)
check('逐作层把默认键写实为 ["K_F9"]（默认就是 F9）',
      re.search(r'A11yHost\.CfgBackendCycleKey = \["K_F9"\]', p_text) is not None)
check("契约层提供跨启动记忆接口 recall/remember（平台层不直接碰引擎）",
      re.search(r"def recall\(", c_text) is not None
      and re.search(r"def remember\(", c_text) is not None)

print()
print("=" * 72)
print(f"结论：{'全部通过' if FAIL == 0 else str(FAIL) + ' 项不通过'}")
print("=" * 72)
raise SystemExit(0 if FAIL == 0 else 1)
