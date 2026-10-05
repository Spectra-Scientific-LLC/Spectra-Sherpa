# Rebuild Windows ICO from the existing web/sidebar logo, preserving aspect ratio.
# Run from any directory using PowerShell on Windows.
param(
    [string]$Source = (Join-Path $PSScriptRoot '..\frontend\public\logo.png'),
    [string]$Destination = (Join-Path $PSScriptRoot 'electron\assets\logo.ico')
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$Original = [Drawing.Image]::FromFile((Resolve-Path $Source))
$Frames = @()
try {
    foreach ($Size in @(16, 24, 32, 48, 64, 128, 256)) {
        $Bitmap = New-Object Drawing.Bitmap($Size, $Size)
        $Graphics = [Drawing.Graphics]::FromImage($Bitmap)
        $Buffer = New-Object IO.MemoryStream
        try {
            $Graphics.Clear([Drawing.Color]::Transparent)
            $Graphics.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $Ratio = [Math]::Min($Size / $Original.Width, $Size / $Original.Height)
            $Width = [int][Math]::Round($Original.Width * $Ratio)
            $Height = [int][Math]::Round($Original.Height * $Ratio)
            $Graphics.DrawImage($Original, [int](($Size-$Width)/2), [int](($Size-$Height)/2), $Width, $Height)
            $Bitmap.Save($Buffer, [Drawing.Imaging.ImageFormat]::Png)
            $Frames += [pscustomobject]@{ Size=$Size; Bytes=$Buffer.ToArray() }
        } finally { $Buffer.Dispose(); $Graphics.Dispose(); $Bitmap.Dispose() }
    }
} finally { $Original.Dispose() }
$Stream = [IO.File]::Create($Destination)
$Writer = New-Object IO.BinaryWriter($Stream)
try {
    $Writer.Write([uint16]0)
    $Writer.Write([uint16]1)
    $Writer.Write([uint16]$Frames.Count)
    $Offset = 6 + 16 * $Frames.Count
    foreach ($Frame in $Frames) {
        $Dimension = if ($Frame.Size -eq 256) { 0 } else { $Frame.Size }
        $Writer.Write([byte]$Dimension)
        $Writer.Write([byte]$Dimension)
        $Writer.Write([byte]0)
        $Writer.Write([byte]0)
        $Writer.Write([uint16]1)
        $Writer.Write([uint16]32)
        $Writer.Write([uint32]$Frame.Bytes.Length)
        $Writer.Write([uint32]$Offset)
        $Offset += $Frame.Bytes.Length
    }
    foreach ($Frame in $Frames) { $Writer.Write([byte[]]$Frame.Bytes) }
} finally { $Writer.Dispose(); $Stream.Dispose() }
