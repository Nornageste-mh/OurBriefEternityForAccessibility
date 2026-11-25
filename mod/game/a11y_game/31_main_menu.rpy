# A11yFramework / Ren'Py 版 —— 逐作层（L3）
#
# 《永恒与星辰与日常》无障碍补丁 · 主菜单朗读
#
# ── 为什么必须覆盖 `screen main_menu` ────────────────────────────────────────
#
# 本作主菜单（`scripts/screens/screen_main_menu.rpy` 实查）是**纯图片按钮**：
#
#     imagebutton:
#         idle  "gui/custom2/title/title_menu_main_start_normal.png"
#         hover "gui/custom2/title/title_menu_main_start_click.png"
#         action [PlayRandomSystemVoice(10), Start()]
#
# 图片按钮既没有 `alt`，也没有文本子节点，于是朗读链是：
#   `Button._tts_all()` -> `alt(self.action)`（behavior.py:1199）
#   `alt(clicked)`      -> `clicked.alt`      （behavior.py:507-524）
# 而 `Start()` / `SafeContinue()` / `ShowMenu(...)` / `Quit(...)` 都**不带 alt**
# （引擎只为**内建**界面设 alt，如存档槽 `00action_file.rpy:395`）。
#
# ⇒ 朗读文本为空。实测用户反馈就是「主菜单完全听不到菜单项」。
#
# ── 文案从哪来（不许猜，全部看图确认）─────────────────────────────────────
#
# 按钮图上同时印着英文与中文，本补丁读**中文**那一行。
# 依据：`tools/` 从 images.rpa 里解出按钮图后逐张看图得到（不是从文件名猜的）：
#
#     title_menu_main_start_normal.png      START     开始游戏
#     title_menu_main_continue_normal.png   CONTINUE  继续游戏
#     title_menu_main_load_normal.png       LOAD      读取游戏
#     title_menu_main_system_normal.png     SYSTEM    系统设置
#     title_menu_main_extra_normal.png      EXTRA     特殊模式
#     title_menu_main_exit_normal.png       EXIT      退出游戏
#
# ── 覆盖原则 ────────────────────────────────────────────────────────────────
#
# 1. **视觉逐字保留**：下面每个尺寸/位置/过渡/音效/条件分支都与原作一致，
#    只增 `alt`（只影响朗读，不影响画面）。
# 2. **不改 `action`**：按钮的激活语义与游戏原生完全一致
#    （包括 `PlayRandomSystemVoice(...)` 那串系统语音）。
# 3. 「继续游戏」在没存档时是 `insensitive`（图是 locked），朗读文案相应写成
#    「（尚未解锁）」那样与画面一致的说明 —— 上游红线是「把本来能看到/能操作的
#    东西等价呈现」，不可用就要说出来，但不能替玩家把它变可用。

init offset = -10

# ⚠ **Python 函数必须写在 `init python:` 块里** —— 本文件初版把下面两个函数写成
#   裸的顶层 `def`，引擎直接拒绝解析（`File "…31_main_menu.rpy", line 50:
#   expected statement.`），玩家看到的是「解析脚本失败」；`init offset` 是编译期
#   指令，不能让顶层容纳 `def`。这条已由断言 A2 机械拦住（tools/lint_patch.py）。
init -10 python:

    def _a11y_demo_unlocked():
        """1.70 起主菜单的「特殊模式」解锁条件多了一项 `obe_demo`。

        原作 `scripts/screens/screen_main_menu.rpy:121` 是
        `if persistent.gallery_unlocked or obe_demo:`（1.70 新增的 Demo 版开关，
        `scripts/options.rpy` 里 `define -999 obe_demo = _obe_demo_build`，
        正式版恒为 False）。1.63 上没有这个变量，所以**必须**用 getattr 探测；
        取不到按 False 处理，与正式版一致。
        """
        try:
            if persistent.gallery_unlocked:
                return True
        except Exception:
            return False
        try:
            return bool(getattr(renpy.store, "obe_demo", False))
        except Exception:
            return False

    def _a11y_has_title_language_button():
        """1.70 的标题页语言切换按钮是否存在（`screen title_language_button`）。

        ⚠ 这个探测必须发生在**界面求值时**，不能在 `init` 期引用：
        `screen title_language_button` 由游戏自己的 `screen_language.rpy` 定义，
        1.63 上根本不存在，`use` 一个不存在的界面会让整个主菜单报错。
        """
        try:
            return bool(renpy.has_screen("title_language_button"))
        except Exception:
            return False

    def _a11y_main_menu_items():
        """主菜单条目 —— **只列「引擎真的能聚焦到」的那些**。

        文案与画面上的中文一致（看图确认，见文件头）。

        ⚠⚠ **这份清单必须与引擎实际能聚焦的控件逐个对应。**
        未解锁时，原作在「特殊模式」那一格放的是 `add "…_extra_locked.png"`
        ——**一张图，不是按钮**（见下面 screen 的 `else` 分支），所以它根本不进
        `focus_list`，游戏自己的导航会跳过它。补丁原来照样把它列进清单，于是
        引擎给 5 个候选、补丁报 6 条，**序号整体错位**：报「特殊模式」，
        实际焦点在「退出游戏」上（维护者实机反馈）。

        按「跟着游戏走」处置：**锁定期间不进清单**（不朗读、不占序号），
        解锁后自动回到清单里。依据：`scripts/options.rpy:233`
        `define persistent.gallery_unlocked = False`，剧情里 4 处置真；
        原作界面判断在 `scripts/screens/screen_main_menu.rpy:118`，
        与本文件的 screen 分支逐字一致。

        ── 1.70 的改动 ────────────────────────────────────────────────────
        1.70 标题页多了一个语言切换按钮（`TitleLanguageButton`，位于 (0,56)），
        比 vbox（ypos 115）更靠上 ⇒ 按**视觉 y,x 次序**它是第一项。批量播报
        与逐项焦点播报必须用**同源**文案，所以两处都取
        `24_l10n.rpy` 的当前主语言名（批量用短句 `_a11y_language_switch_item()`，
        焦点用长句 `_a11y_language_switch_alt()`）。

        ⚠ 本文件的 `screen main_menu` 是**死代码**（游戏 `screen_main_menu.rpy`
        在 init 0 定义，本文件 `init offset = -10` 永远被盖掉），保留它是
        历史原因；真正的主菜单朗读走 `22_uialt.rpy` 的图片表 + 本函数 +
        平台层的批量播报。所以**不要**依赖这里的 screen 语句去补 1.70 的东西。
        """
        items = []
        # 1.70 才有这个按钮；1.63 上探测失败 ⇒ 清单保持原样（零行为变化）。
        if _a11y_has_title_language_button():
            # 注意：这一项**已经**由 `_a11y_language_switch_item()` 翻好
            # （它读当前界面语言给「切换语言：English」），**不要**再包
            # `_A11yT` —— 二次翻译会把英文串当中文键去查词典，白跑一趟。
            items.append(_a11y_language_switch_item())
        # 其余条目是**补丁自产的中文文案**，必须在这里翻好：
        # 平台层只翻模板与分隔符（见 `10_renpy_adapter.announce_main_menu`），
        # 选项名由逐作层负责 —— 否则英文界面下刚进标题画面会念出
        # 「Main menu. 开始游戏, 继续游戏, ...」这种半中半英的句子。
        items.extend([
            _A11yT("开始游戏"),
            _A11yT("继续游戏"),
            _A11yT("读取游戏"),
            _A11yT("系统设置"),
        ])
        if _a11y_demo_unlocked():
            items.append(_A11yT("特殊模式"))
        items.append(_A11yT("退出游戏"))
        return items

    # 把清单交给平台层 —— 平台层不知道本作主菜单有哪些按钮（分层要求）
    A11yHost.MainMenuItems = _a11y_main_menu_items


screen main_menu(force=False):
    tag menu

    # ⚠ 这里**不再**用 `on "show"` 播报 —— 实测它不触发
    #   （`tag menu` 会让引擎复用界面实例，切到设置再回来并不重新 show）。
    #   真正的触发在平台层 `_menu_watch()` 的每帧轮询里，见那里的说明。
    add "chunbai"

    if force:
        add "main_menu_bg":
            zoom 1.01
        add "titlenew_bg_2"
        add "titlenew_copyright"
        add "title_logo_a"
    else:
        add "main_menu_bg" at main_menu_bg_transform:
            zoom 1.01
        add "titlenew_bg_2" at main_menu_bg_transform
        add "titlenew_copyright" at main_menu_bg_transform
        add "title_logo_a" at main_menu_bg_transform

    # ── 1.70 标题页的语言切换按钮 ────────────────────────────────────────────
    # 原作 1.70 在背景块之后 `use title_language_button`（含 `main_menu_extral`），
    # 位置与 1.63 的视觉完全不变，所以这里照抄、只加运行期探测保护：
    # 1.63 上这个 screen 不存在，直接 `use` 会让整个主菜单解析失败。
    # 按钮实例是 `TitleLanguageButton`（`ImageButton` 子类），没有 `alt`、
    # 图像来自 `DynamicDisplayable`，所以文案由 `22_uialt.rpy` 的
    # `_a11y_ui_alt_for` 按**类型名**兜底（与本文件批量播报共用同一句）。
    if _a11y_has_title_language_button():
        use title_language_button

    vbox:
        # ⚠ `group_alt` 是**样式属性**，必须挂在 displayable 上，不能当 screen
        #   语句层级的关键字 —— 后者被引擎直接拒绝：
        #     `'group_alt' is not a keyword argument or valid child of the screen statement`
        #   （跑 `--lint` 抓到的，见 README「如何复现分析」）。
        #   进入这一组时报一次组名，玩家就知道自己到了主菜单。
        group_alt "主菜单"
        xpos 2452
        ypos 115
        spacing 40
        xanchor 1.0

        imagebutton:
            alt _A11yT("开始游戏")
            idle "gui/custom2/title/title_menu_main_start_normal.png"
            hover "gui/custom2/title/title_menu_main_start_click.png"
            at main_menu_show_btn(1.0 if not force else 0.0)
            activate_sound persistent.button_activate_sound
            hover_sound persistent.button_hover_sound
            xalign 1.0
            action [PlayRandomSystemVoice(10), Start()]

        imagebutton:
            alt _A11yT("继续游戏")
            idle "gui/custom2/title/title_menu_main_continue_normal.png"
            hover "gui/custom2/title/title_menu_main_continue_click.png"
            insensitive "gui/custom2/title/title_menu_main_continue_locked.png"
            activate_sound persistent.button_activate_sound
            hover_sound persistent.button_hover_sound
            at main_menu_show_btn(1.1 if not force else 0.1)
            xalign 1.0
            action SafeContinue()

        imagebutton:
            alt _A11yT("读取游戏")
            idle "gui/custom2/title/title_menu_main_load_normal.png"
            hover "gui/custom2/title/title_menu_main_load_click.png"
            activate_sound persistent.button_activate_sound
            hover_sound persistent.button_hover_sound
            at main_menu_show_btn(1.2 if not force else 0.2)
            xalign 1.0
            action [PlayRandomSystemVoice(5), ShowMenu("load")]

        add "title_divider" at main_menu_show_btn(1.3 if not force else 0.3)

        imagebutton:
            alt _A11yT("系统设置")
            idle "gui/custom2/title/title_menu_main_system_normal.png"
            hover "gui/custom2/title/title_menu_main_system_click.png"
            hover_sound persistent.button_hover_sound
            at main_menu_show_btn(1.4 if not force else 0.4)
            xalign 1.0
            action [PlayRandomSystemVoice(1), ShowMenu("preferences")]

        # 1.70：解锁条件多了 `or obe_demo`（Demo 版），判断集中在
        # `_a11y_demo_unlocked()` 里，保证与上面那份清单**同源**。
        if _a11y_demo_unlocked():
            imagebutton:
                alt _A11yT("特殊模式")
                idle "gui/custom2/title/title_menu_main_extra_normal.png"
                hover "gui/custom2/title/title_menu_main_extra_click.png"
                activate_sound persistent.button_activate_sound
                hover_sound persistent.button_hover_sound
                at main_menu_show_btn(1.5 if not force else 0.5)
                xalign 1.0
                action ShowMenu("main_menu_extral")
        else:
            # 原作在这里放的是**不可点**的锁定图（`add`，不是 `imagebutton`）。
            # 无障碍层保持不变，只补一句朗读说明它为什么按不了。
            add "gui/custom2/title/title_menu_main_extra_locked.png":
                alt _A11yT("特殊模式（尚未解锁）")
                at main_menu_show_btn(1.5 if not force else 0.5)
                xalign 1.0

        add "title_divider" at main_menu_show_btn(1.6 if not force else 0.6)

        imagebutton:
            alt _A11yT("退出游戏")
            idle "gui/custom2/title/title_menu_main_exit_normal.png"
            hover "gui/custom2/title/title_menu_main_exit_click.png"
            activate_sound persistent.button_activate_sound
            hover_sound persistent.button_hover_sound
            at main_menu_show_btn(1.7 if not force else 0.7)
            xalign 1.0
            action Quit(confirm=not main_menu)
