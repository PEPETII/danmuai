// W-BILILIVE-DM-PLUGIN-PUSH-004: DanmuAI 主链路主动推送本地接收端。
// DanmuAI POST http://127.0.0.1:18766/api/plugin/danmuai/push/ → AddDM() 本地显示。
// 与 BRIDGE-003（插件 → DanmuAI /reply）方向相反；失败只 Log()，不抛到宿主。

using System;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;

namespace DanmuAiMockPlugin
{
    public sealed class DanmuAiPushListener : IDisposable
    {
        // 与 app/web_api/bililive_dm_push.py 常量对齐
        public const string PushListenerPrefix = "http://127.0.0.1:18766/api/plugin/danmuai/push/";
        private const int MaxItems = 5;
        private const int MaxItemChars = 60;

        private readonly Action<string> _log;
        private readonly Action<string> _addDm;
        private readonly HttpListener _listener;
        private CancellationTokenSource _cts;
        private Task _acceptTask;

        public DanmuAiPushListener(Action<string> log, Action<string> addDm)
        {
            _log = log ?? (_ => { });
            _addDm = addDm ?? (_ => { });
            _listener = new HttpListener();
            _listener.Prefixes.Add(PushListenerPrefix);
        }

        public bool IsRunning { get; private set; }

        public void Start()
        {
            if (IsRunning)
            {
                return;
            }

            try
            {
                _listener.Start();
                _cts = new CancellationTokenSource();
                _acceptTask = Task.Run(() => AcceptLoopAsync(_cts.Token));
                IsRunning = true;
                _log("push listener started: " + PushListenerPrefix);
            }
            catch (Exception ex)
            {
                _log("push listener start failed: " + ex.Message);
            }
        }

        public void Stop()
        {
            if (!IsRunning)
            {
                return;
            }

            try
            {
                _cts?.Cancel();
                if (_listener.IsListening)
                {
                    _listener.Stop();
                }
            }
            catch (Exception ex)
            {
                _log("push listener stop exception: " + ex.Message);
            }
            finally
            {
                IsRunning = false;
                _log("push listener stopped");
            }
        }

        public void Dispose()
        {
            Stop();
            _cts?.Dispose();
        }

        private async Task AcceptLoopAsync(CancellationToken token)
        {
            while (!token.IsCancellationRequested)
            {
                HttpListenerContext context = null;
                try
                {
                    context = await _listener.GetContextAsync().ConfigureAwait(false);
                }
                catch (HttpListenerException)
                {
                    // listener.Stop() 会中断 GetContextAsync
                    break;
                }
                catch (ObjectDisposedException)
                {
                    break;
                }
                catch (Exception ex)
                {
                    _log("push accept exception: " + ex.Message);
                    continue;
                }

                if (context == null)
                {
                    continue;
                }

                _ = Task.Run(() => HandleRequestAsync(context));
            }
        }

        private async Task HandleRequestAsync(HttpListenerContext context)
        {
            var response = context.Response;
            try
            {
                var request = context.Request;
                if (!string.Equals(request.HttpMethod, "POST", StringComparison.OrdinalIgnoreCase))
                {
                    await WriteJsonAsync(response, 405, new PushResponse
                    {
                        ok = false,
                        error = "method_not_allowed",
                        displayed = 0,
                    }).ConfigureAwait(false);
                    return;
                }

                string body;
                using (var reader = new StreamReader(request.InputStream, request.ContentEncoding ?? Encoding.UTF8))
                {
                    body = await reader.ReadToEndAsync().ConfigureAwait(false);
                }

                PushRequest payload;
                try
                {
                    payload = JsonConvert.DeserializeObject<PushRequest>(body);
                }
                catch (Exception ex)
                {
                    await WriteJsonAsync(response, 400, new PushResponse
                    {
                        ok = false,
                        error = "invalid_json:" + ex.Message,
                        displayed = 0,
                    }).ConfigureAwait(false);
                    return;
                }

                if (payload == null || payload.items == null || payload.items.Length == 0)
                {
                    await WriteJsonAsync(response, 400, new PushResponse
                    {
                        ok = false,
                        error = "empty_items",
                        displayed = 0,
                    }).ConfigureAwait(false);
                    return;
                }

                var sanitized = SanitizeItems(payload.items);
                if (sanitized.Length == 0)
                {
                    await WriteJsonAsync(response, 400, new PushResponse
                    {
                        ok = false,
                        error = "empty_items",
                        displayed = 0,
                    }).ConfigureAwait(false);
                    return;
                }

                int displayed = 0;
                foreach (var item in sanitized)
                {
                    try
                    {
                        _addDm(item);
                        displayed++;
                    }
                    catch (Exception ex)
                    {
                        _log("push AddDM exception: " + ex.Message);
                    }
                }

                _log("push received batch_id=" + payload.batch_id + " displayed=" + displayed);
                await WriteJsonAsync(response, 200, new PushResponse
                {
                    ok = true,
                    error = null,
                    displayed = displayed,
                }).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                try
                {
                    _log("push handle exception: " + ex.Message);
                    await WriteJsonAsync(response, 500, new PushResponse
                    {
                        ok = false,
                        error = "internal_error",
                        displayed = 0,
                    }).ConfigureAwait(false);
                }
                catch
                {
                    // 绝不让异常冒泡到弹幕姬宿主
                }
            }
        }

        private static string[] SanitizeItems(string[] items)
        {
            var result = new System.Collections.Generic.List<string>();
            var seen = new System.Collections.Generic.HashSet<string>();
            foreach (var raw in items)
            {
                if (raw == null)
                {
                    continue;
                }
                var text = raw.Replace("\r", "").Trim();
                if (string.IsNullOrWhiteSpace(text))
                {
                    continue;
                }
                if (text.Length > MaxItemChars)
                {
                    text = text.Substring(0, MaxItemChars - 1) + "…";
                }
                if (seen.Contains(text))
                {
                    continue;
                }
                seen.Add(text);
                result.Add(text);
                if (result.Count >= MaxItems)
                {
                    break;
                }
            }
            return result.ToArray();
        }

        private static async Task WriteJsonAsync(HttpListenerResponse response, int statusCode, PushResponse payload)
        {
            var json = JsonConvert.SerializeObject(payload);
            var buffer = Encoding.UTF8.GetBytes(json);
            response.StatusCode = statusCode;
            response.ContentType = "application/json; charset=utf-8";
            response.ContentLength64 = buffer.Length;
            await response.OutputStream.WriteAsync(buffer, 0, buffer.Length).ConfigureAwait(false);
            response.OutputStream.Close();
        }

        public sealed class PushRequest
        {
            public string source { get; set; }
            public int batch_id { get; set; }
            public string[] items { get; set; }
            public string persona { get; set; }
        }

        public sealed class PushResponse
        {
            public bool ok { get; set; }
            public string error { get; set; }
            public int displayed { get; set; }
        }
    }
}
