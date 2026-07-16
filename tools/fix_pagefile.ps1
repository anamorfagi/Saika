# fix_pagefile.ps1 — задаёт файл подкачки Windows фиксированного размера
# 16-32 ГБ на системном диске. Лечит "os error 1455" (paging file too small /
# commitment limit) при загрузке Qwen3-TTS и прочих крупных моделей.
# Требует прав администратора (bat-обёртка их запрашивает). Нужна перезагрузка.
$ErrorActionPreference = 'Stop'

$drive = $env:SystemDrive          # обычно C:
$path  = "$drive\pagefile.sys"
$init  = 16384                     # начальный размер, МБ
$max   = 32768                     # максимальный размер, МБ

Write-Host "Настраиваю файл подкачки: $path  ($init-$max МБ)..." -ForegroundColor Cyan

# 1) выключить "автоматически выбирать объём файла подкачки"
$cs = Get-CimInstance Win32_ComputerSystem
if ($cs.AutomaticManagedPagefile) {
    Set-CimInstance -InputObject $cs -Property @{ AutomaticManagedPagefile = $false }
    Write-Host "  автоуправление отключено" -ForegroundColor DarkGray
}

# 2) задать явный размер через реестр (REG_MULTI_SZ PagingFiles).
#    Формат строки: "<путь> <начальный> <максимальный>"
$mm = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management'
Set-ItemProperty -Path $mm -Name 'PagingFiles' `
    -Value @("$path $init $max") -Type MultiString

# 3) проверка диска: хватит ли места под максимум
$freeGb = [math]::Round((Get-PSDrive ($drive.TrimEnd(':'))).Free / 1GB, 1)
Write-Host ("Свободно на {0}: {1} ГБ (нужно ~{2} ГБ под максимум)" -f `
    $drive, $freeGb, [math]::Round($max/1024,0)) -ForegroundColor DarkGray

Write-Host ""
Write-Host "Готово. Перезагрузи компьютер, чтобы файл подкачки применился." -ForegroundColor Green
if ($freeGb -lt ($max/1024)) {
    Write-Host "ВНИМАНИЕ: на диске меньше $([math]::Round($max/1024,0)) ГБ свободно — " `
               "освободи место, иначе подкачка не вырастет до максимума." -ForegroundColor Yellow
}
Read-Host "Нажми Enter для выхода"
