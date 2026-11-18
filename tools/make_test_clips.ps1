# Generates the routing, latency and judder test clips into test-clips\.
# H.264 4:2:0 needs even dimensions, so the center clip is 2308x1076 rather than 2308x1075.

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $Root 'test-clips'
New-Item -ItemType Directory -Force -Path $Out | Out-Null

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw 'FFmpeg was not found. Run: winget install Gyan.FFmpeg, then open a new PowerShell window.'
}

$Font = 'C\:/Windows/Fonts/arialbd.ttf'
$Seconds = 120
$Encode = @('-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-g', '30', '-an', '-movflags', '+faststart')

function Get-Labels([string]$Title) {
    return "drawtext=fontfile='$Font':text='$Title':fontsize=220:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2-170," +
           "drawtext=fontfile='$Font':text='%{n}':fontsize=110:fontcolor=white:box=1:boxcolor=black:boxborderw=14:x=(w-text_w)/2:y=(h/2)+40," +
           "drawtext=fontfile='$Font':text='%{pts\:hms}':fontsize=110:fontcolor=white:box=1:boxcolor=black:boxborderw=14:x=(w-text_w)/2:y=(h/2)+200"
}

function New-Clip([string]$Name, [string]$Background, [string]$Bar, [string]$Filter) {
    Write-Host "Creating $Name ..."
    $Arguments = @(
        '-y', '-hide_banner', '-loglevel', 'error',
        '-f', 'lavfi', '-i', "color=c=${Background}:r=60:d=$Seconds",
        '-f', 'lavfi', '-i', "color=c=white:s=${Bar}:r=60:d=$Seconds",
        '-filter_complex', $Filter
    ) + $Encode + @((Join-Path $Out $Name))
    & ffmpeg @Arguments
    if ($LASTEXITCODE -ne 0) { throw "FFmpeg failed while creating $Name" }
}

New-Clip 'TEST_CENTER.mov' '0xC81414:s=2308x1076' '60x1076' `
    ("[0:v][1:v]overlay=x='mod(t,1)*(W-w)':y=0:shortest=1," + (Get-Labels 'CENTER'))

New-Clip 'TEST_SIDE.mov' '0x1430C8:s=1920x1080' '1920x60' `
    ("[0:v][1:v]overlay=x=0:y='mod(t,1)*(H-h)':shortest=1," + (Get-Labels 'SIDE'))

New-Clip 'TEST_JUDDER.mov' 'black:s=1920x1080' '32x1080' `
    "[0:v][1:v]overlay=x='mod(n*32,W)':y=0:shortest=1"

Write-Host "Done. Clips are in $Out"
