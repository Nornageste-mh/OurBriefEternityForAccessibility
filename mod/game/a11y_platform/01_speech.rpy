# A11yFramework / Ren'Py 版 —— 平台层（L1）· 朗读后端链
#
# 对应上游的 `platform/Speech.cs` + `Nvda.cs` + `Sapi.cs` 三个文件。
# 上游后端链是 Tolk -> NVDA -> ZDSR -> SAPI；本实现的两个差异**都是刻意的**，
# 理由写在下面（并按上游纪律：差异要说明依据，不许默默改）。
#
# L1 冻结层，逐作不得改写。

init -100 python:

    # ============================================================ 后端链调度
    class A11ySpeech(object):
        """朗读后端的注册与「只升不降」调度。

        ── 与上游的两处差异（都是刻意的，按上游纪律写明依据）────────────────

        1. **ZDSR（争渡）不适配。** 上游把它列为实验阶段（README 原文：ZDSR 后端
           「真正出声（中文往返）」属**没做过的验证**，「在此之前不要把这一级当成
           『已验证可用』」）。本机实测同样印证：`InitTTS` 返回 0，而判据
           `GetSpeakState` 返回 2（读屏没有运行或没有授权）。按维护者决定不做这一级。

        2. **Tolk 不随包分发。** 它需要一整套读屏驱动 dll 伴随，而相对「NVDA
           controller client 直连」的增量主要是覆盖 JAWS / SuperNova / ZoomText 等
           **中文用户基本不用**的读屏。本实现改为 NVDA 直连 + SAPI 兜底；玩家若自行
           在游戏根目录放 `Tolk.dll`，会自动把它接在链首（见 `A11yTolkBackend`）。

        ── 照抄上游、不再重新发明的三条 ────────────────────────────────────

        1. 后端**只升不降** —— 已停在 SAPI 时，若 NVDA 变为可用则换过去。
           没有这一步，「先开游戏、后开读屏」的玩家会一直听 SAPI。
        2. 朗读**抛异常绝不上抛**给游戏主循环 —— 失败就降级并允许重试。
        3. 初始化失败时把每个后端的结论串成一行日志，一眼看出「为什么全灭」。
        """

        #: 朗读新文本时是否打断上一句。
        #:
        #: ★ **默认 False（排队，不打断）** —— 实机取证后的决定。第一版每次 `True`
        #: （先 `cancelSpeech()` 再念），直觉上「新内容优先」更合理，实测后果是：
        #:   · 开局三次播报（开屏播报 / 引擎的「机器朗读已启用」/ 主菜单）挤在一起
        #:     互相打断 → **主菜单那句刚起头就没了，听感是「菜单哑了」**；
        #:   · 剧情里脚本推进比读屏快，于是**每一句都被下一句打断** → 用户原话
        #:     「读出来的大概率不是现在屏幕上显示的这一句」。
        #:
        #: 改成排队之后一句都不丢 —— 这正是上游那条红线要的：「只读一部分 =
        #: 无障碍完整性问题」。代价是朗读滞后于画面，但**滞后可以忍受，缺失不行**，
        #: 而且玩家随时可以按重读键把当前句拉回来（策略复盘见 docs §7.3）。
        #: 逐作层若确实需要「新优先」的语义（例如限时选择），可对单条传 `interrupt=True`。
        CfgInterrupt = False

        #: 定期重试可用后端的间隔（秒）。用于「先开游戏、后开读屏」的玩家。
        RETRY_INTERVAL = 3.0

        #: 后端模式的轮换表（F9 键按这个顺序切换）。
        #:
        #: `""` = 自动（NVDA -> 引擎同款 SAPI）；`"两者"` = 同时走所有可用后端。
        #: 「两者」是**诊断档 + 兜底档**：本机实机上 NVDA 控制器出现过「返回码恒为 0
        #: 但只有第一条出声」的现象（见 `register_builtin` 的「尚未查清」一节）。
        #: 有这一档，玩家按一下 F9 就能当场听出是哪一路在响 —— 不必关掉游戏改配置再重开。
        CfgModes = ["", "NVDA", "SAPI(引擎同款)", "两者"]

        def __init__(self):
            self._backends = []
            self._active = None
            self._pinned = ""
            self._last_retry = 0.0
            self._registered = False
            self._mode = ""
            self._last_spoke = []

        # -------------------------------------------------------- 注册
        def register(self, backend):
            """顺序即优先级，**先注册者优先**。"""
            self._backends.append(backend)

        def register_builtin(self):
            """注册本实现自带的后端链。幂等。

            ── 后端顺序是三次失败试出来的（每一步都是实机取证，不是推测）──────

            1. 最初照抄上游 `NVDA -> SAPI`。实机结果：**只响第一条，之后全静默，
               而返回码一直是 0**。
            2. 于是把 SAPI 提到链首（裸 COM 直调 vtable）。实机结果：**游戏硬崩** ——
               当场复现到 `exit=-1073741819`（0xC0000005 访问冲突），日志停在开屏
               播报送出之后。最可能是 COM 公寓/线程问题：SAPI 对象在初始化线程创建，
               却在渲染线程调用，且 SDL 的线程模型不保证 STA 语义。
            3. 最终采用**引擎自己那条已被验证不崩的路**：`wscript say.vbs <文本>`
               子进程（见 `A11ySayVbsBackend`）。引擎在 Windows 上的默认 TTS 就是走它，
               而且用户实机听到的中文正是它读出来的 —— 屏幕上那句「机器朗读已启用」
               就是这条路径念的。它放在链首，因为它是本作**唯一被证明能稳定出声**的路。

            `NVDA` 控制器仍然保留在链上（放在 SAPI 之后）：它的判据
            `nvdaController_testIfRunning` 是可靠的，在别的机器上它才是首选；
            本作这台机器上它只响一次的原因已记入 docs §7.5 的「尚未查清」，
            不当成已验证可用。
            """
            if self._registered:
                return
            self._registered = True

            tb = A11yTolkBackend()
            if tb.probe():
                self.register(tb)
                A11yHost.log("Tolk 可用，已接入链首（玩家自备 dll）")

            # ★ 顺序：**NVDA 优先，say.vbs 兜底**（按维护者要求改回 NVDA 优先）。
            #   备选后端的结论（都有实机依据，不是偏好）：
            #     · `A11yNvdaBackend`    借读屏发声，语速音色是玩家自己的设置
            #                            —— 无障碍补丁应有的默认；
            #     · `A11ySayVbsBackend`  引擎自己的 Windows TTS 路径（`wscript say.vbs`），
            #                            实测**不崩**，作兜底；代价是系统语音而非读屏语音；
            #     · 裸 COM 直调 SAPI     **代码已删除**，一注册就把游戏崩了 ——
            #                            结论见下方「裸 COM 直调 SAPI —— 已删除」一节。
            #
            # ⚠ **尚未查清**（按上游诚实纪律如实标注，不写成「已可用」）：
            #   本机实机上 NVDA 控制器出现过「只响第一条、之后静默，而
            #   `nvdaController_speakText` 返回码始终为 0」的现象；同一现象在纯宿主
            #   脚本里**复现不出来**（`tools/probe_nvda_race.py` 连续 3×3 次全部正常）。
            #   因此不能断言 NVDA 这条路已经可靠 —— 玩家若遇到「只响一次」，
            #   把配置 `CfgSpeechBackend` 设成 `"SAPI(引擎同款)"` 可切到兜底后端。
            self.register(A11yNvdaBackend())
            self.register(A11ySayVbsBackend())

        def set_pinned(self, name):
            """把后端钉死成 `name`（排查用）。钉死后不可用**不回退** —— 这是刻意的。"""
            self._pinned = (name or "").strip()
            self._active = None

        # -------------------------------------------------------- 模式（F9 切换）
        def set_mode(self, mode):
            """设置后端模式：`""` 自动 / 后端名 钉死 / `"两者"` 同时。

            ⚠ **名字写错不能变成「整局没有后端」。** 钉死的语义是「不回退」，所以一个
            拼错的配置名会让补丁**彻底哑掉** —— 而那是无障碍补丁最糟的故障形态
            （玩家听到的是「补丁坏了」，维护者看到的日志是「没有可用后端」，两边都无从
            下手）。这里因此先对已注册后端名做一次白名单核对，不认识就退回自动并写一行
            Warning（上游纪律：**不静默失效**）。
            """
            m = (mode or "").strip()
            if m and m != "两者":
                known = [b.name for b in self._backends]
                if m.lower() not in [k.lower() for k in known]:
                    A11yHost.log("Warning: 不认识的后端名 %r（可用: %s），改用自动"
                                 % (m, " / ".join(known) if known else "(无)"))
                    m = ""
            self._mode = m
            if m and m != "两者":
                self.set_pinned(m)
            else:
                self.set_pinned("")
            A11yHost.log("朗读模式 -> %s | 后端结论: %s" % (self.mode_label(), self.verdict()))
            return self.mode_label()

        def cycle_mode(self):
            """按 `CfgModes` 轮换一档，返回新档位的中文名（供播报）。"""
            modes = list(self.CfgModes)
            try:
                i = modes.index(self._mode)
            except ValueError:
                i = 0
            return self.set_mode(modes[(i + 1) % len(modes)])

        def mode_label(self):
            """档位的中文名（供播报与日志）。

            「自动」档要带上**它实际挑中了谁** —— 否则玩家按 F9 切到自动，听到的只有
            「自动」两个字，还是不知道现在是谁在念。
            """
            if self._mode == "两者":
                return "两者同时"
            if self._mode:
                return self._mode
            return "自动（%s）" % self.backend_name()

        # -------------------------------------------------------- 选择
        def _pick(self):
            if self._pinned:
                for b in self._backends:
                    if b.name.lower() == self._pinned.lower():
                        return b if b.available() else None
                return None

            cur = self._backends.index(self._active) if self._active in self._backends else len(self._backends)

            # 只升不降：名次更靠前（i 更小）且可用 -> 升级
            for i, b in enumerate(self._backends):
                if i >= cur:
                    break
                if b.available():
                    A11yHost.log("朗读后端升级: %s -> %s" % (
                        self._active.name if self._active else "(无)", b.name))
                    self._active = b
                    return self._active

            if self._active is not None and self._active.available():
                return self._active

            for b in self._backends:
                if b.available():
                    if self._active is not b:
                        A11yHost.log("朗读后端: %s" % b.name)
                    self._active = b
                    return self._active
            return None

        # -------------------------------------------------------- 生命周期
        def init(self):
            try:
                self.register_builtin()
                for b in self._backends:
                    try:
                        b.init()
                    except Exception:
                        A11yHost.log_exc("后端 %s 初始化异常" % b.name)
                self._pick()
                A11yHost.log("后端结论: %s" % self.verdict())
            except Exception:
                A11yHost.log_exc("A11ySpeech.init 异常")

        def tick(self):
            import time
            try:
                now = time.monotonic()
                if now - self._last_retry < self.RETRY_INTERVAL:
                    return
                self._last_retry = now
                self._pick()
            except Exception:
                pass

        # -------------------------------------------------------- 查询
        def backend_name(self):
            """当前**实际会出声**的后端名 —— 也是 `said_result` 里那一栏。

            ⚠⚠ **这里必须「现问一次」，不能只看缓存。** 实机事故：开屏播报说
            「没有可用的朗读后端，请确认读屏软件正在运行」，而那句提示**正是被读屏
            念出来的** —— 自相矛盾。根因：`set_mode()`（F9 那一档加的）会经
            `set_pinned("")` 把 `self._active` 清成 `None`（意思是「下次发声时重新挑
            一个」），`speak()` 确实会重新挑（`b = self._active or self._pick()`），
            **`backend_name()` 却只会照实返回「没有」** —— 于是「先问名字、再发声」的
            开屏播报拿到了一个**过期状态**。

            教训：**「查询接口」与「执行接口」对同一份状态的解读必须一致** —— 这种
            不对称平时看不出来，只在「先查询后执行」的调用顺序下才暴露，而且暴露的
            方式是**说出自相矛盾的话**（回归点见 `tools/probe_speech.py`）。
            现在两者一致：`_active` 为空时统一调 `_pick()`（内部有 2 秒可用性缓存，
            代价可忽略）。
            """
            if self._mode == "两者":
                names = self._last_spoke or self._available_names()
                return "两者(%s)" % ("+".join(names) if names else "无可用后端")
            b = self._active if self._active is not None else self._pick()
            return b.name if b is not None else "(无)"

        def _available_names(self):
            """当前可用的后端名列表（仅用于展示）。"""
            out = []
            for b in self._backends:
                try:
                    if b.available():
                        out.append(b.name)
                except Exception:
                    continue
            return out

        def verdict(self):
            """把每个后端的结论串成一行 —— 「为什么全灭」要一眼看得出。"""
            parts = []
            for b in self._backends:
                try:
                    ok = b.available()
                except Exception:
                    ok = False
                parts.append("%s=%s" % (b.name, "可用" if ok else b.reason()))
            return " | ".join(parts) if parts else "(无后端)"

        # -------------------------------------------------------- 发声
        def speak(self, text, interrupt=None):
            """朗读 `text`。返回是否成功。**绝不抛异常。**

            `interrupt=None`（默认）表示「按 `CfgInterrupt` 的策略走」；
            传 `True` / `False` 可对单条覆盖。

            ⚠ **失败时绝不标记后端失效。** 第一版在异常时调 `invalidate()`，想的是
            「下次 tick 会重新挑一个」—— 真实后果是：一次偶发失败（例如朗读时正好在
            切场景）就把 NVDA 标成失效，之后一路降到 SAPI 或干脆没有后端，表现为
            **游戏突然哑掉且不再恢复**。宁可下次再试同一个后端，也不要静默降级。
            降级只发生在**可用性探测**里（`_pick()` 调 `available()`），那里有明确判据
            （`nvdaController_testIfRunning`）。
            兜住这条不变量的做法是：把 `invalidate()` 这个接口**一起删掉** ——
            它已无任何调用方，留着只会诱使别人再把静默降级写回来。
            """
            if not text:
                return False
            if interrupt is None:
                interrupt = self.CfgInterrupt
            try:
                if self._mode == "两者":
                    return self._speak_all(text, interrupt)
                b = self._active if self._active is not None else self._pick()
                if b is None:
                    A11yHost.log("朗读失败: 没有可用后端（%s）" % self.verdict())
                    return False
                b.speak(text, interrupt)
                return True
            except Exception as e:
                A11yHost.log("朗读异常（保持当前后端 %s）: %s: %s" % (
                    self.backend_name(), type(e).__name__, e))
                return False

        def _speak_all(self, text, interrupt):
            """「两者同时」档：同一句交给**所有可用后端**，返回「至少有一路成功」。

            每一路的成败单独记日志 —— 这条日志就是为了回答「读屏到底收没收到」这个
            查了很多轮的问题：如果 NVDA 那一路写了成功、而玩家只听见 SAPI 的声音，
            那问题在 NVDA 侧，不在本补丁的调用链上。
            """
            spoke, failed = [], []
            for b in self._backends:
                try:
                    if not b.available():
                        continue
                except Exception:
                    continue
                try:
                    b.speak(text, interrupt)
                    spoke.append(b.name)
                except Exception as e:
                    failed.append("%s(%s)" % (b.name, type(e).__name__))
            self._last_spoke = spoke
            if failed:
                A11yHost.log("两者模式: 失败 %s" % ", ".join(failed))
            if not spoke:
                A11yHost.log("两者模式: 没有可用后端（%s）" % self.verdict())
                return False
            return True

        def stop(self):
            try:
                if self._active is not None:
                    self._active.stop()
            except Exception:
                pass


    # ============================================================ say.vbs 后端（引擎同款）
    class A11ySayVbsBackend(object):
        r"""走 `wscript say.vbs` 子进程 —— **引擎自己的 Windows TTS 路径**。

        ── 为什么用它（三个别处没有的好处）─────────────────────────────────

        引擎在 Windows 上的默认 TTS 就是这条（`renpy/display/tts.py:179-193` 实查）：

            say_vbs = os.path.join(os.path.dirname(sys.executable), "say.vbs")
            process = subprocess.Popen(["wscript", say_vbs, s, voice, amplitude])

        1. **已在本作被证明能出声** —— 用户实机听到的中文
           「机器朗读已启用。按 V 来禁用。」就是它读的；
        2. **不崩** —— 它是子进程，与游戏的 COM/线程模型完全隔离（本补丁用裸 COM
           直调 SAPI 时把游戏崩了，`0xC0000005`）；
        3. **可被中断** —— 存下 Popen 句柄，下一条朗读前 terminate 掉即可，
           不依赖任何读屏接口的状态查询。

        代价（如实说明）：声音是**系统语音**（SAPI），语速/音色由系统设置决定，不是
        NVDA 的语音；每条朗读要起一个 `wscript` 进程，比进程内调用重 —— 但实测这个
        开销相对于「一句话的朗读时长」可以忽略。

        `say.vbs` 的参数是 `<text> <voice> <volume>`；
        `voice` 传 `default voice` 表示用系统默认（与引擎的做法一致）。"""

        name = "SAPI(引擎同款)"

        def __init__(self):
            self._proc = None
            self._path = None
            self._why = "未初始化"
            self._ok = False

        def _find(self):
            """找 say.vbs。位置与引擎一致：运行时 python 的同级目录。"""
            import os
            import sys
            cands = []
            try:
                cands.append(os.path.join(os.path.dirname(sys.executable), "say.vbs"))
            except Exception:
                pass
            # 引擎的 `sys.executable` 在游戏里是 <游戏>\lib\py3-windows-x86_64\python.exe
            try:
                gamedir = getattr(config, "gamedir", None)
                basedir = getattr(config, "basedir", None)
                if basedir:
                    cands.append(os.path.join(basedir, "lib", "py3-windows-x86_64", "say.vbs"))
                if gamedir:
                    cands.append(os.path.join(os.path.dirname(gamedir), "lib",
                                              "py3-windows-x86_64", "say.vbs"))
            except Exception:
                pass
            for c in cands:
                if c and os.path.exists(c):
                    return c
            return None

        def probe(self):
            return self._find() is not None

        def init(self):
            self._path = self._find()
            if self._path is None:
                self._why = "找不到 say.vbs"
                return
            self._ok = True
            self._why = "就绪"
            A11yHost.log("say.vbs 后端: %s" % self._path)

        def available(self):
            return self._ok and self._path is not None

        def reason(self):
            return self._why

        def speak(self, text, interrupt=True):
            import subprocess
            import sys
            if not self._path:
                raise RuntimeError("say.vbs 不可用")

            # 中断 = 干掉上一条（这正是引擎 default_tts_function 的做法）
            if self._proc is not None:
                try:
                    self._proc.terminate()
                    self._proc.wait()
                except Exception:
                    pass
                self._proc = None

            s = (text or "").strip()
            if not s:
                return
            # 与引擎一致：双引号去掉（say.vbs 的命令行参数不允许）
            s = s.replace('"', "")

            fsencode = renpy.exports.fsencode
            self._proc = subprocess.Popen([
                "wscript",
                fsencode(self._path),
                fsencode(s),
                fsencode("default voice"),
                fsencode("100"),
            ])

        def stop(self):
            if self._proc is not None:
                try:
                    self._proc.terminate()
                    self._proc.wait()
                except Exception:
                    pass
                self._proc = None


    # ============================================================ NVDA 后端
    class A11yNvdaBackend(object):
        """nvdaControllerClient 的纯 ctypes 封装。上游 `platform/Nvda.cs` 的对应物。

        DLL 探测次序（照抄上游 `Zdsr.cs` 的教训：**必须按绝对路径预加载**）：

            1. 本补丁自己的目录        `<game>/a11y_platform/`
            2. 游戏根目录（玩家自放）  `<basedir>/`
            3. game 目录本身           `<game>/`

        为什么必须按绝对路径显式加载：Windows 的 `LoadLibrary` 会**先搜应用目录**，
        玩家若在别处放了一份旧副本，按基名解析会命中错的那一份。
        按绝对路径加载后，再让按基名解析的调用命中已加载的那个模块。

        导出名核对（**开发期已实证，见 tools/probe_dll.py 输出**）：
            nvdaController_testIfRunning / nvdaController_speakText /
            nvdaController_cancelSpeech
        这三个名字**不是猜的** —— 是读 PE 导出表读出来的（上游 §7 铁律 1）。
        """

        name = "NVDA"
        DLL_NAMES = ("nvdaControllerClient64.dll", "nvdaControllerClient.dll")

        def __init__(self):
            self._lib = None
            self._load_error = None
            self.loaded_from = None
            self._ok = False
            self._why = "未初始化"
            self._tested_at = None
            self._tried = False

        @staticmethod
        def _candidate_dirs():
            r"""DLL 候选目录，按优先级。

            ⚠ **不要用 `__file__`。** 本补丁第一版就是这么写的：

                os.path.dirname(os.path.abspath(__file__))

            它在 Ren'Py 的脚本命名空间里**不保证存在**（`.rpy` 是被编译成 `.rpyc`
            后 exec 的，不是作为普通模块 import 的），而这一句外面包着 `try/except`
            —— 于是异常被吞掉，「补丁自己的目录」这条探测路径**永远静默失效**。
            开发机上因为有硬编码的开发缓存兜底，所以一直没暴露；
            **换到玩家的机器上就会变成「找不到 NVDA dll」→ 静默降级到 SAPI**。

            正确做法是用引擎提供的路径（都是文档化的 config 字段）：
              · `config.gamedir`  —— `<游戏>\game\`
              · `config.basedir`  —— `<游戏>\`
            再加上补丁自己的目录名，拼出 `game\a11y_platform\`。
            """
            import os
            dirs = []

            gamedir = None
            basedir = None
            try:
                gamedir = getattr(config, "gamedir", None) or None
            except Exception:
                pass
            try:
                basedir = getattr(config, "basedir", None) or None
            except Exception:
                pass

            # 1) 补丁自己的目录：<game>\a11y_platform\
            if gamedir:
                dirs.append(os.path.join(gamedir, "a11y_platform"))
            # 2) 游戏根目录（玩家自放 dll 的地方）
            if basedir:
                dirs.append(basedir)
            # 3) game 目录本身
            if gamedir:
                dirs.append(gamedir)

            out = []
            for d in dirs:
                if d and d not in out:
                    out.append(d)
            return out

        def _ensure(self):
            import ctypes
            import os
            if self._lib is not None or self._tried:
                return self._lib is not None
            self._tried = True

            path = None
            for d in self._candidate_dirs():
                for n in self.DLL_NAMES:
                    p = os.path.join(d, n)
                    if os.path.exists(p):
                        path = p
                        break
                if path:
                    break

            if path is None:
                self._load_error = "未找到 nvdaControllerClient64.dll"
                return False

            try:
                lib = ctypes.WinDLL(path)
                lib.nvdaController_testIfRunning.argtypes = []
                lib.nvdaController_testIfRunning.restype = ctypes.c_int
                lib.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
                lib.nvdaController_speakText.restype = ctypes.c_int
                lib.nvdaController_cancelSpeech.argtypes = []
                lib.nvdaController_cancelSpeech.restype = ctypes.c_int
                self._lib = lib
                self.loaded_from = path
                return True
            except Exception as e:
                self._load_error = "%s: %s" % (type(e).__name__, e)
                return False

        def probe(self):
            return self._ensure()

        def init(self):
            if not self._ensure():
                self._why = self._load_error or "加载失败"
                return
            self._test()
            A11yHost.log("NVDA controller: dll=%s 结论=%s" % (self.loaded_from, self._why))

        def _test(self):
            import time
            self._ok = False
            if self._lib is None:
                self._why = self._load_error or "加载失败"
                return
            try:
                rc = self._lib.nvdaController_testIfRunning()
                self._tested_at = time.monotonic()
                if rc == 0:
                    self._ok = True
                    self._why = "在跑"
                else:
                    self._why = "未运行 (rc=%d)" % rc
            except Exception as e:
                self._why = "调用异常 %s" % type(e).__name__

        def available(self):
            import time
            if not self._ensure():
                return False
            # testIfRunning 有代价，缓存 2 秒；这样「先开游戏后开 NVDA」也能被发现
            if self._tested_at is None or (time.monotonic() - self._tested_at) > 2.0:
                self._test()
            return self._ok

        def reason(self):
            return self._why

        def speak(self, text, interrupt=True):
            if self._lib is None:
                raise RuntimeError("NVDA dll 未加载")
            if interrupt:
                A11yHost.diag("NVDA cancelSpeech()")
                try:
                    self._lib.nvdaController_cancelSpeech()
                except Exception:
                    pass
            rc = self._lib.nvdaController_speakText(text)
            # ★ 这一行是「NVDA 到底收到没有」的唯一直接证据。
            #   `CfgDiagLog=False` 时它不写（避免刷日志），
            #   而 `said_result` 无论如何都会记下「调用前 / OK」——
            #   两者配合就能分离「没送来」与「送来了没出声」。
            A11yHost.diag("NVDA speakText rc=%d len=%d" % (rc, len(text or "")))
            if rc != 0:
                raise RuntimeError("nvdaController_speakText rc=%d" % rc)

        def stop(self):
            if self._lib is not None:
                self._lib.nvdaController_cancelSpeech()


    # ============================================================ 裸 COM 直调 SAPI —— **已删除**
    #
    # 这里曾经有一个 `A11ySapiBackend`（纯 ctypes 直调 `ISpVoice` vtable，因此不需要
    # pywin32 / comtypes，补丁能保持「零第三方依赖」）。**代码删了，结论留下** ——
    # 因为它一注册就把游戏崩了：把 SAPI 提到链首时当场复现 `exit=-1073741819`
    # （`0xC0000005` 访问冲突），日志停在开屏播报送出之后（见 `register_builtin` 第 2 步）。
    #
    # 该类**从不实例化**（`register_builtin` 不注册它）⇒ 它那三条日志
    # （`SAPI: CoInitializeEx -> ...` / `SAPI: 就绪 (rate=.. volume=..)` /
    # `SAPI: ... —— 槽位可能错位，拒绝使用`）从来没有、也不会出现在 `log.txt` 里，
    # 因此随代码一并删除 —— 其余日志字符串一字未动。
    #
    # 三条仍然有效的上游结论（可重跑的实测代码在 `tools/probe_backend.py`）：
    #
    #   1. **绝不要用 COM 后期绑定**（C# 是 `Type.GetTypeFromProgID("SAPI.SpVoice")` +
    #      `InvokeMember`；Python 对应 `win32com.client.Dispatch` / `comtypes` 动态派发）。
    #      上游实测：Unity 的 Mono 没实现 COM 后期绑定，日志是
    #      `SAPI 不可用: NotImplementedException`，表现是**整局游戏一片安静**。
    #   2. **`SPF_ASYNC` 必须置位**，否则 SAPI 默认同步朗读、会阻塞调用线程 ——
    #      在 Ren'Py 里就是**阻塞主线程导致游戏卡死**。
    #      `stop()` = `Speak(NULL, SPF_ASYNC | SPF_PURGEBEFORESPEAK)`。
    #   3. **初始化时先读 rate/volume 验证 vtable 槽位**：槽位错一位就会当场露馅
    #      （读到不可能的值），而不是等玩家需要朗读时静默失败。
    #      实测值：rate=0、volume=100，判据 `0 <= volume <= 100`。
    #
    # vtable 槽位（上游已实机验证，**错一位就会当场露馅**）：
    #     0 QueryInterface  1 AddRef  2 Release
    #     18 SetVoice  20 Speak  21 SpeakStream  22 GetStatus
    #     28 SetRate  29 GetRate  30 SetVolume  31 GetVolume  32 WaitUntilDone


    # ============================================================ Tolk（可选，玩家自备）
    class A11yTolkBackend(object):
        """Tolk 是**可选**的一级，本补丁**不分发** Tolk.dll。

        为什么不分发：Tolk 需要一整套读屏驱动 dll 伴随，而它相对「NVDA controller
        client 直连」的增量，主要是覆盖 JAWS / SuperNova / ZoomText 这类**中文用户
        基本不用**的读屏。分发体积与合规成本都不划算。

        为什么仍然实现：上游 Tolk 是一级，玩家若自备 `Tolk.dll`（放进游戏根目录），
        本补丁应当能利用它 —— 否则就丢了「用 JAWS 的玩家」这个群体。
        探测不到时静默跳过，不影响 NVDA / say.vbs 两级。
        """

        name = "Tolk"

        def __init__(self):
            self._lib = None
            self._why = "玩家未提供 Tolk.dll"

        def _dirs(self):
            """与 NVDA 后端共用同一套候选目录（理由见那里的说明，别用 `__file__`）。"""
            return A11yNvdaBackend._candidate_dirs()

        def probe(self):
            import ctypes
            import os
            for d in self._dirs():
                p = os.path.join(d, "Tolk.dll")
                if os.path.exists(p):
                    try:
                        lib = ctypes.WinDLL(p)
                        lib.Tolk_Load.argtypes = []
                        lib.Tolk_Load.restype = None
                        lib.Tolk_Output.argtypes = [ctypes.c_wchar_p, ctypes.c_bool]
                        lib.Tolk_Output.restype = ctypes.c_bool
                        lib.Tolk_DetectScreenReader.argtypes = []
                        lib.Tolk_DetectScreenReader.restype = ctypes.c_wchar_p
                        lib.Tolk_Silence.argtypes = []
                        lib.Tolk_Silence.restype = ctypes.c_bool
                        lib.Tolk_IsLoaded.argtypes = []
                        lib.Tolk_IsLoaded.restype = ctypes.c_bool
                        self._lib = lib
                        return True
                    except Exception as e:
                        self._why = "Tolk.dll 加载失败 %s" % type(e).__name__
                        return False
            return False

        def init(self):
            if self._lib is None:
                return
            try:
                self._lib.Tolk_Load()
                name = self._lib.Tolk_DetectScreenReader()
                self._why = "已加载，读屏=%s" % (name or "(未检测到)")
                A11yHost.log("Tolk: " + self._why)
            except Exception as e:
                self._why = "Tolk_Load 异常 %s" % type(e).__name__

        def available(self):
            if self._lib is None:
                return False
            try:
                if not self._lib.Tolk_IsLoaded():
                    self._lib.Tolk_Load()
                return bool(self._lib.Tolk_DetectScreenReader())
            except Exception:
                return False

        def reason(self):
            return self._why

        def speak(self, text, interrupt=True):
            if self._lib is None:
                raise RuntimeError("Tolk 不可用")
            ok = self._lib.Tolk_Output(text, bool(interrupt))
            if not ok:
                raise RuntimeError("Tolk_Output 返回 false")

        def stop(self):
            try:
                if self._lib is not None:
                    self._lib.Tolk_Silence()
            except Exception:
                pass


    # 实例化并挂到契约层（跨模块引用一律走 A11yHost 的具名槽位）
    A11yHost.speech = A11ySpeech()
