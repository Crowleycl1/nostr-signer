<#
Convierte la grabacion de la demo (MP4) en el GIF de la entrega (docs/demo.gif).

Por que asi: ScreenToGif no esta instalado, pero Windows ya trae grabador (Win+Alt+R,
Xbox Game Bar -> C:\Users\<tu>\Videos\Captures) y en esta maquina ya hay ffmpeg. Con eso
alcanza y no hay que instalar nada.

Dos pasadas con paleta propia: un GIF solo admite 256 colores, y dejar que ffmpeg elija
la paleta mirando todo el video (palettegen) en vez de usar la paleta web fija evita que
el texto de la terminal y la UI queden sucios.

Uso:
    powershell -ExecutionPolicy Bypass -File herramientas\gif.ps1 -Entrada "$env:USERPROFILE\Videos\Captures\demo.mp4"
    ... -Desde 3 -Duracion 45      # recorta: empieza en el segundo 3, dura 45
    ... -Ancho 960 -Fps 8          # si el GIF pasa de 10 MB
#>
param(
    [Parameter(Mandatory = $true)][string]$Entrada,
    [string]$Salida = "",
    [int]$Ancho = 1280,
    [int]$Fps = 10,
    [double]$Desde = 0,
    [double]$Duracion = 0
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
if (-not $Salida) { $Salida = Join-Path $raiz "docs\demo.gif" }
if (-not (Test-Path $Entrada)) { throw "No existe: $Entrada" }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw "Falta ffmpeg en el PATH" }

$recorte = @()
if ($Desde -gt 0) { $recorte += @("-ss", "$Desde") }
if ($Duracion -gt 0) { $recorte += @("-t", "$Duracion") }

$paleta = Join-Path $env:TEMP "paleta-demo.png"
$filtro = "fps=$Fps,scale=${Ancho}:-1:flags=lanczos"

Write-Host "1/2 calculando paleta..."
& ffmpeg -hide_banner -loglevel error -y @recorte -i $Entrada -vf "$filtro,palettegen=stats_mode=diff" $paleta
if ($LASTEXITCODE -ne 0) { throw "ffmpeg fallo al generar la paleta" }

Write-Host "2/2 escribiendo $Salida ..."
& ffmpeg -hide_banner -loglevel error -y @recorte -i $Entrada -i $paleta `
    -lavfi "$filtro [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" `
    -loop 0 $Salida
if ($LASTEXITCODE -ne 0) { throw "ffmpeg fallo al escribir el GIF" }
Remove-Item $paleta -ErrorAction SilentlyContinue

$mb = [math]::Round((Get-Item $Salida).Length / 1MB, 2)
Write-Host "Listo: $Salida  ($mb MB)"
if ($mb -ge 10) {
    Write-Warning "GitHub no muestra inline un GIF de 10 MB o mas. Repite con -Fps 8 -Ancho 960, o recorta con -Desde/-Duracion."
} else {
    Write-Host "Cabe en GitHub (menos de 10 MB)." -ForegroundColor Green
}
