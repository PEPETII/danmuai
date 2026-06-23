using System;
using System.IO;
using System.Linq;
using System.Reflection;

class Probe
{
    static int Main()
    {
        var pluginsDir = @"C:\Users\KING\Documents\弹幕姬\Plugins";
        var hostDir = @"C:\Users\KING\AppData\Local\Apps\2.0\WWW1BL9A.TX6\L33M87L4.ZZ4\bili..tion_0000000000000000_0001.0001_1a8ba1f777455ece";
        var dll = Path.Combine(pluginsDir, "BililiveDmMockPlugin.dll");

        AppDomain.CurrentDomain.ReflectionOnlyAssemblyResolve += (s, e) =>
        {
            var name = new AssemblyName(e.Name).Name;
            foreach (var d in new[] { pluginsDir, hostDir })
            {
                var hit = Path.Combine(d, name + ".dll");
                if (File.Exists(hit)) return Assembly.ReflectionOnlyLoadFrom(hit);
            }
            Console.WriteLine("  unresolvable: " + e.Name);
            return null;
        };

        try
        {
            var asm = Assembly.ReflectionOnlyLoadFrom(dll);
            Console.WriteLine("Loaded: " + asm.FullName);
            var t = asm.GetType("DanmuAiMockPlugin.DanmuAiMockPlugin");
            Console.WriteLine("Type: " + t?.FullName);

            // Look for CallDanmuAiAsync
            var m = t?.GetMethod("CallDanmuAiAsync", BindingFlags.NonPublic | BindingFlags.Instance);
            Console.WriteLine("CallDanmuAiAsync: " + m);
            if (m != null)
            {
                Console.WriteLine("  ReturnType: " + m.ReturnType);
                Console.WriteLine("  IsPublic: " + m.IsPublic + " IsPrivate: " + m.IsPrivate);
                Console.WriteLine("  GetILAsByteArray len: " + m.GetMethodBody().GetILAsByteArray().Length);
            }
            // Look for the consts
            var bridgeEndpoint = t?.GetField("BridgeEndpoint", BindingFlags.NonPublic | BindingFlags.Static);
            Console.WriteLine("BridgeEndpoint field: " + bridgeEndpoint);
            if (bridgeEndpoint != null)
            {
                var v = bridgeEndpoint.GetValue(null);
                Console.WriteLine("  Value: " + v);
            }
            var bridgeTimeout = t?.GetField("BridgeTimeoutSec", BindingFlags.NonPublic | BindingFlags.Static);
            Console.WriteLine("BridgeTimeoutSec field: " + bridgeTimeout);
            if (bridgeTimeout != null)
            {
                var v = bridgeTimeout.GetValue(null);
                Console.WriteLine("  Value: " + v);
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine("Top-level error: " + ex);
            if (ex is ReflectionTypeLoadException rtle)
                foreach (var l in rtle.LoaderExceptions) Console.WriteLine("  L: " + l.Message);
        }
        return 0;
    }
}
