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

        def __init__(self):
            self._t = 0.0
            self._loc = {}        # id(widget) -> (界面名, (x, y))
            self._ord = {}        # id(widget) -> (同图名次, 同组总数)
            self._unknown = {}    # 界面 -> set(查不到文案的键)，作业清单
            self._reported = {}   # 去重：同一份清单只写一次日志
            self._beats = 0
            self._focus_id = None
            self._focus_text = None
            self._said_last = (None, None)

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
                    self._loc[id(w)] = (screen, pos)
                    entries.append((w, screen, pos, self._best_key(w)))
                except Exception:
                    continue

            self._ord = _A11yOrdinals([
                (screen, key, pos[0] if pos else None, pos[1] if pos else None,
                 id(w)) for (w, screen, pos, key) in entries])

            # 查不到文案的记成作业清单（那份清单就是下一轮要补的表）
            for w, screen, pos, key in entries:
                if self._has_real_text(w):
                    continue
                k = self._fallback_label(w)
                known = self._unknown.setdefault(screen or "?", set())
                if k not in known:
                    known.add(k)
            self._report()

        # ======================================================= 文本解析（四级）
        def _read_text(self, w):
            """当前控件「应该被念成什么」—— 四级兜底，**永不为空**。

            各级顺序的理由与「两种空」的区分见文件头。
            """
            import renpy.display.behavior as _b
            screen, pos = self._loc.get(id(w), (None, None))

            # ①②③：真实文本
            t = self._real_text(w, screen, pos)
            if t:
                return t
            # ④：兜底标识（引擎明确要求别念的控件除外）
            if self._silent_widget(w):
                return ""
            return self._fallback_label(w) or "未知控件"

        def _real_text(self, w, screen=None, pos=None):
            """①②③ 三级「真实文本」；都取不到返回空串。"""
            import renpy.display.behavior as _b

            # 引擎明确要求别念的控件：直接判空（不走兜底）
            if self._silent_widget(w):
                return ""

            # ① 已注入 / 游戏自带的 alt
            try:
                alt = getattr(w.style, "alt", None)
                if alt:
                    return str(alt)
            except Exception:
                pass

            # ② 控件自己拼得出来的文本
            try:
                t = str(w._tts_all(raw=True)).strip()
                if t:
                    return t
            except Exception:
                pass

            # ③ 查表
            if isinstance(w, _b.Button):
                try:
                    txt = self._table_text(w, screen, pos)
                    if txt:
                        return txt + self._state_suffix(w)
                except Exception:
                    pass
            return ""

        def _has_real_text(self, w):
            try:
                return bool(self._real_text(w, *self._loc.get(id(w), (None, None))))
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
            """
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

            为什么不由引擎念：`Bar._tts_all` 尾巴上硬编码一个「栏」字
            （behavior.py:2664-2671），补丁改不掉，所以自己念。

            名字三级取：preference 名 -> 位置表 -> 只报数值。
            **没登记的内部名不念给玩家听**（会变成「history_list 45%」那种）。
            """
            val = getattr(w, "value", None)
            if val is None:
                return None
            name = None
            for attr in ("name", "preference", "variable"):
                v = getattr(val, attr, None)
                if isinstance(v, str) and v:
                    name = v
                    break
            label = None
            tbl = A11yHost.UiAltByPreference or {}
            if name:
                label = tbl.get(name) or tbl.get(name.lower())
            if label is None:
                ptbl = A11yHost.UiAltByPos or {}
                if screen and pos:
                    label = ptbl.get((screen, pos[0], pos[1]))
            if label is None and name:
                cls = type(val).__name__
                if "ScrollValue" in cls:
                    label = "滚动条"
                elif (" " in name) or any("\u4e00" <= c <= "\u9fff" for c in name):
                    label = name
                else:
                    label = "数值"
            pct = None
            try:
                adj = val.get_adjustment()
                lo, hi, v = float(adj.min), float(adj.max), float(adj.value)
                if hi > lo:
                    pct = int(round((v - lo) * 100.0 / (hi - lo)))
            except Exception:
                pct = None
            if label is None and pct is None:
                return None
            if label is None:
                label = "数值"
            return label if pct is None else "%s %d%%" % (label, pct)

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
            """焦点变化 -> 念新控件；同一控件文本变了 -> 也念（滑杆靠这条）。"""
            import renpy.display.focus as _f
            import renpy.display.behavior as _b
            w = _f.get_focused()
            if w is None:
                self._focus_id = None
                self._focus_text = None
                return
            text = self._read_text(w)
            if id(w) == self._focus_id:
                if text and text != self._focus_text:
                    self._focus_text = text
                    A11yHost.said("[alt] 值变化: " + text[:60])
                    A11yHost.repeat.say(text, interrupt=True, record=False)
                return

            self._focus_id = id(w)
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
            my = (id(w), text)
            if my == self._said_last:
                return
            self._said_last = my
            try:
                last = getattr(A11yHost.rpy, "last_sink_text", None)
            except Exception:
                last = None
            if last and (text in last or last in text):
                return
            A11yHost.said("[alt] 播报: " + text[:60])
            A11yHost.repeat.say(text, interrupt=True, record=False)

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
