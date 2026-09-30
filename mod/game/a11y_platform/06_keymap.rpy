# A11yFramework / Ren'Py 版 —— 平台层（L1）· 按键绑定
#
# L1 冻结层，逐作不得改写。
#
# ════════════════════════════════════════════════════════════════════════════
# 两条必须记住的引擎事实（实机撞出来的，不是推的；复盘见 docs §7.1）
# ════════════════════════════════════════════════════════════════════════════
#
# ── 事实一：初始化偏移 `init 1200` 不能改小 ─────────────────────────────────
#
#   `renpy/common/00keymap.rpy:433-466` 在 **init -1100** 做
#       config.underlay = [ _default_keymap ]        # ← 整体赋值，不是 append
#   任何早于它的登记都会被它覆盖掉。本文件因此用 1200（晚于引擎的 -1100/1100，
#   也晚于游戏自己的 init 0 脚本）。
#
# ── 事实二：`renpy.Keymap` 的值是**无参调用**的 ★★ 这条害掉过一整轮 ★★ ──────
#
#   behavior.py:550-565  Keymap.event   rv = run(action)                   # ← 没有参数
#   behavior.py:384-411  run            return action(*args, **kwargs)     # ← args 空
#
#   ⇒ **键处理函数绝不能声明成 `def on_key(self, ev)`**，更不能去读 `ev`：读了就
#     恒为 `None`，于是整个键**静默失效**。补丁第一版正是这么写的 —— 用户实机反馈
#     「重读无效」，取证文件里一行 `[重读]` 都没有（代码一次都没跑到）。
#     被调用就等于按键成立：`map_event` 用 `compile_event`（behavior.py:129-211）
#     拼出来的判据已经把「KEYDOWN / 非长按重复 / 没有按住 alt-meta-ctrl / 键码相符」
#     全判完了。
#
#   ⇒ **进 Keymap 的每一个值都必须是「无参可调用对象」**，
#     `tools/lint_patch.py` 的断言 E 就是从这条来的。
#
# ════════════════════════════════════════════════════════════════════════════
# 键位占用实查（不许猜：对 `renpy/common/00keymap.rpy` 与全部反编译脚本逐个核过）
# ════════════════════════════════════════════════════════════════════════════
#
#   引擎占用：F1 帮助 / F2 进度 / F3 性能 / F4 图像日志 / F7 内存 / F8 单次 profile /
#             F11 全屏 / Tab 跳过 / PageUp-Down-鼠标中键 回退 /
#             Backspace 文本输入删字（`input_backspace`，`00keymap.rpy:86`）
#   本作只改过两处 keymap：`scripts/screens/screen_quick_menu.rpy`（dismiss /
#   hide_windows / game_menu / help / screenshot / self_voicing）与
#   `scripts/screens/screen_gallery.rpy`（dismiss）。
#
#   ⇒ 补丁登记的全部按键（一处不落，见 `_A11yInstallKeymap`）：
#       F5 重读上一句 / F9 切换朗读后端 / F10 整屏朗读 / Ctrl+Shift+I 现场快照 /
#       数字 1-9 选项直选（主键盘 + 小键盘）/ 方向键 ↑↓ 线性导航（左右留给滑杆与视口）
#     F6 / F12 空着（F6 曾用于「界面导航模式」，该模式已删除，见 CHANGELOG 0.0.0.5）。
#
# ⚠ 与维护者其它无障碍仓库的差异（必须写进 README，不能默默不同）：其它仓库的重读键
#   默认是 `Backspace`，本作**不能用它** —— 引擎把它给了文本输入，而本作确实有文本
#   输入界面（`scripts/screens/screen_input.rpy` 实查）。上游纪律：**不抢原生占用的键**。

init 1200 python:

    from renpy.display.behavior import Keymap as _A11yKeymap


    def _A11yValidSpecs(names):
        r"""★ 用**引擎自己的解析器**筛键名，丢掉解析不了的。

        两次事故（都发生在「初始化之后、游戏开始之前」）与现在的做法：

        1. 补丁写过 `K_KP_UP` / `K_KP_DOWN`（想覆盖小键盘方向键），而 pygame 里
           **没有**这些名字；`behavior.py:211` 拿它去 `getattr(pygame.constants, key)`
           ⇒ `AttributeError` ⇒ **游戏完全起不来**。
        2. 判据曾经是「名字在 `dir(pygame.constants)` 里」。它对单段键名（`K_F5`）
           成立，但 Ren'Py 的键名是**可组合**的 —— `ctrl_shift_K_r` / `alt_K_RETURN` /
           `noshift_K_f` / `repeat_K_PAGEUP` / `anyrepeat_K_BACKSPACE` / `mouseup_3`
           在 `pygame.constants` 里都找不到，于是被过滤器**误杀**：逐作层配的重读键
           `ctrl_shift_K_r` 被丢掉、`config.keymap["A11yReread"]` **根本没登记**，
           而 `renpy.Keymap` 照样被构造出来 ⇒ 那个键静默变成永不匹配。用户看到的是
           「重读无效」，日志里只有一行 `已丢弃引擎不认识的键名: ctrl_shift_K_r`，
           看起来还像是「正常的自我保护」。
        3. 现在直接调引擎的 `compile_event(spec, True)` 试解析：解析得了 ⇒ 合法
           （引擎自己认，不可能与本补丁的判断不一致）；抛异常 ⇒ 丢掉。

        ⚠ 必须**临时把 `config.developer` 置为 True** 再解析：`compile_event` 对非法
        名字有两条路（behavior.py:197-199）—— 发行版里 `config.developer` 是假值，
        非法名字**不抛异常**、只静默编译成恒假的 `(False)`，那样本函数永远筛不出坏
        名字，等于没筛。置 True 才能让它当场露馅，拿到异常再吃掉；解析完立刻还原。
        """
        ok, bad = [], []
        try:
            from renpy.display.behavior import compile_event as _compile_event
            old_dev = config.developer
        except Exception:
            # 拿不到引擎解析器时**一个都不放行** —— 宁可补丁的键不生效，
            # 也不能让游戏起不来。
            A11yHost.log("Warning: 取不到 compile_event，补丁按键全部停用")
            return []

        try:
            config.developer = True
            for n in names:
                try:
                    _compile_event(n, True)
                    ok.append(n)
                except Exception:
                    bad.append(n)
        finally:
            try:
                config.developer = old_dev
            except Exception:
                pass

        if bad:
            A11yHost.log("已丢弃引擎解析不了的键名: %s" % ", ".join(bad))
        return ok


    def _A11yNavAction(delta):
        """把「上/下一个」包成**无参**可调用对象（同 `_A11yDigitAction`）。"""
        def _nav_act():
            try:
                if A11yHost.uialt is not None:
                    A11yHost.uialt.nav_move(delta)
            except Exception:
                A11yHost.log_exc("线性导航异常")
        return _nav_act


    def _A11yDigitAction(n):
        r"""把「第 n 个数字键」包成一个**无参**可调用对象（见文件头事实二）。

        一个数字一个 keymap 项，是因为处理函数**收不到事件** —— 读 `ev.unicode` /
        `ev.key` 反算数字在「收不到事件」的前提下根本不成立（第一版连事件都没拿到）。
        分辨按键是**引擎**的活：九个名字、九条判据、九个无参闭包。
        对齐维护者其它仓库的约定（`CfgChoiceHotkeys`「数字键直选」）：主键盘与小键盘都认。
        """
        def _act():
            A11yHost.keys.press_digit(n)
        return _act


    def _A11yInstallKeymap():
        """登记补丁的键名与按键层。幂等。只看**登记成功**的键名。"""
        binds = {}

        # ---- 重读键 ----
        reread = _A11yValidSpecs(list(A11yHost.CfgRereadKey or []))
        if reread and "A11yReread" not in config.keymap:
            config.keymap["A11yReread"] = reread
            A11yHost.log("已登记重读键 A11yReread = %s" % reread)
        if "A11yReread" in config.keymap:
            binds["A11yReread"] = [A11yHost.repeat.on_key]
        else:
            # ★ 登记失败时**绝不放一个名字进 Keymap**：放进去的话，正式版里它会静默
            #   变成恒假（开发者模式下则直接抛异常）—— 前者让玩家以为键坏了，
            #   后者让游戏起不来。
            A11yHost.log("Warning: 重读键登记失败（%r），本次不绑定" % (
                A11yHost.CfgRereadKey,))

        # ---- 数字键直选（1-9，主键盘 + 小键盘）----
        digit_n = 0
        for i in range(1, 10):
            name = "A11yChoiceDigit%d" % i
            specs = _A11yValidSpecs(["%d" % i, "K_KP%d" % i])
            if specs and name not in config.keymap:
                config.keymap[name] = specs
                digit_n += 1
            if name in config.keymap:
                binds[name] = [_A11yDigitAction(i)]
        if digit_n:
            A11yHost.log("已登记选项数字直选键: %d 组（主键盘 + 小键盘）" % digit_n)

        # ---- 朗读后端切换键（排查用）----
        cyc = _A11yValidSpecs(["K_F9"])
        if cyc and "A11yBackendCycle" not in config.keymap:
            config.keymap["A11yBackendCycle"] = cyc
            A11yHost.log("已登记朗读后端切换键 A11yBackendCycle = %s" % cyc)
        if "A11yBackendCycle" in config.keymap:
            binds["A11yBackendCycle"] = [A11yHost.keys.on_backend_cycle]

        # ---- 整屏朗读键 ----
        # 为什么需要它：不是所有内容都是控件 —— 历史记录里过去的台词在 `viewport` 里，
        # 没有 alt、也不是按钮，焦点朗读永远读不到它。F10 空着（占用表见文件头）。
        rds = _A11yValidSpecs(["K_F10"])
        if rds and "A11yReadScreen" not in config.keymap:
            config.keymap["A11yReadScreen"] = rds
            A11yHost.log("已登记整屏朗读键 A11yReadScreen = %s" % rds)
        if "A11yReadScreen" in config.keymap:
            binds["A11yReadScreen"] = [A11yHost.keys.on_read_screen]

        # ---- 现场快照键（诊断用）----
        # ⚠ 这个键以前**只写在注释里**（`90_plugin.rpy` 说「按 Ctrl+Shift+I 打快照，
        #   见 _backend_info」），而那个函数与那个键都不存在。假注释比没有注释更贵：
        #   下一次排查会先去找一个不存在的东西。现在把它做成真的。
        # 用 ctrl_shift_K_i 而不是 shift_K_i：后者是引擎的 inspector
        # （`renpy/common/00keymap.rpy`），带 ctrl 就不冲突。
        dia = _A11yValidSpecs(["ctrl_shift_K_i"])
        if dia and "A11yDiag" not in config.keymap:
            config.keymap["A11yDiag"] = dia
            A11yHost.log("已登记现场快照键 A11yDiag = %s" % dia)
        if "A11yDiag" in config.keymap:
            binds["A11yDiag"] = [A11yHost.keys.on_diag]

        # ---- 线性导航键（方向键）----
        # 为什么补丁要接管方向键：自语音打开时引擎走 `focus_ordered`（线性），关掉后走
        # `focus_nearest`（几何就近），而几何就近在设置界面那种两列混排里**够不到一部分
        # 控件** —— 用户实机反馈正是「除了对键盘导航做出了限制就没区别了」。
        # 详见 08_uialt.rpy 的 `nav_move` 与 docs §8.2。
        #
        # 只管上下：左右要留给滑杆（`adjust_left/right`）与视口滚动 —— 那些控件在自己的
        # `event` 里就吃掉了按键，而**只有上面没人要的按键才会落到这一层**，天然不冲突。
        nav_up = _A11yValidSpecs(["K_UP"])
        nav_down = _A11yValidSpecs(["K_DOWN"])
        if nav_up and "A11yNavUp" not in config.keymap:
            config.keymap["A11yNavUp"] = nav_up
            A11yHost.log("已登记线性导航键 A11yNavUp = %s" % nav_up)
        if nav_down and "A11yNavDown" not in config.keymap:
            config.keymap["A11yNavDown"] = nav_down
            A11yHost.log("已登记线性导航键 A11yNavDown = %s" % nav_down)
        if "A11yNavUp" in config.keymap:
            binds["A11yNavUp"] = [_A11yNavAction(-1)]
        if "A11yNavDown" in config.keymap:
            binds["A11yNavDown"] = [_A11yNavAction(1)]

        if not binds:
            A11yHost.log("Warning: 没有任何补丁按键登记成功，按键层未插入")
            return

        # ★ 值全部是**无参可调用对象**（见文件头事实二）：`A11yHost.repeat.on_key` 是
        #   绑定方法（签名 `(self)`，调用时自绑 self，实际零参数）；数字与后端切换是闭包。
        km = _A11yKeymap(**binds)
        config.underlay.append(km)
        A11yHost.log("已插入按键层 %s (underlay 现有 %d 项)" % (
            sorted(binds.keys()), len(config.underlay)))


    class A11yKeys(object):
        """补丁自己的按键。

        ★ 两条纪律（照抄上游流水线）：

        1. **不去抢游戏原生占用的键**。README 必须列出「游戏原生占用的键」，声明补丁
           不抢、也不拿来当重读键。本作原生的推进/回退键全部来自引擎默认 keymap
           （`renpy/common/00keymap.rpy` 的 `_default_keymap`）—— 这是读
           `scripts/options.rpy`、`scripts/gui.rpy` 与 `00keymap.rpy` 实查出来的；
           全作唯一一处自定义键是 `scripts/debug/screen_profiler.rpy` 的 `shift_K_p`。
        2. **走 Ren'Py 的 keymap 机制**，不自己监听原始按键：好处是玩家能在引擎设置里
           改，keymap 的冲突检测也替我们兜底；代价是处理函数**收不到事件**（见文件头
           事实二），要区分按键内容只能「一个键一个名字」。
        """

        def install(self):
            """把补丁的键加进 keymap 与输入层。幂等。"""
            try:
                _A11yInstallKeymap()
            except Exception:
                A11yHost.log_exc("登记键盘绑定失败")

        # ------------------------------------------------------------ 数字键直选
        def press_digit(self, n):
            """数字键直选（`n` 从 1 开始）。**无参调用链的末端。**

            只在**选项界面正在显示**时生效；其余时候数字键照常交给游戏
            （上游红线：无障碍层不得改变游戏原有行为）。
            实现见 a11y_game/30_choice.rpy 的 `A11yChoice.press()`。
            """
            try:
                A11yHost.said("[按键] 数字 %d" % n)
                A11yHost.choice.press(n)
            except Exception:
                A11yHost.log_exc("数字键直选异常")

        # ------------------------------------------------------------ 后端切换
        def on_backend_cycle(self):
            """F9：在「自动 / NVDA / 引擎同款 SAPI / 两者同时」之间轮换。

            给玩家这个键，是因为本机实机上出现过「NVDA 控制器返回码恒为 0，但只有
            第一条出声」（见 01_speech.rpy 的「尚未查清」一节与 docs §7.5）：排查这类
            问题最重要的是能**当场换一条出声通路**并立刻听到结果，而不是关掉游戏改配置
            再重开 —— 盲人玩家做一次这样的循环成本极高。
            「两者同时」让同一句话同时走 NVDA 与引擎同款 SAPI：听得出哪一路在响就不必
            再靠猜，同时它也是**兜底档**（某一路坏了，另一路照读）。
            """
            try:
                A11yHost.key_cue()
                label = A11yHost.speech.cycle_mode()
                # 用新后端立刻报一句，玩家马上知道切成了哪一档。
                # `record=False`：不进重读缓冲（重读键应该重读剧情，不是这句）。
                A11yHost.repeat.say("朗读后端：%s" % label,
                                    interrupt=True, record=False)
            except Exception:
                A11yHost.log_exc("切换朗读后端失败")

        # ------------------------------------------------------------ 整屏朗读
        def on_read_screen(self):
            """F10：把**当前整个界面**念一遍。无参（见文件头事实二）。

            给「不是控件的内容」准备的：历史记录里过去的台词、某个界面上成排的文本。
            玩家按一下就听得到眼前有什么，不必靠方向键一个个摸。
            """
            try:
                # 先响一声「按键收到了」—— 它是这条键唯一的即时反馈：整屏朗读的内容
                # 由引擎随后送出，失败时是安静的，而安静容易被误判成「按键坏了」
                # （见契约层 CfgKeyCue）。
                A11yHost.key_cue()
                A11yHost.said("[按键] 整屏朗读")
                if not A11yHost.rpy.read_screen():
                    A11yHost.repeat.say("朗读界面失败。", record=False)
            except Exception:
                A11yHost.log_exc("整屏朗读异常")

        # ------------------------------------------------------------ 现场快照
        def on_diag(self):
            """Ctrl+Shift+I：把一份现场快照写进 `log.txt`（诊断用，无参）。

            它回答的是排查时最花时间的那个问题：「**该读的送到了没有**」：
            朗读后端与可用性结论 / 界面控件的文案覆盖与「未识别」清单（那就是下一轮的
            作业清单）/ 当前焦点被念成什么 / 引擎那一侧的完整现场（`probe_report`：
            自语音状态、根 displayable 能读到什么、焦点表内容）。

            ⚠ `probe_report` 会打印**界面上出现的文本**，所以这份 `log.txt` 按 IP 红线
            **只发给维护者、不得公开**（README 已写明）。
            """
            try:
                A11yHost.key_cue()
                A11yHost.said("[按键] 现场快照")
                A11yHost.log("=== 现场快照 ===")
                A11yHost.log("后端: %s | %s" % (
                    A11yHost.speech.backend_name(), A11yHost.speech.verdict()))
                if A11yHost.uialt is not None:
                    A11yHost.log(A11yHost.uialt.snapshot())
                A11yHost.rpy.probe_report("手动")
                A11yHost.log("=== 快照结束（内容见 log.txt） ===")
                # 给一句听觉确认：快照本身写在文件里，但玩家要知道「按到了」。
                A11yHost.repeat.say("已记录现场快照。", record=False)
            except Exception:
                A11yHost.log_exc("现场快照异常")

    A11yHost.keys = A11yKeys()
