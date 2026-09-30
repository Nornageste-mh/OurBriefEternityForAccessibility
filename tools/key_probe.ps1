# 按键通路自证：模拟按键 + 读日志，确认补丁的键真的接上了
#
# 为什么需要它：无障碍补丁最容易出的一类问题是「键没接上」——
# 功能代码写对了，但按键事件从来没走到它那里。
# 本补丁开发期就撞过一次：挂在 `config.underlay` 的 `Keymap` 会被**无参调用**，
# 于是「重读」在游戏启动时就自己触发了一次（详见 a11y_platform/05_repeat.rpy 的注释）。
#
# 本脚本做两件事：
#   1. 用 SendKeys 往游戏窗口发按键（`v` / Ctrl+Shift+R / 方向键 / 回车）
#   2. 读 log.txt 里补丁自己的输出，看这些按键有没有产生预期效果
#
# ⚠ Ren'Py 的按键处理是标准 pygame 事件循环，所以 SendKeys 这类
#   合成按键与真人按键走的是**同一条路径**，能证明「键接上了」。
#   它证明不了「读屏发声是否自然」—— 那需要真人听。

[CmdletBinding()]
param(
    [string]$GameDir = "F:\Steam\steamapps\common\永恒与星辰与日常",
    [int]$WaitSeconds = 20
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms

function Find-GameWindow {
    # 游戏进程名就是运行时 python.exe，用窗口标题匹配更稳。
    $procs = Get-Process -Name python -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -ne "" }
    if (-not $procs) {
        $procs = Get-Process -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowTitle -match "永恒|Eternity|OurBrief" }
    }
    return $procs | Select-Object -First 1
}

$win = Find-GameWindow
if (-not $win) {
    Write-Error "找不到游戏窗口。请先启动游戏，并确认它有可见窗口。"
    exit 1
}

Write-Host "目标窗口: [$($win.MainWindowTitle)] pid=$($win.Id)"
Write-Host "把它切到前台…"

# 用 Win32 的 SetForegroundWindow（比 AppActivate 稳）
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Fg {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
}
"@
[Fg]::ShowWindow($win.MainWindowHandle, 9) | Out-Null   # SW_RESTORE
[Fg]::SetForegroundWindow($win.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 800

$log = Join-Path $GameDir "log.txt"
$before = 0
if (Test-Path $log) { $before = (Get-Item $log).Length }

$script:steps = @(
    @{ name = "按下 v（引擎内建：切换自语音）"; keys = "v" },
    @{ name = "按下 Ctrl+Shift+R（补丁：重读上一条）"; keys = "^+r" },
    @{ name = "按下 Ctrl+Shift+I（补丁：报后端）"; keys = "^+i" },
    @{ name = "按下回车（推进）"; keys = "{ENTER}" },
    @{ name = "按下 下（菜单/选项导航）"; keys = "{DOWN}" }
)

foreach ($s in $script:steps) {
    Write-Host ("  发送: " + $s.name)
    [System.Windows.Forms.SendKeys]::SendWait($s.keys)
    Start-Sleep -Milliseconds 1500
}

Start-Sleep -Seconds $WaitSeconds

Write-Host ""
Write-Host "=== 按键后新写入的补丁日志 ==="
if (-not (Test-Path $log)) { Write-Host "（没有 log.txt）"; exit 0 }

# 只取新增部分
$fs = [System.IO.File]::Open($log, [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
try {
    if ($before -gt 0 -and $before -lt $fs.Length) { $fs.Seek($before, 'Begin') | Out-Null }
    $sr = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::UTF8)
    $new = $sr.ReadToEnd()
    $sr.Close()
} finally { $fs.Close() }

$hits = $new -split "`r?`n" | Where-Object { $_ -match '\[A11y' }
if ($hits) { $hits | ForEach-Object { Write-Host $_ } }
else { Write-Host "（没有新的 [A11y] 行 —— 可能按键没送到，或游戏不在前台）" }

Write-Host ""
Write-Host "怎么判读："
Write-Host "  · 出现「on_key」/「repeat」相关行 → 重读键接上了"
Write-Host "  · 出现「朗读后端：」→ Ctrl+Shift+I 接上了"
Write-Host "  · v 键切换自语音不会写日志（那是引擎自己的键）——"
Write-Host "    要确认它，请听：按 v 应有「Self-voicing disabled.」或恢复朗读"
