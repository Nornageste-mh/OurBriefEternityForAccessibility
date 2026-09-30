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
        """
        items = ["开始游戏", "继续游戏", "读取游戏", "系统设置"]
        try:
            if persistent.gallery_unlocked:
                items.append("特殊模式")
        except Exception:
            # 取不到就按**画面上的默认状态**（未解锁）处理：
            # 宁可少报一项，也绝不报一个玩家按不到的项
            # ——错报会让玩家按回车去做另一件事，比少报危险得多。
            pass
        items.append("退出游戏")
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
            alt "开始游戏"
            idle "gui/custom2/title/title_menu_main_start_normal.png"
            hover "gui/custom2/title/title_menu_main_start_click.png"
            at main_menu_show_btn(1.0 if not force else 0.0)
            activate_sound persistent.button_activate_sound
            hover_sound persistent.button_hover_sound
            xalign 1.0
            action [PlayRandomSystemVoice(10), Start()]

        imagebutton:
            alt "继续游戏"
            idle "gui/custom2/title/title_menu_main_continue_normal.png"
            hover "gui/custom2/title/title_menu_main_continue_click.png"
            insensitive "gui/custom2/title/title_menu_main_continue_locked.png"
            activate_sound persistent.button_activate_sound
            hover_sound persistent.button_hover_sound
            at main_menu_show_btn(1.1 if not force else 0.1)
            xalign 1.0
            action SafeContinue()

        imagebutton:
            alt "读取游戏"
            idle "gui/custom2/title/title_menu_main_load_normal.png"
            hover "gui/custom2/title/title_menu_main_load_click.png"
            activate_sound persistent.button_activate_sound
            hover_sound persistent.button_hover_sound
            at main_menu_show_btn(1.2 if not force else 0.2)
            xalign 1.0
            action [PlayRandomSystemVoice(5), ShowMenu("load")]

        add "title_divider" at main_menu_show_btn(1.3 if not force else 0.3)

        imagebutton:
            alt "系统设置"
            idle "gui/custom2/title/title_menu_main_system_normal.png"
            hover "gui/custom2/title/title_menu_main_system_click.png"
            hover_sound persistent.button_hover_sound
            at main_menu_show_btn(1.4 if not force else 0.4)
            xalign 1.0
            action [PlayRandomSystemVoice(1), ShowMenu("preferences")]

        if persistent.gallery_unlocked:
            imagebutton:
                alt "特殊模式"
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
                alt "特殊模式（尚未解锁）"
                at main_menu_show_btn(1.5 if not force else 0.5)
                xalign 1.0

        add "title_divider" at main_menu_show_btn(1.6 if not force else 0.6)

        imagebutton:
            alt "退出游戏"
            idle "gui/custom2/title/title_menu_main_exit_normal.png"
            hover "gui/custom2/title/title_menu_main_exit_click.png"
            activate_sound persistent.button_activate_sound
            hover_sound persistent.button_hover_sound
            at main_menu_show_btn(1.7 if not force else 0.7)
            xalign 1.0
            action Quit(confirm=not main_menu)
