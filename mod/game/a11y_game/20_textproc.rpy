# A11yFramework / Ren'Py 版 —— 逐作层（L3）
#
# 《永恒与星辰与日常》无障碍补丁 · 文本清洗（TextProc）
#
# 上游流水线把「文本清洗」列为逐作**必须重查**的两件事之一（各作要处理的类别
# 完全不同）：平台层先给一批**通用排版噪声**（见 `10_renpy_adapter.rpy` 的
# `GENERIC_SUBS`），本文件只补**本作专属**的那几条 —— 与上游 `TextProc.cs` 一致。
#
# 本作实测类别与数量（`tools/script_stats2.py`，只统计不输出原文）：
#
#   连续省略号 1460 处 ← 平台层通用规则已覆盖（本作最主要的排版噪声）
#   全角引号「」 112 处 ← 本文件补（见 SUBS）
#   遮蔽问号？？？  3 处 ← 平台层规范成三连；说话人名里的换成「未知」（见下）
#   {} 插值 2 处         全角括号【】 1 处
#
# 结论：本作行内富文本**极其干净**（无 ruby 旁注、无抹除符号、无行内注释），
# 逐作规则的复杂度远低于上游三作。

init -60 python:

    import re as _a11y_game_re

    class A11yGameText(object):
        """本作的清洗规则与说话人处理。"""

        # ------------------------------------------------------------ 说话人
        #: 本作的遮蔽名。依据 `scripts/roles/role.rpy` 实查：`temp_` 与 `temp_2`
        #: 的 name 都是 "？？？"，分别是还没揭示身份的时语 / 星弥（两者的 image
        #: 与 voice_tag 不同）。读屏念「问号问号问号」没有意义，换成「未知」——
        #: 与上游《钟塔》对 `【 ?  ? 】` 的处理同一个判断。
        #:
        #: ⚠ 同文件还实查到三个**合说角色**：`syxm_`「时语&星弥」、`lxcxm_`
        #: 「林小凑&星弥」、`lxcsy_`「林小凑&时语」。名字里的 `&` 在部分读屏里会
        #: 读成「and」或直接吞掉，而 `speech_plan` 目前原样使用 `who` ——
        #: **已知缺口**，不是已修复。
        MASKED_NAMES = {
            "？？？": "未知",
            "???": "未知",
            "??": "未知",
            "?": "未知",
        }

        # ------------------------------------------------------------ 清洗规则
        #: 追加到引擎的 `config.tts_substitutions`。
        #: 每一条都必须来自**实查**，不许凭感觉加（上游 §7 铁律 3）。
        SUBS = [
            # 依据：`scripts/roles/role.rpy` 的 `Character(...)` 实参（15 个角色里
            # 14 个带这对前后缀）—— 台词朗读串于是变成 `林小凑: 「 台词内容 」`
            # 这种嵌套引号。读屏念引号既啰嗦又打乱语流，而说话人信息已由「谁:」承担。
            (_a11y_game_re.compile(r"[「『]\s*"), ""),
            (_a11y_game_re.compile(r"\s*[」』]"), ""),
        ]

        # ------------------------------------------------------------ 朗读计划
        #: 挂到契约层，由平台层的 tts 出口调用（签名 `(who, what) -> str`）。
        def speech_plan(self, who, what):
            """决定「这一句念什么」。

            本作是**全语音**作品（`scripts/options.rpy:50` `config.has_voice = True`，
            `:295` `config.auto_voice = "audio/voice/{id}.ogg"`，`audio.rpa` 实测
            含 2094 个配音文件），所以：

            - **配音在播时**，引擎自己就不朗读整条（`renpy/display/tts.py:419-421`
              见到 `config.tts_voice_channels` 里的通道在播就 `return`），
              我们不必也不该去重复念一遍台词；
            - 这里只做一件引擎不做的事：**把遮蔽说话人换成可理解的词**
              （引擎会把「？？？」原样念出来，读屏只知道那是三个问号）；
            - 无配音的行（旁白/独白 2451 行，占剧情文本 43%）引擎照常朗读全文，
              我们**不做任何削减** —— 那是叙事内容，不能漏。
            """
            if who and who.strip() in self.MASKED_NAMES:
                return "%s: %s" % (self.MASKED_NAMES[who.strip()], what)
            return "%s: %s" % (who, what) if who else what

    A11yGameText = A11yGameText()

    # 把朗读计划挂到契约层（跨层只走 A11yHost 的具名槽位）
    A11yHost.SpeechPlan = A11yGameText.speech_plan

    # ---------------------------------------------------------------- 无配音角色
    #
    # ★ 维护者原话：「主角是没有配音的，它也需要读屏支持」——
    #   这是**按作品事实做的调整**，不是修 bug。
    #
    # 问题出在哪：`preferences.voice_sustain = True`（`options.rpy:279`）
    # 让上一句的配音在下一句开始时**还在播**，于是「本来没配音的主角」
    # 被运行时判据（配音通道在不在播）误判成有配音 ⇒ 平台层只念名字，
    # **主角的台词正文被吞掉**。
    #
    # 判据必须是作品事实，所以这里从**游戏自己的角色定义**里推导，
    # 不硬编码任何名字（名字改了、加了新角色，这段会自动跟上）：
    #
    #   `scripts/roles/role.rpy` 实查：有配音的角色**都带 `voice_tag`**
    #   （时语 `shiyu` / 星弥 `xingmi` / 房东 `fangdong` / 摊主 `suyouqing`…），
    #   而主角「林小凑」`lxc_` 与同事A/B/C、服务员、人事主管**都没有** ——
    #   引擎的 `config.auto_voice = "audio/voice/{id}.ogg"`（`options.rpy:295`）
    #   正是靠 `voice_tag` 拼文件名，没有 tag 就没有配音文件。
    #
    # ⚠ 注意**不要**按名字子串判断：合说角色 `lxcxm_`「林小凑&星弥」与
    #   `lxcsy_`「林小凑&时语」**带** `voice_tag`（那两句是有人声的），
    #   所以必须按**完整名精确匹配**，否则会把合说句也当成无配音、
    #   在配音之上再念一遍正文。
    _A11Y_UNVOICED = None

    def _a11y_unvoiced_map():
        """`{角色名: True}` —— 从游戏自己的 `Character` 定义推导，不硬编码。

        惰性构建并缓存：`define ... = Character(...)` 是 `init` 阶段执行的，
        本文件是 `init -60`，那时它们还不一定都在，所以在**第一次用到时**才扫。
        """
        global _A11Y_UNVOICED
        if _A11Y_UNVOICED is not None:
            return _A11Y_UNVOICED
        out = {}
        try:
            import store as _store
            members = list(vars(_store).items())
            n_all = len(members)
            n_char = 0
            for _k, _v in members:
                try:
                    # ⚠ 用**鸭子类型**识别角色，不要按类名判断：
                    #   `Character(...)` 返回的是 `ADVCharacter` / `NVLCharacter`
                    #   这类子类，写 `type(v).__name__ == "Character"` 会一个都扫不到
                    #   （实测就是这样 —— 启动日志里当时是「推导: 0 个」）。
                    cls = type(_v)
                    cname = cls.__name__
                    if cname not in ("ADVCharacter", "NVLCharacter", "Character"):
                        # 兜底：有些包装类名不同，但一定带 name/voice_tag 两个属性
                        if not (hasattr(_v, "name") and hasattr(_v, "voice_tag")):
                            continue
                        if callable(getattr(_v, "name", None)):
                            continue
                    n_char += 1
                    name = getattr(_v, "name", None)
                    if not isinstance(name, str) or not name:
                        continue
                    # 「没有 voice_tag」= 引擎不会为这个角色拼配音文件名
                    # （`config.auto_voice = "audio/voice/{id}.ogg"` 靠它）
                    if not getattr(_v, "voice_tag", None):
                        out[name] = True
                except Exception:
                    continue
            A11yHost.log("无配音角色推导: store %d 项 / 角色 %d 个 / 无配音 %d 个"
                         "（依据角色定义里没有 voice_tag）"
                         % (n_all, n_char, len(out)))
        except Exception:
            A11yHost.log_exc("无配音角色推导失败（退回：全部按有配音处理）")
        _A11Y_UNVOICED = out
        return out

    def _a11y_speaker_is_unvoiced(who):
        """契约层钩子 `SpeakerIsUnvoiced` 的实现。"""
        try:
            if not who:
                return False
            return _a11y_unvoiced_map().get(who.strip(), False)
        except Exception:
            return False

    A11yHost.SpeakerIsUnvoiced = _a11y_speaker_is_unvoiced
