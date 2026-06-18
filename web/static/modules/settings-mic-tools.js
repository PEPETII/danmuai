import { apiFetch } from './transport.js';

let micToolsDeps = {
  showToast: () => {},
};

export function configureSettingsMicTools(deps) {
  micToolsDeps = { ...micToolsDeps, ...deps };
}

export function bindMicTestControls() {
  document.getElementById('btnMicTest')?.addEventListener('click', async () => {
    const btn = document.getElementById('btnMicTest');
    const sendBtn = document.getElementById('btnMicTestSend');
    const statusEl = document.getElementById('micTestStatus');
    if (!btn) return;
    btn.disabled = true;
    if (sendBtn) sendBtn.disabled = true;
    if (statusEl) statusEl.textContent = '录音中…请对着麦克风随便念几句话';
    micToolsDeps.showToast('请对着麦克风随便念几句话（约 3 秒）');
    try {
      const res = await apiFetch('/api/mic/test', {
        method: 'POST',
        body: JSON.stringify({ duration_sec: 3 }),
      });
      const deviceLabel = res.active_input_device_label || res.default_input || '未知输入设备';
      const fallbackBit = res.fallback_to_default ? ' · 已回退默认输入' : '';
      const detail = `${deviceLabel}${fallbackBit} · pcm=${res.pcm_bytes || 0}B · rms=${res.rms ?? 0} · ${res.level || 'unknown'}`;
      if (statusEl) {
        statusEl.textContent = detail;
      }
      micToolsDeps.showToast(res.message || (res.ok ? '麦克风测试通过' : '麦克风测试未通过'), !res.ok);
    } catch (error) {
      if (statusEl) statusEl.textContent = '测试失败';
      micToolsDeps.showToast(error.message || '麦克风测试失败', true);
    } finally {
      btn.disabled = false;
      if (sendBtn) sendBtn.disabled = false;
    }
  });

  document.getElementById('btnMicTestSend')?.addEventListener('click', async () => {
    const btn = document.getElementById('btnMicTestSend');
    const micBtn = document.getElementById('btnMicTest');
    const statusEl = document.getElementById('micTestStatus');
    if (!btn) return;
    btn.disabled = true;
    if (micBtn) micBtn.disabled = true;
    if (statusEl) statusEl.textContent = '录音并发送中…请对着麦克风念几句话';
    micToolsDeps.showToast('录音约 3 秒后将发送到 AI，请对着麦克风说话');
    try {
      const res = await apiFetch('/api/mic/test', {
        method: 'POST',
        body: JSON.stringify({ duration_sec: 3, send_to_ai: true }),
      });
      const deviceLabel = res.active_input_device_label || res.default_input || '未知输入设备';
      const fallbackBit = res.fallback_to_default ? ' · 已回退默认输入' : '';
      const detail = `${deviceLabel}${fallbackBit} · input=${res.input_tokens ?? 0} · output=${res.output_tokens ?? 0} · pcm=${res.pcm_bytes || 0}B`;
      if (statusEl) {
        statusEl.textContent = res.reply_preview
          ? `${detail} · ${res.reply_preview}`
          : detail;
      }
      micToolsDeps.showToast(res.message || (res.ok ? '测试发送成功' : '测试发送失败'), !res.ok);
    } catch (error) {
      if (statusEl) statusEl.textContent = '测试发送失败';
      micToolsDeps.showToast(error.message || '测试发送失败', true);
    } finally {
      btn.disabled = false;
      if (micBtn) micBtn.disabled = false;
    }
  });
}
