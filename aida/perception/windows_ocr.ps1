# Optional Windows-local OCR. Fixed code consumes base64 image bytes via stdin.
# WinRT API contracts: see docs/architecture/local-perception-ocr.md.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$stream = $null
$writer = $null
$bitmap = $null

function Await-Result($Operation, [Type]$ResultType) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq "AsTask" -and $_.IsGenericMethodDefinition -and
            $_.GetGenericArguments().Length -eq 1 -and
            $_.GetParameters().Length -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        } | Select-Object -First 1
    if (-not $method) { throw "WinRT task projection is unavailable." }
    $task = $method.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    if (-not $task.Wait(6000)) { throw "Local OCR operation timed out." }
    return $task.Result
}

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Storage.Streams.DataWriter, Windows.Foundation, ContentType = WindowsRuntime]
    $encoded = [Console]::In.ReadToEnd()
    if ($encoded.Length -gt 27962028) { throw "Input size limit exceeded." }
    $bytes = [Convert]::FromBase64String($encoded)
    if ($bytes.Length -eq 0 -or $bytes.Length -gt 20971520) { throw "Input size limit exceeded." }

    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) {
        '{"status":"unavailable","reason":"no_language"}'
        exit 0
    }
    $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
    $writer = New-Object Windows.Storage.Streams.DataWriter($stream)
    $writer.WriteBytes($bytes)
    $null = Await-Result ($writer.StoreAsync()) ([UInt32])
    $stream.Seek(0)
    $decoder = Await-Result ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $maximum = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension
    if ($decoder.PixelWidth -gt $maximum -or $decoder.PixelHeight -gt $maximum -or
        ([double]$decoder.PixelWidth * $decoder.PixelHeight) -gt 16000000) {
        '{"status":"unavailable","reason":"dimensions"}'
        exit 0
    }
    $bitmap = Await-Result ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await-Result ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $text = [string]$result.Text
    if ($text.Length -gt 8000) { $text = $text.Substring(0, 8000) }
    @{status = "available"; text = $text} | ConvertTo-Json -Compress
}
catch {
    # Do not echo source bytes, recognized content, host paths or exception data.
    '{"status":"unavailable","reason":"unavailable"}'
}
finally {
    if ($null -ne $bitmap) { $bitmap.Dispose() }
    if ($null -ne $writer) { $writer.Dispose() }
    if ($null -ne $stream) { $stream.Dispose() }
}
