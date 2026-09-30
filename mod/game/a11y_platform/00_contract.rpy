# A11yFramework / Ren'Py 版 —— 契约层（L2）：A11yHost
#
# 本文件是 L1 平台层与 L3 逐作层之间的**唯一接口**。
# 上游理由（流水线 §2.2）：契约一旦固化，平台层逐字节复用；
# 不固化，每作都要重做几十上百处改名 + 人工回归。
#
# ── 承重的引擎事实（第一次实机启动时从 log.txt 的 traceback 里读到）──────────
#
#   `init python in <名字>:` 创建的是**独立的命名空间 store**，那个名字**不会**
#   成为默认 store 的属性，块内也引用不到自己：
#
#       init python in a11y_rpy:  ...
#       init 1300 python:  a11y_rpy.foo()   # NameError —— **中断整个 init 1300**
#
#   （连后端链都起不来。）所以本补丁统一成「单一默认 store + `A11y` 前缀」：
#   每个平台文件仍单独成文件（便于对照上游 `platform/*.cs`），而跨文件引用一律
#   走本类上的**具名槽位**（`speech`/`repeat`/`keys`/`rpy`/`choice`/`uialt`），
#   不依赖「别的 store 可见」。
#
# 纪律不变：平台层**一处游戏类型都不引用**，由 `tools/lint_patch.py` 断言 B 机械断言。

init -200 python:

    class A11yHost(object):
        """共享层唯一可见的宿主。上游 `contract/A11yHost.cs` 的 Ren'Py 对应物。"""

        # ------------------------------------------------------------ 元信息
        # 由逐作层填。不填会被 validate() 记一条 Warning，而不是静默失效。
        GameName = ""
        GameVersion = ""
        PatchVersion = ""

        # ------------------------------------------------------------ 配置（由逐作层填）
        #: 朗读后端："" = 自动（NVDA -> SAPI）；也可钉死成 "NVDA" / "SAPI(引擎同款)"（排查用）
        CfgSpeechBackend = ""

        #: 朗读诊断日志：写进 log.txt。**默认关闭** —— 打开时 log.txt 里会出现剧本原文，
        #: 按 IP 红线**不得提交、不得外传**（只在自己排查时临时开）。
        CfgDiagLog = False

        #: ⚠ 契约层默认 True，但**本作逐作层设成 False**，而且现在只有 `validate()`
        #: 那一行日志读它：自语音的开合早已由 `A11yRenpy.ensure_self_voicing`
        #: **无条件关闭**（控件播报由补丁自己负责）。两次改动的实机记录见
        #: `10_renpy_adapter.rpy` 的该函数、docs §8.2。
        CfgAutoEnable = True

        #: 按键提示音：按下补丁自己的按键时先响一声短音，**再**朗读。
        #:
        #: 为什么要这一声：读屏用户分不清「按键没送到」和「送到了但没出声」——
        #: 两种情况的听感都是**安静**（`无障碍可行性验证.md` §7）。
        #: 有了提示音就能三分：有音有朗读=正常 / 有音没朗读=朗读通路坏了 /
        #: 没音=按键根本没送到。
        #:
        #: ⚠⚠ **不要删这个字段**（0.0.0.5 那次整理删过，代价见下）：
        #: `key_cue()` 读它，删掉就 `AttributeError`，而它抛出的位置很致命 ——
        #: `05_repeat.rpy` 的 F5 在响提示音那一步就中断，**`repeat()` 永不执行**；
        #: F9 / F10 / Ctrl+Shift+I 的处理函数整段在 try 里，异常被吞 ⇒
        #: **四个键全部失灵，日志里只有一行 log_exc**。
        #: 现在有断言 I（`tools/lint_patch.py`）在静态层面拦这类「删了定义、
        #: 留着引用」的错误。
        CfgKeyCue = True

        #: 重读键的默认绑定。
        #: ⚠ **不能用 `Backspace`**（维护者其它无障碍仓库用它）：本作是 Ren'Py 游戏，
        #: `renpy/common/00keymap.rpy:86` 把 `Backspace` 给了 `input_backspace`
        #: （`:100`/`:101` = `input_delete_word`/`input_delete_full`）—— 原生键表里有它，
        #: 补丁再抢就会两边争事件，实测后果「按退格没反应」。
        #: 上游纪律的直接应用：**不去抢游戏原生占用的键**。
        #:
        #: 改用 `F5`：对 `00keymap.rpy` 与全部反编译脚本实查，F5 **无人占用**
        #: （已占：F1 帮助 / F2 进度 / F3 性能 / F4 图像日志 / F7 内存 / F8 单次 profile /
        #: F11 全屏）。仍走 Ren'Py 的 keymap，玩家能在引擎设置里改。
        CfgRereadKey = ["K_F5"]

        #: 逐作层的「这一句念什么」钩子，签名 `(who, what) -> str`。
        #: 返回 None 或空串表示不朗读这一条。
        SpeechPlan = None

        #: ★ 逐作层钩子：`SpeakerIsUnvoiced(who) -> bool`
        #: ——「这个说话人**本来就没有配音**吗」。
        #:
        #: 为什么要单开一个钩子、而不是让平台层去问配音通道：
        #: `preferences.voice_sustain = True` 时（本作 `options.rpy:279` 正是如此），
        #: 上一句的配音会在下一句开始时**还在播**，于是「没有配音的说话人」
        #: 会被运行时状态误判成有配音 ⇒ 只念名字、**正文被吞**。
        #: 判据必须是**作品事实**（这个角色有没有配音），那只有逐作层知道。
        #:
        #: 维护者原话（这是**按作品事实做的调整**，不是修 bug）：
        #: 「主角是没有配音的，它也需要读屏支持」。
        #: 本作实现见 `a11y_game/20_textproc.rpy` —— 它从游戏自己的角色定义里
        #: 推导（有配音的角色都带 `voice_tag`），**不硬编码名字**。
        SpeakerIsUnvoiced = None

        #: 逐作层的「主菜单条目」函数，签名 `() -> list[str]` —— 平台层不知道本作
        #: 主菜单有哪些按钮，也不该知道：主菜单是图片按钮，文案要看图确认。
        MainMenuItems = None

        # ------------------------------------------------------------ 平台层槽位
        #: 由各平台文件在 init 阶段填进来（见各自的注释）。
        speech = None
        repeat = None
        keys = None
        rpy = None
        #: 选项界面控制器（逐作层提供：选项长什么样只有逐作知道）
        choice = None

        #: ★ 控件文案表之一：**图片路径 -> 文案**，`{"xxx_normal.png": "文案"}`。
        #:
        #: ⚠ 这些表是**播报时查询**的（拉模型），不是"预先注入、等别人来读"。
        #:    推模型（写 `style.alt` 再指望别人去读）那半代码已删除 —— 那个中间人
        #:    从头到尾没起作用，是好几轮排查走错方向的根源（CHANGELOG 0.0.0.5、docs §8.1）。
        #:
        #: 键可以写全路径、文件名、去掉 `_normal/_idle/_click/_hover/_selected` 的文件名，
        #: 或去掉扩展名的词干 —— 平台层四种都查（宽进）。
        #: 文案必须**看图确认**（上游红线：别名表每条都要有依据），出处写在逐作层注释里。
        UiAltByImage = None

        #: 滑杆（Bar）文案表：`{"music volume": "音乐音量"}`。
        #: 键是引擎的 preference 名（`Preference("music volume")` 里的那个字符串）。
        UiAltByPreference = None

        #: ★ **位置表**：`{("界面名", x, y): "文案"}`。用于**同一张图对应多个含义**时：
        #: 本作设置界面里音乐/音效/语音静音是同一张图，时语与星弥的「有/无」也是同一张图，
        #: 只按图片路径分不出谁是谁。而它们的 `xpos/ypos` 是源码里的字面常量，与引擎焦点表
        #: 给出的坐标一致（`focus.py:88-96` 的 `Focus.x/.y`）⇒ 位置**稳定可核对**。
        UiAltByPos = None

        #: 逐作层的兜底钩子，签名 `(key, widget, ctx) -> str|None`。给「图片路径 + 位置
        #: **都**认不出来」的少数控件用，典型是**循环生成**或**同一张图重复出现**的控件
        #: （存读档的 12 个格子、音声的曲目列表、立绘页六行的小三角）。
        #:
        #: `ctx` 是一个 dict：
        #:     screen   界面名（引擎焦点表里的 `screen_name`）
        #:     pos      (x, y) 屏幕坐标
        #:     ordinal  ★ **同界面、同一张图的第几个**（0 起，按 (y, x) 排序）
        #:     total    同组一共几个
        #:
        #: ⚠ `ordinal` 来自「按屏幕先后排序」而**不是**坐标反推：存读档格子按钮的图是
        #:    462×260、格子是 462×306，按坐标反推会因差 46 像素而**全部判定失败**，
        #:    表现是 12 个存档位一个都不出声（见 08_uialt.rpy 的 `_scan`、docs §8.3）。
        #:    逐作层要「第几个」时**一律用 ordinal**。
        #:
        #: 返回 None 就是不认识（平台层把它记进作业清单，不会编造）。
        UiAltFor = None

        #: 运行期控件朗读文本注入器（平台层实现，见 08_uialt.rpy）
        uialt = None

        #: 舞台标识，随每台机器的存档走，方便排查
        stage = ""

        # ------------------------------------------------------------ 日志
        _logs = []

        #: 补丁启动的单调时间原点（见 `stamp`）。
        _t0 = None

        @staticmethod
        def stamp():
            """`+12.345s` —— 相对补丁起步的**单调时间戳**。

            没有时间轴的取证文件里，「补丁送出去了、读屏没出声」与「送出去之后又被
            自己下一句取消」**长得一模一样**：两次 `OK backend=NVDA` 隔 0.4 秒还是
            4 秒，看不出来。判据（用 `time.monotonic()`，不受系统改时间影响；
            绝对时刻对排查没有价值）：
              · 两条 `OK` 只差几十毫秒 ⇒ 时序/抢占问题；
              · 差好几秒且后面没有别的调用 ⇒ 问题在读屏那一侧。
            """
            try:
                import time
                if A11yHost._t0 is None:
                    A11yHost._t0 = time.monotonic()
                return "+%8.3fs" % (time.monotonic() - A11yHost._t0)
            except Exception:
                return "+   ?    "

        @staticmethod
        def key_cue():
            """按键已经收到的**听觉确认**（一声短提示音）。理由见 `CfgKeyCue`。

            「按键没送到」与「送到了但读屏没出声」在听感上**完全一样**（都是安静），
            读屏用户分不出来。有这一声就能一次三分：有声 + 有朗读 = 正常；
            有声 + 没朗读 = 朗读通路坏了；没声 = 按键没送到（docs §7.4）。
            两个细节都是踩出来的：
              1. **不能同步响** —— `winsound.Beep(1000, 60)` 阻塞 60 毫秒 = 卡三帧，
                 所以丢进守护线程里响；
              2. **不能只用 `MessageBeep`** —— 它播系统声音方案里的那一声，而方案里
                 那一项可以被设成「(无)」，那就成了**安静地"确认"**，比没有更坏
                 （会误判成「按键没送到」）。`Beep` 是直接合成音，不依赖声音方案。

            绝不上抛异常：这一声只是辅助，坏了也不能影响游戏。
            """
            if not A11yHost.CfgKeyCue:
                return

            def _beep():
                try:
                    import winsound
                    winsound.Beep(1000, 60)
                except Exception:
                    try:
                        import winsound
                        winsound.MessageBeep(winsound.MB_ICONASTERISK)
                    except Exception:
                        pass

            try:
                import threading
                threading.Thread(target=_beep, daemon=True).start()
            except Exception:
                pass

        @staticmethod
        def log(msg):
            """唯一的日志出口。"""
            try:
                line = "[A11y] %s %s" % (A11yHost.stamp(), msg)
                A11yHost._logs.append(line)
                if len(A11yHost._logs) > 400:
                    del A11yHost._logs[:200]
                renpy.display.log.write(line + "\n")
            except Exception:
                pass

        @staticmethod
        def log_exc(msg):
            try:
                renpy.display.log.write("[A11y] %s\n" % msg)
                renpy.display.log.exception()
            except Exception:
                pass

        @staticmethod
        def diag(msg):
            """详细诊断日志（含判定过程）。**默认关闭**：打开后 log.txt 会变成
            「含剧本原文 + 判定推理」的排查件，只在本机排查时开。
            """
            if not A11yHost.CfgDiagLog:
                return
            try:
                renpy.display.log.write("[A11y详] %s %s\n" % (A11yHost.stamp(), msg))
            except Exception:
                pass

        @staticmethod
        def said(text):
            """**永久开启**的朗读记录：写「实际送去读屏的那一句」。

            不设开关、且与 `diag()` 分开，是因为补丁的故障只有两类，而用户的口头
            描述区分不开（实测原话：「症状很复杂，我的描述能力无法准确说明问题」），
            开发期又不可能让用户反复陪跑：
              (a) 「该读的没被送来」（挂载点 / 判据问题）；
              (b) 「送来了但读屏没出声」（后端 / 时序问题）。

            所以**始终写**，并且同时写两处 —— `renpy.display.log`（`<游戏>\\log.txt`）
            与补丁自己的 `<游戏>\\a11y_speech.log`。后者是刻意加的：`log.txt` 会被引擎
            在启动时重建，而玩家常常是「开着游戏看现象、关掉才反馈」，一份独立、
            不被覆盖的文件更适合当取证材料。

            ⚠ 它含**剧本原文**：`.gitignore` 已排除，README 写明「只发给维护者」。
            """
            try:
                line = "[A11y读] %s %s\n" % (A11yHost.stamp(), (text or "")[:160])
            except Exception:
                return
            try:
                renpy.display.log.write(line)
            except Exception:
                pass
            try:
                import os
                gd = getattr(config, "gamedir", None)
                if not gd:
                    return
                # 用 basedir（游戏根）而不是 gamedir，方便玩家找到
                bd = getattr(config, "basedir", None) or gd
                path = os.path.join(bd, "a11y_speech.log")
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                pass

        @staticmethod
        def said_result(text, ok, backend):
            """记录一次朗读的**结果**（成功与否 + 当前后端）—— 把「哑掉」拆成
            「没送来」还是「送来了后端没接」的关键一行。
            """
            try:
                line = "[A11y果] %s %s backend=%s text=%r\n" % (
                    A11yHost.stamp(), "OK" if ok else "失败", backend, (text or "")[:60])
            except Exception:
                return
            try:
                renpy.display.log.write(line)
            except Exception:
                pass
            try:
                import os
                bd = getattr(config, "basedir", None) or getattr(config, "gamedir", None)
                if not bd:
                    return
                with open(os.path.join(bd, "a11y_speech.log"), "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                pass

        @staticmethod
        def validate():
            """漏填就写一行 Warning，而不是静默失效。"""
            missing = []
            for k in ("GameName", "GameVersion", "PatchVersion"):
                if not getattr(A11yHost, k, ""):
                    missing.append(k)
            if missing:
                A11yHost.log("Warning: A11yHost 未填: %s" % ", ".join(missing))
            A11yHost.log("契约: 游戏=%s 游戏版本=%s 补丁版本=%s 后端=%s 自动开自语音=%s" % (
                A11yHost.GameName or "?", A11yHost.GameVersion or "?",
                A11yHost.PatchVersion or "?", A11yHost.CfgSpeechBackend or "自动",
                A11yHost.CfgAutoEnable))
            return not missing
