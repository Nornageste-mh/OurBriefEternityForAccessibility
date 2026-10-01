# A11yFramework / Ren'Py 版 —— 逐作层（L3）
#
# 《永恒与星辰与日常》无障碍补丁 · 控件朗读文本表
#
# ── 这份表是干什么的 ────────────────────────────────────────────────────────
#
# 本作控件几乎全是 `imagebutton`：**字印在图上，代码里没有字**。
# 平台层（`a11y_platform/08_uialt.rpy`）在**播报那一刻**拿控件身份来查这里的
# 三张表（**拉模型**）：界面限定键 -> 图片路径 -> 屏幕坐标 -> 本文件末尾的
# 钩子 `UiAltFor`。查出什么就念什么，**不往控件里写任何东西** —— 画面不动。
#
# ── 文案来源纪律：看图确认，不许从文件名猜 ──────────────────────────────────
#
# 上游红线：别名表每一条都要有依据。本文件每条的中文都对应一张**看过的图**：
#
#   · 快捷菜单（`scripts/screens/screen_quick_menu.rpy`，7 个控件）
#     图上印的是英文（AUTO / SKIP / SAVE / LOAD / HISTORY / SYSTEM）＋ 两个纯图标
#     （hide = 划掉的眼睛、revoice = 喇叭），所以中文按「该按钮实际做的事」定名，
#     并**与主菜单同名项保持一致**（SYSTEM 与主菜单的「系统设置」是同一个界面）。
#     图片位置：`gui/custom2/dialog/dialog_menu_*_normal.png`
#   · 确认弹窗（`scripts/screens/screen_confirm.rpy`，2 个控件）：图上**本来就是
#     中文**（确认 / 取消），位置 `gui/custom2/small/miniwindow_bo_{sure,cancel}_normal.png`。
#   · 重听语音（`scripts/screens/screen_say.rpy:175-184`）：只在**本行有配音**时
#     才出现（`if _get_voice_info().filename is not None`），图是喇叭图标，动作是
#     `PlayCharacterVoice(...)` —— 重播这一句的配音。
#
# 设置界面整屏走下面的**位置表**（行标签本身也是图片，逐张看过）；存读档 / 音声 /
# 立绘 / 画廊里**循环生成**的控件走钩子。覆盖面由 `tools/coverage_uialt.py` 机械
# 核对，平台层的 `_report` 把「认不出来的控件」写进 `log.txt` 当**安全网**
# （覆盖率工具扫不到的动态控件就是它报出来的）。补齐时只改本文件，平台层不动。

init -55 python:

    #: `[选项]` 证据日志的去重标记（`(名次, 总数, 文案)`）。
    #: 焦点跟踪每次焦点变化都会调用钩子，不去重会把日志刷满。
    _A11Y_CHOICE_SAID_LAST = [None]

    #: 图片路径 -> 朗读文案。键可以写全路径 / 文件名 / 去后缀的词干。
    A11yHost.UiAltByImage = {
        # ---- 游戏内快捷菜单（对话界面常驻）----
        "dialog_menu_auto_normal.png": "自动",
        "dialog_menu_skip_normal.png": "跳过",
        "dialog_menu_save_normal.png": "保存",
        "dialog_menu_load_normal.png": "读取",
        "dialog_menu_log_normal.png": "记录",
        "dialog_menu_sys_normal.png": "系统设置",
        "dialog_menu_hide_normal.png": "隐藏界面",

        # ---- 对话中的重听语音（仅本行有配音时出现）----
        "dialog_menu_revoice_normal.png": "重听语音",

        # ---- 历史记录里每一条右侧的两个按钮 ----
        # 依据 `scripts/controls/VirtualViewport.rpy:563-590` 实查：
        #   `log_data_bo_jumpback_normal.png` -> ImageButton(clicked=Confirm(
        #        "确定要跳转到该处吗？", yes=RollbackToIdentifier(...)))  ⇒ 跳回这一句
        #   `dialog_menu_revoice_normal.png`（同对话界面那张喇叭图）      ⇒ 重听语音（已在上面）
        # ⚠ 这两个按钮**不是 screen 语句写的**，而是在 `VirtualViewport` 里用 Python
        #   动态建出来的 —— `tools/coverage_uialt.py` 扫不到它们，是**兜底播报**把
        #   jumpback 报了出来（「兜底当探针」：沉默不会告诉你漏了什么，它会）。
        #   复盘见 CHANGELOG 0.0.0.4。
        "log_data_bo_jumpback_normal.png": "跳回这一句",

        # ---- 确认弹窗 ----
        "miniwindow_bo_sure_normal.png": "确认",
        "miniwindow_bo_cancel_normal.png": "取消",

        # ---- 各界面共用的底部按钮（一图一义，放图片表最省事）----
        # 文案就是图上的中文（返回 BACK / 标题 TITLE / 重置 RESET）。
        "general_menu_back_normal.png": "返回",
        "general_menu_title_normal.png": "返回标题画面",
        "sys_menu_reset_normal.png": "重置为默认设置",

        # ---- 主菜单六项 ----
        # 文案依据：主菜单按钮图（`title_menu_main_*_normal.png`）逐张看过，图上
        #   中文（START 开始游戏 / CONTINUE 继续游戏 / LOAD 读取游戏 / SYSTEM
        #   系统设置 / EXTRA 特殊模式 / EXIT 退出游戏）与下面一致。
        # ⚠ 与 `31_main_menu.rpy` 界面覆盖里的 `alt "开始游戏"` **并存**：两条通路
        #   互不依赖（那条给引擎自己的播报链，这条给平台层查表），值必须逐字一致。
        #   0.0.2 之前只靠前者，主菜单整片哑掉，实机日志是
        #   `[alt] 焦点=ImageButton alt='' 引擎队列=0`（复盘见 CHANGELOG 0.0.0.2）。
        "title_menu_main_start_normal.png": "开始游戏",
        "title_menu_main_continue_normal.png": "继续游戏",
        "title_menu_main_load_normal.png": "读取游戏",
        "title_menu_main_system_normal.png": "系统设置",
        "title_menu_main_extra_normal.png": "特殊模式",
        "title_menu_main_exit_normal.png": "退出游戏",

        # ---- 主菜单里「特殊模式」展开后的四个入口 ----
        # （`screen_main_menu.rpy:176-205`，属于同一个 extra 子菜单）
        "title_menu_extra_gallery_normal.png": "图像",
        "title_menu_extra_audio_normal.png": "音声",
        "title_menu_extra_stand_normal.png": "立绘",
        "title_menu_extra_back_normal.png": "返回",

        # ---- 存读档：存档页签（一张图一个页号，天然唯一）----
        # ⚠ 页签图 `general_menu_page_N_normal.png` **被两个界面共用**：存读档里是
        #   「存档页 N」、画廊里是「CG 第 N 页」，所以画廊那一边必须用**界面限定键**
        #   `("gallery", 图片)` 覆盖 —— 平台层先查限定键、再查通用键
        #   （见 08_uialt.rpy 的 `_table_text`）。
        "sl_menu_page_auto_normal.png": "自动存档页",

        # ---- 立绘/音声/图像三个子界面之间的互相跳转（图上是中文）----
        #   图上是「立绘 STANDMODE / 音声 AUDIO DRAMA / 图像 GALLERY」，
        #   所以读中文那半，与画面一致。
        "extra_menu_stand_normal.png": "立绘",
        "extra_menu_audio_normal.png": "音声",
        "extra_menu_gallery_normal.png": "图像",

        # ---- 画廊：动态（影片）页签 ----
        #   图是三角形播放图标，没有文字，所以按它实际做的事定名。
        "extra_gallery_menu_page_mov_normal.png": "动态",
        "extra_gallery_menu_page_mov_confim.png": "动态",

        # ---- 画廊：六部影片 ----
        #   放**图片表**而不是钩子：影片按钮的 idle 是
        #   `Fixed(Frame(缩略图), Transform(角标))`，平台层递归挖出来的文件名可能
        #   是缩略图也可能是角标，而图片表会**把所有键都试一遍**，最稳。
        #   名字依据 `screen_gallery.rpy:229-236` 的 `movie_items`：缩略图文件名是
        #   OP/PV/ED01..ED04，影片本体是 `images/op.webm` / `pv.webm` / `ed1..4.webm`
        #   —— 从游戏自己的资源命名读出来的，不是猜的。
        "extra_gallery_moviethumbnail_OP.png": "片头动画",
        "extra_gallery_moviethumbnail_PV.png": "宣传动画",
        "extra_gallery_moviethumbnail_ED01.png": "片尾动画 1",
        "extra_gallery_moviethumbnail_ED02.png": "片尾动画 2",
        "extra_gallery_moviethumbnail_ED03.png": "片尾动画 3",
        "extra_gallery_moviethumbnail_ED04.png": "片尾动画 4",

        # ---- 音声（ASMR）播放器 ----
        #   暂停键的 idle 是「‖」、selected 是「▶」，也就是同一个键在
        #   播放/暂停之间切换，所以名字要把两种作用都说出来。
        "extra_audio_player_bo_pause_normal.png": "暂停或继续播放",
        "extra_audio_player_bo_replay_normal.png": "重播",

        # ---- 立绘页 ----
        "stand_menu_hide_normal.png": "隐藏所有UI",
        # ⚠ 这两个是「立绘数据」每一行的小三角。写进图片表只能说方向（值在旁边的
        #   text 里）；而平台层**图片表先于钩子**，所以文件末尾钩子里那段「报当前
        #   值」实际到不了 —— **已知缺口**，见那里的说明。
        "stand_data_bo_left_normal.png": "上一个",
        "stand_data_bo_right_normal.png": "下一个",

        # ---- 通用页签：默认按「存档页」解释 ----
        #   这是**兜底**，因为存读档那两个界面的界面名可能是 `file_slots`
        #   （`screen save` / `screen load` 里都是 `use file_slots(...)`），
        #   写死某一个名字反而会漏。画廊那边由下面的限定键覆盖。
        "general_menu_page_1_normal.png": "存档页 1",
        "general_menu_page_2_normal.png": "存档页 2",
        "general_menu_page_3_normal.png": "存档页 3",
        "general_menu_page_4_normal.png": "存档页 4",
        "general_menu_page_5_normal.png": "存档页 5",
        "general_menu_page_6_normal.png": "存档页 6",
        "general_menu_page_7_normal.png": "存档页 7",
        "general_menu_page_8_normal.png": "存档页 8",
        "general_menu_page_9_normal.png": "存档页 9",
        "general_menu_page_10_normal.png": "存档页 10",

        # ---- 画廊里的同一批页签：**限定到界面**，改叫 CG 页 ----
        ("gallery", "general_menu_page_1_normal.png"): "CG 第 1 页",
        ("gallery", "general_menu_page_2_normal.png"): "CG 第 2 页",
        ("gallery", "general_menu_page_3_normal.png"): "CG 第 3 页",
        ("gallery", "general_menu_page_4_normal.png"): "CG 第 4 页",
        ("gallery", "general_menu_page_5_normal.png"): "CG 第 5 页",
        ("gallery", "general_menu_page_6_normal.png"): "CG 第 6 页",
        ("gallery", "general_menu_page_7_normal.png"): "CG 第 7 页",
        ("gallery", "general_menu_page_8_normal.png"): "CG 第 8 页",
        ("gallery", "general_menu_page_9_normal.png"): "CG 第 9 页",
        ("gallery", "general_menu_page_10_normal.png"): "CG 第 10 页",
    }

    #: 滑杆（Bar）文案。键 = 引擎的 preference 名（`Preference("...")` 里的那个串）。
    #: ⚠ 只写**引擎/本作确实在用**的键名。依据：`renpy/common/00preferences.rpy` 的
    #:   标准名，以及本作设置界面源码（`screen_preferences.rpy`）里逐行读出来的
    #:   `Preference("...")`。猜错键名不会报错，只会让滑杆退化成「数值 60%」——
    #:   那种错很难发现，所以宁缺勿滥。
    A11yHost.UiAltByPreference = {
        # 声音设置页（setting_sound）—— 源码逐行核对
        "main volume": "主音量",
        "music volume": "背景音乐",
        "sound volume": "效果音量",
        "voice volume": "角色语音音量",
        # 基础设置页（preferences）里的三个自定义变量滑杆
        "persistent.normal_text_cps": "文本显示速度",
        "persistent.afm_text_cps": "自动模式时的文本显示速度",
        "persistent.text_box_opacity": "文本框透明度",
    }

    #: ★ **位置表**：`{("界面名", x, y): "文案"}`。
    #:
    #: 为什么需要它：本作设置界面里**同一张图出现多次** ——
    #: `sys_data_sound_mute_normal.png` × 5（音乐/音效/语音/时语/星弥）、
    #: `sys_data_sound_char_have/not_normal.png` 各 × 3、
    #: `sys_data_sound_char_test_normal.png` × 2，只按图片路径分不出谁是谁。
    #: 而它们的 `xpos/ypos` 是源码里的字面常量（下表每个坐标都能在
    #: `screen_preferences.rpy` 里查到），且与引擎焦点表一致（`focus.py:88-96`）。
    #:
    #: ── 文案来源（**每一行都看图确认过**）────────────────────────────────
    #:
    #: 设置界面连**行标签本身都是图片**（`sys_data_basic_text.png` /
    #: `sys_data_sound_text.png`，由 `image ...` 语句贴上去），所以中文不是从
    #: 文件名猜的，而是把这两张标签图与每张按钮图都调出来看过：
    #:
    #:   基础页行标签：显示模式 / 字体样式 / 分辨率 / 文本显示速度 /
    #:                 跳过文本 / 自动模式时 文本显示速度 / 瞬间显示已读文本 /
    #:                 选项后…… / 文本框透明度
    #:   声音页行标签：主音量 / 背景音乐 / 效果音量 / 角色语音音量 /
    #:                 点击鼠标停止语音 / 角色语音设置（时语、星弥）/
    #:                 游戏语音 / 系统语音
    #:
    #: 按钮图上的字直接用（全屏模式 / 是 / 否 / 有 / 无 / 加粗 / 继续自动模式 /
    #: 返回 / 重置 / 声音 …）；只有「是 / 否 / 有 / 无」这类**单独一个字分不出
    #: 属于哪一行**的按钮，才把行标签拼在前面（「瞬间显示已读文本：是」）——
    #: 行标签确实在画面上，只是它是一张图，拼起来是等价呈现，不是编造。
    #:
    #: 界面名取自 `screen preferences()` / `screen setting_sound()`
    #: （引擎焦点表的 `Focus.screen.screen_name[0]`，见 08_uialt.rpy）。
    A11yHost.UiAltByPos = {
        # ════════════════ 基础设置（preferences）════════════════════════
        ("preferences", 327, 271): "全屏模式",          # bo1_fullscreen
        ("preferences", 789, 271): "窗口模式",          # bo1_windowed
        ("preferences", 327, 464): "2560×1440",         # bo2_1440p
        ("preferences", 778, 464): "1920×1080",         # bo2_1080p
        ("preferences", 327, 567): "1280×720",          # bo2_720p
        ("preferences", 516, 695): "跳过文本：全部文本",       # bo3_allltext
        ("preferences", 857, 695): "跳过文本：仅已读文本",     # bo3_readtext
        ("preferences", 711, 828): "瞬间显示已读文本：是",     # bo4_yes
        ("preferences", 959, 828): "瞬间显示已读文本：否",     # bo4_no
        ("preferences", 329, 1017): "继续自动模式",      # 3.png
        ("preferences", 778, 1016): "停止自动模式",      # bo5_stopauto
        ("preferences", 328, 1121): "继续跳过模式",      # bo5_stillauto
        ("preferences", 778, 1119): "停止跳过模式",      # bo5_stopskip
        ("preferences", 1375, 271): "加粗",             # bo6_bold
        ("preferences", 1838, 271): "不加粗",           # bo6_unbold
        ("preferences", 1375, 375): "显示描边",          # bo6_stroke
        ("preferences", 1838, 375): "不显示描边",        # bo6_unstroke
        # 底部与页签
        ("preferences", 2053, 70): "声音设置",           # 切到声音页
        ("preferences", 2098, 1261): "返回",            # general_menu_back
        ("preferences", 1741, 1261): "返回标题画面",      # general_menu_title
        ("preferences", 145, 1261): "重置为默认设置",      # sys_menu_reset
        # 滑杆（名字取不到时用位置兜底；三个都是自定义变量滑杆）
        ("preferences", 1458, 585): "文本显示速度",
        ("preferences", 1458, 842): "自动模式时的文本显示速度",
        ("preferences", 1458, 1102): "文本框透明度",

        # ════════════════ 声音设置（setting_sound）══════════════════════
        ("setting_sound", 403, 279): "主音量",           # bar
        ("setting_sound", 403, 428): "背景音乐",         # bar
        ("setting_sound", 1031, 358): "背景音乐静音",     # mute（图复用）
        ("setting_sound", 403, 574): "效果音量",         # bar
        ("setting_sound", 1031, 505): "效果音量静音",     # mute（图复用）
        ("setting_sound", 1453, 282): "角色语音音量",     # bar
        ("setting_sound", 2078, 214): "角色语音音量静音",  # mute（图复用）
        ("setting_sound", 1373, 428): "点击鼠标停止语音：是",   # sound_yes
        ("setting_sound", 1824, 428): "点击鼠标停止语音：否",   # sound_no
        ("setting_sound", 954, 865): "时语：全部语音静音",      # 图复用
        ("setting_sound", 1975, 865): "星弥：全部语音静音",     # 图复用
        ("setting_sound", 760, 930): "测试时语的当前语音音量",   # char_test（图复用）
        ("setting_sound", 1775, 930): "测试星弥的当前语音音量",  # char_test（图复用）
        ("setting_sound", 756, 1006): "时语 游戏语音：有",      # char_have（图复用）
        ("setting_sound", 963, 1006): "时语 游戏语音：无",      # char_not（图复用）
        ("setting_sound", 756, 1077): "时语 系统语音：有",      # char_have（图复用）
        ("setting_sound", 963, 1077): "时语 系统语音：无",      # char_not（图复用）
        ("setting_sound", 1771, 1006): "星弥 游戏语音：有",     # char_have（图复用）
        ("setting_sound", 1979, 1006): "星弥 游戏语音：无",     # char_not（图复用）
        ("setting_sound", 1771, 1077): "星弥 系统语音：有",     # char_have（图复用）
        ("setting_sound", 1979, 1077): "星弥 系统语音：无",     # char_not（图复用）
        # 底部与页签
        ("setting_sound", 1695, 70): "系统设置",         # 切回基础页
        ("setting_sound", 2098, 1261): "返回",
        ("setting_sound", 1741, 1261): "返回标题画面",
        ("setting_sound", 145, 1261): "重置为默认声音设置",
        # 滑杆
        ("setting_sound", 400, 1163): "时语语音音量",
        ("setting_sound", 1420, 1163): "星弥语音音量",
    }


    #: ★ 覆盖率核对用（`tools/coverage_uialt.py` 读这一段）：**位置表覆盖了哪些图**。
    #: 位置表按 `(界面, x, y)` 写、工具无法从坐标反推图名，所以在这里显式列出；
    #: 它必须与上面 `UiAltByPos` 的每一条对应 —— 刻意放在同一个文件、紧挨着，
    #: 就是为了对账方便。为什么这几张图**必须**走位置表，见上面那段。
    #: 这里额外的一张：`1/2/3.png` 是同一个「继续自动模式」按钮的三个状态图。
    A11Y_POS_IMAGES = [
        "1.png", "2.png", "3.png",
        "sys_menu_basic_normal.png", "sys_menu_sound_normal.png",
        "sys_data_basic_bo1_fullscreen_normal.png",
        "sys_data_basic_bo1_windowed_normal.png",
        "sys_data_basic_bo2_1440p_normal.png",
        "sys_data_basic_bo2_1080p_normal.png",
        "sys_data_basic_bo2_720p_normal.png",
        "sys_data_basic_bo3_allltext_normal.png",
        "sys_data_basic_bo3_readtext_normal.png",
        "sys_data_basic_bo4_yes_normal.png",
        "sys_data_basic_bo4_no_normal.png",
        "sys_data_basic_bo5_stopauto_normal.png",
        "sys_data_basic_bo5_stillauto_normal.png",
        "sys_data_basic_bo5_stopskip_normal.png",
        "sys_data_basic_bo6_bold_normal.png",
        "sys_data_basic_bo6_unbold_normal.png",
        "sys_data_basic_bo6_stroke_normal.png",
        "sys_data_basic_bo6_unstroke_normal.png",
        "sys_data_sound_yes_normal.png",
        "sys_data_sound_no_normal.png",
        "sys_data_sound_mute_normal.png",
        "sys_data_sound_char_have_normal.png",
        "sys_data_sound_char_not_normal.png",
        "sys_data_sound_char_test_normal.png",
    ]


    # ════════════════════════════════════════════════════════════════════════
    # 需要「第几个」的控件：靠平台层给的 ordinal，**不靠坐标反推**
    # ════════════════════════════════════════════════════════════════════════
    #
    # 平台层把**同一界面、同一张图**的控件按 (y, x) 排序，名次作为
    # `ctx["ordinal"]` 交给下面的钩子（见 `a11y_platform/08_uialt.rpy` 的 `_scan`）。
    #
    # ⚠ 这里**曾经**用绝对坐标反推（网格几何 + ±2 像素校验），已撤除 —— 它会
    #   **静默失效**：格子按钮的图是 462×260、格子是 462×306，矮 46 像素就校验
    #   不过 ⇒ **12 个存档位一个都不出声**，日志里只有一行「未识别」，看着像还没
    #   做，不像做错了。序号只该依赖「屏幕上的先后」，不该依赖尺寸与内边距。

    #: 立绘页面板六行的标签。**看图确认**：
    #: `gui/custom2/system/extra/stand/stand_data_bg.png` 上依次印着
    #: 角色 / 姿势 / 服装 / 表情 / 符号 / 背景。
    #: 与源码（`stand_mode.rpy:152-159`）一致：`data_group[0..5]` 依次用于
    #: 角色、pose_list、stand_clothes_list、stand_face_list、
    #: stand_manga_fx_list、bg_list —— 两条独立证据对上了。
    _STAND_GROUPS = ["角色", "姿势", "服装", "表情", "符号", "背景"]


    def _a11y_slot_state(slot):
        """这一位是空、还是已有存档（有时间就报时间）。

        槽位名的拼法取自引擎：`persistent._file_page` 是**字符串**
        （`00action_file.rpy:120` 默认 `"1"`，`:623` 由 `FilePage` 改），
        完整槽位名是 `"<页>-<序号>"`（`"1-3"` / `"auto-3"`），
        这正是 `FileTime` / `FileLoadable` 那一套用的名字。
        """
        try:
            page = persistent._file_page
        except Exception:
            page = "1"
        name = "%s-%d" % (page, slot)
        try:
            mt = renpy.slot_mtime(name)
        except Exception:
            # ⚠ 拿不到就**不猜**：返回空串（只报「存档位 N」），而不是报「空」——
            #   把一个有存档的位子报成空，会让玩家以为存档丢了。
            return ""
        if mt is None:
            return "空"
        try:
            return mt.strftime("%m月%d日 %H:%M")
        except Exception:
            return "有存档"


    def _a11y_asmr_label(row):
        """音声曲目第 `row` 行的朗读文案。

        ⚠ 行号≠曲目号：列表只给**已解锁**的曲目建行
        （`music.rpy:345-346` 的 `if is_asmr_track_unlocked(i)`），
        所以先把解锁的挑出来再取第 row 个。
        曲名与标题直接取游戏自己的两份表（`music.rpy:2-3`），
        未解锁的行照画面那样念解锁提示。
        """
        try:
            idxs = [i for i in range(len(asmr_track_files))
                    if is_asmr_track_unlocked(i)]
        except Exception:
            return None
        if not (0 <= row < len(idxs)):
            return None
        i = idxs[row]
        try:
            if is_asmr_track_unlocked(i):
                return "%s %s" % (asmr_track_names[i], asmr_track_titles[i])
            return "%s %s" % (asmr_track_names[i], asmr_track_unlock_hints[i])
        except Exception:
            return None


    def _a11y_stand_value(i):
        """立绘页第 i 行**当前显示的值** —— 逐字复刻 `stand_mode.rpy:251-258`。

        那一行 `text data_name` 的内容是：
            第 0 行：角色名（星弥 / 时语）；其余行：`str(data_group[i]+1).zfill(3)`
        本函数照抄这个算法，所以报出来的与**屏幕上显示的一模一样**
        （等价呈现），而不是我另起一套说法。
        """
        try:
            if i == 0:
                return "星弥" if data_group[0] == 0 else "时语"
            return str(data_group[i] + 1).zfill(3)
        except Exception:
            return ""


    def _a11y_choice_caption(n, total):
        """选项按钮 -> 第几个选项的文案。**把已经抓到的文案接到查表这条路上。**

        ── 为什么必须有这一段（实机日志确认的缺口）────────────────────────────
        原作选项界面里，按钮是**图片按钮**（`dialog_option_bg_normal.png`），
        可读文字 `i.caption` 是它的**兄弟节点**、不在按钮里。补丁虽然覆盖了
        `screen choice` 并给按钮加了 `alt`，但那个覆盖**被原作版本盖掉了**
        （排序证据见 `30_choice.rpy` 文件头），于是实机日志是：

            [alt] 焦点=ImageButton 文本='未命名控件（dialog_option_bg_normal.png，ChoiceReturn）'

        现在覆盖已修好（`alt` 会先命中第 ① 级）；这一段是**并列的第二条通路**：
        万一 `alt` 那条路再次失效（例如别的 mod 又覆盖了一次界面），
        文案仍然能从「已经抓到的这一批选项」里查到 —— 见 `30_choice.rpy` 的
        `A11yChoice.capture` / `_caption_of`。

        ── 凭什么断定「名次」与「选项顺序」一致（代码事实，不是猜）──────────
        1. 原作 `screen_choice.rpy` 的结构是 `vbox` 里 `for i in items:`
           —— 每个选项恰好生成**一个** frame，frame 里恰好**一个** imagebutton，
           没有 `if` 过滤、没有额外按钮（从 `scripts.rpa` 解出来的 `.rpyc`
           反编译逐字核对）。补丁的覆盖版结构与之逐字一致。
        2. 三个按钮的 idle 图**完全相同**（同一张 `dialog_option_bg_normal.png`），
           所以平台层 `_A11yOrdinals` 把它们归成**同一组**，按 `(y, x)` 排行
           （`08_uialt.rpy:82-103` 的 `_A11yOrdinals`）；vbox 让它们 x 相同、
           y 依次增大 ⇒ 名次就是**从上到下 = items 的顺序**。
        3. **数量必须相等**才敢用名次：`total == len(items)` 不成立时说明这一组里
           混进了别的控件（名次与文案之间就没有任何关系了），此时**一个字都不报**，
           交给兜底说「选项 N」。
           这条是抄 `10_renpy_adapter.rpy:577` 的教训原文：
           「**凡是「按位置对上文案」的地方，都必须先断言数量相等。**」

        `total` 与 `n` 由平台层给（`ctx["total"]` / `ctx["ordinal"]`，
        `08_uialt.rpy:386` 的 `_ctx`），本函数**不自己算坐标** ——
        坐标只该用来定先后。
        """
        if n is None:
            return None
        ch = getattr(A11yHost, "choice", None)
        if ch is None:
            return None
        items = getattr(ch, "_items", None) or []
        if total != len(items) or not (0 <= n < len(items)):
            # 数量对不上：**宁可只说「第几个」，也不报一条可能错位的文案**。
            # 报错文案比不报危险得多 —— 玩家会按着念出来的内容去按回车。
            A11yHost.said("[选项] 数量对不上，不报文案: 名次=%s/%s 候选=%d" % (
                n, total, len(items)))
            return None
        try:
            cap = ch._caption_of(items[n])
        except Exception:
            cap = ""
        # ⚠ 必须 `strip()` 之后再判空：`_caption_of` 对**空白串**是照原样返回的
        #   （它只判 `v.strip()` 有没有内容，返回的是没 strip 过的原文）。
        #   不 strip 的话，一个「只有空格」的文案会被当成有效文案念出去 ——
        #   玩家听到的是**一声不响**，正是这次要修的毛病。（离线探针抓到的。）
        cap = (cap or "").strip()
        # ── 焦点兜底的整批播报 ────────────────────────────────────────────
        # 玩家已经把焦点放到选项上了 ⇒ 这一屏确实在显示，而整批播报只能由
        # 界面自己的 `on "show"` 触发（那条路出过事故）。这里补一次，
        # 由 `A11yChoice.ensure_announced` 自己去重，不会念两遍。
        try:
            ch.ensure_announced(items)
        except Exception:
            A11yHost.log_exc("选项整批播报（焦点兜底）失败")
        text = cap if cap else "选项 %d" % (n + 1)

        # ── 正向证据 ──────────────────────────────────────────────────────
        # 维护者只能靠耳朵验收，所以映射对不对必须**能从日志直接看出来**：
        # 名次 K 查到的是哪一条、候选几个、界面是不是 choice，一行里全齐。
        # ⚠ 「界面=choice」是**事实**而不是我写死的标签：这一段只在
        #   `_a11y_ui_alt_for` 判定了动作类名是 `ChoiceReturn`（引擎 `menu`
        #   语句为每个选项生成的动作）之后才会走到。
        sig = (n, total, text)
        if _A11Y_CHOICE_SAID_LAST[0] != sig:
            _A11Y_CHOICE_SAID_LAST[0] = sig
            A11yHost.said("[选项] 界面=choice 候选=%d ordinal=%s 文案='%s'" % (
                len(items), n, text))
        return text


    def _a11y_ui_alt_for(key, w, ctx):
        """逐作层兜底钩子。`ctx` 见契约层 `UiAltFor` 的说明。"""
        n = ctx.get("ordinal")
        total = ctx.get("total")

        # ---- ★ 选项界面的按钮 ----
        # 判据是**动作类名**：`ChoiceReturn` 是引擎 `menu` 语句为每个选项生成的
        # 动作类（实机日志里三个选项全是它）。用类名而不是图名，是因为
        # `dialog_option_bg_normal.png` 这张图别的界面也可能用；用类名可以保证
        # **只**接管选项按钮，不会顺手改掉别的控件的播报。
        try:
            act = getattr(w, "action", None)
            if act is not None and type(act).__name__ == "ChoiceReturn":
                return _a11y_choice_caption(n, total)
        except Exception:
            A11yHost.log_exc("选项文案取用失败")

        # ---- 存读档的 12 个格子 ----
        # 名次 = 同图控件按 (y,x) 的次序 = 格子从左到右、从上到下的次序
        # = 存档位号 - 1（`grid 4 3` 按行填，`screen_load_save.rpy:80` 实查）。
        # `total == 12` 是**保险**：哪天界面改成别的格子数，
        # 宁可退化成「未识别」，也不要报一个错位的号。
        if key == "sl_data_img_bg_empty.png" and n is not None and total == 12:
            slot = n + 1
            state = _a11y_slot_state(slot)
            if state:
                return "存档位 %d，%s" % (slot, state)
            return "存档位 %d" % slot

        # ---- 存读档格子：同一张图的**另一个按钮实例** ----
        # ⚠ 实机日志（`a11y_speech.log`）里出现过这种相邻对照：
        #     [alt] 焦点=ImageButton 文本='存档位 1，空'                       ← 上面那条命中
        #     [alt] 焦点=ImageButton 文本='未命名控件（sl_data_img_bg_empty.png，SafeFileAction）'
        #   两张同图的实例里，有一张没走到上面那条 —— 说明 `total == 12`
        #   这个「先断言数量相等」的保险**在真实布局里会不成立**（那一组里混进了
        #   别的控件）。**具体是哪个控件混进来的，本轮没查清**（要复现一次会话，
        #   用 Ctrl+Shift+I 快照把 `ordinal/total` 打出来才能定论）。
        #
        #   但「报不出位号」不该退化成「报图片名」：玩家至少要知道自己摸到了
        #   哪一个格子。于是这里用**动作自己带的槽位号**兜底 ——
        #   `scripts/controls/save_compat.rpy:101-104` 实查：那个按钮的 action 是
        #   `SafeFileAction(slot)`，而它把槽位号原样存在 `self.slot`
        #   （`self._file_action = FileAction(slot)`）。**这是动作自己的数据，
        #   不是从坐标猜的**，所以哪怕名次对不上也敢报。
        #   拿不到就返回 None（继续走平台层的兜底），绝不编一个号。
        if key == "sl_data_img_bg_empty.png":
            slot = None
            try:
                act = getattr(w, "action", None)
                s = getattr(act, "slot", None)
                if isinstance(s, int):
                    slot = s
                elif isinstance(s, str) and s.isdigit():
                    slot = int(s)
            except Exception:
                slot = None
            if slot is not None:
                state = _a11y_slot_state(slot)
                if state:
                    return "存档位 %d，%s" % (slot, state)
                return "存档位 %d" % slot

        # ---- 音声鉴赏的曲目列表 ----
        if key == "extra_audio_list_bg_normal.png" and n is not None:
            return _a11y_asmr_label(n)

        # ---- 立绘页每行的两个小三角 ----
        # 六行自上而下就是 _STAND_GROUPS 的次序，名次即行号；本意是顺带把**当前
        # 值**也念出来（否则连按十下「下一个」听不出值变没变）。
        # ⚠ 但图片表里已有同名的两条，而平台层查表次序是「图片表先于钩子」，
        #   所以这一段实际到不了（要接通得先动图片表 —— 那会改变播报）。
        if key in ("stand_data_bo_left_normal.png",
                   "stand_data_bo_right_normal.png") and n is not None:
            if n < len(_STAND_GROUPS):
                direction = "上一个" if "left" in key else "下一个"
                cur = _a11y_stand_value(n)
                if cur:
                    return "%s %s，当前 %s" % (_STAND_GROUPS[n], direction, cur)
                return "%s %s" % (_STAND_GROUPS[n], direction)

        # ---- 画廊：CG / 立绘缩略图 ----
        # 这些格子**画面上没有任何文字**（就是一张封面图），既没有可读标题，也不能
        # 从文件名猜内容（`gallery_groups` 里是 `cg100`/`sd4` 这种内部键，报给玩家
        # 只是噪声）。能诚实说出来的只有「它是这一页的第几张」。
        if key and ("cg" in key.lower() or "sd" in key.lower()):
            try:
                k = int(getattr(getattr(w, "action", None), "number", -1)) + 1
            except Exception:
                k = 0
            if k > 0:
                return "第 %d 张" % k
            # ⚠ 这里**不能**退化成用 `ordinal`：画廊每个缩略图的图**各不相同**，
            #   所以每一个自成一「组」，ordinal 恒为 0 —— 用它会报成
            #   「第 1 张」并**对每一张都说第 1 张**。宁可只说「图片」。
            return "图片"
        return None


    #: 登记给平台层 —— **这一行不能少**（曾经被批量改写连带删掉过一次，而当时所有
    #: 断言照样通过，因为契约层允许它为 None；现有断言 F 专拦这一条）。
    A11yHost.UiAltFor = _a11y_ui_alt_for
