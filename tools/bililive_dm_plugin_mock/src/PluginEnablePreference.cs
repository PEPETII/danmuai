// W-BILILIVE-DM-PLUGIN-AUTOENABLE-007: 插件侧用户启用偏好（宿主不记忆勾选时使用）。
// 与 DanmuAI config.db 无关；仅存「用户上次是否主动启用过本插件」。

using System;
using System.IO;

namespace DanmuAiMockPlugin
{
    internal static class PluginEnablePreference
    {
        // 与 bililive_dm 用户数据同目录，便于备份/排查
        private const string PreferenceFileName = "DanmuAI_MockPlugin_enabled.txt";
        private const string EnabledToken = "1";
        private const string DisabledToken = "0";

        private static string PreferencePath =>
            Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
                "弹幕姬",
                PreferenceFileName);

        public static bool ReadEnabled()
        {
            try
            {
                var path = PreferencePath;
                if (!File.Exists(path))
                {
                    return false;
                }

                var text = (File.ReadAllText(path) ?? string.Empty).Trim();
                return string.Equals(text, EnabledToken, StringComparison.Ordinal);
            }
            catch
            {
                return false;
            }
        }

        public static void WriteEnabled(bool enabled)
        {
            try
            {
                var path = PreferencePath;
                var dir = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                {
                    Directory.CreateDirectory(dir);
                }

                File.WriteAllText(path, enabled ? EnabledToken : DisabledToken);
            }
            catch
            {
                // 偏好写入失败不影响宿主；下次冷启动仍须手动启用
            }
        }
    }
}
