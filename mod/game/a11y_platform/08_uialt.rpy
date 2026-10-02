# A11yFramework / Ren'Py 版 —— 平台层（L1）· 界面控件播报
#
# ════════════════════════════════════════════════════════════════════════════
# 这一层做什么
# ════════════════════════════════════════════════════════════════════════════
#
# 本作（以及多数商业 Ren'Py 作品）的控件几乎全是 `imagebutton`：
# **字印在图上，代码里没有字**。于是引擎自己那条「焦点一变就读控件 alt」的
# 通路读不出东西（实测日志：`[alt] 焦点=ImageButton alt=''`）。
# 这一层就补这一段：**焦点一变，补丁念出这个控件是什么**。
#
# ── 核心机制：**拉模型**（播报时查表），不是推模型 ─────────────────────────
#
#   ✅ 现在：焦点变化 -> 拿控件身份（图片名 / 屏幕坐标 / 同图序号）-> 查逐作层的
#            文案表 -> 念出来。全程在**播报那一刻**取数。
#
#   ❌ 曾经：预先算好文案写进 `w.style.alt`（推模型），再指望别人去读它。
#            结果那个中间人从头到尾没起作用 —— 引擎那条路读到空（于是念了它
#            自己的 preference alt「跳过没见过的」和状态词「选定」），
#            补丁自己的播报也读到空（主菜单整片哑掉）。
#            推模型的那半代码**已全部删除**，不要再加回来。
#
#            教训一句话：**不要让"写入"和"读取"之间隔着一个你看不见的中间人。**
#            完整复盘见 `CHANGELOG.md` 的 0.0.0.2 / 0.0.0.3 两节。
#
# ── 文案从哪来：三级查表，都不靠猜 ────────────────────────────────────────
#
#   1. **idle 图片路径**（`ImageButton.state_children["idle_"]`，behavior.py:1251）
#      —— 一图一义的控件，唯一且可 grep；
#   2. **屏幕坐标**（引擎焦点表 `Focus.x/.y`，focus.py:88-96）
#      —— 一图多义时消歧（设置界面里同一张静音图出现 5 次）；
#   3. **逐作层钩子** `UiAltFor(key, widget, ctx)`
#      —— 循环生成的控件，靠 `ctx["ordinal"]`（同图按 (y,x) 排序的名次）。
#
# ── 读不到时：四级兜底，**永不静默**，但要分清两种"空" ──────────────────
#
#   ① `style.alt`（游戏自带或本补丁将来注入的）
#      ⚠ 它**不是**「这个控件的名字」的同义词：引擎会把状态词
#         `_("selected")` 追加进按钮读出来的文本里（behavior.py:1199-1205）。
#         整串就是一个状态词的，本层当它「没名字」处理，继续往下找
#         （实机日志里存读档界面读到过 `文本='selected'`）。
#   ② 控件自己拼得出来的文本（`_tts_all`，textbutton 与 preference 按钮靠这条）
#   ③ 上面那三级查表
#   ④ 兜底标识：图片名 + 动作类名，再不行「未知控件」
#
#   ⚠ 但「空」有两种含义，**必须分开**（实机事故：剧情台词被反复出现的
#     「未知控件（SayBehavior）」顶掉）：
#       · 我不知道这是什么      -> 报标识（④）
#       · 引擎说了别念我        -> **保持安静**（`TTSRoot` 就是这个信号，
#                                 `SayBehavior._tts_all` 无条件抛它，behavior.py:716）
#     判据见 `_silent_widget`。
#
#   ⚠ ④ 的正确定位是**探针**，不是"随便报个名字"：它把漏掉的控件顶到日志第一行
#     （它已经报出过 `log_data_bo_jumpback_normal.png` 这个覆盖率工具扫不到的
#     动态控件）。**沉默不会告诉你漏了什么，它会。**
#
# ── 引擎事实（不要凭印象改）─────────────────────────────────────────────
#
#   · 引擎**只在焦点变化时**朗读：`tts.displayable()` 全引擎只有一个调用点
#     —— `focus.py:217`（`set_focused` 里）。所以「值变了」不会被自动重念，
#     那部分由本层的 `_track_focus` 负责。
#   · `Bar._tts_all` 尾巴上硬编码一个「栏」字（behavior.py:2664-2671），
#     所以滑杆**不由引擎念**，本层自己念（名字 + 数值）。
#   · 引擎自语音在本补丁里**保持关闭**（见 `10_renpy_adapter.py` 的
#     `ensure_self_voicing` 的两次实机记录）：打开它，界面播报就变成
#     容器文字与状态词，而不是控件名字。
#
# L1 冻结层，逐作不得改写。

init -45 python:

    #: `style.alt` 里**只有状态、没有名字**的那几个词 —— 它们不是控件的名字，
    #: 不该被当成名字念（见 `_real_text` 第 ① 级的说明）。
    #:
    #: 键是**引擎自己那个串**：`renpy/common/00accessibility.rpy:33` 的
    #: `_("selected")`，在中文界面下会被翻译成「选定」——所以两个都收。
    #: 这是一个「只影响一个裸状态词」的小筛子：任何一个**带名字**的 alt
    #: （例如引擎的 `"跳过没见过的 [text] selected"`）都不在里面，一字不动。
    _A11Y_BARE_STATE_WORDS = {"selected": True, "选定": True, "已选定": True}


    def _A11yOrdinals(entries):
        """把「同界面 + 同图」的控件按 (y, x) 排行，返回 `{id(widget): (名次, 总数)}`。

        `entries` 每项是 `(screen, key, x, y, id)`；`key` 或坐标为空的那项跳过。

        ⚠ **坐标只用来定先后，不做绝对匹配。** 早期版本按绝对坐标反推格子位置，
        因为按钮图比格子矮 46 像素而**全部判定失败**（12 个存档位一个都不出声），
        而日志里只有一行「未识别」，看起来像还没做、不像做错了。详见 CHANGELOG。

        ⚠ 单拎成模块级函数是为了能被离线探针直接测
        （`tools/probe_ordinal.py` 抽这段源码喂合成布局进去跑）——
        它决定「这是第几个存档位」，算错会**报错位号**，比不报更糟。
        """
        out = {}
        groups = {}
        for screen, key, x, y, wid in entries:
            if not key or x is None or y is None:
                continue
            groups.setdefault((screen, key), []).append((y, x, wid))
        for items in groups.values():
            items.sort()
            total = len(items)
            for n, item in enumerate(items):
                out[item[2]] = (n, total)
        return out


    class A11yUiAlt(object):
        """聚焦控件的朗读文本：查表 -> 四级兜底 -> 线性导航。"""

        #: 扫描间隔（秒）。焦点表只有几十项，0.25 秒足够
        #: （玩家从看见界面到按下第一个键远不止 0.25 秒）。
        WALK_INTERVAL = 0.25

        #: 同一段文案在这个时间窗内**只念一次**（秒）。
        #:
        #: ── 为什么需要它（实机取证：**两次**不同的抽搐都撞在这条上）──────────
        #: 本补丁有两条让位/去重判据，各自只挡住一类重复：
        #:   · `_track_focus` 按**位置键**判断「还是不是同一个控件」；
        #:   · `_announce` 按 `_focus_key`（文本 + 界面 + 坐标）判断「念没念过」。
        #: 但主菜单这种界面**有动画**，引擎每帧重建焦点表、坐标跟着动 ⇒
        #: 位置键一直变，两条都挡不住。实测（自跑，探针每 0.6 秒推一步）：

        #:     [alt] 焦点=ImageButton 文本='开始游戏'   ← 0.5 秒内 11 次
        #:     [alt] 播报: 开始游戏                      ← 每次都真的调了 NVDA
        #:     （…×11，间隔 30~80 ms）

        #: 听感就是「按住方向键 → 同一句抽搐式地反复念」—— 与用户报的那个症状
        #: 完全一致（音声界面的 0.1 秒 timer 只是**最容易触发**的那一个界面）。
        #: 位置会动、身份会变，**唯一稳定的是文案本身**，所以最后一道去重必须按
        #: 文本来做：`(文案, 界面名)` 在这个窗口内只念一次。
        #: 窗口取 0.9 秒：比人手连按方向键的间隔（约 0.3~0.5 秒）长，
        #: 又短于「刻意再听一遍」的间隔，不会把有意义的重读吞掉
        #: （玩家要重听有 **F5**，那是显式通路，不受这里影响）。
        SAY_DEDUP_WINDOW = 0.9

        def __init__(self):
            self._t = 0.0
            self._loc = {}        # id(widget) -> (界面名, (x, y))
            self._ord = {}        # id(widget) -> (同图名次, 同组总数)
            self._unknown = {}    # 界面 -> set(查不到文案的键)，作业清单
            self._reported = {}   # 去重：同一份清单只写一次日志
            self._beats = 0
            self._focus_id = None      # 当前焦点的**位置键** (界面名, (x, y))
            self._focus_text = None
            self._where_miss = 0       # 位置查不到的次数（诊断：静默事故的探针）
            self._said_at = 0.0        # 上次播报的时刻（`SAY_DEDUP_WINDOW` 用）
            self._said_text = None     # 上次播报的 (文案, 界面名)

        # ================================================================ 入口
        def tick(self):
            """每帧一次（平台层挂在 `config.periodic_callbacks`，20 Hz）。"""
            import time
            now = time.monotonic()
            if now - self._t >= self.WALK_INTERVAL:
                self._t = now
                try:
                    self._scan()
                except Exception:
                    A11yHost.log_exc("控件扫描异常")
                # 心跳：头三次各写一行，证明这一层真的在跑。
                # 前几轮吃过亏 —— 「没跑」和「跑了没用」在日志里长得一样。
                if self._beats < 3:
                    self._beats += 1
                    try:
                        import renpy.display.focus as _f
                        n = len(getattr(_f, "focus_list", []) or [])
                    except Exception:
                        n = -1
                    A11yHost.said("[alt] 心跳 #%d: 焦点候选=%d 未识别=%d" % (
                        self._beats, n,
                        sum(len(v) for v in self._unknown.values())))
            try:
                self._track_focus()
            except Exception:
                A11yHost.log_exc("焦点跟踪异常")

        # ================================================================ 扫描
        def _scan(self):
            """遍历**引擎自己的焦点表**，记下每个控件的坐标、序号、以及查不到文案的。

            为什么用 `focus_list`（`focus.py:88-109`、`take_focuses()` 每次渲染重建）：
            `Focus` 上带着控件本体、屏幕坐标、所属界面 —— 那正是「需要文案」的那批
            控件，而且不必自己走渲染树、算偏移量。
            """
            try:
                import renpy.display.focus as _f
                fl = list(_f.focus_list)
            except Exception:
                return

            entries = []
            for fo in fl:
                try:
                    w = getattr(fo, "widget", None)
                    if w is None:
                        continue
                    screen = None
                    try:
                        sn = getattr(fo.screen, "screen_name", None)
                        if isinstance(sn, (tuple, list)) and sn:
                            screen = str(sn[0])
                        elif isinstance(sn, str) and sn:
                            screen = sn
                    except Exception:
                        screen = None
                    pos = None
                    try:
                        if fo.x is not None and fo.y is not None:
                            pos = (int(fo.x), int(fo.y))
                    except Exception:
                        pos = None
                    # ★ 位置**挂在控件自己身上**，不按 `id(w)` 建字典 ——
                    #   理由见 `_where()`：`id()` 只在本轮 interaction 内稳定，
                    #   而本作音声界面每 0.1 秒就重建一次控件，按 id 建的字典
                    #   在下一轮就查不到 ⇒ 那是「导航整片不朗读」那次事故的根因。
                    try:
                        w._a11y_where = (lambda s=screen, p=pos: (s, p))
                        self._loc[id(w)] = (screen, pos)      # 兜底：万一挂不上
                    except Exception:
                        self._loc[id(w)] = (screen, pos)
                    entries.append((w, screen, pos, self._best_key(w)))
                except Exception:
                    continue

            self._ord = _A11yOrdinals([
                (screen, key, pos[0] if pos else None, pos[1] if pos else None,
                 id(w)) for (w, screen, pos, key) in entries])
            # ★ 名次也**挂在控件自己身上**：`_ord` 是按 `id(w)` 建的，而 `id()`
            #   只在本轮 interaction 内稳定（读它的地方可能已经换轮了）。
            #   名次决定「这是第几个存档位 / 第几行曲目」—— 脏了会**报错位号**，
            #   比不报更糟（探针 `probe_ordinal.py` 防的就是这一类）。
            #   `_ord` 保留作兜底，取法见 `_ctx`。
            for (w, screen, pos, key) in entries:
                try:
                    w._a11y_ord = self._ord.get(id(w), (None, None))
                except Exception:
                    pass

            # 查不到文案的记成作业清单（那份清单就是下一轮要补的表）
            for w, screen, pos, key in entries:
                if self._has_real_text(w):
                    continue
                k = self._fallback_label(w)
                known = self._unknown.setdefault(screen or "?", set())
                if k not in known:
                    known.add(k)
            self._report()

        # ======================================================= 控件定位
        #: 「查不到位置」的哨兵。**必须与 `(None, None)` 区分开** ——
        #: 见 `_where()` 的说明（混用会造成整片静默，那是真实发生过的事故）。
        _NO_WHERE = object()

        def _where(self, w):
            """控件的位置键 `(界面名, (x, y))`；查不到返回 `_NO_WHERE`。

            三级取法，**从「不依赖任何缓存」到「依赖缓存」**：

              ① **现读焦点表现场**（`Focus.widget is w`）—— 唯一真正可靠的一级。
                 引擎的 `focus_list` 在**每次渲染时重建**（`focus.py:88-109`
                 `take_focuses()`），所以它永远是**本轮**的坐标，不存在过期问题；
              ② 挂在控件身上的 `w._a11y_where`（`_scan()` 里写的）；
              ③ 按 `id(w)` 查的字典（`_scan()` 里写的）。

            ── 为什么①必须在最前，以及为什么当初那样写会整片静默 ──────────
            实机事故（用户报「导航又不朗读了」）。引擎每轮 interaction 都会
            **重建** screen 里的 displayable，而 `_scan()` 每 0.25 秒才跑一次，
            两次扫描之间换过好几轮 ⇒ ②③ 都可能失配。

            失配本身不致命，致命的是**它与「位置真的取不到」用同一个返回值**：
            两者都是 `(None, None)` ⇒ 「当前焦点」与「上一个焦点」永远相等
            ⇒ `_track_focus` 认成「同一个控件、文本没变」⇒ **一行播报都不发**。
            实机日志原样是这个形状（焦点行在刷，`[alt] 播报:` 一行都没有，
            反而只有几条 `[alt] 值变化:`）：

                [alt] 焦点=ImageButton 文本='开始游戏' 引擎队列=0
                [alt] 焦点=ImageButton 文本='继续游戏' 引擎队列=0
                [alt] 焦点=ImageButton 文本='读取游戏' 引擎队列=0
                （没有任何 [alt] 播报: 行，也没有任何 NVDA 调用）

            所以这里返回**哨兵**而不是 `(None, None)`：让「查不到」彼此
            **互不相等** ⇒ 最坏情况退化成「每次都念」（吵），而不是「全哑」。
            **宁可吵，不可哑** —— 这就是本补丁那条「永不静默」的红线。
            """
            # ① 现读焦点表：与缓存无关，每轮都是最新的
            try:
                import renpy.display.focus as _f
                for fo in _f.focus_list:
                    if getattr(fo, "widget", None) is not w:
                        continue
                    screen = None
                    sn = getattr(getattr(fo, "screen", None), "screen_name", None)
                    if isinstance(sn, (tuple, list)) and sn:
                        screen = str(sn[0])
                    elif isinstance(sn, str) and sn:
                        screen = sn
                    pos = None
                    if fo.x is not None and fo.y is not None:
                        pos = (int(fo.x), int(fo.y))
                    return (screen, pos)
            except Exception:
                pass
            # ② 控件对象自己身上的（跨 interaction 跟着对象走）
            try:
                fn = getattr(w, "_a11y_where", None)
                if fn is not None:
                    return fn()
            except Exception:
                pass
            # ③ 扫描时按 id 建的字典（最不可靠的一级）
            try:
                hit = self._loc.get(id(w))
                if hit is not None:
                    return hit
            except Exception:
                pass
            return self._NO_WHERE

        # ======================================================= 文本解析（四级）
        def _read_text(self, w):
            """当前控件「应该被念成什么」—— 四级兜底，**永不为空**。

            各级顺序的理由与「两种空」的区分见文件头。
            """
            import renpy.display.behavior as _b
            where = self._where(w)
            screen, pos = (None, None) if where is self._NO_WHERE else where

            # ①②③：真实文本
            t = self._real_text(w, screen, pos)
            if t:
                return t
            # ④：兜底标识（引擎明确要求别念的控件除外）
            if self._silent_widget(w):
                return ""
            return self._fallback_label(w) or "未知控件"

        @staticmethod
        def _drop_bare_state(t):
            """把**只有一个状态词**的文本判成空串；名字里的状态词照留。

            ⚠ 这一条必须同时管住 ① 和 ② —— 只筛 ① 是**假的修复**：
              `style.alt` 被筛掉之后流程落进 ② `_tts_all`，而引擎正是在
              `_tts_all` 里把状态词追加回去的（behavior.py:1199-1205），
              于是同一个 `selected` 又原样返回，查表那一级永远走不到。
              实机证据（用户 a11y_speech.log，音声播放界面）：
                  [alt] 焦点=ImageButton 文本='selected'
              而不是本该出现的「音声 05 主题曲 永恒星辰下的日常」。

            两种情形分开处理：
              · 整串就是一个状态词            -> 返回 ""，继续往下找名字（③ 查表）
              · 名字 + 空白 + 状态词          -> 只砍掉尾巴，名字留下
                （引擎的 `"跳过没见过的 [text] selected"` 属于这一类，名字不能丢）
            """
            s = (t or "").strip()
            if not s:
                return ""
            if _A11Y_BARE_STATE_WORDS.get(s):
                return ""
            for w in _A11Y_BARE_STATE_WORDS:
                if s.endswith(w) and len(s) > len(w):
                    head = s[: -len(w)]
                    if head != head.rstrip():        # 状态词前必须有空白
                        return head.strip()
            return s

        def _real_text(self, w, screen=None, pos=None):
            """①②③ 三级「真实文本」；都取不到返回空串。"""
            import renpy.display.behavior as _b

            # 引擎明确要求别念的控件：直接判空（不走兜底）
            if self._silent_widget(w):
                return ""

            # ① 已注入 / 游戏自带的 alt
            #
            # ⚠ 但读到 `selected` 这种**状态词**时，它不是控件的名字（实机日志确认）。
            #   引擎 `Button._tts_all` 在按钮用 `selected_` 前缀样式、
            #   且 `style.alt == style._hover_alt()` 时，把 `_("selected")`
            #   追加在**它返回的那串文本**尾巴上（behavior.py:1199-1205；
            #   该串在 `renpy/common/00accessibility.rpy:33` 登记）。
            #   本作那些用 `selected_idle` 的图片开关因此整串就读成 `selected`，
            #   实机日志原文：`[alt] 焦点=ImageButton 文本='selected'`。
            #   读屏用户听到的「selected」既不是名字也不是中文，等于什么都没说。
            #
            # ⚠⚠ **① 和 ② 都要过筛子**（`_drop_bare_state`），只筛 ① 是假修复：
            #   ① 筛掉之后流程落进 ②，而引擎恰恰是在 ② 里把状态词追加回去的
            #   —— 同一个 `selected` 原样返回，③ 查表永远走不到。
            #   实机症状（用户报「音声播放界面按方向键朗读抽搐」）：曲目名的位置
            #   反复念出 `selected`。修好后这里应读到曲目名。
            #
            #   两种情形分开处理：整串就是状态词 -> 判空、继续往下找名字；
            #   名字 + 空白 + 状态词 -> 只砍尾巴（引擎那种
            #   `"跳过没见过的 [text] selected"` 名字不能丢，状态另有
            #   `_state_suffix` 的「：当前」补）。
            try:
                alt = getattr(w.style, "alt", None)
                if alt:
                    alt = self._drop_bare_state(alt)
                    if alt:
                        return alt
            except Exception:
                pass

            # ② 控件自己拼得出来的文本
            #
            # ⚠ 同样要过一遍状态词筛子：引擎在 `_tts_all` 尾巴上追加
            #   `_("selected")`（behavior.py:1199-1205），所以图片开关在这里
            #   整串读成 `selected`。筛空之后**不要 return**，让它继续走 ③ 查表
            #   —— 那一级才有名字（`extra_audio_list_bg_normal.png` -> 曲目名）。
            #
            # ⚠⚠ **Bar 必须跳过这一级**（实机事故：滑杆念成 `Barbar`）：
            #   `Bar._tts_all` 拼的是 `value.alt` + 一个「栏」字
            #   （behavior.py:2664-2671），而 `BarValue.alt` 默认就是 `"Bar"`
            #   （ui.py:74）⇒ 本作自定义的 `MyAudioPositionValue` 整串读成 `Barbar`。
            #   它**永远非空**，所以只要让它走到这一级，第 ③ 级（`_bar_text`
            #   —— 补丁专门为滑杆写的那一段）就永远轮不到。
            #   补丁对滑杆的立场是明确的：**不由引擎念，由补丁念**
            #   （文件头「引擎事实」里写着那条硬编码的「栏」字），所以这里是
            #   **有意覆盖**引擎，不是漏掉它。
            if not isinstance(w, _b.Bar):
                try:
                    t = self._drop_bare_state(w._tts_all(raw=True))
                    if t:
                        return t
                except Exception:
                    pass

            # ③ 查表
            #
            # ⚠ **Bar 也必须进来**（实机事故：滑杆念成 `Barbar` / `asmr volumebar`）。
            #   这里原来只放 `_b.Button`，而 `Bar` 不是 `Button` ⇒ **整段被跳过**，
            #   滑杆永远走不到查表、直接落到 ② 的引擎 `_tts_all`，念出
            #   `value.alt` + 「栏」字（`MyAudioPositionValue` 没填 alt，于是
            #   默认值 `"Bar"` + `bar` = `Barbar`）。
            #   更贵的一课：`_table_text` 里**本来就有** Bar 分支
            #   （`isinstance(w, _b.Bar) -> _bar_text`），上一版我还在里面
            #   认真修了名字取法 —— **改的是一个走不到的函数**。
            #   「函数改对了」不等于「它会被调用」：门口那道类型判据也属于被改的一部分。
            if isinstance(w, (_b.Button, _b.Bar)):
                try:
                    txt = self._table_text(w, screen, pos)
                    if txt:
                        return txt + self._state_suffix(w)
                except Exception:
                    pass
            return ""

        def _has_real_text(self, w):
            try:
                where = self._where(w)
                screen, pos = (None, None) if where is self._NO_WHERE else where
                return bool(self._real_text(w, screen, pos))
            except Exception:
                return False

        @staticmethod
        def _silent_widget(w):
            """引擎**明确要求不要念**的控件 —— 对它们绝不走兜底。

            依据：`SayBehavior._tts_all` 无条件 `raise TTSRoot()`
            （behavior.py:716），而 `TTSRoot` 的语义就是「别念我，去念根
            displayable」（tts.py:42-47）。把这种"空"当成"我不认识"就会念出
            「未知控件（SayBehavior）」—— 而它每句台词都会新建一个实例，
            于是每句话都被这条噪声顶掉（实机故障，详见 CHANGELOG 0.0.0.3）。

            另外 `DismissBehavior`（点任意处继续）与 `Null`（`key` 语句生成的
            占位）本来也不该进播报，一并排除。
            """
            try:
                import renpy.display.behavior as _b
                if isinstance(w, getattr(_b, "SayBehavior", ())):
                    return True
                if isinstance(w, getattr(_b, "DismissBehavior", ())):
                    return True
            except Exception:
                pass
            try:
                w._tts_all(raw=True)
            except Exception as e:
                if type(e).__name__ == "TTSRoot":
                    return True
            except BaseException:
                pass
            try:
                import renpy.display.layout as _l
                if isinstance(w, _l.Null):
                    return True
            except Exception:
                pass
            return False

        def _fallback_label(self, w):
            """④ 兜底标识：图片名 + 动作类名；都取不到就「未知控件」。

            报的是**可核查的标识**（如
            `未命名控件（log_data_bo_jumpback_normal.png，Confirm）`），
            不是编造的含义：玩家能凭它定位，维护者能凭它补表。
            """
            bits = []
            try:
                k = self._best_key(w)
                if k:
                    bits.append(k)
            except Exception:
                pass
            try:
                a = getattr(w, "action", None)
                if isinstance(a, (list, tuple)):
                    names = [type(x).__name__ for x in a]
                    if names:
                        bits.append("+".join(names))
                elif a is not None:
                    bits.append(type(a).__name__)
            except Exception:
                pass
            if bits:
                return "未命名控件（%s）" % "，".join(bits)
            try:
                return "未知控件（%s）" % type(w).__name__
            except Exception:
                return "未知控件"

        # ------------------------------------------------------------ 查表
        def _table_text(self, w, screen=None, pos=None):
            """三级查表：界面限定键 -> 图片键 -> 位置键 -> 逐作钩子。"""
            import renpy.display.behavior as _b
            if isinstance(w, _b.Bar):
                return self._bar_text(w, screen, pos)
            if not isinstance(w, _b.Button):
                return None

            key = self._best_key(w)
            tbl = A11yHost.UiAltByImage or {}
            keys = self._keys_of(w)

            # 「界面 + 图片」的限定键优先：同一张图在不同界面含义可能不同
            # （`general_menu_page_N` 在存读档是「存档页 N」、在画廊是「CG 第 N 页」）
            if screen:
                for k in keys:
                    t = tbl.get((screen, k))
                    if t:
                        return t
            for k in keys:
                t = tbl.get(k)
                if t:
                    return t

            ptbl = A11yHost.UiAltByPos or {}
            if screen and pos:
                t = ptbl.get((screen, pos[0], pos[1]))
                if t:
                    return t

            fn = A11yHost.UiAltFor
            if fn is not None:
                try:
                    return fn(key, w, self._ctx(w, screen, pos))
                except Exception:
                    A11yHost.log_exc("UiAltFor 钩子异常")
            return None

        def _ctx(self, w, screen, pos):
            """交给逐作钩子的上下文（契约层 `UiAltFor` 有说明）。

            `ordinal` / `total` 是**同界面同图的第几个、共几个**（按 (y, x) 排序）
            —— 逐作层要「第几个」时一律用它，不要自己算坐标（见 `_A11yOrdinals`）。

            ⚠ 名次从**控件自己身上**读（`_scan` 写的 `w._a11y_ord`），
              按 `id(w)` 查 `_ord` 只作兜底 —— 理由同 `_where()`：
              `id()` 只在本轮 interaction 内稳定，而名次算错会**报错位号**。
            """
            n, total = (None, None)
            try:
                hit = getattr(w, "_a11y_ord", None)
                if hit is not None:
                    n, total = hit
            except Exception:
                pass
            if n is None:
                n, total = self._ord.get(id(w), (None, None))
            return {
                "screen": screen,
                "pos": pos,
                "x": pos[0] if pos else None,
                "y": pos[1] if pos else None,
                "ordinal": n,
                "total": total,
            }

        def _bar_text(self, w, screen=None, pos=None):
            """滑杆的「名字 + 当前百分比」。

            为什么不由引擎念：`Bar._tts_all` 拼的是 **`value.alt` + 一个「栏」字**
            （behavior.py:2664-2671），补丁改不掉那个字；而 `BarValue.alt` 的默认值
            是 `"Bar"`（ui.py:74）⇒ 引擎把它念成 `Barbar`。所以自己念。

            ⚠ 名字的第一来源是 **`value.alt`**，不是 `name`：
              引擎把**玩家可读的名字**放在 `value.alt` 上，而 `name` 是内部标识。
              `Preference("mixer asmr volume")` 的结果里
              —— `value.alt == "asmr volume"`（引擎自己拼的，00preferences.rpy:646）、
              `value.mixer == "asmr"`（内部标识）—— 而 `MixerValue` **没有** `name`
              属性，所以只找 `name` 会一无所获、最后念成内部标识。
              实机取证：音声界面的音量滑杆被念成 `asmr volumebar`。

            名字取法（依次）：① `value.alt` 查 preference 表 → ② `name` 查偏好表
            → ③ 位置表 → ④ 类名兜底（`ScrollValue` → 「滚动条」；中文/带空格的内部名
            原样报，便于维护者补表；其余报「数值」）。
            **没登记的内部名不念给玩家听**（会变成「history_list 45%」那种）。
            """
            val = getattr(w, "value", None)
            if val is None:
                return None
            tbl = A11yHost.UiAltByPreference or {}
            label = None
            name = None

            # ① 引擎放在 value 上的可读名（`Preference(...)` 会填它）
            alt = getattr(val, "alt", None)
            if isinstance(alt, str) and alt.strip():
                alt = alt.strip()
                label = tbl.get(alt) or tbl.get(alt.lower())

            # ② 内部标识（`name` / `preference` / `variable`）
            if label is None:
                for attr in ("name", "preference", "variable"):
                    v = getattr(val, attr, None)
                    if isinstance(v, str) and v:
                        name = v
                        break
                if name:
                    label = tbl.get(name) or tbl.get(name.lower())

            # ③ 位置表
            if label is None:
                ptbl = A11yHost.UiAltByPos or {}
                if screen and pos:
                    label = ptbl.get((screen, pos[0], pos[1]))

            # ④ 兜底：绝不把引擎那个空泛的默认 `"Bar"` 念给玩家
            if label is None:
                cls = type(val).__name__
                if "ScrollValue" in cls:
                    label = "滚动条"
                elif isinstance(alt, str) and alt.strip() and alt.strip() != "Bar" \
                        and alt.strip() not in tbl:
                    label = alt.strip()          # 引擎给的可读名，原样用
                elif name and ((" " in name) or any(
                        "\u4e00" <= c <= "\u9fff" for c in name)):
                    label = name
                else:
                    label = "数值"
            pct = self._bar_pct(val)
            if label is None and pct is None:
                return None
            if label is None:
                label = "数值"
            return label if pct is None else "%s %d%%" % (label, pct)

        @staticmethod
        def _bar_pct(val):
            """滑杆当前位置的百分比；取不到返回 `None`（绝不猜成 0）。

            三条取法，按「这个值对象最可能怎么表示自己」排序 —— 全部来自**实机探针
            打出来的接口**，不是猜的（探针原文见 CHANGELOG 0.0.1.5）：

              1. **`get_pos_duration()` -> `(位置, 总长)`**：本作那根**播放进度**滑杆
                 用的自定义值对象走这条（它是逐作自己写的，`get_adjustment()`
                 虽然能调通，但返回的 `Adjustment` **没有 min/max**、`value` 是
                 **秒数** ⇒ 想按 min/max 算百分比**必然失败**，名字后面永远光秃秃）。
                 ⚠ 平台层不写那一类的名字（断言 B）：靠**鸭子类型**认它。
              2. **`adjustment` 的 min/max/value**：普通 `StaticValue`/范围滑杆走这条。
              3. **`get_volume()`**：`MixerValue`（音量滑杆）走这条，返回 0~1。

            三条都不成立时返回 `None`：**名字仍然照念，绝不编一个数值出来。**
            """
            # 1) 位置 / 总长（播放进度那类）
            fn = getattr(val, "get_pos_duration", None)
            if callable(fn):
                try:
                    d = fn()
                    if isinstance(d, (tuple, list)) and len(d) >= 2:
                        cur, total = float(d[0]), float(d[1])
                        if total > 0:
                            return max(0, min(100, int(round(cur * 100.0 / total))))
                except Exception:
                    pass
            # 2) 带范围的 adjustment
            adj = None
            try:
                adj = val.get_adjustment()
            except Exception:
                adj = None
            if adj is None:
                adj = getattr(val, "adjustment", None)
            if adj is not None:
                try:
                    lo = getattr(adj, "min", None)
                    hi = getattr(adj, "max", None)
                    if lo is not None and hi is not None and float(hi) > float(lo):
                        return int(round((float(adj.value) - float(lo)) * 100.0
                                         / (float(hi) - float(lo))))
                except Exception:
                    pass
            # 3) 混音器音量（音量滑杆那类）
            gv = getattr(val, "get_volume", None)
            if callable(gv):
                try:
                    v = float(gv())
                    return max(0, min(100, int(round(v * 100.0))))
                except Exception:
                    pass
            return None

        def _bar_named(self, w, name):
            """滑杆**有名字**时的播报：`名字 + 当前百分比`（拼接的唯一出口）。

            ── 为什么要有这个函数（实机取证）──────────────────────────────
            滑杆的名字可能来自两个地方，而它们**走的是两条不同的路**：

              · `_bar_text`（`_table_text` 内部）—— 它自己会算百分比；
              · 逐作层的**位置表**（`UiAltByPos`）—— 它在 `_table_text` 里
                **先命中就先返回**，于是 `_bar_text` 那段算百分比的代码
                被整个短路。

            实机症状（自跑探针抓到的）：两根滑杆读成 `'播放进度'`。
            `'音声音量'` —— **对，但少了数值**，而滑杆的全部意义就是那个数值：
            「音声音量」本身是常量，玩家要知道的是「现在是多少」。
            所以凡是拿到滑杆名字的地方，都要走这里补上百分比。
            """
            if not name:
                return name
            val = getattr(w, "value", None)
            pct = self._bar_pct(val) if val is not None else None
            return name if pct is None else "%s %d%%" % (name, pct)

        @staticmethod
        def _state_suffix(w):
            """状态后缀 —— 只给**当前选中**的那个加「：当前」（读屏通例）。

            判据是引擎自己的 `Action.get_selected()`：只有单选/开关类动作返回
            True/False，其余返回 None，所以不会给普通按钮乱加状态。
            早期版本对没选中的也加「：关」，于是单选组念成
            「2560×1440：关」这种没有意义的噪声。
            """
            act = getattr(w, "action", None)
            if act is None:
                act = getattr(w, "clicked", None)
            acts = act if isinstance(act, (list, tuple)) else [act]
            for a in acts:
                try:
                    sel = a.get_selected()
                except Exception:
                    continue
                if sel:
                    return "：当前"
                if sel is not None:
                    return ""
            return ""

        # ==================================================== 控件身份（表键）
        @staticmethod
        def _filename_of(d):
            """从一个图片 displayable 上取文件名（几种存放方式都试）。"""
            for attr in ("filename",):
                v = getattr(d, attr, None)
                if isinstance(v, str) and v:
                    return v
            for attr in ("img", "_target", "child"):
                inner = getattr(d, attr, None)
                v = getattr(inner, "filename", None)
                if isinstance(v, str) and v:
                    return v
            try:
                r = repr(d)
                if r.endswith(".png'") or r.endswith('.png"'):
                    return r.strip("'\"")
            except Exception:
                pass
            return None

        def _filenames_in(self, d, depth=3):
            """递归收集一个子树里的图片文件名（宽度优先、限深）。

            图片不一定直接挂在按钮上：画廊的影片按钮是
            `idle Fixed(Frame(缩略图), Transform(角标))`，文件名埋在里层。
            """
            out = []
            if d is None or depth < 0:
                return out
            seen = set()
            queue = [(d, depth)]
            while queue:
                node, dep = queue.pop(0)
                if node is None or id(node) in seen:
                    continue
                seen.add(id(node))
                fn = self._filename_of(node)
                if fn:
                    out.append(fn)
                    continue
                if dep <= 0:
                    continue
                try:
                    kids = node.visit()
                except Exception:
                    kids = None
                for k in (kids or []):
                    if k is not None:
                        queue.append((k, dep - 1))
            return out

        def _keys_of(self, w):
            """一个图片按钮可能对应的**全部**表键（宽进：逐作层写哪种都认）。"""
            keys = []
            root = None
            try:
                sc = getattr(w, "state_children", None)
                root = sc.get("idle_") if sc else None
            except Exception:
                root = None
            for fn in self._filenames_in(root, depth=3):
                fn = str(fn).replace("\\", "/")
                base = fn.rsplit("/", 1)[-1]
                for k in (fn, base):
                    if k not in keys:
                        keys.append(k)
                stem = base.rsplit(".", 1)[0] if "." in base else base
                if stem not in keys:
                    keys.append(stem)
                for suf in ("_normal", "_idle", "_click", "_hover", "_selected"):
                    if stem.endswith(suf):
                        short = stem[: -len(suf)]
                        for k in (short + ".png", short):
                            if k not in keys:
                                keys.append(k)
            return keys

        def _best_key(self, w):
            """给日志与逐作钩子的**规范键**：文件名（不是全路径、优先 .png）。"""
            ks = self._keys_of(w)
            for k in ks:
                if k.endswith((".png", ".webp", ".jpg", ".jpeg")) and "/" not in k:
                    return k
            for k in ks:
                if k.endswith((".png", ".webp", ".jpg", ".jpeg")):
                    return k
            return ks[0] if ks else None

        # ================================================================ 播报
        def _track_focus(self):
            """焦点变化 -> 念新控件；同一控件文本变了 -> 也念（滑杆靠这条）。

            ⚠ 「同一个控件」的判据是**位置键**，不是对象身份 `id(w)`：本作音声
            播放界面有个 0.1 秒的 timer（music.rpy:336），每 0.1 秒重启一次
            interaction ⇒ 同一个按钮每 0.1 秒换一个对象。用 `id(w)` 时
            「同 id 且文本变了」这条支路**永远不会成立**，于是滑杆的百分比
            与「立绘当前值」这类**真·值变化**会被当成新控件的重复播报。
            换成位置键后：位置没动 = 还是那个控件（比文本），位置动了 = 换了控件。
            详见 `_focus_key` 的实机取证。
            """
            import renpy.display.focus as _f
            import renpy.display.behavior as _b
            w = _f.get_focused()
            if w is None:
                self._focus_id = None
                self._focus_text = None
                return
            text = self._read_text(w)
            where = self._where(w)
            miss = where is self._NO_WHERE
            # 位置查不到时**不静默**：写一行，且统计前几次 —— `_where()` 的说明里
            # 记着这类失配曾经让整片界面不朗读。留证据比留空白便宜。
            if miss:
                self._where_miss += 1
                if self._where_miss <= 5:
                    A11yHost.said("[alt] 位置查不到（第 %d 次）：%s 文本=%r" % (
                        self._where_miss, type(w).__name__, (text or "")[:30]))
                here = None if self._focus_id is None else (
                    "__miss__", self._where_miss)
            else:
                here = where
            if here == self._focus_id:
                if text and text != self._focus_text:
                    self._focus_text = text
                    A11yHost.said("[alt] 值变化: " + text[:60])
                    A11yHost.repeat.say(text, interrupt=True, record=False)
                return

            self._focus_id = here
            self._focus_text = text
            try:
                import renpy.display.tts as _t
                q = len(getattr(_t, "tts_queue", []) or [])
            except Exception:
                q = -1
            A11yHost.said("[alt] 焦点=%s 文本=%r 引擎队列=%d" % (
                type(w).__name__, (text or "")[:40], q))
            if not text:
                return                      # 引擎明确要求别念（`_silent_widget`）
            if isinstance(w, _b.Bar):
                A11yHost.said("[alt] 滑杆: " + text[:60])
                A11yHost.repeat.say(text, interrupt=True, record=False)
            else:
                self._announce(w, text)

        def _announce(self, w, text):
            """补丁自己播报（引擎那条通路在本补丁里是关闭的）。

            唯一一条让位判据是**文本比对**：引擎报过的最后一段话里已经包含这一条
            ⇒ 它管了。不要改回「按时间让位」——那条判据会让本层永远让位
            （引擎一直在报别的文本），实机反馈就是「和刚才没区别」。
            """
            # ★ 去重只有**一条**判据：**文案 + 界面 + 时间窗**。
            #
            #   ⚠ 这里曾经还有一条「`(文本,界面,坐标)` 与上次完全相同就不念」。
            #     它是**过强**的，而且与时间窗语义重复 —— 探针当场抓到两个后果：
            #       · 窗口**过期之后**同句再也念不出来（玩家走回来听不到）；
            #       · 引擎刚让位过一条，本层随后就永远念不出那一条。
            #     位置与对象身份在有动画的界面上本来就不稳定（见 `_focus_key`），
            #     拿它们做「念过没有」的判据既不可靠、又只会带来静默。
            #     所以：**位置只用来做身份区分，不做去重**；去重按文案 + 时间窗。
            import time
            now = time.monotonic()
            where = self._where(w)
            screen = None if where is self._NO_WHERE else where[0]
            key = (text, screen)
            if key == self._said_text and (now - self._said_at) < self.SAY_DEDUP_WINDOW:
                return
            try:
                last = getattr(A11yHost.rpy, "last_sink_text", None)
            except Exception:
                last = None
            if last and (text in last or last in text):
                return
            self._said_text = key
            self._said_at = now
            A11yHost.said("[alt] 播报: " + text[:60])
            A11yHost.repeat.say(text, interrupt=True, record=False)

        def _focus_key(self, w, text):
            """播报去重键 —— **不能用控件对象身份**（`id(w)`）。

            ── 为什么（实机取证：用户报「音声播放界面按方向键朗读抽搐」）──────
            引擎的 screen 每轮 interaction 都会**重新构造**它的 displayable
            （`imagebutton` / `textbutton` 都是普通 displayable，不跨 interaction
            复用；只有 `use`/screen 对象本身被缓存）。而本作音声播放界面带

                music.rpy:336    timer 0.1: action [SetVariable(...), ...] repeat True

            这种 timer 会**每 0.1 秒重启一次 interaction** —— 于是同一个按钮
            每 0.1 秒换一个对象：`id(w)` 一直变，「同 id 才算同一个控件」的去重
            永远不成立，而重读层那条 `DEDUP_WINDOW = 1.0` 一到期就再念一遍。
            实机日志原样是这个形状（同一句话，约 1 秒一次，连续几十次）：

                [alt] 焦点=ImageButton 文本='立绘' 引擎队列=0
                [alt] 播报: 立绘
                ……（约 1.0 秒后）一模一样再一遍

            听感就是「按住方向键 → 同一句抽搐式地反复念」。

            ── 所以键取**与对象身份无关**的三样东西 ────────────────────────
            文本 + 界面名 + 坐标。它们对「同一个按钮」稳定，对「真的换了控件」
            不相等（换控件必然换文本或换位置），所以不会吞掉真变化。
            真正跨帧变化的内容（滑杆百分比、立绘当前值）走的是
            `_track_focus` 里「同位置且文本变了」那条支路，不受这里影响。

            ⚠ 位置查不到时**不能退化成 `(None, None)`** —— 那会让所有查不到的
            控件共用一个键，第一个念过之后其余全被去重吞掉（＝静默）。
            位置本身的取法见 `_where()`。
            """
            where = self._where(w)
            if where is self._NO_WHERE:
                return (text, "__nopos__", id(w))
            screen, pos = where
            return (text, screen, pos)

        # ============================================================ 键盘导航
        def nav_candidates(self):
            """可导航控件，按画面**从上到下、从左到右**排好。

            过滤条件照抄引擎 `focus_ordered`（focus.py:848-866）：无位置的焦点
            （`x is None`）、明确不可聚焦（`x is False`）、`keyboard_focus` 为假。

            ⚠ 与引擎**故意不同**的一点：引擎还会跳过 `arg is not None` 的焦点
            （viewport 就是这种，viewport.py:296 传 `NO_MOUSE_FOCUS`），
            于是线性导航到不了视口 —— 而历史记录要靠视口滚动，所以保留。
            """
            out = []
            try:
                import renpy.display.focus as _f
                for f in _f.focus_list:
                    if getattr(f, "x", None) is None or f.x is False:
                        continue
                    w = getattr(f, "widget", None)
                    if w is None:
                        continue
                    try:
                        if not w.style.keyboard_focus:
                            continue
                    except Exception:
                        pass
                    out.append(f)
            except Exception:
                return []
            out.sort(key=lambda f: (f.y, f.x))
            return out

        def nav_move(self, delta):
            """方向键：把焦点**线性**移到上/下一个控件。

            为什么由补丁驱动：引擎自语音关闭时方向键走 `focus_nearest`
            （几何就近，focus.py:898-968），在两列混排的界面里**够不到一部分
            控件**（用户原话「除了对键盘导航做出了限制就没区别了」）。
            读屏用户的导航本来就该是线性的。

            移动后**不在这里朗读** —— 交给 `_track_focus`，全场只有一个播报源。
            """
            items = self.nav_candidates()
            if not items:
                return False
            try:
                import renpy.display.focus as _f
                cur = _f.get_focused()
                idx = None
                for i, f in enumerate(items):
                    if f.widget is cur:
                        idx = i
                        break
                if idx is None:
                    target = items[0] if delta > 0 else items[-1]
                else:
                    n = idx + delta
                    if n < 0 or n >= len(items):
                        return False        # 到头不动（不绕圈，免得听不出边界）
                    target = items[n]
                _f.pending_focus_type = "keyboard"
                _f.change_focus(target)
                return True
            except Exception:
                A11yHost.log_exc("线性导航失败")
                return False

        # ================================================================ 诊断
        def snapshot(self):
            """现场快照（Ctrl+Shift+I）：未识别清单 + 当前焦点读成什么。"""
            try:
                parts = []
                for screen, keys in sorted(self._unknown.items()):
                    ks = sorted(keys)
                    parts.append("%s 未识别 %d: %s" % (
                        screen, len(ks), ", ".join(ks[:10])))
                focus = ""
                try:
                    import renpy.display.focus as _f
                    w = _f.get_focused()
                    if w is not None:
                        focus = "焦点=%s 读成=%r" % (
                            type(w).__name__, self._read_text(w)[:40])
                except Exception:
                    focus = "焦点=?"
                return "控件播报: %s | %s" % (
                    " ; ".join(parts) if parts else "无未识别", focus)
            except Exception:
                return "控件播报: 快照失败"

        def _report(self):
            """把「未识别」清单写进日志 —— 那就是下一轮要补的表。"""
            try:
                for screen, keys in self._unknown.items():
                    sig = tuple(sorted(keys))
                    if self._reported.get(screen) == sig:
                        continue
                    self._reported[screen] = sig
                    A11yHost.log("[alt] 界面 %s 有 %d 个控件没有文案: %s" % (
                        screen, len(sig), ", ".join(sig[:12])))
            except Exception:
                pass


    A11yHost.uialt = A11yUiAlt()
