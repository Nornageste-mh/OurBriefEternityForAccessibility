# A11yFramework / Ren'Py 版 —— 逐作层（L3）入口
#
# 《永恒与星辰与日常》无障碍补丁
#
# 本文件是**唯一**逐作定制的入口 —— 对应上游 A11yFramework 的 `Plugin.cs`。
# 上游 README 的原话：「生成之后平台层就不要再改了 —— 改了就不再是冻结层。」
# 本补丁的平台层在 `game/a11y_platform/`，逐作层在 `game/a11y_game/`，
# `tools/compile_check.py` 会机械断言平台层里没有本作标识符。

# ---------------------------------------------------------------- 契约层填空（L2）
# 上游契约层要求逐作「按顺序填空，最后调一次 Validate() —— 漏填会写一行 Warning，
# 而不是静默失效」。
init -190 python:

    # 元信息
    A11yHost.GameName = "永恒与星辰与日常"
    A11yHost.GameVersion = "1.63"        # 依据：scripts/options.rpy 的 config.version 实查
    A11yHost.PatchVersion = "0.0.0.9"

    # 后端：空 = 自动（NVDA -> SAPI）。
    # ⚠ ZDSR（争渡）按维护者决定**不适配** —— 上游把它列为实验阶段
    #   （README 明写它属「没做过的验证」）。本机实测同样印证：
    #   InitTTS 返回 0，但判据 GetSpeakState 返回 2（读屏没有运行或没有授权）。
    A11yHost.CfgSpeechBackend = ""

    # 朗读诊断日志：默认关闭 —— 打开后 log.txt 会出现剧本原文，
    # 按 IP 红线**不得提交、不得外传**（只在自己排查时临时开）。
    #
    # 现场快照走按键 **Ctrl+Shift+I**（实现见 `a11y_platform/06_keymap.rpy` 的
    # `on_diag`），**不需要**打开这个开关。这里曾经写着「Ctrl+Shift+I 可随时
    # 打印现场快照（见 `_backend_info`）」，而当时**既没有那个键、也没有那个函数**
    # —— 假注释比没有注释更贵（下一次排查会先去找一个不存在的东西），
    # 所以后来把它做成了真的。
    A11yHost.CfgDiagLog = False

    # ⚠ 默认**不**打开引擎的自语音（`CfgAutoEnable = False`）。
    #
    # 第一版把它设为 True，想解决「盲人玩家不知道要按键」的冷启动问题。
    # 但实机取证表明这个做法**反而害了它**：本补丁已经覆盖了「主菜单 / 对话 /
    # 旁白 / 选项」的全部播报，于是变成**两个播报源抢麦** ——
    # 引擎的「机器朗读已启用。」、补丁的「主菜单。开始游戏，……」与
    # 「1．开始游戏」在几十毫秒内先后送出，每次都 `cancelSpeech()` 互相取消，
    # 用户听到的正是「只有音效叮叮当当，没有人说话」。
    #
    # 现在补丁是**唯一播报源**：`A11yHost.speech.speak()` 直连 NVDA，
    # 不经过引擎的 self_voicing 开关，所以不需要把它打开。
    # 玩家若手动按 `v` 打开，引擎的重复条目会被 `_drop_duplicate` 压掉。
    A11yHost.CfgAutoEnable = False

    # 重读键。本作无自定义 keymap，原生按键全部来自引擎默认，
    # 所以空着的键不会撞车（实查表见 a11y_platform/06_keymap.rpy 的文件头）。
    #
    # ⚠⚠ **这里曾经写成 `["ctrl_shift_K_r"]`，而那一版把重读键彻底弄哑了。**
    #   原因不在这一行，而在平台层的键名过滤器：它当时用
    #   「名字在 `dir(pygame.constants)` 里」当合法判据，于是把
    #   **可组合的 Ren'Py 键名**（`ctrl_shift_K_r` 这种）当成坏名字丢掉，
    #   `config.keymap["A11yReread"]` 根本没登记，而 `renpy.Keymap`
    #   照样被构造 —— 那个键于是静默变成「永不匹配」。
    #   取证文件里只留下一行看起来很像「正常自我保护」的
    #   `已丢弃引擎不认识的键名: ctrl_shift_K_r`。
    #   现在过滤器改成用**引擎自己的 `compile_event`** 试解析（见 06_keymap.rpy），
    #   两边不会再各说各话。
    #
    # 用 F5 而不是维护者其它仓库的 Backspace：引擎把 Backspace 给了文本输入
    # （`input_backspace`），而本作确实有文本输入界面
    # （`scripts/screens/screen_input.rpy` 实查）—— 不抢原生键。
    A11yHost.CfgRereadKey = ["K_F5"]


# ⚠ 下面这一段**不能**写成 `init -190 python in A11yHost:` 之后再引用 `A11yHost`：
#   `init python in <名字>` 会创建独立的命名空间 store，那个名字**不会**成为
#   默认 store 的属性，块内也引用不到自己。这条是第一次实机启动时从
#   log.txt 的 traceback 里读到的（NameError: name 'A11yHost' is not defined），
#   本补丁因此统一改成「单一默认 store + 命名前缀」。


# ---------------------------------------------------------------- 逐作层接线
# ⚠ 初始化偏移的次序是**实证**出来的（renpy/main.py 实查）：
#      L332  renpy.config.init()                  把 config.tts_function 设成默认实现
#      L412  renpy.game.script.load_script()      加载全部脚本
#      L488  node.execute_init()                  执行 init 块（按偏移从小到大）
#      L581  renpy.translation.init_translation()
#            └─ renpy/translation/__init__.py:917  renpy.display.tts.init()
#                └─ 这一步才把 config.tts_substitutions **编译**进朗读链
#
#   所以：登记清洗规则与接管 tts_function 只要在 init 阶段做就一定早于 L581。
#   而按键必须在 **init 1100 之后**（00keymap.rpy 在 1100 整体赋值 config.underlay）。
init 1300 python:

    # 0) 契约层自检（漏填写 Warning，而不是静默失效）
    A11yHost.validate()

    # 1) 接管朗读出口 + 起后端链 + 登记清洗规则（逐作规则随参数传入）
    A11yHost.rpy.start(A11yGameText.SUBS)

    # 2) 按键（必须在 init 1100 之后）
    A11yHost.keys.install()

    # 3) ★ 主动把「无配音角色」推一遍 —— **只为在启动日志里留下正向证据**。
    #
    #    推导本身是惰性的（第一次说话时才扫角色定义），那样平时看不到它成没成；
    #    而这一条直接决定「主角的台词会不会被吞」（维护者要求的调整），
    #    属于**必须能验证**的东西。这里在 init 1300 主动跑一次：
    #    此时 `define ... = Character(...)` 都已执行，扫得到。
    #    `tools/check_boot.py` 会检查这行在不在。
    try:
        _a11y_unvoiced_map()
    except Exception:
        A11yHost.log_exc("无配音角色预推导失败")

    # ⚠ 这里**不能**去改 `renpy.display.tts.old_self_voicing`。
    #
    # 第一版为了压掉引擎那句英文的「Self-voicing enabled. 」，在 init 阶段写了
    # `_a11y_tts.old_self_voicing = True`。那是**错的，而且后果很严重**：
    # 看引擎源码（renpy/display/tts.py:409-417），它是「刚从关变开」的边沿检测，
    # 预置成 True 等于告诉引擎「你已经播报过了」—— `last_raw` 于是永远不会被
    # 清空，引擎的「内容没变就不重复读」逻辑认为一切都是旧的 ⇒ **主菜单一次都
    # 不播报**。实测症状正是用户反馈的「只听到开屏那一句，之后全哑」
    #（开屏那句是本补丁直接发的，绕过了引擎的去重）。
    #
    # 正确做法：把开关**留给引擎自己**。多出来的一句英文提示可以接受，
    # 因为它换来的是整条内建播报链正常工作（这是引擎的强项，不该抢）。
