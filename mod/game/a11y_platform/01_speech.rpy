# A11yFramework / Ren'Py 版 —— 平台层（L1）· 朗读后端链
#
# 对应上游的 `platform/Speech.cs` + `Nvda.cs` + `Zdsr.cs` + `Sapi.cs` 四个文件。
# 上游后端链是 Tolk -> NVDA -> ZDSR -> SAPI；本实现**同为四级**，唯一一处差异
# （Tolk 不随包分发）是刻意的，理由写在下面（并按上游纪律：差异要说明依据，
# 不许默默改）。
#
# L1 冻结层，逐作不得改写。

init -100 python:

    # ============================================================ 后端链调度
    class A11ySpeech(object):
        """朗读后端的注册与「只升不降」调度。

        ── 与上游的唯一一处差异（是刻意的，按上游纪律写明依据）──────────────

        **Tolk 不随包分发。** 它需要一整套读屏驱动 dll 伴随，而相对「NVDA
        controller client 直连」的增量主要是覆盖 JAWS / SuperNova / ZoomText 等
        **中文用户基本不用**的读屏。本实现改为 NVDA 直连 + ZDSR + SAPI 兜底；
        玩家若自行在游戏根目录放 `Tolk.dll`，会自动把它接在链首
        （见 `A11yTolkBackend`）；没放就跳过，不影响后面三级。

        ── ZDSR（争渡）这一级：从「不适配」改成「接上」（依据与边界）─────────

        旧版这里写着「ZDSR 不适配，按维护者决定不做这一级」。改的依据不是上游把它
        列为实验阶段，而是**本机实测把那条否定判据解释清楚了**（见 §1.5 的实测）：

          · `InitTTS(0, NULL, False)` 返回 **0**（读屏没在跑时**也是 0**）——
            它只表示「版本对得上」，**不表示读屏在跑**；
          · 真正的判据 `GetSpeakState()` 在同一个进程里返回 **2**
            （读屏没有运行或没有授权）。

        当时的结论「判据不成立」是对的，但它推出的是「这一级不该接」，
        正确的推论是「**照 `GetSpeakState` 判，判不过就顺降**」—— 也就是链上多一级
        「可用就用、不可用就当它不在」的后端，而不是把这一级删掉。
        `A11yZdsrBackend.available()` 因此只认 `GetSpeakState() in (3, 4)`
        （3 正在朗读 / 4 没有朗读），**绝不认 `Speak()` 的返回值** ——
        未授权时 `Speak()` 同样返回 0，拿它当判据就会重新造出
        「自称可用却一句话都不出」这个故障。

        ⚠ **本机只验到哪一步（不许当成已验证）**：本机能加载 dll、`InitTTS -> 0`；
        `GetSpeakState` 两次只读实测一次是 **2**（0.0.1.6 当时读屏没在跑）、
        一次是 **4**（0.0.1.7 复查，读屏在跑）⇒ 判据成立、`available() -> True`。
        但 **「争渡在跑时真的出声（中文往返）」本机仍然没有发生过** ——
        那需要在游戏里按 F9 切到争渡并真听一句（`CfgModes` 里已经有 `"ZDSR"` 这一档）。

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

        #: 后端轮换表的**固定顺序**（后端切换键按这个顺序走一档）。
        #:
        #: ★ 这是**跨补丁的统一约定**（维护者要求）：自动 -> Tolk -> NVDA -> 争渡 ->
        #: SAPI -> 回自动。`""` 是「自动」档（交给 `_pick()` 现挑），其余是后端 `name`。
        #:
        #: ⚠ 表里有这一档**不等于**按键会停在它上面：**不可用的后端会被跳过并播报**
        #: （`cycle_backend()`，那是这个键最重要的一条行为）。Tolk 尤其如此 ——
        #: 它要玩家自备 dll，绝大多数机器上根本没注册。
        CfgModes = ["", "Tolk", "NVDA", "ZDSR", "SAPI(引擎同款)"]

        #: 档位 -> **播报名**（人话）。键是 `CfgModes` 里的档位值（后端名或 `""`）。
        #:
        #: 为什么不在后端类上挂一个 `label`：后端类只回答「我叫什么、能不能用」，
        #: 面向玩家的中文名是**播报层**的事（而且 `""` 这一档根本不是后端）。
        #: `"ZDSR" -> "争渡读屏"` 是维护者要求的叫法 —— 玩家嘴里念的是读屏软件的
        #: 名字，不是我们的类名；念 `ZDSR` 等于让他去对代码。
        ModeNames = {
            "": "自动",
            "Tolk": "Tolk",
            "NVDA": "NVDA",
            "ZDSR": "争渡读屏",
            "SAPI(引擎同款)": "引擎同款 SAPI",
            "两者": "两者同时",
        }

        #: 玩家按后端切换键选中的档位记在这里，跨启动保留（走 `A11yHost.remember`，
        #: 落盘位置是引擎的 persistent）。前缀带 `a11y_` 是为了在玩家的
        #: `persistent` 存档里一眼看出这一条是本补丁写的。
        REMEMBER_KEY = "a11y_speech_backend"

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

            # ★ 顺序：**NVDA 优先，ZDSR 居中，say.vbs 兜底**（按维护者要求改回 NVDA 优先）。
            #   备选后端的结论（都有实机依据，不是偏好）：
            #     · `A11yNvdaBackend`    借读屏发声，语速音色是玩家自己的设置
            #                            —— 无障碍补丁应有的默认；
            #     · `A11yZdsrBackend`    争渡读屏（中文读屏里用户量最大的那一支）。
            #                            放 NVDA 之后、say.vbs 之前：判据是官方的
            #                            `GetSpeakState() in (3, 4)`，判不过就顺降 ——
            #                            争渡没开或没授权时，它的表现与「不在链上」相同；
            #                            它的状态查询缓存 2 秒（短于 `RETRY_INTERVAL`），
            #                            所以「先开游戏、后开争渡」也能在几秒内被接上。
            #                            ⚠ 本机只验到「判据返回 2 ⇒ 顺降」这条路径，
            #                            「争渡在跑时真的出声」尚未实测。
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
            self.register(A11yZdsrBackend())     # ★ 0.0.1.6 接入：NVDA 之后、say.vbs 兜底之前
            self.register(A11ySayVbsBackend())

        def set_pinned(self, name):
            """把后端钉死成 `name`（排查用）。钉死后不可用**不回退** —— 这是刻意的。"""
            self._pinned = (name or "").strip()
            self._active = None

        # -------------------------------------------------------- 模式（后端切换键切换，默认 F9）
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

        def cycle_backend(self):
            r"""后端切换键（默认 F9）：切到**下一个当前可用**的后端，返回要播报的整句话。

            ── 顺序与「跳过」的语义（维护者的统一约定）───────────────────────────

            固定顺序 `自动 -> Tolk -> NVDA -> 争渡 -> SAPI -> 回自动`（= `CfgModes`）。
            **不可用的后端直接跳过，不停在它上面**，并把「跳过了谁、为什么」一并念出来。

            为什么必须「跳过 + 播报跳过」，而不是停在不可用的一档：
              · 停在不可用档 = 按一下键，**世界安静了** —— 而「安静」在本项目里是最贵的
                故障形态（`CfgKeyCue` 那一整段就是为它写的）：分不清「这路坏了」还是
                「键没送到」；
              · 静默跳过 = 玩家以为「少了一级」或「少按了一下」——同样是假信息，
                而且他没有任何办法看出来。
            所以：**跳过 + 说出跳过了谁**。按键表与 FAQ 同步改了 ——
            不能代码一个说法、文档一个说法（那是本项目最忌讳的自相矛盾）。

            ── 落盘（跨启动保留）────────────────────────────────────────────────

            选中之后同时写两处：
              · `A11yHost.CfgSpeechBackend`（**配置面**：`validate()`、现场快照、
                以及任何读配置的地方都立刻跟上）；
              · `A11yHost.remember(self.REMEMBER_KEY, ...)`（引擎的 persistent）。
            只写配置面是不够的：`CfgSpeechBackend` 是逐作层在 `init -190` 赋的字面量，
            **每次启动都会被重写成默认值** —— 「下次启动还记着」只能靠 persistent，
            下次由 `boot_mode()` 读回来。

            ── 为什么 `"两者"` 不再占这个环里的一档 ──────────────────────────────

            0.0.1.6 之前 F9 走的是 `["", "NVDA", "SAPI(引擎同款)", "两者"]`；维护者要求
            所有补丁的这一个键共用同一套顺序（上面五档），所以 `"两者"` 从环里退出。
            它的能力一点没少 —— 仍然可以用配置写死（`CfgSpeechBackend = "两者"`），
            只是不再占按键的档位。**这是行为变更，不是清理**，文档里逐处写明了。
            """
            stops = list(self.CfgModes)
            try:
                i = stops.index(self._mode)
            except ValueError:
                # 当前档位不在表里（`"两者"`，或名字写错时的中间态）：从「自动」的位置
                # 往后走一步，绝不因为状态陌生就卡住不动（那又会变成「按键没反应」）。
                i = 0
            # 「自动」不是一个具体后端，而是一句「按默认优先级现挑」——所以它的起点要按
            # **实际选中的那个后端**算。否则第一下按下去切到的还是同一个后端：实机就是这么
            # 表现的（开着 NVDA 时自动挑中的就是 NVDA），玩家会以为这个键没生效。
            # 四个 C# 仓库里的 `Speech.CycleIndexOf` 是同一条规则，不能一边一个说法。
            if not self._mode:
                active = (getattr(self._active, "name", "") or "")
                for k, s in enumerate(stops):
                    if s and s.lower() == active.lower():
                        i = k
                        break
            skipped = []
            for step in range(1, len(stops) + 1):
                stop = stops[(i + step) % len(stops)]
                # 已经在「自动」上时，再切到「自动」是**空转**（配置没变、声音没变），
                # 跳过它继续往前找。否则「只有一个后端可用、而它正好是最后一档」时，
                # 按一下键只会从自动跳到自动 —— 玩家会以为这个键坏了。
                # 反过来，从钉死的档位按下去时，「自动」是有效落点（= 取消钉死）。
                if not stop and not self._mode:
                    continue
                if self._stop_available(stop):
                    self.set_mode(stop)
                    try:
                        A11yHost.CfgSpeechBackend = stop
                        A11yHost.remember(self.REMEMBER_KEY, stop)
                    except Exception:
                        A11yHost.log_exc("后端选择落盘失败")
                    line = "语音后端：%s" % self.mode_display()
                    if skipped:
                        line += "（已跳过 %s）" % "、".join(skipped)
                    return line
                skipped.append("%s：%s" % (self._display(stop), self._stop_skip_why(stop)))
            # 走完一整圈都没落点 —— 只有 `CfgModes` 被改空才会发生，不该出现
            A11yHost.log("Warning: 后端轮换表里没有可用档位 %r" % (stops,))
            line = "语音后端：%s" % self.mode_display()
            if skipped:
                # 全灭时更要把「试过谁、为什么不行」念出来：这时候玩家最需要知道该去装什么
                line += "（已跳过 %s）" % "、".join(skipped)
            return line

        def boot_mode(self):
            """启动时定档：**配置里写死的 > 玩家上次按键选的 > 自动**。返回档位名。

            优先级为什么是这样排的（不是随手排的）：
              · 配置（`CfgSpeechBackend`）是维护者/高级玩家写在逐作层的**排查手段**，
                必须压得住记忆 —— 否则「我明明把它改成 SAPI 了，怎么还走 NVDA」
                会成为下一个查半天的假故障（本项目已经吃过一次
                「文档一个说法、代码一个说法」的亏）；
              · 配置为空（默认）时，玩家按键留下的选择就是**他自己的偏好**：
                每开一次游戏都要重按一遍切换键的成本极高。

            名字写错（例如记忆里存着一个已经装不回去的 `"Tolk"`）由
            `set_mode()` 的白名单核对兜住：退回自动 + 一行 Warning，不会整局哑掉。
            """
            want = (A11yHost.CfgSpeechBackend or "").strip()
            if not want:
                try:
                    want = (A11yHost.recall(self.REMEMBER_KEY, "") or "").strip()
                except Exception:
                    want = ""
                if want:
                    A11yHost.log("后端：沿用玩家上次按键选定的档位 %r" % want)
            return self.set_mode(want)

        def _display(self, name):
            """档位/后端名 -> 播报名。不认识的**照原样返回**（绝不编一个名字）。"""
            if name == "(无)":
                return "无可用后端"
            return self.ModeNames.get(name, name)

        def _stop_available(self, stop):
            """这一档**现在**能不能切过去。

            `""`（自动）永远算可用 —— 它不是一个后端，而是「让 `_pick()` 现挑」；
            挑不出来时播报里会照实说「无可用后端」，那比「把自动也跳过」诚实。
            名字没注册（例如玩家没放 `Tolk.dll`）一律算不可用 —— 这正是「跳过并说明」
            要处理的主要情况。
            """
            if not stop:
                return True
            for b in self._backends:
                if b.name.lower() == stop.lower():
                    try:
                        return bool(b.available())
                    except Exception:
                        return False
            return False

        def _stop_skip_why(self, stop):
            """被跳过的档位怎么说（**短句**，要进播报）。

            详细的可用性理由不在这里编：`set_mode()` 每次都会把 `verdict()` 那行
            （`ZDSR=争渡读屏没有运行或没有授权`）写进日志，排查看那里。
            播报里塞长句只会让玩家听不完。
            """
            for b in self._backends:
                if b.name.lower() == stop.lower():
                    return "不可用"
            return "未接入"

        def mode_display(self):
            """当前档位的**播报名**（供播报）。

            与 `mode_label()` 的分工：那个是**日志名**（用后端 `name`，方便 grep 对账），
            这个是**给耳朵听的**（`争渡读屏` 而不是 `ZDSR`）。

            「自动」档要带上它**实际挑中了谁** —— 否则玩家切到自动只听到「自动」
            两个字，还是不知道现在是谁在念（同 `mode_label()` 的理由）。
            """
            if self._mode == "两者":
                names = self._last_spoke or self._available_names()
                return "两者同时（%s）" % (
                    "+".join(self._display(n) for n in names) if names else "无可用后端")
            if self._mode:
                return self._display(self._mode)
            return "自动（%s）" % self._display(self.backend_name())

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


    # ============================================================ ZDSR（争渡读屏）后端
    class A11yZdsrBackend(object):
        r"""争渡读屏（ZDSR）的纯 ctypes 封装 —— 上游链 `Tolk -> NVDA -> ZDSR -> SAPI`
        的第三级。上游对应物是 `platform/Zdsr.cs`。

        接口依据：**官方 `ZDSRAPI.txt`**（随争渡分发，本机在
        `C:\Program Files (x86)\zdsr\zdsr\ZDSRAPI.txt` 逐字读过，GBK）。
        本类只用其中四个导出（第五个 `Braille` 允许缺失）：

            int  WINAPI InitTTS(int type, const WCHAR* channelName, BOOL bKeyDownInterrupt)
            int  WINAPI Speak(const WCHAR* text, BOOL bInterrupt)
            int  WINAPI GetSpeakState()
            void WINAPI StopSpeak()
            int  WINAPI Braille(const WCHAR* text, BOOL bFlashMessage)   # 1.0.0.5+ 才有

        导出名不是猜的：`tools/probe_dll.py` 读 PE 导出表核过本机那份 1.0.0.5，
        与上面五个一一对应（没有 `SpeakText` / `PauseSpeak` / `SetVolume` 之类）。

        ── ★ 可用性判据只有一条：`GetSpeakState()` ∈ {3, 4} ★ ────────────────

        这是本项目**用故障换来的纪律**，不是风格问题：

          · 官方文档里 `InitTTS` 只返回 `0 成功 / 1 版本不匹配` ——
            「返回 0」**仅仅表示版本对得上**，读屏没在跑时它照样返回 0（本机实测）；
          · 未授权时 `Speak()` 也返回 0（它的失败码 2 是**送达之后**才判的），
            所以拿 `Speak()` 的返回值当可用性判据，得到的正是本项目明令禁止的
            「自称可用却一句话都不出」；
          · 唯一能回答「读屏在不在、能不能收」的是 `GetSpeakState()`：
            `3 正在朗读 / 4 没有朗读` 才算可用；`1 版本不匹配`、
            `2 没有运行或没有授权`、`8 没有成功送达`、`9 独立通道尚未就绪`
            **一律算不可用**（旧版 `tools/probe_backend.py` 把 `1` 当「就绪」，
            同时把它算进可用 —— 那正是「版本不匹配的 dll 被报成工作正常」的写法，
            已按官方文档修正）。

        ── 加载次序：**注册表里的真实安装目录优先**（与 NVDA 那三条纪律不冲突）──

        官方原文：「应用程序可以直接调用争渡读屏安装目录下的相应 dll 文件……
        **建议直接读取争渡读屏安装目录下的 dll 文件，尽量不要复制到自己程序目录**」，
        理由是 dll 随读屏升级（原文另一句：「争渡读屏 26.6 dll 文件有更新……
        需要重新复制新的 dll 文件」）。

        0.0.1.6 那版只找**默认安装路径**（`C:\Program Files (x86)\zdsr\zdsr` 一类），
        于是「装在 D 盘 / 自定义目录」的玩家要自己去找 dll —— 而找不到 dll 正是
        玩家反馈里最常见的一条。0.0.1.7 改成**先问注册表**：争渡在「卸载」项里
        登记了 `InstallLocation`，读它就能覆盖任何安装位置：

            1. 注册表 `争渡读屏 → InstallLocation`（HKLM + HKCU，32/64 位两个视图）
               —— `DisplayName` 含「争渡」的本体排前面，只含 `zdsr` 的周边工具排后面
               （本机实测：`ZDSR hook control v2.1.0` 也登记了 `InstallLocation`，
               但那目录里没有 `ZDSRAPI.dll`，排后面只是省一次无谓的尝试）；
            2. 默认安装位置 `%ProgramFiles(x86)%\zdsr\zdsr`、`%ProgramFiles%\zdsr\zdsr`、
               `%ProgramFiles(x86)%\zdsr\zdcloud`；
            3. 补丁自己的目录（= 随包带的那一份兜底副本）；
            4. 游戏目录（复用 `A11yNvdaBackend._candidate_dirs()`，玩家自放的 dll 在这里）。

        `A11Y_ZDSR_DIR` 一旦设置就**只找它列出的目录**（多个用 `;` 分隔）：
        ① 排查用（把搜索范围钉死在我说的那一个目录上）；② 自检工具靠它把范围钉死，
        否则本机真实安装会参与进来，断言就变成「碰运气」而不是「机械验证」。
        仍然**一律按绝对路径加载、不写 `__file__`** —— 理由见 NVDA 后端 `_ensure`。

        ── ★ 版本不匹配（`InitTTS` 返回 1）时自动换下一份候选 ★ ─────────────

        这是「随包带一份兜底副本」能成立的前提，也是它**必须**有的配套：
        包里那份 dll 会随争渡升级而过期（官方文档自己就写着「26.6 dll 文件有更新」），
        而**安装目录里那份才是最新的** —— 所以安装目录排在前面，正常情况下轮不到包里那份；
        可玩家机器上千奇百怪（装到别的盘、注册表那条被清掉、机器上装了两份……），
        所以「这一份报版本不匹配」必须能自动往下试，而不是直接判死。

        判据**只有** `InitTTS == 1`（版本不匹配）。其余返回码表示
        「这个后端现在不可用」（读屏没跑 / 没授权），换一份 dll 没有任何意义 ——
        这一点与上游 `Zdsr.cs` 的 `EnsureInit` 逐字一致。全部候选都试完仍不匹配时，
        把「试过哪几份」写进结论（人话），让日志能直接回答「为什么这一级不在链上」。
        """

        name = "ZDSR"

        #: dll 文件名，**64 位在前**：本进程是 64 位（游戏自带运行时是
        #: `lib/py3-windows-x86_64/python.exe`），32 位那份加载必定失败
        #: （`OSError: [WinError 193]`）。列着它只是为了在「机器上只剩 32 位那一份」时
        #: 能把真实原因写进结论，而不是含糊地说一句「找不到 dll」。
        DLL_NAMES = ("ZDSRAPI_x64.dll", "ZDSRAPI.dll")

        #: 默认安装位置（官方 `ZDSRAPI.txt` 原文：「通常位于
        #: C:\Program Files(x86)\zdsr\zdsr 内」）。本机实测该目录存在且含 1.0.0.5。
        #: ⚠ 顺序是**先本体、后云版**：`zdcloud` 那份通常只有 32 位的 `ZDSRAPI.dll`
        #: （本机实测如此），排在本体后面才不会「用一份只有 32 位的目录挡住 64 位那份」。
        #: 路径由 `_default_dirs()` 用环境变量拼（非默认安装盘也能对），不写死盘符。
        DEFAULT_SUBDIRS = (
            ("ProgramFiles(x86)", ("zdsr", "zdsr")),
            ("ProgramFiles", ("zdsr", "zdsr")),
            ("ProgramFiles(x86)", ("zdsr", "zdcloud")),
        )

        #: 注册表「卸载」项的路径（HKLM / HKCU 各查一遍，32 / 64 位两个视图各查一遍）。
        UNINSTALL_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"

        #: 别名覆盖：设了就**只找它列出的目录**（多个用 `;` 分隔）。上游 `Zdsr.cs`
        #: 用的是同一个名字（`A11Y_ZDSR_DIR`），两边便于对照。
        DIR_ENV = "A11Y_ZDSR_DIR"

        #: `GetSpeakState()` 的返回值 → 人话（逐条抄官方文档，**没有 0**）。
        STATE_WHY = {
            1: "版本不匹配",
            2: "争渡读屏没有运行或没有授权",
            8: "命令没有成功送达",
            9: "独立通道尚未就绪",
        }

        #: `InitTTS` 的返回值 → 人话（官方只有两个）。
        INIT_WHY = {1: "版本不匹配"}

        #: 状态查询的缓存时长（秒）。★ 必须短于 `A11ySpeech.RETRY_INTERVAL`（3.0 秒）——
        #: `_pick()` 每 3 秒会问一轮可用性，缓存 2 秒既省掉「每念一句一次跨进程调用」，
        #: 又保证「先开游戏、后开争渡」以及「中途关掉争渡」都能在几秒内被察觉。
        STATE_TTL = 2.0

        #: 握手失败后的重试间隔（秒）。★ 必须限流：读屏没开时 `available()` 每 3 秒
        #: 就会被问一次，不限流就变成「每 3 秒一次 `InitTTS`」，而每次握手 dll 都会
        #: 往 stdout 写一行（见 `_handshake` 的副作用说明）—— 死读屏会把日志刷满。
        #: 握手**成功**后不再重复调用（官方只说它可以重复调用，没说必须）。
        INIT_RETRY_INTERVAL = 30.0

        def __init__(self):
            self._lib = None
            self._load_error = None
            self.loaded_from = None
            self._has_braille = False
            self._tried = False
            self._ok = False
            self._why = "未初始化"
            self._handshake_ok = False
            self._init_rc = None
            self._init_why = None
            self._init_tried_at = None
            self._state = None
            self._state_at = None
            self._state_error = None
            #: 候选 dll 的**绝对路径**表（按优先级，见 `_candidate_paths`）。
            self._paths = []
            #: 当前用的是第几份候选；`InitTTS` 返回 1 时往后走（见 `_select_next_candidate`）。
            self._index = 0
            #: 报过「版本不匹配」的路径 —— 只用来拼人话结论，不做判据。
            self._mismatch = []

        # ------------------------------------------------ 候选目录（0.0.1.7 新增）
        #
        # 这一段的形状是**照上游 `Zdsr.cs` 的 `BuildCandidates` / `RegistryInstallDirs`
        # 搭的**（那份 C# 已经在本机跑通、也是本条改动的参考实现），差别只有语言：
        # 那边直接 P/Invoke `advapi32`，这边用标准库 `winreg`（同样是零第三方依赖）。

        @staticmethod
        def _dirs_from_registry_entries(entries):
            r"""把注册表里的 `(DisplayName, InstallLocation)` 表变成候选目录（纯函数）。

            **本体排前面**：`DisplayName` 含「争渡」的是争渡读屏本体；只含 `zdsr` 的
            排在后面 —— 本机实测就有一条 `ZDSR hook control v2.1.0`
            （`InstallLocation = C:\Program Files\ZDSRHook`），那类周边工具目录里
            **没有** `ZDSRAPI.dll`，排后面只是省一次无谓的尝试，不是判据
            （真正的判据永远是「dll 在不在、能不能加载、判据过不过」）。

            `DisplayName` / `InstallLocation` 缺一个的条目**直接丢**（不猜路径）；
            两个字段在这里 `strip`，安装目录尾部的反斜杠与可能带的引号一并去掉
            （本机注册表里那条就是 `C:\Program Files (x86)\zdsr\zdsr\`，带尾斜杠）。
            """
            exact, loose = [], []
            for disp, loc in (entries or ()):
                try:
                    d = (disp or "").strip()
                    p = (loc or "").strip().strip('"').rstrip("\\/")
                    if not d or not p:
                        continue
                    (exact if "争渡" in d else loose).append(p)
                except Exception:
                    continue
            return exact + loose

        @staticmethod
        def _reg_value(key, winreg, name):
            """读一个字符串值；读不到（不存在 / 不是字符串 / 出错）一律 None。"""
            try:
                v, _t = winreg.QueryValueEx(key, name)
                return v if isinstance(v, str) else None
            except Exception:
                return None

        @staticmethod
        def _read_uninstall_branch(winreg, hive, view):
            """扫一个 `(hive, view)` 下的「卸载」项，返回 `(DisplayName, InstallLocation)` 表。

            单个条目出错只跳过它自己（`continue`），不让一条坏数据毁掉整次枚举。
            """
            out = []
            try:
                key = winreg.OpenKey(hive, A11yZdsrBackend.UNINSTALL_KEY, 0,
                                     winreg.KEY_READ | view)
            except Exception:
                return out
            try:
                n = 0
                while True:
                    try:
                        name = winreg.EnumKey(key, n)
                    except OSError:
                        break
                    n += 1
                    sub = None
                    try:
                        sub = winreg.OpenKey(key, name)
                        disp = A11yZdsrBackend._reg_value(sub, winreg, "DisplayName")
                        loc = A11yZdsrBackend._reg_value(sub, winreg, "InstallLocation")
                        if not disp or not loc:
                            continue
                        # ⚠ 这里必须先按名字**收窄一遍**：卸载项里有几十条与争渡毫无关系的
                        #   程序（本机实测 45 条：7-Zip、Git、Steam 上的一堆游戏……），
                        #   全收进来会让候选目录表变成几十条无谓的路径。
                        #   判据与 `Zdsr.cs` 的 `RegistryInstallDirs` 一致：
                        #   DisplayName 含「争渡」= 本体；含 `zdsr`（不分大小写）= 可能是周边工具。
                        if ("争渡" not in disp) and ("zdsr" not in disp.lower()):
                            continue
                        out.append((disp, loc))
                    except Exception:
                        continue
                    finally:
                        if sub is not None:
                            try:
                                winreg.CloseKey(sub)
                            except Exception:
                                pass
            finally:
                try:
                    winreg.CloseKey(key)
                except Exception:
                    pass
            return out

        @staticmethod
        def _registry_uninstall_entries():
            r"""读注册表「卸载」项里的 `(DisplayName, InstallLocation)`。**绝不抛异常。**

            四个位置各扫一遍（HKLM / HKCU × 默认视图 / 32 位视图 / 64 位视图）；
            本机实测（2026-10-16）争渡读屏登记在
            `HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{301A…}_is1`
            —— 也就是「HKLM + 32 位视图」那一格，**只查 64 位视图会一条都读不到**，
            而这一格正是「自动找到 dll」成不成立的关键，所以几格都查（与 `Zdsr.cs` 同）。

            `winreg` 是标准库，补丁依旧是零第三方依赖。注册表读不到（权限、
            被裁过的系统、非 Windows）只是「没有候选目录」，**不该成为故障源** ——
            所以整段包 `try`，异常一律吞掉，返回空表。
            """
            out = []
            try:
                import winreg
            except Exception:
                return out
            try:
                views = [0]
                for name in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
                    v = getattr(winreg, name, None)
                    if v:
                        views.append(v)
                for hive in (getattr(winreg, "HKEY_LOCAL_MACHINE", None),
                             getattr(winreg, "HKEY_CURRENT_USER", None)):
                    if hive is None:
                        continue
                    for view in views:
                        out.extend(A11yZdsrBackend._read_uninstall_branch(
                            winreg, hive, view))
            except Exception:
                return out
            return out

        @staticmethod
        def _registry_dirs():
            """注册表里登记的争渡安装目录（读不到就是空表，**不抛异常**）。"""
            return A11yZdsrBackend._dirs_from_registry_entries(
                A11yZdsrBackend._registry_uninstall_entries())

        @staticmethod
        def _default_dirs():
            r"""默认安装位置（`%ProgramFiles(x86)%\zdsr\zdsr` 等三条，见 `DEFAULT_SUBDIRS`）。

            ⚠ 用环境变量拼、**不写死盘符**：非默认安装盘上（系统盘不是 C:）官方那个
            `C:\Program Files (x86)` 是错的。环境变量读不到时才退回字面量 ——
            退回只是为了「至少试一次」，真正的覆盖靠上面那条注册表。
            """
            import os
            out = []
            for ev, parts in A11yZdsrBackend.DEFAULT_SUBDIRS:
                base = None
                try:
                    base = os.environ.get(ev)
                except Exception:
                    base = None
                if not base and ev == "ProgramFiles(x86)":
                    base = r"C:\Program Files (x86)"
                if not base and ev == "ProgramFiles":
                    base = r"C:\Program Files"
                if base:
                    out.append(os.path.join(base, *parts))
            return out

        @staticmethod
        def _candidate_dirs():
            r"""dll 候选目录，按优先级（理由见类文档）：

                1. 注册表里登记的实际安装目录（`争渡读屏 → InstallLocation`）
                2. 默认安装位置（`%ProgramFiles(x86)%\zdsr\zdsr` 等）
                3. 补丁自己的目录（= 随包带的那份兜底副本）
                4. 游戏目录（玩家自放的 dll）

            `A11Y_ZDSR_DIR` 一旦设置就**只找它列出的目录**（多个用 `;` 分隔）——
            钉死模式存在的理由是自检：本机真实安装参与进来的话，
            「候选顺序」这类断言就变成碰运气，而不是机械验证。
            """
            import os
            pinned = None
            try:
                pinned = os.environ.get(A11yZdsrBackend.DIR_ENV)
            except Exception:
                pinned = None
            if pinned:
                out = []
                for one in pinned.split(";"):
                    d = one.strip().strip('"')
                    if d and d not in out:
                        out.append(d)
                return out

            dirs = []
            try:
                dirs.extend(A11yZdsrBackend._registry_dirs())
            except Exception:
                pass
            try:
                dirs.extend(A11yZdsrBackend._default_dirs())
            except Exception:
                pass
            try:
                dirs.extend(A11yNvdaBackend._candidate_dirs())
            except Exception:
                pass

            out = []
            seen = set()
            for d in dirs:
                if not d:
                    continue
                key = d.rstrip("\\/").lower()      # Windows 路径大小写不敏感
                if key and key not in seen:
                    seen.add(key)
                    out.append(d)
            return out

        @staticmethod
        def _candidate_paths():
            r"""候选 dll 的**绝对路径**表，按优先级。

            ⚠ 顺序是**文件名优先**：先在所有候选目录里找 64 位那一份，
            找不到才退而找 32 位那份。按目录逐个试两个名字是不对的 ——
            那会让「某个目录里只有 32 位那份」挡住后面目录里可用的 64 位那份
            （进程是 64 位，加载 32 位 dll 必然失败：`OSError [WinError 193]`）。
            """
            import os
            out = []
            # 候选目录只算一次：`_candidate_dirs()` 会读注册表（本机实测约 17ms），
            # 每个文件名各算一遍就是白读一遍。
            dirs = A11yZdsrBackend._candidate_dirs()
            for n in A11yZdsrBackend.DLL_NAMES:
                for d in dirs:
                    p = os.path.join(d, n)
                    try:
                        if os.path.exists(p) and p not in out:
                            out.append(p)
                    except Exception:
                        continue
            return out

        # ------------------------------------------------ 加载 / 换候选 / 握手

        def _load_at(self, index):
            """加载第 `index` 份候选并绑定导出；失败返回 False，原因写进 `_load_error`。"""
            import ctypes
            path = self._paths[index]
            try:
                lib = ctypes.WinDLL(path)
                # ★ 四个必需导出逐个绑定 —— 名字写错/缺失会在这里当场抛 AttributeError，
                #   而不是等到玩家需要朗读时才炸（这条纪律的来历见 NVDA 后端的说明）。
                lib.InitTTS.argtypes = [ctypes.c_int, ctypes.c_wchar_p, ctypes.c_bool]
                lib.InitTTS.restype = ctypes.c_int
                lib.Speak.argtypes = [ctypes.c_wchar_p, ctypes.c_bool]
                lib.Speak.restype = ctypes.c_int
                lib.GetSpeakState.argtypes = []
                lib.GetSpeakState.restype = ctypes.c_int
                lib.StopSpeak.argtypes = []
                lib.StopSpeak.restype = None          # 官方：void WINAPI StopSpeak()
                # `Braille` 只有 1.0.0.5+ 才有（官方文档原文），**缺失是允许的** ——
                # 目前补丁也不用它（平台层没有盲文出口），绑定只为把「这份 dll 有没有」
                # 写进启动日志，方便排查版本过旧的机器。
                try:
                    lib.Braille.argtypes = [ctypes.c_wchar_p, ctypes.c_bool]
                    lib.Braille.restype = ctypes.c_int
                    has_braille = True
                except AttributeError:
                    has_braille = False
            except Exception as e:
                self._load_error = "%s：%s: %s" % (path, type(e).__name__, e)
                return False
            self._lib = lib
            self._index = index
            self.loaded_from = path
            self._has_braille = has_braille
            return True

        def _unload(self):
            r"""卸掉当前这份 dll（换候选时用）。

            `ctypes` **自己不会卸载**（`CDLL` 没有 `__del__`，本机 CPython 3.13 实查），
            所以这里显式 `FreeLibrary` —— 与上游 `Zdsr.cs` 的 `SelectNextCandidate` 同形。
            卸不掉也不影响正确性：整段包 `try`，失败就往下走。
            """
            lib = self._lib
            self._lib = None
            self._handshake_ok = False
            self._state = None
            self._state_at = None
            self._state_error = None
            self._ok = False
            h = getattr(lib, "_handle", None)
            if not h:
                return
            try:
                import ctypes
                ctypes.windll.kernel32.FreeLibrary(ctypes.c_void_p(h))
            except Exception:
                pass

        def _select_next_candidate(self):
            r"""换下一份候选 dll（**只在 `InitTTS` 返回 1 时**调用，理由见类文档）。

            返回 True = 后面某一份已经加载上；False = 后面没有了，
            或者后面几份都加载不上（`_load_error` 里是最后一份的失败原因）。
            """
            if not self._paths:
                return False
            nxt = self._index + 1
            if nxt >= len(self._paths):
                return False
            self._unload()
            for i in range(nxt, len(self._paths)):
                if self._load_at(i):
                    return True
            return False

        def _ensure(self):
            """加载 dll 并绑定导出。幂等。范式与理由见 `A11yNvdaBackend._ensure`。

            ⚠ 某一份加载失败**会继续试下一份**（与上游 `Zdsr.cs` 的 `ProbeFrom` 一致）：
            「包里那份是坏的 / 位宽装错了」不该挡住安装目录里那份可用的，反之亦然。
            """
            if self._lib is not None:
                return True
            if self._tried:
                return False
            self._tried = True

            self._paths = self._candidate_paths()
            if not self._paths:
                self._load_error = "未找到 ZDSRAPI_x64.dll（争渡读屏未安装？）"
                return False
            for i in range(len(self._paths)):
                if self._load_at(i):
                    return True
            return False

        def _handshake(self):
            r"""与读屏握手一次：`InitTTS(0, None, False)`。成功一次后不再重复。

            三个参数都是官方文档写死的值，逐条有理由：

              · `type=0`（读屏通道）—— 声音走玩家自己的读屏设置（语速/音色/声卡），
                这与「借读屏发声」的初衷一致；`1` 是独立通道，本项目不用。
              · `channelName=None` —— 官方原文：「type 为 0 时忽略，传入 NULL」。
                ⚠ 必须传 `None` 而不是 `""`（空串是 type=1 的写法）。
              · `bKeyDownInterrupt=False` —— 按键**不**打断。本补丁的朗读是排队语义
                （`A11ySpeech.CfgInterrupt=False`，依据见那里的长注释）：玩家按键时
                正在念的那一句必须念完，否则又变成「只读一部分 = 无障碍完整性问题」。

            ⚠ **副作用（本机实测）**：每调用一次 `InitTTS`，dll 都会往 **stdout** 写一行

                --------------InitTTS rt = N

            游戏进程里 stdout 被引擎收进 `log.txt`，所以启用 ZDSR 之后 `log.txt` 会多出
            这类行 —— 它**不是**本补丁的日志（本补丁的日志一律带 `[A11y]` 前缀），
            排查时别把它当成我们打印的东西。`INIT_RETRY_INTERVAL` 那条限流同时也是
            为了不让这种行刷屏。

            ── ★ `rc == 1`（版本不匹配）时换下一份候选 ★ ──────────────────────

            与上游 `Zdsr.cs` 的 `EnsureInit` 逐字同形：**只有 `1` 会换候选**。
            官方文档里 `InitTTS` 只有两个返回值（`0 成功 / 1 版本不匹配`），
            `0` 在上面就返回 True 了；所以走到这条判断的要么是 `1`，要么是文档之外的值 ——
            后者一律按「这个后端现在不可用」处理，换一份 dll 没有任何意义，
            直接判不可用、让 `A11ySpeech` 顺降到下一级。

            `rc == 1` 的含义是「这份 dll 与玩家机器上的争渡对不上」。两种情形都要能活：
            **包里那份太旧**（官方文档自己写着 26.6 更新过 dll）⇒ 换到安装目录那份；
            **安装目录那份是坏的/对不上**（装了两份、升级到一半）⇒ 换回包里那份。
            全部候选都试完仍不匹配时，把「试过哪几份」写进结论 ——
            `reason()` 那一行是排查「为什么这一级不在链上」的唯一线索。
            """
            import time
            if self._handshake_ok:
                return True
            now = time.monotonic()
            if self._init_tried_at is not None and \
                    (now - self._init_tried_at) < self.INIT_RETRY_INTERVAL:
                return False
            self._init_tried_at = now

            while True:
                try:
                    self._init_rc = self._lib.InitTTS(0, None, False)
                except Exception as e:
                    self._init_rc = None
                    self._init_why = "InitTTS 调用异常 %s: %s" % (type(e).__name__, e)
                    self._why = self._init_why
                    A11yHost.log("ZDSR " + self._init_why)
                    return False
                rc = self._init_rc
                if rc == 0:
                    self._handshake_ok = True
                    A11yHost.log("ZDSR InitTTS(0=读屏通道, NULL, 按键不打断) -> 0")
                    return True
                self._init_why = "InitTTS 返回 %d（%s）" % (rc, self.INIT_WHY.get(rc, "未知"))
                if rc != 1:
                    self._why = self._init_why
                    A11yHost.log("ZDSR " + self._init_why)
                    return False
                # rc == 1：这一份与读屏对不上 —— 记下来，换下一份候选再握手
                if self.loaded_from and self.loaded_from not in self._mismatch:
                    self._mismatch.append(self.loaded_from)
                if not self._select_next_candidate():
                    self._init_why = (
                        "InitTTS 返回 1（版本不匹配），%d 份候选 dll 全试过都不匹配：%s"
                        % (len(self._mismatch), "、".join(self._mismatch)))
                    self._why = self._init_why
                    A11yHost.log("ZDSR " + self._init_why)
                    return False
                A11yHost.log("ZDSR InitTTS 返回 1（版本不匹配），换下一份候选重试：%s"
                             % self.loaded_from)

        def _read_state(self):
            """问一次 `GetSpeakState()`（**判据的唯一来源**），记下时间戳与结论。

            `self._ok` 只在这里被写 —— 也就是说：除了「状态 ∈ {3,4}」，
            没有任何别的路径能让这个后端自称可用。
            """
            import time
            self._state = None
            self._state_error = None
            try:
                self._state = int(self._lib.GetSpeakState())
            except Exception as e:
                self._state_error = "%s: %s" % (type(e).__name__, e)
            self._state_at = time.monotonic()
            if self._state in (3, 4):
                self._ok = True
                self._why = "正在朗读" if self._state == 3 else "在跑（没有朗读）"
            elif self._state is None:
                self._ok = False
                self._why = "GetSpeakState 调用异常（%s）" % (self._state_error or "未知")
            else:
                self._ok = False
                self._why = self.STATE_WHY.get(self._state, "未知返回码 %d" % self._state)

        def init(self):
            if not self._ensure():
                self._why = self._load_error or "加载失败"
                return
            if self._handshake() and self._state_at is None:
                # ⚠ 只在**握手成功**之后读状态（0.0.1.7 起的护栏）：握手以
                # 「版本不匹配，候选都试完了」收场时，再读一次状态只会把那条
                # 更值钱的结论覆盖成「GetSpeakState 调用异常 / 未知返回码」——
                # 那是**换候选之后**的次生现象，不是原因。
                self._read_state()
            A11yHost.log("ZDSR: dll=%s 盲文导出=%s 结论=%s" % (
                self.loaded_from,
                "有" if self._has_braille else "无（1.0.0.1 没有这个导出）",
                self._why))

        def available(self):
            """★ 判据只有 `GetSpeakState() in (3, 4)` —— **绝不看 `Speak()` 的返回值**。

            失败一律返回 False（而不是抛异常），链上据此顺降到下一级；
            调用代价与缓存策略见 `STATE_TTL` 的说明。
            """
            import time
            if not self._ensure():
                return False
            if not self._handshake():
                # 握手失败（或还在限流窗口里）：不必再问状态，直接判不可用
                return False
            now = time.monotonic()
            if self._state_at is None or (now - self._state_at) > self.STATE_TTL:
                self._read_state()
            return self._ok

        def reason(self):
            """人话写明「为什么不可用」。

            ⚠⚠ **绝不允许抛异常。** `A11ySpeech.verdict()` 只给 `available()` 包了
            `try`，读 `reason()` 时**没有** `try`（见那边的实现）—— 所以这里一旦抛出，
            「后端结论」那一行日志就会被打断，而那一行正是排查「为什么全灭」的唯一
            线索。整段包 `try` 之外还有一条纪律：**这里不做任何跨进程调用**，
            只读缓存下来的字符串（状态由 `available()` 负责刷新）。

            `_why` 一旦被写成结论就**优先于** `_load_error` 返回：0.0.1.7 起
            「所有候选都版本不匹配」这条结论比「最后一份加载失败」更接近真相
            （那条路径换候选时会先 `_unload()`，`_lib` 因此可能是 None）。
            """
            try:
                if self._lib is None and self._why == "未初始化":
                    return self._load_error or "未初始化"
                return self._why
            except Exception as e:
                return "原因取用异常 %s" % type(e).__name__

        def speak(self, text, interrupt=True):
            """透传 `Speak(text, bInterrupt)`；`rc != 0` 抛异常。

            `interrupt` **原样透传**（上游/出口层怎么决定就怎么用）：`True` = 清空排队
            立刻打断，`False` = 等空闲时念。这里不自己改打断语义 —— 打断策略由
            `A11ySpeech.CfgInterrupt` 与 `A11yRepeat.INTERRUPT_AFTER` 决定。

            抛异常的语义与 NVDA 后端**完全一致**（`rc != 0` 就 raise），由
            `A11ySpeech.speak()` 兜住并**保持当前后端**、绝不静默降级。
            """
            if self._lib is None:
                raise RuntimeError("ZDSR dll 未加载")
            rc = self._lib.Speak(text, bool(interrupt))
            # 与 NVDA 那一路同样的直接证据：这一行回答「读屏到底收到没有」。
            # `CfgDiagLog=False` 时它不写；`said_result` 无论如何都记「调用前 / OK」。
            A11yHost.diag("ZDSR Speak rc=%d len=%d" % (rc, len(text or "")))
            if rc != 0:
                raise RuntimeError("ZDSR Speak rc=%d" % rc)

        def stop(self):
            if self._lib is not None:
                self._lib.StopSpeak()


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
