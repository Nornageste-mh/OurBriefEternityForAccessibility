# A11yFramework / Ren'Py 版 —— 逐作层（L3）
#
# 《永恒与星辰与日常》无障碍补丁 · 选项界面
#
# ── 为什么必须覆盖 `screen choice` ────────────────────────────────────────────
#
# 本作选项界面（`scripts/screens/screen_choice.rpy` 实查）里，图片按钮与选项
# 文字是**兄弟节点**，不是一个整体：
#
#     frame:
#         imagebutton:
#             idle  "gui/custom2/dialog/dialog_option_bg_normal.png"
#             hover "gui/custom2/dialog/dialog_option_bg_click.png"
#             action i.action
#         text i.caption:            ← text 是 frame 的子节点，**不是** imagebutton 的
#
# 于是朗读链是 `Button._tts_all()` -> `alt(self.action)`
# （renpy/display/behavior.py:1199）-> `clicked.alt`（behavior.py:507-524）。
#
# 而引擎只为**内建**界面设 `action.alt`（存档槽 `00action_file.rpy:395`、设置项
# `00preferences.rpy:690`）—— `menu` 语句产生的选项 action 不带 alt
# （`00action_*.rpy` 逐一实查，没有一处给菜单选项设 alt），按钮自己又读不到兄弟
# 节点的文本（`Button._tts()` 明确返回 `""`，behavior.py:1196）。
#
# 结论：不覆盖这个界面，盲人玩家到了选项处**什么都听不到**。全作只有 3 处选项
# （每处 3 分支，见 无障碍可行性验证.md §3.3），但都是剧情分支点，听不到
# 就等于卡死。
#
# ── 数字键直选 ──────────────────────────────────────────────────────────────
#
# 对齐维护者其它无障碍仓库的约定（`CfgChoiceHotkeys`「数字键直选」，默认开）：
# 按 `1`-`9` 选择对应编号的选项，主键盘与小键盘都认。
# 编号只出现在**播报**里（「1．开始游戏」）—— 画面一个字都不加，与原作逐字一致，
# 于是「听到第几个」与「按几」永远对得上；报编号是等价呈现，不是新增信息。

init -60 python:

    class A11yChoice(object):
        """选项界面的朗读与数字键直选。"""

        def __init__(self):
            self._items = []

        # ------------------------------------------------------------ 采集
        def capture(self, items):
            """在 `screen choice` 即将显示时调用，存下这一批选项。

            存下来是为了两件事：数字键直选要知道有几个选项、每个的 action 是什么；
            以及整批播报能一次念完（而不是被引擎逐条念一半）。
            """
            self._items = list(items or [])
            A11yHost.log("选项界面: %d 个选项" % len(self._items))

        # ------------------------------------------------------------ 题干
        @staticmethod
        def question():
            """取 `menu` 语句的题干。

            来源是 `renpy.game.context()._menu`（引擎在执行 `menu` 时放进上下文里的
            那一批待选项），其元素的 `prompt` 就是题干 —— 只读引擎已有的状态。

            本作的选项界面**不显示题干**（`screen_choice.rpy` 里没有题干文本，
            题干由 `menu` 语句的 narrator 行承担），所以题干已经被当作普通台词
            朗读过一次；这里再取一次只为「整批播报」时给听众一个上下文，
            缺了也不影响可用性。
            """
            try:
                menu = renpy.game.context()._menu
                if not menu:
                    return ""
                for entry in menu:
                    p = getattr(entry, "prompt", None)
                    if isinstance(p, str) and p.strip():
                        return p.strip()
            except Exception:
                pass
            return ""

        # ------------------------------------------------------------ 播报
        def announce(self, question=""):
            """整批播报：先念题干，再逐条念编号 + 选项文本。

            为什么整批念、而不是等玩家用方向键一个个摸：盲人玩家到了选项处
            必须先知道**一共有几个选项、分别是什么**，否则只能在黑暗里逐个试探。
            """
            if not self._items:
                return
            if not question:
                question = self.question()
            parts = []
            q = (question or "").strip()
            if q:
                parts.append(q)
            for i, it in enumerate(self._items, 1):
                cap = self._caption_of(it)
                if cap:
                    parts.append("%d．%s" % (i, cap))
            parts.append("按数字键选择。")
            msg = " ".join(parts)
            # 记下来供平台层压掉引擎的重复播报（见 _drop_duplicate）
            try:
                A11yHost.rpy.note_choice_announce(msg)
            except Exception:
                pass
            A11yHost.repeat.say(msg, interrupt=True)

        @staticmethod
        def _caption_of(item):
            """取一个选项的可读文本。

            选项是 `renpy.ast.MenuEntry` 之类带 `caption` 的对象（`screen choice`
            里就是 `i.caption`，实查 screen_choice.rpy）。取不到就返回空串，**不猜**。
            """
            for attr in ("caption", "label"):
                try:
                    v = getattr(item, attr, None)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
                except Exception:
                    pass
            return ""

        # ------------------------------------------------------------ 数字键
        def press(self, n):
            """数字键直选。`n` 从 1 开始。

            只在**选项界面正在显示**时生效；其余时候数字键照常交给游戏
            （上游红线：无障碍层不得改变游戏原有行为）。
            """
            if not self._items:
                return
            if n < 1 or n > len(self._items):
                A11yHost.repeat.say("没有第 %d 个选项。" % n, record=False)
                return
            item = self._items[n - 1]
            cap = self._caption_of(item)
            A11yHost.repeat.say("已选择 %d．%s" % (n, cap), interrupt=True)
            try:
                act = getattr(item, "action", None)
                if act is None:
                    A11yHost.repeat.say("这个选项无法激活。", record=False)
                    return
                renpy.display.behavior.run(act)
            except Exception:
                A11yHost.log_exc("激活第 %d 个选项失败" % n)
                A11yHost.repeat.say("激活选项失败。", record=False)

    A11yHost.choice = A11yChoice()


    def _a11y_choice_shown(items):
        """`screen choice` 的 `on "show"` 处理：采集 + 整批播报。"""
        try:
            A11yHost.choice.capture(items)
            A11yHost.choice.announce()
        except Exception:
            A11yHost.log_exc("选项播报失败")


screen choice(items):

    # 界面显示时：采集这一批选项，然后**整批播报**一次。
    # 用 `on "show"` 而不是 python 语句，是为了保证只在**真的显示**时做一次。
    on "show" action Function(_a11y_choice_shown, items)

    vbox:
        xalign 0.5
        yalign 0.4
        spacing 0
        # ⚠ `group_alt` 是**样式属性**，必须挂在 displayable 上（不能当 screen
        #   语句层级的关键字，引擎会直接拒绝 —— 报错原文见 31_main_menu.rpy）。
        group_alt "选项"

        for i in items:
            frame:
                background None
                xysize (1287, 165)
                imagebutton:
                    # ★ 补丁的实质改动：给按钮一个朗读文本。
                    #   alt 只影响朗读，不影响画面。
                    alt i.caption
                    idle "gui/custom2/dialog/dialog_option_bg_normal.png"
                    hover "gui/custom2/dialog/dialog_option_bg_click.png"
                    activate_sound persistent.button_activate_sound
                    hover_sound persistent.button_hover_sound
                    action i.action
                text i.caption:
                    xalign 0.5
                    ypos 40
                    color "#ffffff"
                    outlines [(3, "#7d959b", 0, 0)]
                    size 46
                    font "SourceHanSansSC-Medium.otf"
