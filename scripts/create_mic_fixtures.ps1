# Synthetic Korean user speech only. Generated WAVs stay outside Git.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$output = Join-Path $PSScriptRoot '../artifacts/mic-e2e'
New-Item -ItemType Directory -Force $output | Out-Null
$cases = @{
    normal = '오늘은 일이 많아서 조금 지쳤어요. 잠깐 숨을 돌리고 싶어요. 따뜻하게 한 문장으로 이야기해 주세요.'
    short = '네 라고만 짧게 대답해 주세요.'
    interrupt = '마음이 복잡할 때 편안하게 쉬는 방법을 다섯 가지 알려 주세요. 각 방법을 자세하게 설명해 주세요.'
}
foreach ($name in $cases.Keys) {
    $speech = New-Object System.Speech.Synthesis.SpeechSynthesizer
    try {
        $speech.SelectVoice('Microsoft Heami Desktop')
        $speech.SetOutputToWaveFile((Join-Path $output "$name.wav"))
        $speech.Speak($cases[$name])
    } finally { $speech.Dispose() }
}
$cases | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $output 'fixtures.json')
