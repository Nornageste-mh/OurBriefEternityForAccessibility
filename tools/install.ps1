# 安装 / 卸载补丁到游戏目录（开发期用，也可给玩家手工参照）
#
# 用法（Windows PowerShell 5.1 与 PowerShell 7 都可以）：
#   powershell -ExecutionPolicy Bypass -File tools\install.ps1
#   powershell -ExecutionPolicy Bypass -File tools\install.ps1 -Uninstall
#   powershell -ExecutionPolicy Bypass -File tools\install.ps1 -GameDir "D:\..."
#
# 不传 -GameDir 时**自动探测**游戏目录，次序见下面 `Find-GameDir`
# （注册表 InstallPath -> libraryfolders.vdf 里的全部库 -> 当前目录 ->
#  脚本所在目录的上级）。命中哪个会打印出来，一个都没命中就列清楚「试过哪里」。
#
# ⚠ 本文件必须以 **UTF-8 带 BOM** 保存。
#   上游流水线陷阱 G5 原文：「`.ps1` 含中文且无 BOM → PS 5.1 按 GBK 解码 → 语法错误」。
#   本文件第一次生成时正是无 BOM，实测报 `Missing closing '}'`，已按该条修正。
#   ✅ 这条现在有机器拦：`python tools\lint_patch.py` 的**断言 J**
#      会扫 `tools\*.ps1` 的头三个字节是不是 `EF BB BF`，丢了 BOM 就红。
#
# 设计原则（照抄上游流水线的安装方式）：
#   **只往 game\ 下放我们自己的文件，绝不改动游戏原有文件。**
#   上游 SenrenBanka 的 0.1.0.4 就是为「撤销分发改好的整包」而发的 ——
#   分发游戏资源既有版权问题，也让补丁无法干净卸载。
#   本补丁装的是「松散 .rpy 叠加层」：Ren'Py 的 loader.py:108-109 明确
#   「Files on disk should be checked before archives.」，
#   所以这种方式是引擎官方支持的，不需要重新打包任何 .rpa。

[CmdletBinding()]
param(
    # 留空 = 自动探测。要指定就写 -GameDir "<游戏根目录>"。
    # （以前这里写死的是本机路径 `F:\Steam\steamapps\common\永恒与星辰与日常` ——
    #   对任何别的机器都是错的，而且与 README 里「会自动找 Steam 库里的游戏目录」
    #   那句话不符：README 说的是真的，写死的默认值却让它成了假话。）
    [string]$GameDir = "",
    [switch]$Uninstall,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$SrcRoot  = Join-Path $RepoRoot "mod\game"

# 本补丁全部文件的**文件名前缀**。卸载只删这些，绝不碰引擎的 00*.rpyc。
#
# ⚠ 这份清单必须与 `mod\game\` 下的实际文件名**逐个对上**。
#   第一版漏了 `07_uinav` / `21_uilabels` / `31_main_menu` ——
#   于是改了源码但旧 `.rpyc` 没被删掉，引擎继续跑旧编译产物，
#   表现正是那句最难查的话：「改了代码没反应」。
#
#   ⚠⚠ **新加/改名补丁文件时，必须同时改这里。**
#      漏登记的后果是：源码更新了、旧 `.rpyc` 还在，引擎继续跑旧编译产物，
#      表现就是「怎么改都没反应」——本项目真的这么卡过好几轮。
#      ✅ 这条现在有机器拦：`python tools\lint_patch.py` 的**断言 H**
#         会比对这份清单与 `mod\game\**\*.rpy` 的实际文件名，对不上就红。
$OurPrefixes = @("00_contract", "01_speech", "05_repeat",
                 "06_keymap", "08_uialt", "10_renpy_adapter",
                 "20_textproc", "22_uialt", "30_choice", "31_main_menu",
                 "90_plugin")

function Write-Step($m) { if (-not $Quiet) { Write-Host $m } }

# ---------------------------------------------------------------- 游戏目录自动探测
#
# 为什么要有这一段：README 写的是「它会自动找 Steam 库里的游戏目录」，
# 而第一版把默认值写成了**这一台机器**的路径 —— 换台机器、换个 Steam 库
# 就必然失败，玩家看到的是「游戏目录不存在: F:\...」这种无从下手的报错。
#
# 探测次序（与 README 的说法一致，且每一步都把「试过哪里」留痕）：
#   1. 注册表里的 Steam 安装目录：
#        HKCU:\Software\Valve\Steam
#        HKLM:\SOFTWARE\WOW6432Node\Valve\Steam
#        HKLM:\SOFTWARE\Valve\Steam
#      （优先 `InstallPath`；HKCU 在部分机器上只有 `SteamPath`，一并接受）
#   2. `<Steam>\steamapps\libraryfolders.vdf` 里列出的**所有**库目录。
#      ⚠ 只解析 `"path"` 行，**不引第三方模块**（玩家机器上没有那些模块）。
#      顺便也读各库自己的 `steamapps\libraryfolders.vdf`：Steam 允许
#      库套库，只读主库那一份会漏。
#   3. 依次检查 `<库>\steamapps\common\永恒与星辰与日常\game` 是否存在。
#   4. 便于「从解压出来的发布包里直接跑」：当前目录、脚本所在目录的上级。
#
# 判据统一走 `Test-GameDir`：必须有 `game\` 子目录**并且**能找到启动器文件。
#   · 只认 `game\` 会把游戏根当安装目录（`.rpa` 都在 `game\` 里）；
#   · 又必须比「目录存在」严 —— `F:\Steam\steamapps\common` 这类父目录
#     存在但里面没有本作，不能算命中。

function Test-GameDir([string]$Path) {
    if (-not $Path) { return $false }
    if (-not (Test-Path (Join-Path $Path "game"))) { return $false }
    foreach ($exe in @("OurBriefEternity.exe", "OurBriefEternity.py")) {
        if (Test-Path (Join-Path $Path $exe)) { return $true }
    }
    return $false
}

function Normalize-Path([string]$Path) {
    # 注册表里 Steam 把路径写成 `f:/steam`，vdf 里写成 `F:\Steam` —— 同一个目录。
    # 实测教训：这两个字符串在第 3 个字符处就不同（`/`=47 vs `\`=92），
    # 所以**只做大小写无关比较是不够的**（`-ieq` 与 OrdinalIgnoreCase 都返回 False；
    # 我一开始把它误判成「-eq 区分大小写」，绕着这事多跑了两轮）。必须先把分隔符统一。
    # Windows 的 API 两种都接受，这里统一成 `\`（与 vdf 里的写法一致）。
    $p = $Path.Trim().Replace("/", "\")
    $p = $p.TrimEnd("\")
    if (-not $p) { return $Path.Trim() }
    return $p
}

function Add-Probed([string]$Path) {
    # 记录「试过哪里」，给探测失败的报错用：归一化后去重、保持先后次序。
    # ⚠ 探测失败时**必须**把这份清单打出来 —— 玩家手里只有一个
    #   「游戏目录不存在」是没法自救的，得让他看见脚本到底去过哪些地方。
    # 用 `-ieq`：盘符大小写在不同来源里不一样（注册表 `f:` vs vdf `F:`）。
    $n = Normalize-Path $Path
    foreach ($q in $script:Probed) {
        if ($q -ieq $n) { return }
    }
    $script:Probed.Add($n)
}

function Get-SteamInstallPaths {
    # 返回注册表里登记过的 Steam 安装目录（去重，保持优先次序）。
    $out = New-Object System.Collections.Generic.List[string]
    $probes = @(
        @{ Key = "HKCU:\Software\Valve\Steam";                  View = "Registry32" },
        @{ Key = "HKLM:\SOFTWARE\WOW6432Node\Valve\Steam";      View = "Registry64" },
        @{ Key = "HKLM:\SOFTWARE\Valve\Steam";                  View = "Registry64" }
    )
    foreach ($p in $probes) {
        foreach ($name in @("InstallPath", "SteamPath")) {
            try {
                $v = (Get-ItemProperty -Path $p.Key -Name $name -ErrorAction Stop).$name
            } catch { continue }
            if (-not $v) { continue }
            $v = Normalize-Path $v
            $seen = $false
            foreach ($q in $out) {
                if ($q -ieq $v) { $seen = $true }      # -ieq：见 Add-Probed 的说明
            }
            if ((Test-Path $v) -and (-not $seen)) { $out.Add($v) }
        }
    }
    return $out
}

function Get-VdfLibraryPaths([string]$VdfPath) {
    # 从 libraryfolders.vdf 里抓出所有 `"path"  "<路径>"`。
    # VDF 是 Valve 自家的格式：键和值都用双引号包着，反斜杠要转义（`F:\\Steam`）。
    # 这里只认 `path` 一行 —— 本脚本不需要库的其它字段（label / apps / 大小）。
    if (-not (Test-Path $VdfPath)) { return @() }
    $out = @()
    foreach ($line in ([System.IO.File]::ReadAllLines($VdfPath, [System.Text.Encoding]::UTF8))) {
        if ($line -match '^\s*"path"\s*"(.+?)"\s*$') {
            $v = $Matches[1] -replace '\\\\', '\'
            $v = $v -replace '\\"', '"'
            if ($v -and (Test-Path $v)) { $out += $v }
        }
    }
    return $out
}

function Find-GameDir {
    # 命中就返回游戏根目录，否则返回 $null；`$script:Probed` 记录试过的位置。
    $script:Probed = New-Object System.Collections.Generic.List[string]

    $steamRoots = New-Object System.Collections.Generic.List[string]
    foreach ($s in (Get-SteamInstallPaths)) {
        $s = Normalize-Path $s
        if (-not $steamRoots.Contains($s)) { $steamRoots.Add($s) }
    }

    # ---- 1) 注册表给的 Steam 安装目录本身
    foreach ($s in $steamRoots) {
        Add-Probed $s
        if (Test-GameDir $s) { return $s }
    }

    # ---- 2) 各库目录（主库的 vdf + 每个库自己的 vdf，库套库也能覆盖）
    $libs = New-Object System.Collections.Generic.List[string]
    foreach ($root in $steamRoots) {
        $own = Join-Path $root "steamapps"
        if ((Test-Path $own) -and (-not $libs.Contains($root))) { $libs.Add($root) }
    }
    foreach ($vdf in @(@($steamRoots | ForEach-Object { Join-Path $_ "steamapps\libraryfolders.vdf" }) +
                       @($libs | ForEach-Object { Join-Path $_ "steamapps\libraryfolders.vdf" }))) {
        foreach ($lib in (Get-VdfLibraryPaths $vdf)) {
            $lib = Normalize-Path $lib
            if (-not $libs.Contains($lib)) { $libs.Add($lib) }
        }
    }

    # ---- 3) 每个库下的 steamapps\common\<游戏>\game
    foreach ($lib in $libs) {
        $cand = Join-Path $lib "steamapps\common\永恒与星辰与日常"
        Add-Probed $cand
        if (Test-GameDir $cand) { return $cand }
    }

    # ---- 4) 从解压出来的发布包里直接跑：当前目录，以及脚本所在目录的上级
    $here = @(
        (Get-Location).Path,
        (Split-Path -Parent $PSScriptRoot)
    )
    foreach ($h in $here) {
        if (-not $h) { continue }
        Add-Probed $h
        if (Test-GameDir $h) { return $h }
    }

    # 常见位置兜底：有的机器注册表里没有 Valve 键，但 Steam 装在默认路径。
    foreach ($guess in @(
        "C:\Program Files (x86)\Steam",
        "C:\Program Files\Steam",
        "D:\Steam",
        "D:\SteamLibrary",
        "E:\Steam",
        "E:\SteamLibrary"
    )) {
        Add-Probed $guess
        if (Test-GameDir $guess) { return $guess }
        $cand = Join-Path $guess "steamapps\common\永恒与星辰与日常"
        Add-Probed $cand
        if (Test-GameDir $cand) { return $cand }
    }

    return $null
}

# 给维护者/自动化留的后门：ETERNITY_GAME_DIR 优先于自动探测（与
# `tools\lint_patch.py` 认的 `ETERNITY_GAME_DIR` 是同一个名字）。
if (-not $GameDir -and $env:ETERNITY_GAME_DIR) {
    $GameDir = $env:ETERNITY_GAME_DIR
}

if (-not $GameDir) {
    $GameDir = Find-GameDir
    if ($GameDir) {
        Write-Host "自动探测到游戏目录: $GameDir"
    } else {
        Write-Host "自动探测没能找到游戏目录。试过这些位置："
        foreach ($p in $script:Probed) { Write-Host "  · $p" }
        Write-Host ""
        Write-Host "请用 -GameDir 指定游戏**根**目录（里面应当同时有 OurBriefEternity.exe 与 game\ 子目录）："
        Write-Host '  powershell -ExecutionPolicy Bypass -File tools\install.ps1 -GameDir "<游戏根目录>"'
        Write-Host '  （Steam 上右键游戏 -> 管理 -> 浏览本地文件，就是那个目录。）'
        Write-Error "找不到游戏目录 —— 自动探测失败，且没有指定 -GameDir"
        exit 1
    }
}

if (-not (Test-Path $GameDir)) {
    Write-Error "游戏目录不存在: $GameDir"
    exit 1
}
if (-not (Test-GameDir $GameDir)) {
    Write-Error "在 $GameDir 找不到 OurBriefEternity.exe 或 game\ 子目录 —— 用 -GameDir 指定正确路径"
    exit 1
}

$DstPlatform = Join-Path $GameDir "game\a11y_platform"
$DstGame     = Join-Path $GameDir "game\a11y_game"

function Remove-OurRpyc($root) {
    # 只删**我们自己**的 .rpyc。判据是完整前缀匹配，不是通配符
    # —— `a11y_*.rpyc` 这种写法是错的（它匹配不到 00_contract 这类名字），
    # 而 `0*_*.rpyc` 更危险（会撞上引擎的 00keymap.rpyc）。
    foreach ($f in (Get-ChildItem $root -Recurse -File -ErrorAction SilentlyContinue)) {
        if ($f.Extension -ne ".rpyc") { continue }
        $base = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
        if ($OurPrefixes -contains $base) {
            Remove-Item $f.FullName -Force
            Write-Step "已删除编译产物 $($f.Name)"
        }
    }
}

if ($Uninstall) {
    foreach ($d in @($DstPlatform, $DstGame)) {
        if (Test-Path $d) {
            Remove-Item $d -Recurse -Force
            Write-Step "已删除 $d"
        }
    }
    Remove-OurRpyc (Join-Path $GameDir "game")
    Write-Step "卸载完成。游戏原有文件一个都没动过。"
    exit 0
}

if (-not (Test-Path $SrcRoot)) {
    Write-Error "找不到源目录: $SrcRoot"
    exit 1
}

foreach ($pair in @(@("a11y_platform", $DstPlatform), @("a11y_game", $DstGame))) {
    $src = Join-Path $SrcRoot $pair[0]
    $dst = $pair[1]
    if (-not (Test-Path $src)) { Write-Error "缺少源目录 $src"; exit 1 }
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    $files = Get-ChildItem $src -File -Filter *.rpy
    foreach ($f in $files) {
        Copy-Item $f.FullName (Join-Path $dst $f.Name) -Force
    }
    Write-Step "已安装 $($files.Count) 个文件 -> $dst"
}

# 删掉旧的 .rpyc，强制引擎按最新源码重编。
# 不这么做的坑：改了 .rpy 但旧的 .rpyc 时间戳更新时，引擎会用旧的编译产物，
# 表现为「改了代码没反应」。
Remove-OurRpyc (Join-Path $GameDir "game")

# ---------------------------------------------------------------- NVDA 客户端 dll
# 补丁的 NVDA 后端需要 nvdaControllerClient64.dll（LGPL-2.1，随包分发、未经修改）。
# 探测次序见 a11y_platform/01_speech.rpy 的 `_candidate_dirs`：
#     <game>\a11y_platform\  ->  <游戏根>\  ->  <game>\
# 这里放到**游戏根目录** —— 与上游三作的做法一致（显式放在最外层，
# 最不容易被别处的旧副本抢走）。
$NvdaSrc = @(
    (Join-Path $RepoRoot "mod\nvdaControllerClient64.dll"),
    (Join-Path $RepoRoot "mod\game\nvdaControllerClient64.dll"),
    (Join-Path $RepoRoot "mod\nvdaControllerClient.dll")
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($Uninstall) {
    foreach ($n in @("nvdaControllerClient64.dll", "nvdaControllerClient.dll")) {
        $p = Join-Path $GameDir $n
        if (Test-Path $p) { Remove-Item $p -Force; Write-Step "已删除 $n" }
    }
} else {
    if ($NvdaSrc) {
        $dstDll = Join-Path $GameDir "nvdaControllerClient64.dll"
        Copy-Item $NvdaSrc $dstDll -Force
        Write-Step "已安装 NVDA 客户端 dll -> $dstDll"
    } else {
        Write-Warning "没找到 nvdaControllerClient64.dll —— NVDA 后端会不可用，补丁将降级到 SAPI。"
        Write-Warning "请把它放到 $GameDir\ 或 $RepoRoot\mod\ 下。"
    }
}

Write-Step "安装完成。"
Write-Step ""
Write-Step "  按键："
Write-Step "    F5                 重读上一句"
Write-Step "    F9                 切换朗读后端（自动 / NVDA / 引擎同款 SAPI / 两者同时）"
Write-Step "    1 - 9              直接选择对应编号的选项（含小键盘）"
Write-Step "    方向键 / 回车      引擎原生：菜单与界面导航、确认"
Write-Step ""
Write-Step "  [!] 重读键不是 Backspace —— 本作把它留给了文本输入（引擎 input_backspace）。"
Write-Step "  [!] 不要用 v 键：那是引擎内建的 self_voicing 开关，"
Write-Step "      在 Windows 上走 SAPI，不认识 NVDA。本补丁的朗读默认已开启。"
