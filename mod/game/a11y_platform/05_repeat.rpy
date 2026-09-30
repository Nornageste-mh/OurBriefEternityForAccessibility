# A11yFramework / Ren'Py 版 —— 平台层（L1）· 重读缓冲区
#
# 对应上游 `platform/Repeat.cs`。L1 冻结层，逐作不得改写。

init -103 python:

    # 说明：这里曾经有一段「KEYDOWN 常数 + 事件守卫」的代码，
    # 用来让键处理函数「只在真按键时才动作」。那段逻辑是**基于错误前提**的：
    # `renpy.Keymap` 的值是**无参调用**的（behavior.py:559 -> :411），
    # 处理函数根本收不到事件 —— 读事件必然读到 None，于是那个键永远不响。
    # 现在处理函数一律写成无参，不需要任何常量。复盘见 CHANGELOG。
    # （`tests`：断言 E 会拦住任何带参数的处理函数。）

    def _A11yHostBackendName():
        """安全地取当前后端名（崩溃定位用，绝不能自己抛异常）。"""
        try:
            return A11yHost.speech.backend_name()
        except Exception:
            return "(取后端名失败)"

    class A11yRepeat(object):
        """重读缓冲区 —— **全补丁唯一的朗读出口**。

        ⚠ 关于按键：见 `on_key` 的说明 —— 挂在 `config.underlay` 的 `Keymap`
        会**无参调用**键处理函数，所以它们必须写成**无参**、
        且绝不能去读事件（读了就恒为假 → 整个键静默失效）。
        """

        #: 说明：这里曾经有 `KEYDOWN = _A11Y_KEYDOWN` 这个类属性，
        #: 供「读事件判断是不是真按键」的旧写法使用。那套写法已删除
        #: （见文件头），**属性也一并删掉** —— 留着它会让本文件的 init 抛
        #: `NameError`，而 **init 链一断，后面的按键层与播报层就全部不执行**
        #: （实机事故：日志里「已插入按键层」那行消失，只剩「登记键盘绑定失败」）。
        #: 所以：删常量时**必须连引用一起删**，并检查日志里的正向证据行。

        REPEAT_PREFIX = "重读："

        #: 同一条文本在这个时间窗内不重复朗读。
        DEDUP_WINDOW = 1.0

        #: 打断的**最小间隔**：距上次朗读不足这个秒数时**不打断**（改为排队）。
        #:
        #: ★ 这个常量取代了先前那个错误的 `MIN_INTERVAL`。
        #:   旧的那个是「丢弃后来的文本」，实测吞掉了 40% 的旁白，
        #:   直接违反上游红线「只读一部分 = 无障碍完整性问题」。
        #:   现在的做法**截然相反**：文本一条都不丢，丢的只是「打断」这个动作。
        #:
        #: 依据（实机取证，用户的 a11y_speech.log）：
        #:
        #:     主菜单。开始游戏，…… 按方向键移动，回车键确认。   ← 长句
        #:     1．开始游戏                                      ← 几十毫秒后
        #:     4．系统设置
        #:
        #: 三句都成功送给了 NVDA（返回 0），但用户**一句都听不到**。
        #: 原因：补丁每次朗读都先 `cancelSpeech()`，
        #: 于是长句刚起头就被短句取消；短句又被下一句取消。
        #: 而启动阶段还有**引擎自己的**自语音播报（`CfgAutoEnable=True` 会打开它），
        #: 两个播报源在几十毫秒内互相取消 —— 听感就是「叮叮当当但没人说话」。
        #:
        #: 判据刻意与「是否正在说话」无关，只看**距上次朗读过了多久**：
        #: 不依赖 NVDA 是否提供状态查询，也没有竞态。
        #: 后果是短促的连续导航会排队念完（略滞后），但**一句都不丢**。
        INTERRUPT_AFTER = 1.5

        def __init__(self):
            self._last = ""
            self._last_at = 0.0
            self._dropped = 0

        def say(self, text, interrupt=None, record=True):
            """唯一的朗读出口。`record=False` 用于不该被重读的即时反馈。"""
            if not text:
                return False
            t = text.strip()
            if not t:
                return False

            import time
            now = time.monotonic()

            # ---- 防重复（见 DEDUP_WINDOW）----
            if t == self._last and (now - self._last_at) < self.DEDUP_WINDOW:
                self._dropped += 1
                A11yHost.said_result("(去重丢弃) " + t, None, A11yHost.speech.backend_name())
                return True

            # ---- 打断降级：离得太近就不打断（见 INTERRUPT_AFTER）----
            if interrupt is None:
                gap = now - self._last_at
                interrupt = (gap >= self.INTERRUPT_AFTER)
                if not interrupt:
                    A11yHost.said_result("(排队不打断 gap=%.2f) %s" % (gap, t), None,
                                         A11yHost.speech.backend_name())

            if record:
                self._last = t
            self._last_at = now
            A11yHost.said(t)

            # ★ 崩溃定位：**调用前先落盘**。
            #   本补丁经过一次「游戏启动即硬崩」（`exit=-1073741819`
            #   = 0xC0000005 访问冲突，日志停在开屏播报之后）。
            #   原生崩溃不留 Python traceback，唯一能定位的办法就是在调用前
            #   写下标记 —— 崩溃后 `a11y_speech.log` 的最后一行就指明是哪个后端。
            A11yHost.said_result("(调用前) " + t, None, _A11yHostBackendName())
            ok = A11yHost.speech.speak(t, interrupt)
            A11yHost.said_result(t, ok, A11yHost.speech.backend_name())
            return ok

        def remember(self, text, record=True):
            """只把文本记进重读缓冲区，**不出声**。

            ── 为什么需要「记而不念」（对齐上游流水线的硬规则）──────────────

            维护者要求：**已经配音的台词不需要朗读名字**（配音本身就在说明是谁在说）。
            于是这类行补丁一个字都不念 —— 但那样 `_last` 就停在上一条**没配音**的行上，
            玩家在配音台词处按 **F5**，听到的会是更早的那一句。

            上游把这一条当成**已知 BUG 类**记录过，不是我的新发现：

              · `Reader.cs`：「有配音的行如果只 `Speech.Stop()` 而不记缓冲区，
                退格会念出**上一句**，玩家会以为『这一句翻不回来』」
                —— 那是一条**真实反馈**；
              · `Repeat.cs`：「**凡是玩家可能想重听的东西，都要进缓冲区** ——
                包括有配音的行。补丁只是不自动念它，玩家主动按重读键
                仍然要能听到（这是它**唯一的朗读通路**）」；
              · 发布清单：「重读能覆盖：普通台词 / **有配音台词** / 选项组 /
                快进经过的行」。

            所以记的是**整句台词**（不是只记名字）：配音错过了、或没听清，
            按 F5 让读屏把它念一遍，正是重读键该干的事。
            """
            t = (text or "").strip()
            if not t:
                return False
            if record:
                self._last = t
            return True

        def repeat(self):
            """重读最后一条。空缓冲区时给出提示，而不是一片安静。"""
            if not self._last:
                return self.say("没有可重读的内容", record=False)
            A11yHost.said("[重读] " + self._last)
            # 重读是玩家主动发起的，应当立刻出声 -> 显式打断
            ok = A11yHost.speech.speak(self.REPEAT_PREFIX + self._last, True)
            A11yHost.said_result(self.REPEAT_PREFIX + self._last, ok,
                                 A11yHost.speech.backend_name())
            return ok

        def last(self):
            return self._last

        def has_last(self):
            return bool(self._last)

        def clear(self):
            self._last = ""

        def on_key(self):
            r"""重读键被按下。调用方**不传任何参数** —— 这正是关键所在。

            ⚠⚠ **本补丁代价最大的一次误判，引擎源码实证：**

                renpy/display/behavior.py:550-565   Keymap.event
                    for name, action in self.keymap.items():
                        if map_event(ev, name):
                            rv = run(action)          # ← 无参数调用
                renpy/display/behavior.py:384-411   run
                    return action(*args, **kwargs)    # ← args 是空的

            `renpy.Keymap` 把自己那本字典的值当作**无参可调用对象**执行 ——
            引擎**永远不会**把按键事件交给它。而 `map_event(ev, name)`
            本身已经把「这是一次真正的按键」判完了：
            `compile_event`（behavior.py:129-161）拼出来的判据是

                ev.type == KEYDOWN  and  (not ev.repeat)
                and not (ev.mod & KMOD_ALT) and not (ev.mod & KMOD_META)
                and not (ev.mod & KMOD_CTRL) and ev.key == <绑定的那个键>

            所以本函数**既拿不到事件、也不需要事件**：被调用就等于按键成立。

            ── 因为这条守卫而白扔的一轮（实机取证）──────────────────────────

            补丁先前为了「别在没有按键时触发」而写了

                if ev is None or getattr(ev, "type", None) != KEYDOWN:
                    return

            它有**两条**独立的理由恒为真，任何一条单独存在都足以让这个键哑掉：

              (1) `ev` 永远是 `None`（Keymap 无参调用）；
              (2) `KEYDOWN` 这个常数取错了 —— 补丁写的是 `import pygame`，
                  而 Ren'Py 8 里根本没有名为 `pygame` 的模块（只有 shim
                  `renpy.pygame`），于是走了兜底值 `2`，
                  而真实事件类型是 **768**（`tools/probe_keymap.py` 实测）。

            于是重读键**从来不做任何事**。用户实机反馈：「重读无效」。
            取证文件里**一行 `[重读]` 都没有**（`a11y_speech.log` 16 行
            = 两次启动，全部止于主菜单），连 `[按键]` 这种痕迹也没有 ——
            也就是说**代码从来没被执行到过一次**。

            守卫的方向搞反了：它挡掉的恰好是唯一一次真正的按键。

            上游流水线那条纪律是「挂载点必须先确认它真的存在且真的能触发」，
            这里补上它的**下半句**：
            **还要确认引擎是用什么签名调用它的** ——
            「把事件当参数传进来」是 Unity / BepInEx 那一侧的习惯，Ren'Py 不是。
            """
            A11yHost.said("[按键] 重读键")
            # ★ 先响一声「按键收到了」，再朗读 —— 这一声是给盲人测试用的三分判别，
            #   理由见契约层 `CfgKeyCue`。它**必须在朗读之前**：
            #   如果朗读通路是哑的，这声提示音就是唯一能证明按键送到了的东西。
            A11yHost.key_cue()
            self.repeat()


    A11yHost.repeat = A11yRepeat()
