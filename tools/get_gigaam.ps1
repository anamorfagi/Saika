# Скачивает веса GigaAM v3_e2e_rnnt в кэш пакета (~/.cache/gigaam).
# Источник — CDN Сбера, НЕ huggingface. Запускать на машине с интернетом.
$ErrorActionPreference = "Stop"
$model = "v3_e2e_rnnt"
$md5   = "2730de7545ac43ad256485a462b0a27a"
$dir   = Join-Path $env:USERPROFILE ".cache\gigaam"
$base  = "https://cdn.chatwm.opensmodel.sberdevices.ru/GigaAM"
New-Item -ItemType Directory -Force -Path $dir | Out-Null

function Get-One($url, $dest) {
  if (Test-Path $dest) { Write-Host "уже есть: $dest"; return }
  Write-Host "качаю $url"
  Invoke-WebRequest -Uri $url -OutFile "$dest.part" -UseBasicParsing
  Move-Item "$dest.part" $dest -Force
  Write-Host "готово: $dest"
}

Get-One "$base/$model.ckpt"            (Join-Path $dir "$model.ckpt")
Get-One "$base/${model}_tokenizer.model" (Join-Path $dir "${model}_tokenizer.model")

$have = (Get-FileHash (Join-Path $dir "$model.ckpt") -Algorithm MD5).Hash.ToLower()
if ($have -ne $md5) {
  Write-Host "ПЛОХО: md5 $have, ждали $md5 — файл битый, удаляю"
  Remove-Item (Join-Path $dir "$model.ckpt") -Force
  exit 1
}
Write-Host "md5 сошёлся. GigaAM готов, перезапускать сборку не нужно — движок подхватит кэш при следующей загрузке СЛУХА."
