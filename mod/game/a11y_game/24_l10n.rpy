# A11yFramework / Ren'Py 版 —— 逐作层（L3）：界面语言本地化
#
# 《永恒与星辰与日常》无障碍补丁 0.0.2.0
#
# 背景（1.70 新增的界面事实，依据 `tmp/extracted-scripts-new/scripts/`）：
#   1.70 把「语言」做成了一整页设置 —— `screen setting_language` 里有四个分组
#   （主语言 / 操作界面语言 / 文本语言 / 配音语言），标题页还多了一个
#   `TitleLanguageButton` 用来循环切换主语言。也就是说**玩家可以把界面切成
#   英文 / 日文 / 繁体中文**，而补丁自己造出来的那些朗读文案原先只有中文。
#
# 本文件只做一件事：给契约层的 `A11yHost.Translate` 填一个实现 ——
# `str -> str`，把**补丁自产的界面文案**翻成当前界面语言。
#
# ⚠ 三条纪律（和平台层的 `_A11yT` 说明是同一件事，不遵守就是数据红线）：
#   ① **只翻补丁造出来的字**：查表结果、状态后缀「：当前」、兜底控件名、
#      开局播报、主菜单批量播报、选项提示、按键提示、语言页分组名。
#      对话原文、选项正文、角色真名**一律不经过这里** —— 那是作品原文，
#      原样送到朗读后端就对了（引擎自己已经按 `tl/` 翻过一次了，再翻一次
#      只会双重翻译）。
#   ② **1.63 恒等**：老版本没有 `l10n_ui`，`_preferences.language` 也没有意义，
#      于是这里一律原样返回 —— 老版本行为**零变化**。
#   ③ **翻不出来就原样**：宁可让读屏念一句中文，也不能因为查表失败而念空
#      或者崩掉（异常在 `_A11yT` 里已被兜住）。
#
# 译文来源（可核查）：
#   · 语言名 / 分组名 / tab 文字：`tmp/images-l10n/` 里解包的图片文字，
#     以及 `tl/<lang>/gui/localization/*.png` 的官方译法（维护者已肉眼核对）。
#   · 能对上游戏自带词表的，平台层第一优先走游戏的 `l10n_ui()`（catalog，
#     见 `python-packages/obe_localization_catalog.py`）；本文件的词表是
#     **兜底 + 补丁自造词**。
#   · 角色名（时语 / 星弥）在英文界面按拼音 Shiyu / Xingmi，日繁保留汉字。
#
# 初始化偏移：`-56`。必须早于 `22_uialt.rpy` 的 `-55` —— 那一层在 init 期
# 就要用本文件的 `_a11y_lang_label()` 拼语言页的位置表；而本文件本身又只
# 定义纯函数，不碰运行期状态，所以再早也没有副作用。

init -56 python:

    # ------------------------------------------------------------ 语言标识
    #: 语言名用**本名**（图片上印的就是本名，读屏念出来也应当是本名）。
    _A11Y_L10N_LANG_NAMES = {
        "schinese": "简体中文",
        "tchinese": "繁體中文",
        "japanese": "日本語",
        "english": "English",
    }

    #: 配音语言按钮上的名字（图片 `sys_data_language_bo2_cn` / `bo1_jpn` 的文字）。
    _A11Y_L10N_VOICE_NAMES = {
        "schinese": "中文",
        "japanese": "日本語",
    }

    #: 语言页四个分组的标题：中文版来自背景大图 `sys_data_language_text.png`，
    #: 其余语言来自官方 `tl/<lang>/` 同名图（维护者已核对）。
    _A11Y_L10N_GROUPS = {
        "main": {"zh": "主语言", "english": "Main Language",
                 "japanese": "メイン言語", "tchinese": "主要語言"},
        "ui": {"zh": "操作界面语言", "english": "UI Language",
               "japanese": "UI言語", "tchinese": "操作界面語言"},
        "text": {"zh": "文本语言", "english": "Subtitle Language",
                 "japanese": "文字言語", "tchinese": "文本語言"},
        "voice": {"zh": "配音语言", "english": "Voice Language",
                  "japanese": "音声言語", "tchinese": "配音語言"},
    }

    #: 标题页按钮在「定制」状态下的名字（图片 `title_language_custom_*`）。
    _A11Y_L10N_CUSTOM = "自定义"

    def _a11y_l10n_entry(en, ja, tw):
        """一条词表项：只列三种目标语言（中文原文就是键本身）。"""
        return {"english": en, "japanese": ja, "tchinese": tw}

    def _a11y_l10n_ui_language():
        """当前**界面**语言。取不到就按简体中文（= 恒等）。"""
        try:
            lang = getattr(_preferences, "image_language", None)
            if not lang:
                lang = getattr(_preferences, "language", None)
            return lang or "schinese"
        except Exception:
            return "schinese"

    def _a11y_l10n_main_language():
        """当前**主**语言（标题页语言按钮的 `LANGUAGE now:` 就是它）。"""
        try:
            return getattr(_preferences, "language", None) or "schinese"
        except Exception:
            return "schinese"

    def _a11y_l10n_is_custom():
        """是否处于「定制」状态（文本/界面/配音与主语言不一致）。

        直接问游戏自己的 `l10n_is_custom()`；老版本没有这个函数就是 False。
        """
        fn = getattr(renpy.store, "l10n_is_custom", None)
        if fn is None:
            return False
        try:
            return bool(fn())
        except Exception:
            return False

    # ------------------------------------------------------------ 语言页文案
    def _a11y_lang_label(group, lang):
        """语言页某个按钮的中文原文（真正翻译发生在播报时，见 `_a11y_translate`）。

        为什么表里存**中文**而不是当场翻好：位置表是 init 期建的，
        那时玩家还没选语言、`_preferences` 也还没定；而且播报发生在运行期，
        必须按「按下的那一刻」的界面语言念（玩家可能刚点了切换）。
        """
        g = _A11Y_L10N_GROUPS.get(group, _A11Y_L10N_GROUPS["main"])
        if group == "voice":
            name = _A11Y_L10N_VOICE_NAMES.get(lang, _A11Y_L10N_LANG_NAMES.get(lang, "?"))
        else:
            name = _A11Y_L10N_LANG_NAMES.get(lang, "?")
        return "%s：%s" % (g["zh"], name)

    def _a11y_language_switch_alt():
        """标题页语言按钮的朗读文案（逐项焦点播报用）。

        图片上写的是 `LANGUAGE now: <当前主语言>`，定制状态下写 `自定义`。
        按钮的动作是「循环切换到下一个主语言」，所以文案说「切换语言」。

        ⚠ **先翻模板，再 `%` 格式化**（实机报告 D3，唯一 FAIL）：
          词表的键是**带 `%s` 的模板原文**，直接翻格式化后的串必然查不到；
          而语言名（简体中文 / English / 日本語 …）是**语言本名**，不翻。
        """
        return _A11yT("切换语言，当前主语言：%s，回车切换") % \
            _a11y_language_current_name()

    def _a11y_language_current_name():
        """当前主语言的显示名（定制状态下是「自定义」）。

        ⚠ 「自定义」是**补丁自产的词**，要过 `_A11yT`（verifier 复测 §3.11 的残留项：
          英/日句子里曾嵌一个中文「自定义」）。四个语言名是**本名**，永远不翻。
          简体界面下 `_A11yT` 恒等 ⇒ 仍是「自定义」，1.63 也恒等。
        """
        if _a11y_l10n_is_custom():
            return _A11yT(_A11Y_L10N_CUSTOM)
        return _A11Y_L10N_LANG_NAMES.get(_a11y_l10n_main_language(), "简体中文")

    def _a11y_language_switch_item():
        """主菜单**批量播报**里那一条（比按钮 alt 短，去掉操作提示）。

        为什么不与按钮 alt 完全同句：批量播报是「一屏有哪几项」的清单，
        每项都带「回车切换」会淹没其它项；但**名字部分同源**
        （都走 `_a11y_language_current_name()`），保证两处说法一致。

        与 alt 一样的坑：**先翻模板再格式化**（词表键是带 `%s` 的模板）。
        """
        return _A11yT("切换语言：%s") % _a11y_language_current_name()

    # ------------------------------------------------------------ 词表
    # 键 = 补丁里出现的中文原文（含 `%` 模板，占位符必须原样保留）。
    # 覆盖范围 = 22_uialt 的图片表 / 位置表、31_main_menu 的按钮 alt、
    # 平台层与选项控制器的固定短语、语言页分组名。
    _A11Y_L10N_DICT = {
        # ---- 对话菜单（dialog_menu_*）
        "自动": _a11y_l10n_entry("Auto", "オート", "自動"),
        "跳过": _a11y_l10n_entry("Skip", "スキップ", "跳過"),
        "保存": _a11y_l10n_entry("Save", "セーブ", "儲存"),
        "读取": _a11y_l10n_entry("Load", "ロード", "讀取"),
        "记录": _a11y_l10n_entry("History", "履歴", "記錄"),
        "系统设置": _a11y_l10n_entry("System Settings", "システム設定", "系統設定"),
        "隐藏界面": _a11y_l10n_entry("Hide UI", "UIを隠す", "隱藏介面"),
        "重听语音": _a11y_l10n_entry("Replay Voice", "音声を再生", "重聽語音"),
        "跳回这一句": _a11y_l10n_entry("Jump to This Line", "この台詞へ戻る",
                                  "跳回這一句"),

        # ---- 通用按钮
        "确认": _a11y_l10n_entry("Confirm", "確認", "確認"),
        "取消": _a11y_l10n_entry("Cancel", "キャンセル", "取消"),
        "返回": _a11y_l10n_entry("Back", "戻る", "返回"),
        "返回标题画面": _a11y_l10n_entry("Return to Title", "タイトルへ戻る",
                                 "返回標題畫面"),
        "重置为默认设置": _a11y_l10n_entry("Reset to Defaults", "初期設定に戻す",
                                  "重置為預設設定"),
        "重置为默认声音设置": _a11y_l10n_entry("Reset Sound to Defaults",
                                   "音声設定を初期化", "重置為預設聲音設定"),
        "重置为简体中文": _a11y_l10n_entry("Reset to Simplified Chinese",
                                 "簡体字中国語に戻す", "重置為簡體中文"),

        # ---- 标题页主菜单
        "开始游戏": _a11y_l10n_entry("New Game", "はじめから", "開始遊戲"),
        "继续游戏": _a11y_l10n_entry("Continue", "つづきから", "繼續遊戲"),
        "读取游戏": _a11y_l10n_entry("Load", "ロード", "載入"),
        "特殊模式": _a11y_l10n_entry("Extra", "おまけ", "特殊模式"),
        "特殊模式（尚未解锁）": _a11y_l10n_entry("Extra (Locked)", "おまけ（未解放）",
                                       "特殊模式（尚未解鎖）"),
        "退出游戏": _a11y_l10n_entry("Quit", "終了", "退出遊戲"),
        "主菜单": _a11y_l10n_entry("Main Menu", "メインメニュー", "主選單"),
        "切换语言，当前主语言：%s，回车切换": _a11y_l10n_entry(
            "Switch language, current main language: %s, press Enter to switch",
            "言語を切り替え、現在のメイン言語：%s、Enter で切り替え",
            "切換語言，目前主要語言：%s，按 Enter 切換"),
        "切换语言：%s": _a11y_l10n_entry(
            "Switch language: %s", "言語を切り替え：%s", "切換語言：%s"),

        # ---- 特殊模式（Extra）内的界面
        "图像": _a11y_l10n_entry("Gallery", "ギャラリー", "圖像"),
        "音声": _a11y_l10n_entry("Audio", "オーディオ", "音聲"),
        "立绘": _a11y_l10n_entry("Characters", "立ち絵", "立繪"),
        "自动存档页": _a11y_l10n_entry("Auto Save Page", "オートセーブ",
                                "自動存檔頁"),
        "动态": _a11y_l10n_entry("Movies", "ムービー", "動態"),
        "片头动画": _a11y_l10n_entry("Opening Movie", "オープニング",
                                "片頭動畫"),
        "宣传动画": _a11y_l10n_entry("Promo Movie", "プロモーションムービー",
                                "宣傳動畫"),
        "暂停或继续播放": _a11y_l10n_entry("Pause or Resume", "一時停止／再開",
                                   "暫停或繼續播放"),
        "重播": _a11y_l10n_entry("Replay", "再生", "重播"),
        "隐藏所有UI": _a11y_l10n_entry("Hide All UI", "UIをすべて隠す",
                                 "隱藏所有UI"),
        "上一个": _a11y_l10n_entry("Previous", "前へ", "上一個"),
        "下一个": _a11y_l10n_entry("Next", "次へ", "下一個"),
        # 立绘页六行的分组名（`22_uialt.rpy` 的 `_STAND_GROUPS`，与
        # `scripts/screens/stand_mode.rpy` 的 data_group 顺序一致）
        "角色": _a11y_l10n_entry("Character", "キャラクター", "角色"),
        "姿势": _a11y_l10n_entry("Pose", "ポーズ", "姿勢"),
        "服装": _a11y_l10n_entry("Outfit", "衣装", "服裝"),
        "表情": _a11y_l10n_entry("Expression", "表情", "表情"),
        "符号": _a11y_l10n_entry("Symbol", "記号", "符號"),
        "背景": _a11y_l10n_entry("Background", "背景", "背景"),
        "星弥": _a11y_l10n_entry("Xingmi", "星弥", "星彌"),
        "时语": _a11y_l10n_entry("Shiyu", "時語", "時語"),

        # ---- 系统设置：基础页
        "全屏模式": _a11y_l10n_entry("Fullscreen", "フルスクリーン", "全螢幕"),
        "窗口模式": _a11y_l10n_entry("Windowed", "ウィンドウ", "視窗模式"),
        "跳过文本：全部文本": _a11y_l10n_entry("Skip: All Text", "スキップ：すべて",
                                     "跳過文字：全部文字"),
        "跳过文本：仅已读文本": _a11y_l10n_entry("Skip: Read Text Only",
                                       "スキップ：既読のみ", "跳過文字：僅已讀文字"),
        "瞬间显示已读文本：是": _a11y_l10n_entry("Instant Read Text: Yes",
                                       "既読テキスト即時表示：はい",
                                       "瞬間顯示已讀文字：是"),
        "瞬间显示已读文本：否": _a11y_l10n_entry("Instant Read Text: No",
                                       "既読テキスト即時表示：いいえ",
                                       "瞬間顯示已讀文字：否"),
        "继续自动模式": _a11y_l10n_entry("Resume Auto Mode", "オートモード再開",
                                 "繼續自動模式"),
        "停止自动模式": _a11y_l10n_entry("Stop Auto Mode", "オートモード停止",
                                 "停止自動模式"),
        "继续跳过模式": _a11y_l10n_entry("Resume Skip Mode", "スキップモード再開",
                                 "繼續跳過模式"),
        "停止跳过模式": _a11y_l10n_entry("Stop Skip Mode", "スキップモード停止",
                                 "停止跳過模式"),
        "加粗": _a11y_l10n_entry("Bold", "太字", "加粗"),
        "不加粗": _a11y_l10n_entry("Not Bold", "太字なし", "不加粗"),
        "显示描边": _a11y_l10n_entry("Outline", "縁取りあり", "顯示描邊"),
        "不显示描边": _a11y_l10n_entry("No Outline", "縁取りなし", "不顯示描邊"),

        # ---- 系统设置：计分/滑杆
        "主音量": _a11y_l10n_entry("Main Volume", "主音量", "主音量"),
        "背景音乐": _a11y_l10n_entry("Background Music", "BGM", "背景音樂"),
        "效果音量": _a11y_l10n_entry("Sound Volume", "効果音音量", "效果音量"),
        "角色语音音量": _a11y_l10n_entry("Voice Volume", "ボイス音量",
                                 "角色語音音量"),
        "音声音量": _a11y_l10n_entry("Audio Volume", "オーディオ音量",
                                 "音聲音量"),
        "文本显示速度": _a11y_l10n_entry("Text Speed", "テキスト速度",
                                 "文字顯示速度"),
        "自动模式时的文本显示速度": _a11y_l10n_entry(
            "Auto-Mode Text Speed", "オートモードのテキスト速度",
            "自動模式時的顯示速度"),
        "文本框透明度": _a11y_l10n_entry("Text Box Opacity",
                                 "テキストボックスの不透明度", "文字框透明度"),
        "背景音乐静音": _a11y_l10n_entry("Mute Background Music", "BGMを消音",
                                 "背景音樂靜音"),
        "效果音量静音": _a11y_l10n_entry("Mute Sound", "効果音を消音",
                                 "效果音量靜音"),
        "角色语音音量静音": _a11y_l10n_entry("Mute Voice", "ボイスを消音",
                                  "角色語音靜音"),
        "点击鼠标停止语音：是": _a11y_l10n_entry("Click to Stop Voice: Yes",
                                      "クリックで音声停止：はい",
                                      "點擊滑鼠停止語音：是"),
        "点击鼠标停止语音：否": _a11y_l10n_entry("Click to Stop Voice: No",
                                      "クリックで音声停止：いいえ",
                                      "點擊滑鼠停止語音：否"),
        "播放进度": _a11y_l10n_entry("Playback Progress", "再生位置", "播放進度"),

        # ---- 系统设置：角色语音（角色名在英文界面按拼音，日繁保留汉字）
        "时语：全部语音静音": _a11y_l10n_entry("Mute All Shiyu Voice",
                                     "時語：すべての音声を消音",
                                     "時語：全部語音靜音"),
        "星弥：全部语音静音": _a11y_l10n_entry("Mute All Xingmi Voice",
                                     "星弥：すべての音声を消音",
                                     "星彌：全部語音靜音"),
        "测试时语的当前语音音量": _a11y_l10n_entry("Test Shiyu Voice Volume",
                                       "時語のボイス音量をテスト",
                                       "測試時語目前的語音音量"),
        "测试星弥的当前语音音量": _a11y_l10n_entry("Test Xingmi Voice Volume",
                                       "星弥のボイス音量をテスト",
                                       "測試星彌目前的語音音量"),
        "时语 游戏语音：有": _a11y_l10n_entry("Shiyu Game Voice: On",
                                    "時語 ゲーム音声：あり", "時語 遊戲語音：有"),
        "时语 游戏语音：无": _a11y_l10n_entry("Shiyu Game Voice: Off",
                                    "時語 ゲーム音声：なし", "時語 遊戲語音：無"),
        "时语 系统语音：有": _a11y_l10n_entry("Shiyu System Voice: On",
                                    "時語 システム音声：あり",
                                    "時語 系統語音：有"),
        "时语 系统语音：无": _a11y_l10n_entry("Shiyu System Voice: Off",
                                    "時語 システム音声：なし",
                                    "時語 系統語音：無"),
        "星弥 游戏语音：有": _a11y_l10n_entry("Xingmi Game Voice: On",
                                    "星弥 ゲーム音声：あり",
                                    "星彌 遊戲語音：有"),
        "星弥 游戏语音：无": _a11y_l10n_entry("Xingmi Game Voice: Off",
                                    "星弥 ゲーム音声：なし",
                                    "星彌 遊戲語音：無"),
        "星弥 系统语音：有": _a11y_l10n_entry("Xingmi System Voice: On",
                                    "星弥 システム音声：あり",
                                    "星彌 系統語音：有"),
        "星弥 系统语音：无": _a11y_l10n_entry("Xingmi System Voice: Off",
                                    "星弥 システム音声：なし",
                                    "星彌 系統語音：無"),
        "时语语音音量": _a11y_l10n_entry("Shiyu Voice Volume", "時語のボイス音量",
                                 "時語語音音量"),
        "星弥语音音量": _a11y_l10n_entry("Xingmi Voice Volume", "星弥のボイス音量",
                                 "星彌語音音量"),

        # ---- 语言页（1.70 新增）
        "语言": _a11y_l10n_entry("Language", "言語", "語言"),
        "基础设置": _a11y_l10n_entry("Basic Settings", "基本設定", "基礎設定"),
        "声音设置": _a11y_l10n_entry("Sound Settings", "サウンド設定", "聲音設定"),
        "声音": _a11y_l10n_entry("Sound", "サウンド", "聲音"),
        "定制": _a11y_l10n_entry("Customize", "カスタム", "自訂"),
        "自定义": _a11y_l10n_entry("Custom", "カスタム", "自訂"),

        # ---- 平台层（L1）与选项控制器的固定短语
        "：当前": _a11y_l10n_entry(": current", "：現在", "：目前"),
        # 只是 `[alt] 值变化:` **日志行**里的短语（`A11yHost.said` 只写日志、
        # 不朗读，见 00_contract.rpy 的说明）；跟着翻是为了英文会话里排查日志
        # 时不出现「一半中文一半英文」。实机报告 D4：英文界面点语言页 reset
        # 后这行仍写中文 —— 前缀当时没走本地化表（`text` 本身早已过 Translate；
        # 点 reset 后界面切回简体，`text` 显示中文是正常结果）。
        "值变化": _a11y_l10n_entry("value change", "値の変化", "值變化"),
        "未命名控件（%s）": _a11y_l10n_entry("Unnamed control (%s)",
                                  "名称未設定のコントロール（%s）",
                                  "未命名控件（%s）"),
        "未知控件（%s）": _a11y_l10n_entry("Unknown control (%s)",
                                 "不明なコントロール（%s）", "未知控件（%s）"),
        "未知控件": _a11y_l10n_entry("Unknown control", "不明なコントロール",
                                 "未知控件"),
        "滚动条": _a11y_l10n_entry("Scroll bar", "スクロールバー", "捲軸"),
        "数值": _a11y_l10n_entry("Value", "値", "數值"),
        "未知": _a11y_l10n_entry("Unknown", "不明", "未知"),
        "没有可重读的内容": _a11y_l10n_entry("Nothing to repeat.",
                                  "読み直せる内容がありません。",
                                  "沒有可重讀的內容"),
        "重读：": _a11y_l10n_entry("Repeat: ", "読み直し：", "重讀："),
        "朗读界面失败。": _a11y_l10n_entry("Failed to read the screen.",
                                 "画面の読み上げに失敗しました。", "朗讀介面失敗。"),
        "已记录现场快照。": _a11y_l10n_entry("Snapshot saved.",
                                   "現場スナップショットを記録しました。",
                                   "已記錄現場快照。"),
        "%s无障碍补丁。没有可用的朗读后端，请确认读屏软件正在运行。":
            _a11y_l10n_entry(
                "%s accessibility patch. No speech backend available; "
                "please make sure your screen reader is running.",
                "%sアクセシビリティパッチ。利用可能な読み上げバックエンドが"
                "ありません。スクリーンリーダーが起動しているか確認してください。",
                "%s無障礙補丁。沒有可用的朗讀後端，請確認讀屏軟體正在執行。"),
        "%s无障碍补丁 %s 已加载。朗读后端：%s。":
            _a11y_l10n_entry(
                "%s accessibility patch %s loaded. Speech backend: %s.",
                "%sアクセシビリティパッチ %s を読み込みました。"
                "読み上げバックエンド：%s。",
                "%s無障礙補丁 %s 已載入。朗讀後端：%s。"),
        "主菜单。%s。按方向键移动，回车键确认。按 F5 重读上一句。":
            _a11y_l10n_entry(
                "Main menu. %s. Use the arrow keys to move, Enter to confirm. "
                "Press F5 to repeat the last line.",
                "メインメニュー。%s。方向キーで移動、Enter で決定。"
                "F5 で前の文を読み直します。",
                "主選單。%s。按方向鍵移動，Enter 鍵確認。按 F5 重讀上一句。"),
        "，": _a11y_l10n_entry(", ", "、", "，"),
        "本游戏": _a11y_l10n_entry("the game", "本作", "本遊戲"),
        "永恒与星辰与日常": _a11y_l10n_entry("Our Brief Eternity",
                                   "永恒与星辰与日常", "永恆與星辰與日常"),

        # ---- 选项控制器
        "选项": _a11y_l10n_entry("Choices", "選択肢", "選項"),
        "按数字键选择。": _a11y_l10n_entry("Press a number key to choose.",
                                  "数字キーで選択してください。",
                                  "按數字鍵選擇。"),
        "没有第 %d 个选项。": _a11y_l10n_entry("There is no option %d.",
                                     "%d 番目の選択肢はありません。",
                                     "沒有第 %d 個選項。"),
        "已选择 %d．%s": _a11y_l10n_entry("Selected %d. %s",
                                  "%d．%s を選択しました", "已選擇 %d．%s"),
        "这个选项无法激活。": _a11y_l10n_entry("This option cannot be activated.",
                                     "この選択肢は実行できません。",
                                     "這個選項無法啟用。"),
        "激活选项失败。": _a11y_l10n_entry("Failed to activate the option.",
                                  "選択肢の実行に失敗しました。", "啟用選項失敗。"),
        "%d．%s": _a11y_l10n_entry("%d. %s", "%d．%s", "%d．%s"),

        # ---- 22_uialt 的动态模板
        "选项 %d": _a11y_l10n_entry("Option %d", "選択肢 %d", "選項 %d"),
        "存档位 %d，%s": _a11y_l10n_entry("Save Slot %d, %s",
                                  "セーブスロット %d、%s", "存檔位 %d，%s"),
        "存档位 %d": _a11y_l10n_entry("Save Slot %d", "セーブスロット %d",
                                 "存檔位 %d"),
        "第 %d 张": _a11y_l10n_entry("Image %d", "%d 枚目", "第 %d 張"),
        "图片": _a11y_l10n_entry("Image", "画像", "圖片"),
        "空": _a11y_l10n_entry("Empty", "空き", "空"),
        "有存档": _a11y_l10n_entry("Saved", "セーブあり", "有存檔"),
        "%m月%d日 %H:%M": _a11y_l10n_entry("%m/%d %H:%M", "%m月%d日 %H:%M",
                                   "%m月%d日 %H:%M"),
        "%s %s，当前 %s": _a11y_l10n_entry("%s %s, current %s",
                                  "%s %s、現在 %s", "%s %s，目前 %s"),
    }

    # ---- 语言页分组标题（4 组 × 4 语言 = 16 条，含「配音语言」那两条）
    for _gkey in ("main", "ui", "text"):
        for _lang in ("schinese", "tchinese", "japanese", "english"):
            _zh = "%s：%s" % (_A11Y_L10N_GROUPS[_gkey]["zh"],
                             _A11Y_L10N_LANG_NAMES[_lang])
            _A11Y_L10N_DICT[_zh] = {
                "english": "%s: %s" % (_A11Y_L10N_GROUPS[_gkey]["english"],
                                       _A11Y_L10N_LANG_NAMES[_lang]),
                "japanese": "%s：%s" % (_A11Y_L10N_GROUPS[_gkey]["japanese"],
                                       _A11Y_L10N_LANG_NAMES[_lang]),
                "tchinese": "%s：%s" % (_A11Y_L10N_GROUPS[_gkey]["tchinese"],
                                       _A11Y_L10N_LANG_NAMES[_lang]),
            }
    for _vlang in ("schinese", "japanese"):
        _zh = "%s：%s" % (_A11Y_L10N_GROUPS["voice"]["zh"],
                          _A11Y_L10N_VOICE_NAMES[_vlang])
        _A11Y_L10N_DICT[_zh] = {
            "english": "%s: %s" % (_A11Y_L10N_GROUPS["voice"]["english"],
                                   _A11Y_L10N_VOICE_NAMES[_vlang]),
            "japanese": "%s：%s" % (_A11Y_L10N_GROUPS["voice"]["japanese"],
                                   _A11Y_L10N_VOICE_NAMES[_vlang]),
            "tchinese": "%s：%s" % (_A11Y_L10N_GROUPS["voice"]["tchinese"],
                                   _A11Y_L10N_VOICE_NAMES[_vlang]),
        }

    # ---- 数字后缀类（存档页 / CG 页 / 片尾动画）——逐个展开，别用正则猜
    for _n in range(1, 11):
        _A11Y_L10N_DICT["存档页 %d" % _n] = _a11y_l10n_entry(
            "Save Page %d" % _n, "セーブページ%d" % _n, "存檔頁 %d" % _n)
        _A11Y_L10N_DICT["CG 第 %d 页" % _n] = _a11y_l10n_entry(
            "CG Page %d" % _n, "CG %d ページ" % _n, "CG 第 %d 頁" % _n)
    for _n in range(1, 5):
        _A11Y_L10N_DICT["片尾动画 %d" % _n] = _a11y_l10n_entry(
            "Ending Movie %d" % _n, "エンディング %d" % _n, "片尾動畫 %d" % _n)

    # ------------------------------------------------------------ 翻译入口
    def _a11y_translate(text):
        """补丁自产文案 -> 当前界面语言。契约层 `_A11yT` 的唯一实现方。

        顺序（都要能解释）：
          ① 界面语言是简体中文 ⇒ **原样返回**（绝大多数玩家的路径，也是 1.63 的路径）。
          ② 游戏自带的 `l10n_ui()`（1.70 才有）：能翻就翻 —— 好处是与游戏
             自己界面上的用词完全一致（例如 `自动` -> `Auto`）。只接受
             「确实变了」的结果，避免它把未知串原样吐回来时干扰 ③。
          ③ 补丁自己的词表：补丁自造的短语（「：当前」「未命名控件（%s）」、
             语言页分组名……）游戏词表里没有，只能自己来。
          ④ 都不命中 ⇒ 原样（宁可念中文，不可念空）。
        """
        if not text:
            return text
        lang = _a11y_l10n_ui_language()
        if lang == "schinese":
            return text
        fn = getattr(renpy.store, "l10n_ui", None)
        if fn is not None:
            try:
                out = fn(text)
            except Exception:
                out = None
            if out and out != text:
                return out
        entry = _A11Y_L10N_DICT.get(text)
        if entry:
            out = entry.get(lang)
            if out:
                return out
        return text

    A11yHost.Translate = _a11y_translate

    # 正向证据：日志里能看出「本地化层装上了、词表多大、当前界面语言是什么」。
    # 不打印词表内容（词表本身没有 IP 风险，但保持日志简洁）。
    A11yHost.log("本地化层已装配: 词表 %d 条，界面语言=%s，游戏词表 l10n_ui=%s"
                 % (len(_A11Y_L10N_DICT), _a11y_l10n_ui_language(),
                    "有" if getattr(renpy.store, "l10n_ui", None) else "无"))
