# Enumerate all loaded .NET assemblies inside the 弹幕姬 process via
# CreateRemoteThread + GetAssemblies; fall back to clr.dll module walk.
$bililive = Get-Process -Id 33608 -ErrorAction SilentlyContinue
if (-not $bililive) { Write-Error "弹幕姬 not found"; exit 1 }

# PowerShell can't directly enumerate AppDomain assemblies; use reflection
# over a temporary in-process injected script. Easiest: walk System.Diagnostics.Process
# Modules and look for any assembly with our plugin GUID/PE marker.
# Without injecting code, the cleanest probe is: ask the SDK what assemblies
# are reachable via Assembly.LoadFrom. That requires in-proc execution.
# So we'll use a different approach: use the WMI Win32_Process to find loaded
# native DLLs (we already did) and look for any "B站" plugin file via
# handle enumeration.
# Pragmatic short-cut: enumerate ALL native modules and grep for our DLLs
# by substring (case-insensitive). Note: .NET Framework loadable
# assemblies don't always appear in Process.Modules for powershell.exe
# remote, but a CreateToolhelp32Snapshot does. Let's use a small C# probe.

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Collections.Generic;
public static class Nt {
    [DllImport("kernel32.dll")] static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint pid);
    [DllImport("kernel32.dll")] static extern bool Module32First(IntPtr h, ref MODULEENTRY32 m);
    [DllImport("kernel32.dll")] static extern bool Module32Next(IntPtr h, ref MODULEENTRY32 m);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    public struct MODULEENTRY32 { public uint dwSize; public uint th32ModuleID; public uint th32ProcessID; public uint GlsSnapCount; public uint ProccntUsage; public IntPtr modBaseAddr; public uint modBaseSize; public IntPtr hModule; [MarshalAs(UnmanagedType.ByValTStr, SizeConst=256)] public string szModule; [MarshalAs(UnmanagedType.ByValTStr, SizeConst=260)] public string szExePath; }
    public static List<string> AllModules(uint pid) {
        var L = new List<string>();
        IntPtr h = CreateToolhelp32Snapshot(0x8, pid);
        if (h == IntPtr.Zero) return L;
        var m = new MODULEENTRY32(); m.dwSize = (uint)Marshal.SizeOf(m);
        if (Module32First(h, ref m)) {
            do { L.Add(m.szExePath); } while (Module32Next(h, ref m));
        }
        CloseHandle(h);
        return L;
    }
}
"@ -ErrorAction SilentlyContinue
[Nt]::AllModules(33608) | Where-Object { $_ -match "Mock|Plugin|Framework|弹幕|Newtonsoft" } | Sort-Object -Unique
