"""The one fixed PowerShell script a poll runs; nothing is built from config or credential input."""

HEALTH_SCRIPT = (
    "$ErrorActionPreference='Stop';"
    "$cpu=(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average;"
    "$os=Get-CimInstance Win32_OperatingSystem;"
    "$disk=Get-CimInstance Win32_LogicalDisk -Filter \"DeviceID='C:'\";"
    "\"cpu=$cpu\";"
    "\"mem=$($os.TotalVisibleMemorySize) $($os.FreePhysicalMemory)\";"
    "\"disk=$($disk.Size) $($disk.FreeSpace)\";"
    "\"hostname=$env:COMPUTERNAME\""
)
