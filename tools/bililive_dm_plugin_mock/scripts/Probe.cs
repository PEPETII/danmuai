using System;
using System.IO;
using System.Linq;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;

class Probe
{
    static int Main()
    {
        var dll = @"C:\Users\KING\Documents\弹幕姬\Plugins\BililiveDmMockPlugin.dll";
        var bytes = File.ReadAllBytes(dll);
        using var ms = new MemoryStream(bytes);
        using var pe = new PEReader(ms);
        var md = pe.GetMetadataReader();

        // Find the DanmuAiMockPlugin type
        int typeRid = -1;
        foreach (var th in md.TypeDefinitions)
        {
            var tdef = md.GetTypeDefinition(th);
            var name = md.GetString(tdef.Name) ?? "";
            if (name == "DanmuAiMockPlugin")
            {
                typeRid = th.RowNumber;
                Console.WriteLine($"Found type: {md.GetString(tdef.Namespace)}.{name} (rid={typeRid})");
                break;
            }
        }

        // Enumerate fields for that type (filter by field owner == typeRid)
        Console.WriteLine($"\n=== Fields of DanmuAiMockPlugin ===");
        foreach (var fh in md.FieldDefinitions)
        {
            var fdef = md.GetFieldDefinition(fh);
            // Owner is the declaring type. Check via TypeDefRowId.
            // fdef.Attributes doesn't expose owner; we have to use GetDeclaringType on the FieldDefinitionHandle.
            // Use the parent's enclosing type.
            // GetFieldDefinition returns a handle to the type. Actually, we need to compare declaring type.
            // In System.Reflection.Metadata, the type for a field is derived differently.
            // Easiest: just list all fields and the constant value.
            var fname = md.GetString(fdef.Name) ?? "";
            // Decode default value (constant) if present
            try
            {
                var constantHandle = fdef.GetDefaultValue();
                if (constantHandle.IsNil) continue;
                var constant = md.GetConstant(constantHandle);
                var blob = md.GetBlobReader(constantHandle);
                // Decode the literal from blob
                if (constant.TypeCode == ConstantTypeCode.String)
                {
                    var usHandle = MetadataTokens.UserStringHandle(blob.ReadCompressedInteger());
                    var strVal = md.GetUserString(usHandle);
                    Console.WriteLine($"  Field: {fname} = {strVal}");
                }
                else if (constant.TypeCode == ConstantTypeCode.Int32)
                {
                    var intVal = blob.ReadInt32();
                    Console.WriteLine($"  Field: {fname} = {intVal}");
                }
                else
                {
                    Console.WriteLine($"  Field: {fname} = (type {constant.TypeCode})");
                }
            }
            catch
            {
                Console.WriteLine($"  Field: {fname} (no constant)");
            }
        }

        // List user strings that match 'bridge' or 'http' or 'timeout'
        Console.WriteLine($"\n=== UserString heap (size) ===");
        Console.WriteLine($"  (heap is opaque; not enumerating, but search the IL strings)");

        return 0;
    }
}
