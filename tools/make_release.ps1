# 打发布包：dist\OurBriefEternityA11y-<版本>.zip
#
# 用法（Windows PowerShell 5.1 与 PowerShell 7 都可以）：
#   powershell -ExecutionPolicy Bypass -File tools\make_release.ps1
#   powershell -ExecutionPolicy Bypass -File tools\make_release.ps1 -OutDir "D:\发布"
#   powershell -ExecutionPolicy Bypass -File tools\make_release.ps1 -Version 0.0.0.9   # 仅调试用
#
# ⚠ 本文件必须以 **UTF-8 带 BOM** 保存（同 install.ps1，断言 J 专拦这件事）。
#
# 产出是**「解压即用」**的包：**包里没有安装器**。zip 内的目录结构与游戏目录
# **一一对应**，所以「安装」这一个动作就是「把 zip 解压到游戏根目录、合并覆盖」：
#
#   game\a11y_platform\*.rpy         →  <游戏目录>\game\a11y_platform\
#   game\a11y_game\*.rpy             →  <游戏目录>\game\a11y_game\
#   game\nvdaControllerClient64.dll  →  <游戏目录>\game\
#   安装说明.md / 常见问题.md / licenses\  →  <游戏目录>\（文档与许可证，可留可删）
#
# ⚠ 为什么不再有安装器：曾经的包把 `install.ps1` 放在**包根**，而脚本是按
#   「自己在 `tools\` 下、仓库布局」定位源码的（`$RepoRoot` = 脚本所在目录的上级），
#   于是玩家解压后直接跑**必然**报「找不到源目录」（实测 exit=1）。
#   维护者的决定是**干脆不要安装器** —— 少一个会坏的环节，玩家侧也就不再需要
#   「自动探测 Steam 库 / `-GameDir`」那一套说明。
#   开发期自用的安装器仍是 `tools\install.ps1`：它留在仓库里给维护者自己用
#   （自动探测游戏目录、删掉自己的旧 `.rpyc`、逐字节校验 dll），**不进发布包**。
#   下面 `$ALLOWED_EXT` 里**没有 `.ps1`** ⇒「包里没有安装器」是**机械保证**的：
#   任何脚本文件进清单都会在自检处报错退出，而不是靠人记得别放。
#
# 这个脚本要防住的三类**静默故障**：
#
#   1. 版本号与代码不一致 —— 版本号**从代码里解析**（`90_plugin.rpy` 的
#      `A11yHost.PatchVersion`），不手写。手写过一次（标签 v0.0.0.5 里写的是
#      0.0.0.4），后果是维护者按日志对账对不出来；断言 G 管标签与代码一致，
#      本脚本管**包名与代码一致** —— 两头都机械核对，人才不用记。
#
#   2. zip 里混进游戏资源 —— 本仓库的 IP 红线是「不包含任何游戏资源」。
#      打包时最容易的翻车方式是「顺手把整个 game\ 目录塞进去」，
#      于是把 `.rpa` / 解包产物 / 剧本原文 / 截图 / 日志一起发了出去。
#      所以打之前对**清单本身**过一遍黑名单 + 白名单，命中就报错退出（不是警告）。
#
#   3. zip 条目分隔符不统一 —— .NET 的 `ZipFile.CreateFromDirectory` 与
#      `Compress-Archive` 在 Windows 上**都会写成反斜杠**（本机实测：
#      条目名是 `a\b\c.txt`）。跨平台解包工具对反斜杠的处理并不一致
#      （有的把它当普通字符，于是解出一个名叫 `a\b\c.txt` 的怪文件）。
#      本脚本用 `CreateEntryFromFile(..., entryName)` 显式指定条目名，
#      并在写完后再**重新打开 zip 逐条核验**：出现反斜杠就报错（不是静默接受）。
#
# 清单（要打进包的全部内容 —— 玩家把 zip 解压到游戏目录后，看到的就是这些）：
#   安装说明.md / 常见问题.md        ← mod\package\
#   licenses\*                      ← mod\package\licenses\
#   game\a11y_platform\*.rpy        ← mod\game\a11y_platform\（补丁平台层）
#   game\a11y_game\*.rpy            ← mod\game\a11y_game\（补丁逐作层）
#   game\nvdaControllerClient64.dll ← mod\game\ 或 mod\
#
# 共 16 条：11 个 `.rpy` + 1 个 dll + 2 份玩家文档 + 2 份许可证文本。
# **不含 install.ps1，也不含任何 `.ps1`。**

[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$OutDir = "",
    [string]$Version = "",
    [switch]$SkipGitCheck
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------- 常量

# 游戏目录名（Steam 里就叫这个）与 Steam AppID 4169820。
# AppID 脚本本身用不上，写在这里是为了排查时能一眼对上「玩家说的是不是本作」。
$GameDirNm = "永恒与星辰与日常"
$PkgName   = "OurBriefEternityA11y"

#: 补丁自己的文件必须来自这两个目录，别处的一律不收。
$PATCH_SUBDIRS = @("a11y_platform", "a11y_game")

#: zip 里补丁文件的顶层目录名 —— **故意与游戏目录同名**：
#: 玩家把 zip 解压到游戏根目录，`game\...` 就正好落在 `<游戏目录>\game\...`，
#: 中间不需要任何搬运步骤（这就是「解压即用」的全部机关）。
$ZipGameDir = "game"

#: ⚠ IP 红线：zip 里**不得**出现这些扩展名。
#:   判据写在「要打进包的那份清单」上，所以任何来源的文件都跑不掉。
$FORBIDDEN_EXT = @(
    ".rpa", ".rpyc", ".rpyb",          # 游戏资源与编译产物
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".psd", ".svg",
    ".ogg", ".opus", ".mp3", ".wav", ".m4a", ".flac",
    ".mp4", ".webm", ".avi", ".mkv", ".mov",
    ".log", ".bak", ".tmp", ".dmp", ".sav",
    ".zip", ".7z", ".rar", ".tar", ".gz",
    ".exe", ".pyc", ".pdb", ".ttf", ".otf"          # 游戏启动器 / 字体 / 调试符号
)

#: 解包产物与截图目录：即使里面混着白名单扩展名也不许进包。
$FORBIDDEN_SEG = @("extracted", "shots", "_img", "saves", "cache", "unrpyc", "dist")

#: 允许的扩展名（白名单比黑名单更硬：新出现的格式默认不进包）。
#: ⚠ 这里**故意没有 `.ps1`**：包是解压即用的，玩家侧不需要跑任何脚本，
#:   所以「包里没有安装器」由这条白名单机械保证（放行 `.ps1` 就等于
#:   允许把安装器再塞回去，那种事不该靠人记得别做）。
$ALLOWED_EXT = @(".rpy", ".md", ".dll", ".txt", ".json")

#: NVDA 客户端 dll（LGPL-2.1，随包分发、**未经修改**）。
#: 这里只**记录并打印** SHA256，不做硬编码比对 —— 硬编码了，换 dll 时人就会去改常量，
#: 核对也就失去意义。改由自洽性检查兜底：仓库里的 dll 应当与**已经装进游戏目录**
#: 的那一份逐字节相同（这就是「未经修改」那条声明的机械核对）。
$NVDA_DLL_NAME = "nvdaControllerClient64.dll"

#: 固定的条目时间戳（1980-01-01 是 ZIP 格式的下限）。
#: 好处：同一份源码打两次包，zip 逐字节相同（可对账、可复现）。
$ZipEpoch = [datetime]::SpecifyKind([datetime]::new(1980, 1, 1, 0, 0, 0),
                                    [System.DateTimeKind]::Unspecified)

# ---------------------------------------------------------------- 小工具

function Fail([string]$Message) {
    Write-Host ""
    Write-Host "打包中止：$Message" -ForegroundColor Red
    exit 1
}

function Get-EntryName([string]$Rel) {
    # zip 内部路径：统一 `/`，且不许出现 `..` / 盘符 / 前导斜杠。
    $s = $Rel.Replace("\", "/")
    if ($s.StartsWith("/")) { Fail "条目名不该以斜杠开头：$Rel" }
    if ($s -match "^[A-Za-z]:") { Fail "条目名不该带盘符：$Rel" }
    foreach ($seg in ($s -split "/")) {
        if ($seg -eq "" -or $seg -eq "." -or $seg -eq "..") {
            Fail "条目名里有空段 / . / ..：$Rel"
        }
    }
    return $s
}

function Test-RelInManifest([string]$Rel) {
    foreach ($m in $script:Manifest) { if ($m.Rel -eq $Rel) { return $true } }
    return $false
}

function Assert-NotGameAsset([string]$Rel) {
    $s = $Rel.Replace("\", "/")
    $ext = [System.IO.Path]::GetExtension($s).ToLowerInvariant()
    if ($FORBIDDEN_EXT -contains $ext) {
        Fail ("IP 红线：清单里有禁止的扩展名 '{0}' —— {1}" -f $ext, $s)
    }
    if ($ALLOWED_EXT -notcontains $ext) {
        Fail (("清单里出现未列入白名单的扩展名 '{0}' —— {1}`n" +
               "        （要放行就显式加进 `$ALLOWED_EXT，不要绕过检查）") -f $ext, $s)
    }
    foreach ($seg in ($s -split "/")) {
        if ($FORBIDDEN_SEG -contains $seg.ToLowerInvariant()) {
            Fail ("IP 红线：清单里出现禁止的目录名 '{0}' —— {1}" -f $seg, $s)
        }
    }
}

function Add-ManifestFile([string]$SrcPath, [string]$Rel, [string]$What) {
    # 收集 → 校验。存在性/空文件在这里就拦住，不留到写 zip 时才炸。
    Assert-NotGameAsset $Rel
    $rel = Get-EntryName $Rel
    if (-not (Test-Path -LiteralPath $SrcPath -PathType Leaf)) {
        Fail ("缺少{0}`n        找不到文件：{1}" -f $What, $SrcPath)
    }
    $len = (Get-Item -LiteralPath $SrcPath).Length
    if ($len -le 0) { Fail "文件是空的（0 字节）：$SrcPath" }
    $script:Manifest += [pscustomobject]@{
        Src  = $SrcPath
        Rel  = $rel
        What = $What
        Size = $len
    }
}

function Add-ManifestTree([string]$Dir, [string]$RelPrefix, [string[]]$Exts,
                          [string]$What, [switch]$Required) {
    if (-not (Test-Path -LiteralPath $Dir -PathType Container)) {
        Fail ("缺少{0}`n        找不到目录：{1}" -f $What, $Dir)
    }
    $found = @(Get-ChildItem -LiteralPath $Dir -Recurse -File -ErrorAction Stop |
               Sort-Object FullName)
    $taken = 0
    foreach ($f in $found) {
        $ext = $f.Extension.ToLowerInvariant()
        if ($Exts -contains $ext) {
            Add-ManifestFile $f.FullName (Join-Path $RelPrefix $f.Name) $What
            $taken++
        } else {
            Fail (("目录里有不该进包的文件：{0}`n" +
                   "        （只收 {1}；游戏资源一个都不许进包）") -f $f.FullName, ($Exts -join " / "))
        }
    }
    if ($taken -eq 0 -and $Required) {
        Fail ("{0}：目录里一个 {1} 都没有 —— {2}" -f $What, ($Exts -join " / "), $Dir)
    }
    return $taken
}

function Add-ManifestTreeIfExists([string]$Dir, [string]$RelPrefix, [string[]]$Exts,
                                 [string]$What) {
    if (-not (Test-Path -LiteralPath $Dir -PathType Container)) { return 0 }
    return (Add-ManifestTree $Dir $RelPrefix $Exts $What)
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

# ---------------------------------------------------------------- 0. 定位仓库

if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
Write-Host "仓库根目录: $RepoRoot"

$PluginFile = Join-Path $RepoRoot "mod\game\a11y_game\90_plugin.rpy"
if (-not (Test-Path -LiteralPath $PluginFile)) { Fail "找不到版本号来源文件：$PluginFile" }

if (-not $OutDir) { $OutDir = Join-Path $RepoRoot "dist" }
$OutDir = [System.IO.Path]::GetFullPath($OutDir)

# ---------------------------------------------------------------- 1. 版本号（从代码解析）

$pluginText = [System.IO.File]::ReadAllText($PluginFile, [System.Text.Encoding]::UTF8)
$m = [regex]::Match($pluginText, 'A11yHost\.PatchVersion\s*=\s*"([^"]+)"')
if (-not $m.Success) {
    Fail (("在 {0} 里找不到 A11yHost.PatchVersion = `"x.y.z.w`" —— " +
           "版本号必须从代码里解析，不手写") -f $PluginFile)
}
$CodeVersion = $m.Groups[1].Value
if ($CodeVersion -notmatch '^\d+\.\d+\.\d+\.\d+$') {
    Fail "解析出的版本号格式不对：'$CodeVersion'（期望 x.y.z.w）"
}
$VersionTag = "v$CodeVersion"
Write-Host "版本号（解析自 mod\game\a11y_game\90_plugin.rpy）: $CodeVersion   标签应为 $VersionTag"

$UseVersion = $CodeVersion
if ($Version) {
    $UseVersion = $Version.TrimStart("v")
    if ($UseVersion -ne $CodeVersion) {
        Write-Warning (("-Version {0} 与代码里的 {1} 不一致 —— 仅调试可用；" +
                        "正式发布包必须与代码一致（否则日志没法对账）") -f `
                       $UseVersion, $CodeVersion)
    }
}

# ---------------------------------------------------------------- 2. git 对账（可跳过）

$HaveGit = $null -ne (Get-Command git -ErrorAction SilentlyContinue)
if (-not $SkipGitCheck -and $HaveGit) {
    $tag = ""
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"      # git 的正常「没标签」退出码不该中断脚本
    try { $tag = (@(& git -C $RepoRoot describe --tags --exact-match HEAD 2>$null) -join "").Trim() }
    catch { $tag = "" }
    try { $dirty = (@(& git -C $RepoRoot status --porcelain 2>$null) -join "").Trim() }
    catch { $dirty = "" }
    $ErrorActionPreference = $oldEap

    if ($tag -and ($tag -ne $VersionTag)) {
        Write-Warning ("当前 HEAD 的标签是 {0}，而代码里的版本对应 {1}（断言 G 会红；发布前请对齐）" -f `
                       $tag, $VersionTag)
    } elseif ($tag) {
        Write-Host "git 标签对账: $tag == $VersionTag  OK"
    } else {
        Write-Host "git 标签对账: 当前提交没有版本标签（未打标签 = 还没到发布节点）"
    }
    if ($dirty) {
        Write-Warning "工作区有未提交的改动 —— 打出来的包无法用 git 复现（发布前请先提交/打标签）"
    }
}

# ---------------------------------------------------------------- 3. 清单

$script:Manifest = @()

# ⚠ 这里**故意没有 install.ps1**：发布包是「解压即用」的，玩家不需要运行任何脚本。
#   于是包内的相对路径就是**相对游戏根目录**的路径 —— 也就是下面所有条目
#   都以 `$ZipGameDir\`（= `game\`）开头、包根只放文档与 licenses\ 的原因。
#   （开发期自用的安装器留在仓库的 tools\install.ps1，不进包。）

# 文档。⚠ 这两个文件必须由维护者写出来（玩家侧的中文说明），
# 缺了就报错并说清楚要补哪两个文件 —— 打一个「解压后不知道该干什么」的包
# 比不打包更糟；而静默降级（少放文档照样出包）会让缺文档这件事没人发现。
$PkgDir = Join-Path $RepoRoot "mod\package"
Add-ManifestFile (Join-Path $PkgDir "安装说明.md") "安装说明.md" "玩家安装说明"
Add-ManifestFile (Join-Path $PkgDir "常见问题.md") "常见问题.md" "玩家常见问题"
Add-ManifestTree (Join-Path $PkgDir "licenses") "licenses" @(".txt", ".md") `
    "第三方许可（licenses\）" -Required | Out-Null

# 补丁本体。只收 .rpy，且必须来自 a11y_platform / a11y_game；
# 进包后统一挂到 `game\` 下（= 游戏目录里的那一层）。
foreach ($sub in $PATCH_SUBDIRS) {
    $n = Add-ManifestTree (Join-Path $RepoRoot "mod\game\$sub") "$ZipGameDir\$sub" `
            @(".rpy") "补丁层 $sub" -Required
    Write-Host "  补丁层 $sub`: $n 个 .rpy"
}

# NVDA 客户端 dll：zip 里固定放 `game\`（解压后 = `<游戏目录>\game\`，
# 也就是 a11y_platform/01_speech.rpy 的候选目录之一）。
# 仓库里它可能放在 mod\ 或 mod\game\（两种都接受，进包路径统一）。
$dllSrc = @(
    (Join-Path $RepoRoot "mod\game\$NVDA_DLL_NAME"),
    (Join-Path $RepoRoot "mod\$NVDA_DLL_NAME")
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $dllSrc) {
    Fail (("找不到 {0} —— 期望在 mod\game\ 或 mod\ 下`n" +
           "        （NVDA 后端没有它就不出声；发布包里必须有）") -f $NVDA_DLL_NAME)
}
Add-ManifestFile $dllSrc "$ZipGameDir\$NVDA_DLL_NAME" "NVDA 客户端 dll"

# ---------------------------------------------------------------- 4. 清单自检（IP 红线）

Write-Host ""
Write-Host "== 清单自检（IP 红线：不得包含任何游戏资源）=="
$dupe = $script:Manifest | Group-Object Rel | Where-Object { $_.Count -gt 1 }
if ($dupe) { Fail ("清单里有重复条目：" + (($dupe | ForEach-Object { $_.Name }) -join "、")) }

foreach ($e in $script:Manifest) {
    if (-not (Test-Path -LiteralPath $e.Src -PathType Leaf)) {
        Fail "清单里的源文件不见了：$($e.Src)"
    }
    # 补丁文件必须来自 mod\game\a11y_platform 或 mod\game\a11y_game
    # （进包后挂在 `game\` 下，正好等于游戏目录里的那一层）
    if ($e.Rel -like "$ZipGameDir/*") {
        $ok = ($e.Rel -eq "$ZipGameDir/$NVDA_DLL_NAME")
        foreach ($sub in $PATCH_SUBDIRS) {
            if ($e.Rel -like "$ZipGameDir/$sub/*") { $ok = $true }
        }
        if (-not $ok) {
            Fail ("补丁文件来源非法（只允许 {0}\a11y_platform / {0}\a11y_game / {0}\{1}）：{2}" -f `
                  $ZipGameDir, $NVDA_DLL_NAME, $e.Rel)
        }
    }
    # 解压即用 ⇒ 条目必须**正好落在游戏目录布局里**：要么 `game\...`，
    # 要么包根的文档，要么 `licenses\...`。别的相对路径（例如曾经的
    # `mod\game\...`）解压后落在游戏目录里根本没人读 —— 而玩家看不出来，
    # 只会觉得「补丁没生效」。所以这里机械拦住。
    if (-not (($e.Rel -like "$ZipGameDir/*") -or ($e.Rel -like "licenses/*") -or
              ($e.Rel -notlike "*/*"))) {
        Fail ("条目不在「游戏目录布局」里（只允许 {0}\... 、licenses\... 或包根文档）：{1}" -f `
              $ZipGameDir, $e.Rel)
    }
    # 再核一次：源文件的真实扩展名也必须在白名单里（防「改名混进来」）
    $srcExt = [System.IO.Path]::GetExtension($e.Src).ToLowerInvariant()
    if ($ALLOWED_EXT -notcontains $srcExt) {
        Fail "源文件扩展名 '$srcExt' 不在白名单里：$($e.Src)"
    }
}
$totalRaw = ($script:Manifest | Measure-Object -Property Size -Sum).Sum
Write-Host (("  条目 {0} 个，未压缩合计 {1:N0} 字节 —— 白名单通过，" +
             "未出现 {2} 或 {3} 一类禁止内容") -f `
            $script:Manifest.Count, $totalRaw,
            (($FORBIDDEN_EXT | Where-Object { $_ -in @(".rpa", ".rpyc", ".log", ".png") }) -join " "),
            ($FORBIDDEN_SEG -join " "))

# ---------------------------------------------------------------- 5. 写 zip

if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}
$OutDir = (Resolve-Path -LiteralPath $OutDir).Path
$ZipPath = Join-Path $OutDir "$PkgName-$UseVersion.zip"

# 删除前先确认「这个路径确实是要覆盖的那个包」：必须在 -OutDir 之内、扩展名是 .zip。
if (Test-Path -LiteralPath $ZipPath -PathType Leaf) {
    $full = [System.IO.Path]::GetFullPath($ZipPath)
    $outPrefix = $OutDir.TrimEnd("\") + "\"
    if (-not $full.StartsWith($outPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        Fail "拒绝删除输出目录之外的文件：$full"
    }
    if ([System.IO.Path]::GetExtension($full) -ne ".zip") {
        Fail "拒绝删除非 .zip 文件：$full"
    }
    Write-Host "覆盖已有产物: $full"
    Remove-Item -LiteralPath $full -Force
}

# ⚠ 两个程序集都要显式加载（PowerShell 5.1 上没有「隐式加载」这回事）：
#   System.IO.Compression        → ZipArchive / ZipArchiveMode / CompressionLevel
#   System.IO.Compression.FileSystem → ZipFile / ZipFileExtensions
# 实测：只加载后者时，第一句 `[System.IO.Compression.ZipArchiveMode]::Create`
# 就报 `Unable to find type`，而 A11y 断言不会管到这里 —— 只有真跑一次才能发现。
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$entries = New-Object System.Collections.Generic.List[object]
$zw = $null
$fs = $null
try {
    $fs = [System.IO.File]::Open($ZipPath, [System.IO.FileMode]::CreateNew,
                                 [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    $zw = New-Object System.IO.Compression.ZipArchive(
              $fs, [System.IO.Compression.ZipArchiveMode]::Create)
    foreach ($e in ($script:Manifest | Sort-Object Rel)) {
        # ⚠ 这里**不能**用 `ZipFileExtensions::CreateEntryFromFile`：
        #   那个方法会把条目立刻打开写入，之后再设 `LastWriteTime` 会抛
        #   「Cannot modify entry in Create mode after entry has been opened for writing」
        #   （本机实测就是这么炸的）。所以自己 CreateEntry -> 先定时间戳 -> 再写内容。
        $entry = $zw.CreateEntry($e.Rel, [System.IO.Compression.CompressionLevel]::Optimal)
        # 固定时间戳 ⇒ 同一份源码打两次包，zip 逐字节相同（可复现、可对账）
        $entry.LastWriteTime = [System.DateTimeOffset]$ZipEpoch
        $out = $entry.Open()
        $in = $null
        try {
            $in = [System.IO.File]::Open($e.Src, [System.IO.FileMode]::Open,
                                         [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
            $in.CopyTo($out)
        } finally {
            if ($in) { $in.Dispose() }
            $out.Dispose()
        }
    }
    $zw.Dispose()
    $zw = $null
} finally {
    if ($zw) { $zw.Dispose() }
    if ($fs) { $fs.Dispose() }
}

# ---------------------------------------------------------------- 6. 写完之后逐条核验

Write-Host ""
Write-Host "== zip 条目核验（分隔符统一 '/'、布局与游戏目录一一对应、不含任何 .ps1）=="
# 条目清单在**写完并重新打开**之后才收集：此时 Length / CompressedLength 才是终值
# （Create 模式里刚写进去的条目，长度字段还没定下来）。
$zipInfo = @{}
$totalInZip = 0
$za = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
try {
    $bad = @()
    $inZip = @{}
    foreach ($entry in $za.Entries) {
        $inZip[$entry.FullName] = $true
        $zipInfo[$entry.FullName] = [pscustomobject]@{
            Name   = $entry.FullName
            Size   = $entry.Length
            Packed = $entry.CompressedLength
        }
        $totalInZip += $entry.Length
        if ($entry.FullName.Contains("\")) {
            $bad += $entry.FullName
            continue
        }
        Assert-NotGameAsset $entry.FullName
        # 「包里没有安装器」再显式断言一道：白名单（`$ALLOWED_EXT`）里已经没有
        # `.ps1`，这里额外拦一次，是为了让以后「顺手放行一个脚本」也必须先删掉
        # 这句断言 —— 让人看见自己在做什么。
        if ([System.IO.Path]::GetExtension($entry.FullName).ToLowerInvariant() -eq ".ps1") {
            Fail ("zip 里出现了 .ps1（包是解压即用的，不该带任何脚本）：{0}" -f `
                  $entry.FullName)
        }
        if ($entry.Length -le 0) { Fail "zip 里有 0 字节条目：$($entry.FullName)" }
        # 清单以外的条目一律不许出现（防「顺手多塞了东西」）
        if (-not (Test-RelInManifest $entry.FullName)) {
            Fail "zip 里出现清单之外的条目：$($entry.FullName)"
        }
    }
    if ($bad.Count -gt 0) {
        Fail (("zip 条目含有反斜杠（跨平台解包会出怪名字）：`n        {0}") -f `
              ($bad -join "`n        "))
    }
    $missing = @()
    foreach ($e in $script:Manifest) {
        if (-not $inZip.ContainsKey($e.Rel)) { $missing += $e.Rel }
    }
    if ($missing.Count -gt 0) {
        Fail ("清单里有没写进 zip 的条目：" + ($missing -join "、"))
    }
    if ($za.Entries.Count -ne $script:Manifest.Count) {
        Fail "zip 条目数 $($za.Entries.Count) 与清单 $($script:Manifest.Count) 不一致"
    }
    if ($totalInZip -ne $totalRaw) {
        Fail "zip 内未压缩总长 $totalInZip 与清单合计 $totalRaw 不一致"
    }
    Write-Host "  OK  $($za.Entries.Count) 个条目全部使用 '/'，且全部在清单内"
} finally {
    $za.Dispose()
}

# ---------------------------------------------------------------- 7. 打印条目清单与体积

$zipLen = (Get-Item -LiteralPath $ZipPath).Length
$sha = Get-Sha256 $ZipPath
$ratio = 1 - ($zipLen / [double]$totalInZip)

Write-Host ""
Write-Host "== 发布包 =="
Write-Host ("  文件: {0}" -f $ZipPath)
Write-Host ("  版本: {0}（解析自代码；git 标签应为 {1}）" -f $UseVersion, $VersionTag)
Write-Host ("  体积: {0:N0} 字节（未压缩内容 {1:N0} 字节，压缩率 {2:P1}）" -f `
            $zipLen, $totalInZip, $ratio)
Write-Host ("  SHA256: {0}" -f $sha)
Write-Host ""
Write-Host ("  条目清单（{0} 条）:" -f $zipInfo.Count)
Write-Host ("    {0,-50} {1,12} {2,12}" -f "条目名（zip 内路径，统一 /）", "原始", "压缩后")
Write-Host ("    {0} {1} {2}" -f ("-" * 50), ("-" * 12), ("-" * 12))
foreach ($e in ($zipInfo.Values | Sort-Object Name)) {
    Write-Host ("    {0,-50} {1,12:N0} {2,12:N0}" -f $e.Name, $e.Size, $e.Packed)
}

# ---------------------------------------------------------------- 8. dll 自洽性核对

Write-Host ""
Write-Host "== NVDA 客户端 dll =="
Write-Host ("  来源: {0}" -f $dllSrc)
Write-Host ("  SHA256: {0}" -f (Get-Sha256 $dllSrc))
$installed = Join-Path (Join-Path "F:\Steam\steamapps\common" $GameDirNm) $NVDA_DLL_NAME
if (Test-Path -LiteralPath $installed -PathType Leaf) {
    $h1 = Get-Sha256 $dllSrc
    $h2 = Get-Sha256 $installed
    if ($h1 -eq $h2) {
        Write-Host ("  与游戏目录里已装的那一份逐字节相同：{0}  OK" -f $installed)
    } else {
        Write-Warning ("与游戏目录里那一份**不一致**：{0} vs {1}（{2}）" -f $h1, $h2, $installed)
        Write-Warning "  若确实要换 dll，请同步更新 THIRD-PARTY-NOTICES.md 里的说明与版本"
    }
} else {
    Write-Host "  游戏目录里没有已装的 dll，跳过一致性比对"
}

Write-Host ""
Write-Host "完成。这个 zip 里只有补丁 .rpy + 玩家文档 + NVDA 客户端 dll，没有任何游戏资源。"
Write-Host "      **解压即用**：玩家把 zip 解压到游戏根目录（与 OurBriefEternity.exe 同级）、"
Write-Host "      选「合并 / 覆盖」就装完了 —— 包里没有安装器，也不需要跑任何脚本。"
exit 0
