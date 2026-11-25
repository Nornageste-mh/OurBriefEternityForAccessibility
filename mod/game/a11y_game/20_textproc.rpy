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
            # ★ 1.70：文本语言 = english 时，台词引号换成**西文弯引号**。
            #   依据 `scripts/controls/localization.rpy:86-90` 的
            #   `l10n_quote_open()` / `l10n_quote_close()`：英文返回 `“` / `”`，
            #   日文与繁中仍用「」。不剥的话英文台词会念出“quote”两个词。
            #   ⚠ 只剥**双**弯引号；`‘ ’` 故意不动 —— 英文里的 ’ 同时是撇号
            #     （don’t），剥掉会变成 dont，反而破坏单词。
            (_a11y_game_re.compile(r"[“]\s*"), ""),
            (_a11y_game_re.compile(r"\s*[”]"), ""),
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
                # ★ 「未知」是**补丁自己造出来的词**（引擎原文只有「？？？」），
                #   所以要跟着界面语言翻；说话人的真名与台词正文照原样。
                return "%s: %s" % (_A11yT(self.MASKED_NAMES[who.strip()]), what)
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
    _A11Y_UNVOICED_KEY = None

    def _a11y_unvoiced_map():
        """`{角色名: True}` —— 从游戏自己的 `Character` 定义推导，不硬编码。

        惰性构建并缓存：`define ... = Character(...)` 是 `init` 阶段执行的，
        本文件是 `init -60`，那时它们还不一定都在，所以在**第一次用到时**才扫。

        ★ 1.70 修正（依据 `tmp/extracted-scripts-new/scripts/role.rpy:15-31`）：
        1.70 的 16 个角色全部写成
        `Character(lambda: l10n_text("名字"), dynamic=True, ...)`，
        `Character.__init__` 把 `name` **原样存成 callable**
        （`renpy/character.py:1051` `self.name = v("name")`），
        于是原来那句 `if not isinstance(name, str): continue` 会**一个角色都
        扫不到** —— 地图恒为空，`SpeakerIsUnvoiced` 恒 False。修法：
          · 判据仍然是 **`voice_tag`**（有 tag 才有 `audio/voice/{id}.ogg`）；
          · 名字 callable 时**调一次**取当前语言的显示名（`dynamic=True` 的
            lambda 无参数，调用安全；失败就跳过该角色）；
          · 缓存带「语言指纹」：文本/界面/主语言任一变化就重建
            （英文界面下角色名是 Elysia / Stella，键会变）。
        """
        global _A11Y_UNVOICED, _A11Y_UNVOICED_KEY
        try:
            lang_now = (getattr(_preferences, "text_language", None),
                        getattr(_preferences, "image_language", None),
                        getattr(_preferences, "language", None))
        except Exception:
            lang_now = None
        if _A11Y_UNVOICED is not None and _A11Y_UNVOICED_KEY == lang_now:
            return _A11Y_UNVOICED
        out = {}
        try:
            import store as _store
            members = list(vars(_store).items())
            n_all = len(members)
            n_char = 0
            n_dyn = 0
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
                    n_char += 1
                    name = getattr(_v, "name", None)
                    if callable(name):
                        # 1.70 的动态名字（`lambda: l10n_text(...)`）
                        n_dyn += 1
                        try:
                            name = name()
                        except Exception:
                            continue
                    if not isinstance(name, str) or not name:
                        continue
                    # 「没有 voice_tag」= 引擎不会为这个角色拼配音文件名
                    # （`config.auto_voice = "audio/voice/{id}.ogg"` 靠它）
                    if not getattr(_v, "voice_tag", None):
                        out[name] = True
                except Exception:
                    continue
            A11yHost.log("无配音角色推导: store %d 项 / 角色 %d 个 / 动态名 %d 个 /"
                         " 无配音 %d 个（依据角色定义里没有 voice_tag）"
                         % (n_all, n_char, n_dyn, len(out)))
        except Exception:
            A11yHost.log_exc("无配音角色推导失败（退回：全部按有配音处理）")
        _A11Y_UNVOICED = out
        _A11Y_UNVOICED_KEY = lang_now
        return out

    def _a11y_speaker_is_unvoiced(who):
        """契约层钩子 `SpeakerIsUnvoiced` 的实现。

        第一判据是**运行时角色对象上的 `voice_tag`**（引擎自己的事实），
        名字表只是对象拿不到时的兜底 —— 因为 1.70 的名字会随语言变，
        拿名字当唯一钥匙迟早对不上（英文界面是 Elysia / Stella）。
        """
        # ① 首选：引擎的「上一句是谁说的」就在 store 里，通常是角色对象本身
        #    （`say` 语句把它设成 who 表达式的值；见 `10_renpy_adapter.rpy`
        #    的 `_get_who_name()` 对 str/对象的两种处理）。
        try:
            import store as _store
            w = getattr(_store, "_last_say_who", None)
            if isinstance(w, str):
                w = getattr(_store, w, None)
            if w is not None and hasattr(w, "voice_tag") and hasattr(w, "name"):
                return not getattr(w, "voice_tag", None)
        except Exception:
            pass
        # ② 兜底：名字表（1.63 走的就是这条；1.70 下只在对象拿不到时用）
        try:
            if not who:
                return False
            return _a11y_unvoiced_map().get(who.strip(), False)
        except Exception:
            return False

    A11yHost.SpeakerIsUnvoiced = _a11y_speaker_is_unvoiced
