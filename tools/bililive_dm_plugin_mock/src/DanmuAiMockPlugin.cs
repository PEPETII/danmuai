// W-BILILIVE-DM-PLUGIN-MOCK-001 + W-BILILIVE-DM-PLUGIN-BRIDGE-002 + PUSH-004:
// Minimal bililive_dm DMPlugin that:
//   - Validates Start / Stop / Admin / ReceivedDanmaku(Comment) -> AddDM()
//     local-display chain (mock-001).
//   - Posts each Comment to DanmuAI's local bridge endpoint
//     (POST http://127.0.0.1:18765/api/plugin/bililive-dm/reply) and
//     AddDM()s every returned item (mock-bridge-002).
//
// Scope (mock-bridge-002):
//   - LOCAL bypass bridge only. AddDM() writes to the bililive_dm host's
//     local danmaku layer; it does NOT push anything back to the live
//     room. There is no auth, no retry policy, no fallback to main AI
//     pipeline (see W-BILILIVE-DM-PLUGIN-BRIDGE-002 for contract).
//
// Failure isolation:
//   - HTTP failure / timeout / non-2xx / malformed JSON / empty items
//     only writes a Log() line; the host must not crash, must not freeze.
//   - The HTTP call is fire-and-forget so ReceivedDanmaku() returns
//     immediately and the host's danmaku pump is never blocked.

using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using BilibiliDM_PluginFramework;
using Newtonsoft.Json;

namespace DanmuAiMockPlugin
{
    public class DanmuAiMockPlugin : DMPlugin
    {
        // Preset danmu lines exposed via Admin() for manual verification.
        // Five flavors required by the mock-001 work order: short CN / long CN /
        // user-prefixed / AI reply style / degradation hint. These are
        // displayed locally via AddDM(); nothing leaves the host.
        private static readonly string[] PresetDanmu =
        {
            "【mock-短】你好弹幕姬",
            "【mock-长】这是一条较长的中文预置弹幕，用来验证 AddDM 在长文本下的本地显示效果。",
            "【mock-评论】用户: 小电视 -> 弹幕: 前排打卡！",
            "【mock-AI】AI 回复：笑死，这直播间的氛围也太欢乐了吧。",
            "【mock-降级】注意：插件当前未连接 DanmuAI，仅做本地链路演示。"
        };

        // W-BILILIVE-DM-PLUGIN-BRIDGE-002: bridge endpoint constants.
        // DanmuAI Web Console binds 127.0.0.1:18765 (see app/web_console.py).
        // Path must match app/web_api/bililive_dm_bridge.py:BRIDGE_PATH.
        private const string BridgeEndpoint = "http://127.0.0.1:18765/api/plugin/bililive-dm/reply";
        private const int BridgeTimeoutSec = 3;
        private const string PluginSecretHeader = "X-DanmuAI-Plugin-Secret";

        // Shared HttpClient — single instance avoids socket exhaustion per
        // comment event. Disposed in DeInit().
        private static readonly HttpClient SharedHttpClient = CreateHttpClient();

        // W-BILILIVE-DM-PLUGIN-PUSH-004: 接收 DanmuAI 主链路主动推送。
        private DanmuAiPushListener _pushListener;

        private static HttpClient CreateHttpClient()
        {
            var client = new HttpClient
            {
                Timeout = TimeSpan.FromSeconds(BridgeTimeoutSec),
            };
            return client;
        }

        private static string TryReadPluginSecret()
        {
            try
            {
                var appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
                var path = Path.Combine(appData, "DanmuAI", "bililive_dm_plugin.secret");
                if (!File.Exists(path))
                {
                    return null;
                }
                var text = File.ReadAllText(path).Trim();
                return string.IsNullOrEmpty(text) ? null : text;
            }
            catch
            {
                return null;
            }
        }

        // DTOs — mirror app/web_api/bililive_dm_bridge.py schema.
        // Field names are deliberately snake_case so Newtonsoft.Json's default
        // serializer (no [JsonProperty] attribute needed) produces the wire
        // format the DanmuAI bridge expects.
        public sealed class BridgeRequest
        {
            public int? room_id { get; set; }
            public string user_name { get; set; }
            public string user_id { get; set; }
            public string text { get; set; }
        }

        public sealed class BridgeResponse
        {
            public bool ok { get; set; }
            public string error { get; set; }
            public string[] items { get; set; }
        }

        public DanmuAiMockPlugin()
        {
            PluginName = "DanmuAI Mock Plugin";
            PluginAuth = "danmuai-local";
            PluginCont = "n/a (W-BILILIVE-DM-PLUGIN-MOCK-001 + BRIDGE-002 PoC)";
            PluginVer = "0.3.0-push";
            PluginDesc =
                "W-BILILIVE-DM-PLUGIN-MOCK-001: 本地链路 PoC；" +
                "W-BILILIVE-DM-PLUGIN-BRIDGE-002/003: 评论事件 → DanmuAI 旁路桥接；" +
                "W-BILILIVE-DM-PLUGIN-PUSH-004: DanmuAI 生成按钮 → 本地 HttpListener 推送；" +
                "AddDM() 仅本地显示，不向 B 站直播间自动发弹幕。";

            ReceivedDanmaku += OnReceivedDanmaku;
        }

        public override void Start()
        {
            // base.Start() flips Status and writes "PluginName Start!" to stdout.
            base.Start();
            try
            {
                Log("插件已启动（Start）");
                AddDM("【mock】插件已启动，本地显示验证。");
                _pushListener = new DanmuAiPushListener(Log, text => AddDM(text));
                _pushListener.Start();
            }
            catch (Exception ex)
            {
                Log("Start 异常：" + ex.Message);
            }
        }

        public override void Stop()
        {
            base.Stop();
            try
            {
                _pushListener?.Stop();
                _pushListener?.Dispose();
                _pushListener = null;
                Log("插件已停止（Stop）");
            }
            catch (Exception ex)
            {
                Log("Stop 异常：" + ex.Message);
            }
        }

        public override void Inited()
        {
            try
            {
                Log("插件已 Inited（所有插件加载完毕）");
            }
            catch (Exception ex)
            {
                Log("Inited 异常：" + ex.Message);
            }
        }

        public override void DeInit()
        {
            try
            {
                Log("插件已 DeInit（弹幕姬主程序退出）");
                ReceivedDanmaku -= OnReceivedDanmaku;
                _pushListener?.Stop();
                _pushListener?.Dispose();
                _pushListener = null;
                SharedHttpClient.Dispose();
            }
            catch (Exception ex)
            {
                Log("DeInit 异常：" + ex.Message);
            }
        }

        public override void Admin()
        {
            // Manual verification entry point: push 5 preset danmu lines
            // through AddDM() one at a time, with per-line try/catch so a
            // single failure does not abort the rest of the sequence.
            foreach (var line in PresetDanmu)
            {
                try
                {
                    AddDM(line);
                }
                catch (Exception ex)
                {
                    Log("AddDM 异常：" + ex.Message);
                }
            }
        }

        private void OnReceivedDanmaku(object sender, ReceivedDanmakuArgs e)
        {
            // Bridge-002 entry: only Comment events get bridged. Other event
            // types (gifts, welcomes, SC, ...) are intentionally ignored —
            // this matches W-BILILIVE-DM-PLUGIN-BRIDGE-002 §"非目标".
            if (e == null || e.Danmaku == null)
            {
                return;
            }

            if (e.Danmaku.MsgType != MsgTypeEnum.Comment)
            {
                return;
            }

            string userName = e.Danmaku.UserName ?? "匿名";
            string userId = e.Danmaku.UserID_str ?? string.Empty;
            string text = e.Danmaku.CommentText ?? string.Empty;

            try
            {
                Log("收到评论：" + userName + " => " + text);
            }
            catch
            {
                // Log() must never bubble up here.
            }

            // Fire-and-forget so the host's danmaku pump is not blocked.
            // All failure paths inside CallDanmuAiAsync swallow exceptions
            // and only write a Log() line.
            _ = CallDanmuAiAsync(userName, userId, text);
        }

        // Bridge-002: POST comment event to DanmuAI's local bridge endpoint
        // and AddDM() every returned item. Never throws; never blocks the
        // host. Total budget is bounded by HttpClient.Timeout.
        private async Task CallDanmuAiAsync(string userName, string userId, string text)
        {
            try
            {
                var req = new BridgeRequest
                {
                    room_id = this.RoomId,
                    user_name = userName,
                    user_id = userId,
                    text = text,
                };

                string json = JsonConvert.SerializeObject(req);
                using (var content = new StringContent(
                    json,
                    Encoding.UTF8,
                    "application/json"))
                using (var request = new HttpRequestMessage(HttpMethod.Post, BridgeEndpoint))
                {
                    request.Content = content;
                    var secret = TryReadPluginSecret();
                    if (!string.IsNullOrEmpty(secret))
                    {
                        request.Headers.TryAddWithoutValidation(PluginSecretHeader, secret);
                    }

                    using (var resp = await SharedHttpClient.SendAsync(request))
                    {
                        // HttpClient throws on 4xx/5xx if we don't read the body
                        // and the request was non-success; we read either way
                        // so the bridge's diagnostic body is never wasted.
                        string body = await resp.Content.ReadAsStringAsync();

                        if (!resp.IsSuccessStatusCode)
                        {
                            Log("bridge http failed: " + (int)resp.StatusCode + " " + body);
                            return;
                        }

                        BridgeResponse data;
                        try
                        {
                            data = JsonConvert.DeserializeObject<BridgeResponse>(body);
                        }
                        catch (Exception ex)
                        {
                            Log("bridge json parse failed: " + ex.Message);
                            return;
                        }

                        if (data == null || !data.ok || data.items == null || data.items.Length == 0)
                        {
                            Log("bridge empty or failed: " + (data?.error ?? "unknown"));
                            return;
                        }

                        foreach (var item in data.items)
                        {
                            if (!string.IsNullOrWhiteSpace(item))
                            {
                                try
                                {
                                    AddDM(item);
                                }
                                catch (Exception ex)
                                {
                                    Log("bridge AddDM 异常：" + ex.Message);
                                }
                            }
                        }
                    }
                }
            }
            catch (TaskCanceledException)
            {
                // HttpClient.Timeout fires as TaskCanceledException on net461.
                Log("bridge timeout: " + BridgeTimeoutSec + "s");
            }
            catch (HttpRequestException ex)
            {
                Log("bridge http exception: " + ex.Message);
            }
            catch (Exception ex)
            {
                // Catch-all: bridge failures must never propagate back to
                // the bililive_dm host's ReceivedDanmaku pump.
                Log("bridge exception: " + ex.Message);
            }
        }
    }
}