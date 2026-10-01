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
# ── ⚠⚠ 覆盖**曾经整个失效**（实机日志确认，别再踩一次）─────────────────────
#
# 症状（维护者 `a11y_speech.log` 原文）：
#
#     [alt] 焦点=ImageButton 文本='未命名控件（dialog_option_bg_normal.png，ChoiceReturn）'
#
# 根因不是「文案取不到」，而是**下面这个 `screen choice` 从来没有生效过**：
#
#   · 原作自己也定义了 `screen choice` —— `scripts/screens/screen_choice.rpy`
#     （`scripts.rpa` 里解出来的 `.rpyc` 实查：`screen choice(items)` 里
#     `imagebutton` 只有 idle/hover/音效/`action i.action`，**没有 alt**，
#     文字是 frame 的另一个子节点 `text i.caption`）。
#   · 引擎按 `(priority, sort_key, fn, dn)` 给脚本文件排序
#     （`renpy/script.py:386-413`）：松散文件走 `priority = 1`、`sort_key = 文件名`
#     （`30_choice.rpy` -> `"3"`），`.rpa` 归档走 `priority = 1`、
#     `sort_key = parts[1]`（`scripts/screens/screen_choice.rpyc` -> `"scripts"`）。
#     `"3" < "scripts"` ⇒ **本文件先执行、原作后执行**（`fn` 再当次级键也翻不过来）。
#   · 顶层 `screen` 语句被包成 `ast.Init(..., -500 + l.init_offset)`
#     （`renpy/parser.py:1207-1222`），`l.init_offset` 默认 0
#     （`renpy/lexer.py:669`）。**两边都是 -500**，于是后执行的原作版本覆盖本文件
#     （`renpy/display/screen.py:252` `screens[name[0], v] = self`）。
#
# 后果有两层，两层都在日志里对得上：
#   1. 原作那个 `imagebutton` 没有 `alt` ⇒ 控件播报落到四级兜底 ⇒ 玩家只听到
#      「未命名控件（dialog_option_bg_normal.png，ChoiceReturn）」；
#   2. 本文件 `on "show"` 的采集 + 整批播报**根本不存在于运行时** ⇒
#      6032 行日志里 `[选项]` / 「按数字键选择」一行都没有。
#
# 修法：用 `init offset` 把本文件的 `screen choice` 抬到原作之后执行 ——
#   `init offset = 10` ⇒ 该 screen 的优先级变成 `-500 + 10 = -490`，
#   而原作仍是 `-500`。init 优先级小的先执行（`renpy/script.py:447`），
#   所以本文件**后**注册、**我们赢**。
#
#   ⚠ `31_main_menu.rpy` 用的是**相反**方向的 `init offset = -10`（-510），
#     那是故意的：本作**没有**自己的 `screen main_menu`，主菜单由引擎的
#     `_layout/screen_main_menu.rpym` 提供，让引擎那份后注册才对（与本作
#     画面一致）。**两个方向都是「让画面的那份赢」，不是随手写的数。**
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
            #: 已经整批播报过的那一批（按选项文案的元组认）—— 防重复播报。
            #: `None` 表示「当前这一屏还没念过」。
            self._batch_key = None
            #: 这一批是靠哪条路念出去的：`show`（界面的 `on "show"`）
            #: 还是 `focus`（焦点兜底，见 `ensure_announced`）。给日志用。
            self._batch_via = None

        # ------------------------------------------------------------ 采集
        def capture(self, items):
            """在 `screen choice` 即将显示时调用，存下这一批选项。

            存下来是为了两件事：数字键直选要知道有几个选项、每个的 action 是什么；
            以及整批播报能一次念完（而不是被引擎逐条念一半）。

            ⚠ **重入安全**：这个方法现在有**两个**调用点 —— 界面的
            `on "show"`，以及焦点兜底 `ensure_announced()`（见那里的说明）。
            同一批选项重复采集不做任何事，所以谁先到都不影响结果。
            """
            items = list(items or [])
            key = self._key_of(items)
            if key == self._batch_key and self._items:
                return
            self._items = items
            # 换了一批（哪怕是同一批的第一次）就允许重新整批播报一次。
            # 只在「内容变了」时清标记：同一批被采集两次不会导致念两遍。
            self._batch_key = None
            self._batch_via = None
            A11yHost.log("选项界面: %d 个选项" % len(self._items))

        @classmethod
        def _key_of(cls, items):
            """这一批选项的指纹 —— 用文案序列认，不用 `id()`。

            ⚠ 不能用 `id(item)`：引擎每帧都会重建 `MenuEntry` 对象，
            `id()` 每帧都变，等于「永远是新的一批」，会把整批播报刷成复读机。
            """
            return tuple(cls._caption_of(it) for it in items)

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

            **同一批只念一次**（`_batch_key` 去重）：这个方法现在有两个调用点
            （`on "show"` 与焦点兜底 `ensure_announced`），两个都跑到也只念一遍。
            """
            return self._announce(question, "show")

        def _announce(self, question="", via="show"):
            if not self._items:
                return False
            key = self._key_of(self._items)
            if key == self._batch_key:
                return False
            self._batch_key = key
            self._batch_via = via
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
            # 正向证据：整批播报**走的是哪条路**。上一轮 6032 行日志里一行
            # 选项播报都没有，而当时无法从日志分辨「钩子没触发」还是
            # 「触发了但没话可说」—— 这一行把两者分开。
            A11yHost.said("[选项] 整批播报 触发=%s 候选=%d 文案='%s'" % (
                via, len(self._items), msg[:80]))
            # 记下来供平台层压掉引擎的重复播报（见 _drop_duplicate）
            try:
                A11yHost.rpy.note_choice_announce(msg)
            except Exception:
                pass
            A11yHost.repeat.say(msg, interrupt=True)
            return True

        def ensure_announced(self, items):
            """焦点兜底：**玩家已经摸到选项了，整批播报却还没念过** ⇒ 补念一次。

            ⚠ 为什么需要它（不是保险起见，是被实机事故逼出来的）：

            上一版整批播报只挂在界面自己的 `on "show"` 上，而
            `31_main_menu.rpy:89` 记着一条同类事故 ——
            `on "show"` 在**真实路径上不可靠**（那次是 `tag menu` 复用界面实例）。
            它的教训原文是：「**一个存在的钩子不等于它会在你需要的时候被调用**」。

            于是这里再加一条**一定会被走到**的路：控件钩子 `UiAltFor` ——
            玩家能把焦点放到选项按钮上，就说明这一屏选项正在显示；而焦点
            恰恰是这一层的生命线，它不可能不被调用。两条路共用
            `_announce` 的去重标记，所以**不会念两遍**。

            返回 `True` 表示这一批的整批播报已经念出去了。
            """
            if not items:
                return False
            self.capture(items)
            if not self._items:
                return False
            if self._key_of(self._items) == self._batch_key:
                return True
            return self._announce(via="focus")

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
        """`screen choice` 的 `on "show"` 处理：采集 + 整批播报。

        ⚠ 这条路**不足以单独承担**整批播报（见文件头那段：`on "show"` 在真实
        路径上出过事故），所以还有第二条路 —— 控件钩子里的
        `A11yChoice.ensure_announced()`（`22_uialt.rpy` 的 `_a11y_ui_alt_for`）。
        两条路共用同一份去重标记，谁先到谁念，不会念两遍。
        """
        try:
            A11yHost.choice.capture(items)
            A11yHost.choice.announce()
        except Exception:
            A11yHost.log_exc("选项播报失败")


# ⚠⚠ 这一行是**覆盖能不能生效的关键**，别当成可有可无的装饰：
#   本文件（松散文件）比 `scripts.rpa` 里的 `scripts/screens/screen_choice.rpyc`
#   先执行，而两边注册 `screen choice` 的优先级都是默认的 `-500`
#   ⇒ 不加这一行，原作那份会**盖掉**下面这个 screen（完整证据链见文件头）。
#   `init offset` 是编译期指令，只影响它**下面**的语句，所以放在这里最贴近用途。
init offset = 10


screen choice(items):

    # 界面显示时：采集这一批选项，然后**整批播报**一次。
    # 用 `on "show"` 而不是 python 语句，是为了保证只在**真的显示**时做一次。
    # （可靠性由 `ensure_announced` 兜底，见 `_a11y_choice_shown` 的说明。）
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
