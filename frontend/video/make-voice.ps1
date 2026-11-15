# Synthesises one WAV per narration line with the Windows speech engine (offline)
# and writes their durations, so the recording can hold each caption long enough.
#   powershell -File video\make-voice.ps1      (from frontend/)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$out = Join-Path (Split-Path -Parent $root) "video-output\voice"
New-Item -ItemType Directory -Force $out | Out-Null

$lines = Get-Content (Join-Path $root "narration.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice("Microsoft Zira Desktop")
$synth.Rate = 1
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(22050, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)

$durations = @{}
foreach ($line in $lines) {
    $path = Join-Path $out "$($line.id).wav"
    $synth.SetOutputToWaveFile($path, $format)
    $synth.Speak($line.speech)
    $synth.SetOutputToNull()
    $bytes = (Get-Item $path).Length - 44
    $durations[$line.id] = [int]($bytes / (22050 * 2) * 1000)
}
$synth.Dispose()
$durations | ConvertTo-Json | Set-Content (Join-Path $out "durations.json") -Encoding UTF8
"Generated $($lines.Count) clips, total $([int](($durations.Values | Measure-Object -Sum).Sum / 1000)) s of speech"
