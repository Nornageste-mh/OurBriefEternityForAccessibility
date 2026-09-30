# A11yFramework / Ren'Py 版 —— 引擎适配层（L2.5）· 朗读出口接管
#
# 这一层在上游 A11yFramework 里**不存在**，是新加的，理由如实说明：
#
#   上游的 L1 平台层直接建在 UnityEngine 上 —— 它认 Selectable、CanvasGroup、
#   WorldToScreenPoint，挂载点靠 Harmony。Ren'Py 是完全不同的引擎：
#     - 没有 uGUI，界面是 screen language 描述的 displayable 树；
#     - 没有 Harmony，挂钩走引擎自己的 config 回调；
#     - 但引擎**自带**一整套 self-voicing 基础设施（焦点跟踪、alt、
#       `_tts_all`、控件角色识别、`config.tts_function` 出口）。
#
#   本补丁对它的用法只有两条（**不是**「把『读什么』交给引擎」）：
#     · 接管 `config.tts_function` —— 引擎真出声时，发声走本补丁的后端链；
#     · `read_screen()` 借它拼一次整屏文本（触发与发声仍归本补丁）。
#   引擎自语音**保持关闭**：对话/旁白、界面控件、选项的播报全由补丁自己负责，
#   控件走 `08_uialt.rpy` 的**拉模型**（播报那一刻才查逐作文案表）。
#   为什么不用引擎那条路（它报的是容器文字与状态词，没有控件名字）见
#   `ensure_self_voicing`；推模型与导航模式的复盘见 CHANGELOG 0.0.0.2 / 0.0.0.5。
#
# 本文件里出现的都是**引擎通用**的东西（不带任何本作标识符），逐作不得改写。
# tools/lint_patch.py 的断言 B 会机械拦下来。

init -50 python:

    import re as _a11y_re

    class A11yRenpy(object):
        """把 Ren'Py 的 self-voicing 出口接到 A11yFramework 的后端链上。"""

        # ---------------------------------------------------------------- 通用清洗
        # ★ 本节规则只依赖「中文视觉小说的通用排版习惯」，不依赖任何本作知识。
        #   逐作专属规则由逐作层通过 `add_substitutions()` 追加。
        #
        #   为什么清洗必须落在这一层：上游流水线把「文本清洗」列为逐作必须重查的
        #   两件事之一，原因就是**各作要处理的类别完全不同**。
        #   这里先给出通用的一批，逐作再补自己那份 —— 与上游 TextProc.cs 的分工一致。
        GENERIC_SUBS = [
            # 「连续省略号」在朗读里会被逐字念成「省略号省略号…」，
            # 这是中文视觉小说最常见的排版噪声（本作实测 1460 处）。
            (_a11y_re.compile(r"…{2,}|\.{6,}"), "……"),
            (_a11y_re.compile(r"—{2,}|─{2,}"), "——"),
            (_a11y_re.compile(r"[~～]{2,}"), "～"),
            (_a11y_re.compile(r"[!！]{3,}"), "！！！"),
            (_a11y_re.compile(r"[?？]{3,}"), "？？？"),
            (_a11y_re.compile(r"[ \u3000]{2,}"), " "),
            (_a11y_re.compile(r"\\n"), " "),
        ]

        def __init__(self):
            self._game_subs = []
            self._started = False
            self._startup_done = False
            self._dialogue_installed = False
            #: 过滤器被调用过（可能是执行，也可能是预测）—— 只当信号用
            self._filter_seen = False
            #: 上一次真正朗读出去的那一句（用 `_last_say_what` 的值做去重）
            self._last_announced_what = None
            #: 去重窗口用（见 `_drop_duplicate`）
            self._last_dialogue = ""
            self._announcing = False
            #: 主菜单播报的边沿标记（见 `_menu_watch`）
            self._menu_shown = False
            #: 上一次引擎从本补丁出口送出的**文本**（见 `_tts_sink`）。
            #: `08_uialt.rpy` 的控件播报靠它判断「引擎报的是不是就是这一条」——
            #: **只比文本，不比时间**：按时间让位那条判据已废（引擎会一直报别的
            #: 文本，本层会永远让位）。
            self.last_sink_text = None

        # ---------------------------------------------------------------- 逐作接口
        def add_substitutions(self, pairs):
            """逐作层登记自己那份清洗规则。必须在 `start()` 之前调用。"""
            for p in pairs:
                self._game_subs.append(p)

        # ---------------------------------------------------------------- 登记
        def register_subs(self):
            """把清洗规则登记到 `config.tts_substitutions`。

            ⚠ 时机是**实证**出来的，不是猜的：

                renpy/main.py:412   renpy.game.script.load_script()   加载全部脚本
                renpy/main.py:488   node.execute_init()              执行 init 块
                renpy/main.py:581   renpy.translation.init_translation()
                                    └─ renpy/translation/__init__.py:917
                                       renpy.display.tts.init()
                                       └─ **这一步才**把 config.tts_substitutions
                                          **编译**进 renpy.display.tts.tts_substitutions

            本文件所有 init 块都早于 `tts.init()`，所以只能往
            `config.tts_substitutions` 登记，不能去塞那个尚未建好的已编译列表。

            登记格式 `(已编译的正则, 替换串)`（`tts.py:242-248` 实查）：非 str 的
            pattern 被原样收下、替换串直接交给 `re.sub`，所以反引用要写 `"\\1"`
            （`tts.py:246` 只对 str 分支做 `\\` 转义）。
            """
            try:
                lst = config.tts_substitutions
                for p in self.GENERIC_SUBS:
                    lst.append(p)
                for p in self._game_subs:
                    lst.append(p)
                A11yHost.log("清洗规则已登记: 通用 %d 条 + 逐作 %d 条（config 现 %d 条）"
                             % (len(self.GENERIC_SUBS), len(self._game_subs), len(lst)))
            except Exception:
                A11yHost.log_exc("登记清洗规则失败")

        # ---------------------------------------------------------------- 出口接管
        def _tts_sink(self, s):
            """`config.tts_function` 的新实现。

            它收到的是**引擎已经拼好的最终朗读串** ——
            包括 self-voicing 的开关提示、界面控件的 alt、
            以及对话框的「谁 + 说什么」（`displayable.py:637` 用 `": "` 拼接）。
            我们不重新实现「读什么」，只改「怎么发声」：
            全部经 `A11yRepeat.say()` 走同一出口，于是重读键能重读其中任何一条。

            ⚠ 前提是**引擎那条链真的走到了出口**：`tts.displayable()` 在
            `self_voicing` 为假时直接 return（`tts.py:398-405`；`tts()` 与
            `speak()` 同样如此），而 `ensure_self_voicing` 每次交互都把自语音
            关掉 —— 所以本函数平时不响，只在玩家手动打开自语音时才会被走到。

            ★ 顺带记下**这次出口送出的文本**（`last_sink_text`）：
            `08_uialt.rpy` 的控件播报靠它判断「引擎报的是不是就是这一条」，
            于是引擎吭声时让位、引擎沉默时补上（实机里出现过引擎报**容器文字**
            而不是控件名字的情况）。
            """
            self.last_sink_text = s
            try:
                s = self._apply_plan(s)
            except Exception:
                A11yHost.log_exc("SpeechPlan 异常，退回原文")
                s = s
            s = self._strip_engine_noise(s)
            if not s:
                return
            # ★ 去重：同一句话不要念两遍。
            #
            # 实测现象：同一句台词会出现两条 `say:` 日志 —— 一条来自我们自己的
            # `announce_dialogue`，另一条来自**引擎自己的 self-voicing**。
            # 判据：与刚念过的那句吻合，且**不是我们自己的调用**（`_announcing`）。
            # 前提同上（引擎自语音平时是关的），所以它多数时候不会触发 ——
            # 它是玩家手动打开自语音时的保险，代价是零。
            if self._drop_duplicate(s):
                A11yHost.diag("丢弃引擎重复朗读: %r" % s[:80])
                return
            try:
                A11yHost.repeat.say(s, interrupt=True)
            except Exception:
                A11yHost.log_exc("tts_function 异常")

        def _drop_duplicate(self, s):
            r"""判断引擎这一条**是不是本补丁已经念过的**，是就丢弃。

            ── 为什么只比「刚念过的那句台词」────────────────────────────────

            现在的分工是：**对话/旁白、界面控件、选项的播报全由补丁自己负责**
            （控件走 `08_uialt.rpy` 的拉模型），引擎自语音保持关闭
            （`ensure_self_voicing` 每次交互都关）。于是两个源同时出声只有一种
            可能：玩家手动打开了自语音 —— 那种情况下**让位判据在
            `08_uialt.rpy` 的 `_announce`**（拿 `last_sink_text` 做文本比对），
            不在这里。

            早期版本还比过 `_last_menu_announce` / `_last_choice_announce` /
            `_last_menu_item` 三条 —— 当时 `CfgAutoEnable=True`，引擎也报菜单
            与控件，两个源在几十毫秒内交替念同样的东西。那三条对应的字段已随
            0.0.0.5 与本次整理删除，**不要加回来**：拿存下来的整批播报文本去压
            引擎的控件播报，会把该听见的一起吃掉（复盘见 CHANGELOG 0.0.0.2）。

            引擎读不出台词（对话朗读一节开头有实测记录），所以「引擎重复念一句
            台词」本来就少 —— 这条判据留着当保险，代价是零。
            """
            if self._announcing:
                return False                       # 本补丁自己的调用，放行
            t = (s or "").strip()
            if not t:
                return True

            own = [self._last_dialogue]
            for o in own:
                if not o:
                    continue
                o = o.strip()
                if not o:
                    continue
                if t == o or t in o or o in t:
                    return True

            # ⚠ 不要再加回「自己念过的整批播报就丢弃」那几条比较（见文档字符串）：
            #   让位判据只有一条，在 `08_uialt.rpy` 的 `_announce` 里。
            return False

        def _apply_plan(self, s):
            """把最终朗读串交给逐作钩子过一遍。

            约定：引擎拼好的串形如 `谁: 台词`（`displayable.py:637` 实查）。
            这里把 `who` / `what` 拆出来给钩子，
            钩子只需决定「这一句念什么」，不必自己解析字符串。
            """
            plan = A11yHost.SpeechPlan
            if plan is None:
                return s
            if ": " in s:
                who, _, what = s.partition(": ")
                return plan(who, what)
            return plan("", s)

        #: 引擎在跳过/快进时拼进根 displayable 的噪声前缀。
        #: 依据：实测日志里出现的
        #: `root_tts='正在快进: ▸: ▸: ▸: 但——'` ——
        #: 那是 `screen skip_indicator`（本作 scripts/screens/screen_skip_indicator.rpy）
        #: 的文本被 `_tts_common` 的 `": "` 拼接带进来的。
        #: 玩家不需要听见「正在快进」后面跟一串三角符号。
        _NOISE = None

        #: 引擎自语音开关提示（见 `_strip_engine_noise`）。
        _SELFVOICE = None

        def _strip_engine_noise(self, s):
            if not s:
                return s
            if A11yRenpy._NOISE is None:
                A11yRenpy._NOISE = _a11y_re.compile(
                    r"^(?:\s*(?:正在快进|正在跳过|skipping|fast\s*forward)\s*:?\s*"
                    r"(?:[▸►▶・:：\s])*)+")
                # 引擎**打开自语音的那一刻**会自带一句提示
                # （`tts.py:409-417` 的 `"Self-voicing enabled. "`，
                #   本作 `tl/None/common.rpym:13-14` 译作「机器朗读已启用。」）。
                # 那是引擎在报**它自己的开关**，不是玩家要听的内容 —— 吃掉它。
                # ⚠ **但绝不去预设 `old_self_voicing` 来消除它**：
                #   那会让引擎的 `last_raw` 永不清空，界面一次都不播报
                #   （事故记录见 `ensure_self_voicing`）。
                A11yRenpy._SELFVOICE = _a11y_re.compile(
                    r"^(?:\s*(?:Self-voicing enabled\.|Self-voicing disabled\."
                    r"|机器朗读已启用。|机器朗读已禁用。"
                    r"|Clipboard voicing enabled\.|剪贴板朗读已启用。)\s*)+")
            try:
                out = A11yRenpy._NOISE.sub("", s).strip()
                out = A11yRenpy._SELFVOICE.sub("", out).strip()
                # 全部是噪声时返回空串，让上层直接不出声
                if not out or set(out) <= set("▸►▶:： "):
                    return ""
                return out
            except Exception:
                return s

        # ---------------------------------------------------------------- 整屏朗读
        def read_screen(self):
            """朗读**当前整个界面**（F10，键表见 `06_keymap.rpy`）。

            ── 为什么需要它 ──────────────────────────────────────────────────

            有些内容**不是控件**，靠焦点朗读永远读不到。最典型的是
            「历史记录」界面里过去那些台词：它们在 `viewport` 里，
            既没有 `alt`，也不是按钮 —— 补丁给按钮补文案的那套机制
            对它完全无效。玩家必须能主动把眼前的界面读一遍。

            ── 实现：借引擎拼一次整屏文本，而不是自己重写一遍 ────────────────

            `renpy.display.tts.displayable(None)` 的参数为 `None` 时，
            引擎会把 `root` 当作朗读目标（`tts.py:423-424`），拼出整屏文本 ——
            包括 `group_alt`（组名）、`renpy.notify` 的通知文本，以及它自己的
            去重。补丁只负责触发，不自己走一遍 displayable 树。

            ⚠ 这一步要求引擎自语音**开着**：`tts.displayable()` 在
            `self_voicing` 为假时**直接 return**（`tts.py:398-405`），而
            `ensure_self_voicing` 每次交互都把它关掉 —— 所以这里**必须在这一个
            调用期间临时把它打开**，读完立刻恢复。

            早先这里只写了「自语音关闭时只有触发与日志，没有引擎那一步」，
            等于**F10 按下去永远没有声音**（而且日志里只有 `[按键] 整屏朗读`
            一行触发记录，看起来像"读了但没声"，很难查）。
            文本一旦进了 TTS 队列就不再受这个开关影响
            （`tts.tick()` 每帧把队列交给出口），所以恢复得很安全。

            ⚠ 触发前必须清空 `last_raw`：引擎有「内容没变就不重复念」的判据
            （`tts.py:447-448`），而玩家按 F10 的意图恰恰是「再念一遍」——
            不清空的话第二次按**悄无声息**，会被当成按键坏了。
            """
            try:
                import renpy.display.tts as _t
                _t.last_raw = None

                # 临时打开自语音（只为这一个调用；读完恢复）
                saved = None
                try:
                    import renpy.game as _g
                    saved = _g.preferences.self_voicing
                    if not saved:
                        _g.preferences.self_voicing = True
                except Exception:
                    saved = None

                try:
                    _t.displayable(None)
                finally:
                    if saved is not None:
                        try:
                            _g.preferences.self_voicing = saved
                        except Exception:
                            pass
                return True
            except Exception:
                A11yHost.log_exc("朗读当前界面失败")
                return False

        def install_sink(self):
            """把出口指向本框架。在 init 阶段调用，早于玩家看到任何界面。"""
            self._disable_engine_voice_guard()

            # 1) 登记清洗规则（必须早于 tts.init()，见 register_subs 的说明）
            self.register_subs()

            # 2) 接管朗读出口
            try:
                config.tts_function = self._tts_sink
                A11yHost.log("已接管 config.tts_function")
            except Exception:
                A11yHost.log_exc("接管 tts_function 失败")

            # 3) 后端链
            try:
                A11yHost.speech.init()
                # ⚠ 模式必须在 `init()` **之后**设：`set_mode` 会用已注册后端名
                #   做白名单核对（拼错的配置名不能让补丁整局哑掉），
                #   而那份白名单是 `init()` -> `register_builtin()` 填的。
                A11yHost.speech.set_mode(A11yHost.CfgSpeechBackend)
            except Exception:
                A11yHost.log_exc("后端链初始化失败")

        def _disable_engine_voice_guard(self):
            r"""★ 拆掉引擎那条「配音在播就不朗读」的守卫 —— 它是本作哑掉的**根因**。

            引擎源码 `renpy/display/tts.py:419-421`：

                for i in renpy.config.tts_voice_channels:   # 默认 ["voice"]
                    if not prefix and renpy.audio.music.get_playing(i):
                        return          # ← 直接返回，后面的朗读代码根本不执行

            `config.tts_voice_channels` 默认是 `["voice"]`（`config.py` 实查，
            本作没有改过它），而本作的**系统语音**恰好走在 `voice` 通道上
            （`scripts/controls/PlayRandomSystemVoice.rpy` 实查：
            `def __init__(self, scene_group, channel="voice")`）。于是**游戏每播
            一次按钮系统语音，引擎就在源头把朗读掐掉**，根本走不到
            `config.tts_function`（我们的出口）—— 实测症状与用户描述一致：
            「只有游戏自带的音效叮叮当当的响」、音效越频繁补丁越哑。

            可以安全清空，因为：本补丁**自己**已按「本行有没有配音」精确判断
            要不要念正文（`_line_has_voice()` + 三条规则，见 `announce_dialogue`），
            不需要引擎这层粗粒度守卫；而它的副作用（把系统语音、音效也算作
            「配音」）会把**旁白与界面播报**一起掐掉。
            清空之后：有配音的角色台词仍只报名字（由补丁判断），
            旁白/主角独白照常全文朗读，系统语音不再阻断任何朗读。
            """
            try:
                old = list(config.tts_voice_channels)
                config.tts_voice_channels = []
                A11yHost.log("已拆掉引擎的配音守卫: tts_voice_channels %r -> []" % (old,))
            except Exception:
                A11yHost.log_exc("清空 tts_voice_channels 失败")

        # ---------------------------------------------------------------- 冷启动
        def ensure_self_voicing(self):
            r"""确保引擎的自语音**始终是关的** —— 界面控件播报由本补丁负责。

            ── 两次实机记录（来回改过两次，**改回去之前先读这里**）───────────

            **关**：用户亲耳确认可用 —— 主菜单整批 + 逐项都由本补丁的焦点跟踪
              报出，原话「主菜单怎么说也是能朗读了」。
            **开**：当时的理由看着很充分 —— 引擎自带 `focus.py:217` 焦点变化
              -> 读控件 `alt`、`group_alt` 组名、`renpy.notify` 通知、内容去重，
              还有自语音打开时的线性方向键顺序（`focus.py:890-895`）。
              实机结果，用户原话：**「主菜单不读，设置界面有些读有些不读」**。
              取证文件里引擎报的是设置界面的一段说明文字、它自己的状态词
              「选定」（本作 tl 把 `selected` 译作「选定」）、preference 按钮
              内建的 alt「跳过没见过的」—— 全是引擎自己凑出来的文本，没有一条
              是控件名字，补丁给控件写的那份文案一条都没出现。

            结论：**拿不到实机调试时，把播报押在一条自己观察不到的引擎通路上
            是错的。** 现在的分工：焦点一变，`08_uialt.rpy` 的 `_track_focus`
            就查表念该控件（拉模型）；引擎那条通路保持关闭 ⇒ 也不会再冒出
            「容器文字」与状态词。完整复盘见 CHANGELOG 0.0.0.2。

            ⚠ **绝不要预设 `renpy.display.tts.old_self_voicing`**：它是
            「刚从关变开」的边沿标记（`tts.py:409-417`），预设成 True 会让
            `last_raw` 永不清空，引擎的「内容没变就不重复念」逻辑会认为
            一切都是旧的 —— 实测后果是**整个界面一次都不播报**。
            """
            try:
                if _preferences.self_voicing:
                    _preferences.self_voicing = False
                    A11yHost.log("已关闭引擎自语音：控件播报改由本补丁负责"
                                 "（理由见 A11yRenpy.ensure_self_voicing 的两次实机记录）")
            except Exception:
                A11yHost.log_exc("关闭引擎自语音失败")

            try:
                self.once_startup()
            except Exception:
                A11yHost.log_exc("开屏播报失败")

        def once_startup(self):
            """开屏播报，只做一次。"""
            if self._startup_done:
                return
            self._startup_done = True
            self.announce_startup()

        def announce_startup(self):
            """开屏播报：只报「补丁在、后端是哪个」。

            ── 为什么这一句要**短到极致** ────────────────────────────────────

            它是整个游戏的第一句，而主菜单那句紧跟其后、而且会**打断它**
            （见 `announce_main_menu`）。按中文读屏默认语速，一句 45 字要念七八秒，
            这七八秒里玩家只能干等 —— 而真正有用的是「主菜单有哪些项、
            按什么键」，不是版本号。

            所以按键提示**挪到主菜单那句里**（那时玩家正好要动手），
            这里只留「补丁已加载 + 后端是谁」。后端是谁要报：
            排查「为什么没声音」时，这是第一时间要知道的事。

            ── 为什么不能说「按 V 开关语音」────────────────────────────────
            `v` 是引擎内建的 `self_voicing` 开关（`renpy/common/00keymap.rpy`），
            而在 Windows 上引擎默认走 `say.vbs` -> **SAPI**，
            **它不认识正在运行的 NVDA**。对 NVDA 用户来说按 `v`
            并不是「开关朗读」，而是「换一个声音念」或「干脆不念」。
            第一版的开屏提示写了这句话，实测把维护者（读屏用户）误导了。
            """
            name = A11yHost.GameName or "本游戏"
            ver = A11yHost.PatchVersion or "?"
            backend = A11yHost.speech.backend_name()

            if backend == "(无)":
                msg = "%s无障碍补丁。没有可用的朗读后端，请确认读屏软件正在运行。" % name
            else:
                msg = "%s无障碍补丁 %s 已加载。朗读后端：%s。" % (name, ver, backend)
            ok = A11yHost.repeat.say(msg, interrupt=True)
            # ★ 自检：**说「没有后端」却把它念出来了** ⇒ 判定取到了过期状态。
            #   这一条是实机事故的防线：开屏播报曾一边说「没有可用的朗读后端」，
            #   一边被 NVDA 清楚地念出来。根因见 `A11ySpeech.backend_name`。
            if backend == "(无)" and ok:
                A11yHost.log("Warning: 开屏播报自称没有后端，但朗读成功了 —— "
                             "backend_name() 与 speak() 的状态解读不一致（见 01_speech.rpy）")
            A11yHost.log("开屏播报后端=%s（%s）" % (backend, "已出声" if ok else "未出声"))

        # ---------------------------------------------------------------- 启动
        def start(self, game_subs=None):
            """由逐作层调用一次。`game_subs` 为该作的清洗规则。"""
            if self._started:
                return
            self._started = True
            if game_subs:
                self.add_substitutions(game_subs)
            self.install_sink()
            self.install_dialogue()
            config.interact_callbacks.append(self._tick)
            config.interact_callbacks.append(self.ensure_self_voicing)
            # ★ **每帧**的挂载点与上面那两个不是一回事，见 `_periodic` 的说明。
            config.periodic_callbacks.append(self._periodic)
            A11yHost.log("A11yRenpy 已启动（interact 回调 2 个 + 每帧回调 1 个）")

        def _tick(self):
            """**每次交互开始时**跑一次（`config.interact_callbacks`）。

            ⚠ 这个挂载点的语义是实证出来的，不是望文生义：
            `renpy/display/core.py:2445-2446` 在 `interact_core` 的**开头**
            把 `config.interact_callbacks` 里的每一项**无参**调用一次 ——
            也就是**一次交互一次**，绝不是「每帧一次」。
            对「对话朗读」来说这正合适：每一句台词都是一个新交互，
            所以对话一推进就会被走到（这也是对话一直是好的那一部分）。
            但**对焦点跟踪完全不合适** —— 那类活儿挂在 `_periodic` 上。
            """
            try:
                self._flush_dialogue()
            except Exception:
                pass

        def _periodic(self):
            """**每帧**跑一次（`config.periodic_callbacks`）。

            ⚠ 这个挂载点的**频率语义**是实证出来的，不是望文生义
            （`renpy/display/core.py:3060-3065`：`PERIODIC` 事件到达时逐个
            **无参**调用；`PERIODIC_INTERVAL = 50`，`core.py:124/938`
            —— 桌面端 20 Hz）：

              · `interact_callbacks` 是**一次交互一次**，
                而方向键移动焦点走的 `change_focus()` **不重启交互**
                （`focus.py:534-579`）—— 所以「跟随焦点」的活儿
                挂在 `interact_callbacks` 上必然漏掉绝大多数变化。
                这是「主菜单无效」的根因（复盘见 CHANGELOG 与 docs/）。

            这里做的三件事都是**幂等且廉价**的：
              · `speech.tick()` —— 内部按 3 秒节流，只管「先开游戏后开读屏」；
              · `uialt.tick()`  —— 内部每 0.25 秒扫一遍引擎焦点表，记下控件身份
                                   （界面 / 坐标 / 同图名次）供播报时查表；
                                   另外每帧只比较一个字符串（值变化检测）；
              · `_menu_watch()` —— 边沿触发，界面没变就什么都不做。
            """
            try:
                A11yHost.speech.tick()
            except Exception:
                pass
            try:
                if A11yHost.uialt is not None:
                    A11yHost.uialt.tick()
            except Exception:
                pass
            try:
                self._menu_watch()
            except Exception:
                pass

        def _menu_watch(self):
            """主菜单出现时报一次。用**每帧轮询**，不依赖 `on "show"`。

            ⚠ 实测事故：补丁第一版在主菜单覆盖界面里用
            `on "show" action Function(...)` 播报，**没有触发**。
            原因是 `screen main_menu` 带 `tag menu`，引擎会复用同一个 tag 的
            界面实例（切到设置再回来时并不重新 show），
            于是这个钩子在真实路径上不可靠。

            教训与对话那次的 `config.all_character_callbacks` 是同一条：
            **一个存在的钩子不等于它会在你需要的时候被调用** ——
            要么用日志证明它被调用了，要么换一个一定会被走到的地方。

            「一定会被走到的地方」就是每帧回调（`config.periodic_callbacks`，
            见 `_periodic`）加一个边沿标记：进主菜单时播一次，离开后重置，
            再回来会再播一次（这正是需要的语义）。
            """
            showing = False
            try:
                showing = renpy.get_screen("main_menu") is not None
            except Exception:
                showing = False
            if not showing:
                try:
                    showing = bool(renpy.showing("main_menu"))
                except Exception:
                    showing = False

            if not showing:
                self._menu_shown = False
                return
            if not self._menu_shown:
                self._menu_shown = True
                try:
                    A11yHost.rpy.announce_main_menu()
                except Exception:
                    A11yHost.log_exc("主菜单播报失败")
            # ⚠ 逐项播报**不在这里** —— 在 `08_uialt.rpy` 的 `_track_focus`：
            #   焦点一变就念该控件的文本（拉模型：播报那一刻才取数 ——
            #   优先读控件自己的 `style.alt`，主菜单六个按钮的 `alt` 写在
            #   逐作层的屏幕覆盖里，见 `31_main_menu.rpy`）。
            #   这比补丁按 y 坐标反推序号**更准**：读到的一定是真正被聚焦的
            #   那个控件，未解锁的「特殊模式」不是按钮、不在焦点表里，
            #   于是天然不会被念到 —— 而按 y 反推时它会让序号整体错位一位
            #   （实机事故，复盘见 CHANGELOG 0.0.0.2）。

        # ══════════════════════════════════════════════════════════════════
        # 这里曾经是本补丁自己写的「主菜单逐项播报」（按 y 坐标反推序号 +
        # 逐作层维护的平行文案清单），两次失败后撤除。现在逐项播报在
        # `08_uialt.rpy` 的 `_track_focus` 里（报**真正被聚焦的那个控件** +
        # 查表，拉模型），本函数只管整批播报。
        #
        # ── 两次失败的原因是通用教训，与主菜单无关，留着 ──────────────────
        #
        # 第一版失效：挂在 `config.interact_callbacks` 上。那个挂载点是
        #   **一次交互一次**（`core.py:2445-2446`），而方向键移动焦点走的
        #   `change_focus()` **不重启交互**（`focus.py:534-579`）—— 于是判定
        #   只在「刚进界面、还没有焦点」时跑过一次，留下「无几何（焦点=None）」
        #   之后**永不再被调用**。教训：**挂载点的调用频率是语义的一部分**。
        #
        # 第二版失效（接口对了、频率也对了，仍然错）：它用「候选 y 的名次」
        #   当序号，却**不要求候选数与条目数相等** —— 数量不等时名次与文案
        #   下标之间没有任何关系，报文案就是编造（未解锁的「特殊模式」是一张
        #   图、不是按钮、不在焦点表里，于是序号整体错位一位）。
        #   教训：**凡是「按位置对上文案」的地方，都必须先断言数量相等。**
        #   （复盘见 CHANGELOG 0.0.0.2）
        # ══════════════════════════════════════════════════════════════════


        def announce_main_menu(self):
            """整批播报主菜单。

            文本由逐作层提供 —— 平台层不知道本作主菜单有哪些按钮，
            也不该知道（`tools/lint_patch.py` 的断言 B 会拦下来）。
            """
            items = None
            try:
                fn = A11yHost.MainMenuItems
                if fn is not None:
                    items = fn()
            except Exception:
                A11yHost.log_exc("MainMenuItems 异常")
            if not items:
                return
            # ⚠ 按键提示只留 **F5**：F10「朗读整个界面」实测**没有预期效果**
            #   （维护者实机反馈），按维护者要求**不再向玩家提起**它
            #   —— 键与代码留着（未查清），但不做承诺、不当卖点。
            #   （复盘见 CHANGELOG 0.0.0.7；代码在 `read_screen()`。）
            msg = "主菜单。%s。按方向键移动，回车键确认。按 F5 重读上一句。" % "，".join(items)
            A11yHost.said("[主菜单播报]")
            # 标记为本补丁自己的调用，否则 `_drop_duplicate` 会把它当重复压掉
            self._announcing = True
            try:
                # ⚠⚠ `interrupt=True` **是改回来的，不要再改成排队**。
                #
                # 中间试过「排队、不打断」（理由是不想丢掉开屏那句的尾巴）——
                # **实机后果是主菜单整批播报听不到**，用户原话
                # 「主菜单怎么又不朗读了」：开屏播报很长，菜单播报排队在它
                # 后面，而玩家一动（焦点一变 `_track_focus` 就会播报、按键有
                # 提示音）这条排队项就被取消。
                #
                # 现在的分工很干脆：
                #   · 开屏那句压到最短（只剩「补丁已加载 + 后端是谁」）；
                #   · 主菜单这句**立刻打断**它，把「有哪些项 + 怎么走 + 按什么键」
                #     一次说完 —— 那才是玩家此刻要的东西。
                A11yHost.repeat.say(msg, interrupt=True)
            finally:
                self._announcing = False

        def note_choice_announce(self, msg):
            """逐作层的选项界面在整批播报之后调用（`30_choice.rpy`）。

            ⚠ 现在**什么都不存**，保留这个入口只为不改逐作层的调用点：
            压引擎重复条目的那几条比较早已撤掉（见 `_drop_duplicate`），
            存下来的文本没有任何读者 —— 它**不是**「记下来供去重」。
            """

        # ---------------------------------------------------------------- 对话朗读
        # ★★ 本补丁最核心、也是最「逐作通用」的一段 ★★
        #
        # 为什么不能靠引擎内建自语音朗读台词 —— 这是**实测**出来的，不是推测：
        #
        #   `focus.set_focused()` 调 `tts.displayable()`（focus.py:217）。对话框
        #   聚焦的是 `SayBehavior`，而它的 `_tts_all` 无条件
        #   `raise TTSRoot()`（behavior.py:716）—— 意思是「别念我这个控件，
        #   去念根 displayable」。`displayable()` 于是回退到
        #   `root._tts_all()`（tts.py:423-434）。
        #
        #   而实测（tools 的诊断探针，见 README「如何复现分析」）：
        #     对话进行中 root.layers = ['master','overlay','screens','transient']
        #     master  层：只有背景与立绘（Image/Solid），无文本
        #     screens 层：只有 quick_menu 的按钮（Button._tts() 恒为 ""，by design）
        #     transient层：只有 SayBehavior 本身 → 抛 TTSRoot
        #     ⇒ root._tts_all() == ''   ——**台词一个字都取不到**
        #
        #   同时实测 `renpy.get_screen('say')` 在对话期取到的是别的交互的缓存，
        #   逐帧采样恒为 None；`focus_list` 在对话期长度为 0（只在主菜单有 5 个）。
        #
        #   结论：**Ren'Py 8.6 的内建自语音在本作里读不出台词。**
        #   补丁必须自己承担对话朗读 —— 这正是「每作都会冒出一个的
        #   本作特有形态」，只不过这一次它是引擎层面的。
        #
        # 挂载点选 `config.say_menu_text_filter`（`ast.py:971` 在每个 say 语句
        # 执行前同步调用，见 `install_dialogue`），而不是去 patch 引擎内部函数
        # —— 后者在 Ren'Py 版本升级时会碎。

        def install_dialogue(self):
            """登记对话朗读的挂载点。幂等。

            ── 为什么不用 `config.all_character_callbacks`（实测教训）──────────

            第一版用的就是它（引擎给说话人的官方接口，本作
            `scripts/screens/screen_say.rpy` 自己也在用它缓存侧边图）——
            注册确实成功、手动自调用也成功，但**真实 say 语句推进时，引擎一次
            都没有调用它**（日志里那条 `cb show ...` 从未出现）。

            教训：上游流水线 §7 铁律 1 说「不许猜方法名和对象名」，下半句是
            **也不许假设一个存在的挂载点一定会被调用** —— 必须用日志证明它
            真的被调用了。

            ── 现在用的挂载点 ─────────────────────────────────────────────

            `config.say_menu_text_filter`：`renpy/ast.py:971` 在**每个 say 语句
            执行前同步调用**它，`ast.py:1787` 在每个 menu 选项上调用它。
            本作**没有占用**这个钩子（读 scripts/options.rpy 与全部反编译脚本实查）。

            它只拿到文本、拿不到说话人，所以这里只负责「捕获 + 打标记」，
            说话人在下一帧由 `_flush_dialogue()` 从 `_last_say_who` 取
            （`ast.py:985` 在 say 执行前设置，因此下一帧读到的必定是本行的）。
            """
            if self._dialogue_installed:
                return
            self._dialogue_installed = True
            try:
                config.say_menu_text_filter = self._text_filter
                A11yHost.log("对话朗读挂载点已登记 (config.say_menu_text_filter)")
            except Exception:
                A11yHost.log_exc("登记对话朗读挂载点失败")

        def _text_filter(self, s):
            r"""`config.say_menu_text_filter` 的实现。

            ⚠ 它必须**原样返回文本** —— 这是过滤器，不是回调；
            改了它就会改掉游戏显示的内容（上游红线：无障碍层不得改变游戏行为）。
            所以这里只做「打一个标记」，返回值原封不动。

            ⚠⚠ **这里记下的文本不能直接拿去朗读。** 实测事故：用户反馈
            「剧情部分的文本，每一句都读的对，但读出来的大概率不是现在屏幕上
            显示的这一句」。原因是这个过滤器**不只在执行时被调用，预加载时
            也会**：`renpy/ast.py:971` 是 `Say.execute`，`renpy/ast.py:1017` 是
            **`Say.predict`**（预读下一句）—— 记下来的常常是「还没显示的那句」。

            真正朗读的文本由 `_flush_dialogue()` 从**权威来源**取
            （`store._last_say_what`，见那里的说明）。

            另外它也会在 `--lint` 时被调用（lint.py:472）。那时没有 game context，
            所以整段包在 try 里，出错就算了 —— 绝不能让 lint 因为补丁而失败。
            """
            try:
                self._filter_seen = True
            except Exception:
                pass
            return s

        def _flush_dialogue(self):
            r"""朗读**当前正在显示**的那一句。

            ── 权威来源是 `store._last_say_what`，不是过滤器捕获的文本 ──────

            `renpy/ast.py:984-988` 在**真正执行** say 之前写入：

                if getattr(who, "record_say", True):
                    renpy.store._last_say_who  = self.who
                    renpy.store._last_say_what = what

            它与 `Say.predict` 那条路径无关，所以写进去的**一定是正在显示的内容**。
            过滤器捕获的文本则会掺进预测结果（见 `_text_filter` 的说明），
            因此只拿来当「有新台词了」的信号。

            去重：同一句只念一次。判据用 `_last_say_what` 的值本身 ——
            引擎在预测时不会改它，所以「值没变」就等于「还是同一句」。
            """
            if not self._filter_seen:
                return
            self._filter_seen = False

            what = None
            try:
                what = getattr(store, "_last_say_what", None)
            except Exception:
                what = None
            if not isinstance(what, str) or not what.strip():
                # 还没执行到 say（可能只是预测）—— 下一帧再看
                self._filter_seen = True
                return

            if what == self._last_announced_what:
                return
            self._last_announced_what = what

            who = self._speaker_name()
            try:
                self.announce_dialogue(who, what)
            except Exception:
                A11yHost.log_exc("对话朗读异常")

        def _speaker_name(self):
            """取**本行**说话人的显示名。

            来源是 `store._last_say_who`（`ast.py:985` 在 say 执行前写入）。
            它存的是**源码里的表达式串**（形如 `xx_`），
            所以再拿它去 store 取对象、读 `Character.name`
            —— 这样拿到的一定是画面上的**显示名**，不是角色变量名。
            没有说话人时它是 `None`，本函数返回空串（旁白/主角独白）。

            本函数刻意**不含任何本作的标识符** —— 说话人是谁属于逐作知识，
            平台层只负责「把变量名换成显示名」这套通用规则。
            """
            try:
                w = getattr(store, "_last_say_who", None)
                if w is None:
                    return ""
                if isinstance(w, str):
                    obj = getattr(store, w, None)
                    if obj is not None:
                        return getattr(obj, "name", "") or ""
                    return w
                return getattr(w, "name", "") or ""
            except Exception:
                return ""

        @staticmethod
        def _line_has_voice():
            """本行是否配有语音文件（引擎的权威判据）。

            ⚠ 不要改用「配音**通道**是否正在播放」来判断：本作
            `preferences.voice_sustain = True`，上一行的配音会在下一行开始时
            仍在播放，拿它判会把连续旁白整段误判成「有配音」（实测）。
            """
            try:
                vi = _get_voice_info()
                return bool(getattr(vi, "auto_filename", None))
            except Exception:
                return False

        @staticmethod
        def _voice_audible():
            """配音通道现在**听得见**吗（玩家可能把它调到 0 或静音）。

            为什么要有这一条：规则 2 现在是「有配音就一个字都不念」
            （维护者要求：配音本身就在说明是谁在说）。可玩家要是把配音音量
            拉到 0，那些行就会**既没有配音、也没有朗读** —— 整段剧情凭空消失。
            这种漏读是无障碍里最严重的一类，所以在这里兜一下：
            配音听不见时，退回「全文朗读」。

            判据用**玩家偏好里的混音器音量**（`preferences.get_volume`，
            `preferences.py:351` 实查），不是通道当前状态 —— 后者前面已经吃过亏。
            取不到音量时**假定听得见**（宁可少念，不可与配音打架）。
            """
            try:
                import renpy.game as _g
                v = _g.preferences.get_volume("voice")
                if v is not None and float(v) <= 0.0:
                    return False
            except Exception:
                pass
            return True

        # ⚠ 这里**故意没有**「跳过中 / 还在说话」这类守卫 —— 两条判据都实测过、
        #   都不能用：
        #     · `config.skipping` 有 `None` / `"fast"` / `"slow"` 三态
        #       （`00action_menu.rpy:303-336`、`behavior.py:350` 实查）：只有
        #       `"fast"` 是引擎真的在快进，`"slow"` 是「跳过已读」—— 拿
        #       「非 None」当判据会把慢速跳过一起误伤。本作的「自动」又是另一条
        #       开关（`preferences.afm_enable`，`AutoAfterChoices.rpy` 实查），
        #       `config.skipping` 不能当它的代理。
        #     · `tts_queue` 非空只表示「有文本还没被 `tick()` 送出去」，而
        #       `tick()` 由渲染循环驱动 —— 与「读屏正在说话」无关。第一版加过
        #       这一条当守卫，结果**整局朗读被静音**（最难查的一类故障）。
        #   语义明确的判据只有 `renpy.display.tts.is_active()`（`tts.py:76-77`，
        #   朗读进程存活期间为真）；真需要「等上一条说完」时用它。

        @staticmethod
        def _clean_for_speech(s):
            """把文本过一遍与朗读链相同的清洗，保证「听到的」与「读到的」一致。"""
            try:
                import renpy.display.tts as _t
                return _t.apply_substitutions(s)
            except Exception:
                return s

        def announce_dialogue(self, who, what, voice=None):
            """对话朗读的**策略**。

            ★ 判据是**有没有角色名**，不是「有没有配音文件」。

            这一条是维护者（本人即读屏用户）实机试听后纠正的，原话：
            「旁白和主角是没有配音的，对于旁白，是没有角色名的，
              因此对于没有配音的内容，直接朗读全部内容就行。」

            这条规则比「查配音文件」更可靠 —— **前者的失败是实测到的**：
            第一版用 `VoiceInfo.auto_filename` 判「本行有没有配音」，
            结果连续旁白全被判成「有配音」而整段跳过朗读
            （探针日志里连着四条 `dialogue(voice) 旁白，跳过`）。
            而旁白 / 独白占本作剧情文本的 **43.2%**，漏读就是叙事残缺
            —— 正是上游那条红线「只读一部分 = 无障碍完整性问题」。

            最终规则（三条，按优先级）：

            1. **没有角色名** ⇒ 旁白 / 主角内心独白 ⇒ **无条件朗读全文**。
               这个判据本身是可直接观测的事实：引擎拼出来的 `谁: 台词`
               在没有说话人时**根本不带 `": "` 前缀**（`displayable.py:637`
               实查用 `": "` 连接），所以「有没有角色名」不需要猜。
            2. **有角色名、有配音** ⇒ 只报「名字：」，正文交给配音。
            3. **有角色名、无配音** ⇒ 全文朗读。
            """
            if not what:
                return
            text = self._clean_for_speech(what)

            has_speaker = bool(who and who.strip())
            if voice is None:
                # 只有「有角色名」才需要问配音 —— 旁白根本不走配音
                if not has_speaker:
                    voice = False
                else:
                    # ★ 先问「这个说话人**本来就没有配音**吗」—— 维护者原话：
                    #   「主角是没有配音的，它也需要读屏支持」。
                    #
                    #   为什么不能只看配音通道在不在播：本作
                    #   `preferences.voice_sustain = True`（`options.rpy:279`），
                    #   上一句的配音会在下一句开始时**还在播**，于是主角这句被
                    #   `tts.is_active()` 误判成「有配音」⇒ 只念名字、**正文被吞**。
                    #
                    #   判据是作品事实，不是运行时状态：游戏自己的角色定义里
                    #   **有配音的角色都带 `voice_tag`**（时语/星弥/房东…），
                    #   主角「林小凑」与几个配角没有（`scripts/roles/role.rpy` 实查）。
                    #   逐作层据此给出答案（平台层不知道本作有哪些角色）。
                    unvoiced = False
                    fn = A11yHost.SpeakerIsUnvoiced
                    if fn is not None:
                        try:
                            unvoiced = bool(fn(who))
                        except Exception:
                            A11yHost.log_exc("SpeakerIsUnvoiced 钩子异常")
                    voice = False if unvoiced else self._line_has_voice()
                    if unvoiced:
                        A11yHost.diag("说话人原本无配音，按全文朗读: %r" % who[:20])

            # 记下这一行，供 `_drop_duplicate` 抑制引擎那条重复朗读。
            self._last_dialogue = text.strip()

            plan = A11yHost.SpeechPlan
            if plan is not None:
                try:
                    planned = plan(who, text)
                    if planned is not None:
                        text = planned
                except Exception:
                    A11yHost.log_exc("SpeechPlan 异常，退回原文")

            self._announcing = True
            try:
                if not has_speaker:
                    # 规则 1：旁白 / 主角独白 —— 无条件全文朗读
                    A11yHost.diag("规则1 旁白(无角色名) 全文朗读: %r" % text[:60])
                    A11yHost.repeat.say(text, interrupt=True)
                elif voice and self._voice_audible():
                    # 规则 2：有配音 —— **不自动念**，但要做两件事。
                    #
                    # 维护者原话：「已经配音的角色台词就不需要朗读名字了」——
                    # 配音本身就在说明是谁在说，再念名字是噪声。
                    #
                    # ① **整句进重读缓冲区**（`remember`，只记不念）。
                    #    这一条是**对齐上游流水线**的硬规则，不是我临时想的：
                    #      上游 `Reader.cs`：「有配音的行如果只 Speech.Stop() 而不记
                    #      缓冲区，退格会念出**上一句**，玩家会以为『这一句翻不回来』」
                    #      —— 那是一条**真实反馈**；
                    #      上游 `Repeat.cs`：「凡是玩家可能想重听的东西，都要进缓冲区
                    #      —— 包括有配音的行……玩家主动按重读键仍然要能听到
                    #      （这是它唯一的朗读通路）」；
                    #      上游发布清单：「重读能覆盖：普通台词 / **有配音台词** /
                    #      选项组 / 快进经过的行」。
                    #    ⇒ 记的是**整句台词**（不是只记名字）：配音错过了、或没听清，
                    #      按 F5 让读屏把它念一遍，正是重读键该干的事。
                    #
                    # ② **打断上一句还没念完的朗读**（上游 `Nvda.cs` 同款处置：
                    #    「切到有配音的台词时，避免和语音重叠」）。
                    #    这一条我以前漏了：规则 2 不发声 ⇒ 也就不会触发出口里的
                    #    「打断」逻辑 ⇒ 上一句的长旁白会一直念下去，盖住配音的开头。
                    A11yHost.diag("规则2 有配音 静音（整句入重读缓冲区）: %r" % who[:20])
                    A11yHost.repeat.remember(text)
                    try:
                        A11yHost.speech.stop()
                    except Exception:
                        pass
                else:
                    # 规则 3：有角色名但无配音 —— 全文朗读
                    # （若说话人本来就没配音，或玩家把配音调到听不见，
                    #   都走这一条；否则那几句会变成一片安静。）
                    A11yHost.diag("规则3 无配音 全文朗读: %r" % text[:60])
                    A11yHost.repeat.say(text, interrupt=True)
            finally:
                self._announcing = False

        # ---------------------------------------------------------------- 诊断
        def probe_report(self, tag):
            """取证用：把「朗读决策点的全部相关事实」写进日志。

            ⚠ 由 Ctrl+Shift+I 的现场快照调用（`06_keymap.rpy` 的 `on_diag`，
            **不需要** `CfgDiagLog`）。它**会打印剧本文本**（`root._tts_all` 与
            `get_screen()._tts` 的结果），所以按 IP 红线：**产生的 log.txt
            不得提交、不得外传**，只在本机排查时用。

            为什么需要它：无障碍补丁最难的一环从来不是「后端不出声」，
            而是「引擎决定不念这一条」。那一步在
            `renpy/display/tts.py:displayable()` 里 —— 只有把
            `self_voicing` / 配音通道 / `focus_list` / 根 displayable
            四样同时看到，才能判断是谁把话吞了。
            本补丁正是靠这段探针查明了「引擎内建自语音读不出台词」这个事实。
            """
            try:
                import renpy.audio.music as _m
                import renpy.display.focus as _f
                import renpy.display.tts as _t

                r = _t.root
                layers = getattr(r, "layers", None)

                vch = []
                for ch in renpy.config.tts_voice_channels:
                    try:
                        vch.append((ch, _m.get_playing(ch)))
                    except Exception:
                        vch.append((ch, "?"))

                fl = _f.focus_list
                focused = _f.get_focused()

                A11yHost.log("PROBE[%s] sv=%r layers=%r voice=%r focus_n=%d focused=%s root_tts=%r" % (
                    tag,
                    renpy.game.preferences.self_voicing,
                    sorted(layers.keys(), key=str) if layers else None,
                    vch, len(fl),
                    type(focused).__name__ if focused is not None else None,
                    (r._tts_all(raw=False)[:120] if r is not None else None)))

                if layers:
                    for lname in sorted(layers.keys(), key=str):
                        ld = layers[lname]
                        try:
                            lt = ld._tts_all(raw=False)
                        except Exception as e:
                            lt = "<异常 %s>" % type(e).__name__
                        try:
                            kids = len(ld.visit())
                        except Exception:
                            kids = -1
                        if kids == 0:
                            continue
                        A11yHost.log("PROBE[%s]   layer %-10s %-14s visit=%d tts=%r" % (
                            tag, lname, type(ld).__name__, kids, str(lt)[:140]))

                for i, fo in enumerate(fl[:8]):
                    w = getattr(fo, "widget", None)
                    A11yHost.log("PROBE[%s]   focus[%d] %s arg=%r" % (
                        tag, i, type(w).__name__ if w is not None else None, fo.arg))

                for sname in ("say", "choice", "main_menu", "quick_menu"):
                    try:
                        sc = renpy.get_screen(sname)
                    except Exception:
                        sc = None
                    if sc is None:
                        continue
                    try:
                        stt = sc._tts(raw=False)
                    except Exception as e:
                        stt = "<异常 %s>" % type(e).__name__
                    A11yHost.log("PROBE[%s]   screen %-10s %s _tts=%r" % (
                        tag, sname, type(sc).__name__, str(stt)[:160]))
            except Exception as e:
                A11yHost.log("PROBE[%s] 探针自身异常 %s: %s" % (tag, type(e).__name__, e))


    A11yHost.rpy = A11yRenpy()
