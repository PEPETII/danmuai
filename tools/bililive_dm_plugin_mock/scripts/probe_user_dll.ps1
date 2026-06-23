# Inspect the deployed DLL's IL to confirm CallDanmuAiAsync is what we think
Add-Type -AssemblyName System.Reflection.Metadata
$dll = "C:\Users\KING\Documents\弹幕姬\Plugins\BililiveDmMockPlugin.dll"
$bytes = [System.IO.File]::ReadAllBytes($dll)
$ms = New-Object System.IO.MemoryStream (,$bytes)
$peReader = New-Object System.Reflection.PortableExecutable.PEReader($ms)
$mdReader = $peReader.GetMetadataReader()

# Enumerate all MemberReferences (calls to other assemblies)
"=== MemberReferences (external calls) ==="
foreach $mr in $mdReader.MemberReferences {
    $h = $mr.Parent
    $member = $mdReader.GetMemberReference($mr)
    $parent = $mdReader.GetString($member.Parent.ToString())
}

# Just dump all strings
"=== String heap (look for 'bridge ') ==="
$us = $mdReader.GetHeapMetadataOffset([System.Reflection.Metadata.HeapIndex.UserString])
"Searching for key strings..."
$xml = ""
$xmlDoc = New-Object System.Xml.XmlDocument
"Length: $($bytes.Length)"
