# Optional local perception OCR

Perception reviews immutable captured image bytes. Qt checks decoding and pixel limits; an optional injected text extractor can add text observations. The built-in Windows adapter uses Windows.Media.Ocr through Windows PowerShell and never sends images to a network service.

Enable it explicitly with `AIDA_LOCAL_OCR_ENABLED=1` in the desktop runtime environment. No extra Python package or downloaded OCR model is required. The host must provide the WinRT OCR APIs and a supported Windows OCR language pack; unsupported hosts and missing language packs produce an explicit unavailable result. The normal image review still works with OCR disabled.

The adapter sends base64 snapshot bytes over stdin to a fixed application script. It does not interpolate image text into shell code, write temporary image files, or reread the original selected path. Its subprocess is hidden, bounded to eight seconds by default (maximum fifteen), and reaped by subprocess.run on timeout. Input is capped at 20 MiB, decoding checks the OS maximum image dimension and a 16-million-pixel ceiling, and extracted text is capped at 8,000 characters.

Extracted text appears only as quoted, untrusted evidence in the local review. It is not routed as a command, added to Brain context, executed, or used to authorize an action. OCR is fallible and does not supply a diagnosis; semantic image interpretation remains unavailable.

The implementation follows the documented [OcrEngine API](https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr.ocrengine?view=winrt-26100), [WinRT AsTask projection](https://learn.microsoft.com/en-us/dotnet/api/system.windowsruntimesystemextensions.astask?view=dotnet-uwp-10.0), [BitmapDecoder](https://learn.microsoft.com/en-us/uwp/api/windows.graphics.imaging.bitmapdecoder.getsoftwarebitmapasync?view=winrt-26100), and [DataWriter.StoreAsync](https://learn.microsoft.com/en-us/uwp/api/windows.storage.streams.datawriter.storeasync?view=winrt-26100).

Automated tests inject fake subprocess and extractor boundaries; they never invoke real OCR or upload data. Native acceptance remains required on Windows 10/11 with and without the installed OCR language pack, including timeout, large-image and hostile text cases.
