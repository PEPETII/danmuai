import { apiFetch } from './transport.js';
import { t } from './i18n.js';

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
    if (statusEl) statusEl.textContent = t('dynamic.settingsMicTools.录音中_请对着麦克风随便念几句话');
    micToolsDeps.showToast(t('dynamic.settingsMicTools.请对着麦克风随便念几句话_约_3_秒'));
    try {
      const res = await apiFetch('/api/mic/test', {
        method: 'POST',
        body: JSON.stringify({ duration_sec: 3 }),
      });
      const deviceLabel = res.active_input_device_label || res.default_input || t('dynamic.settingsMicTools.未知输入设备');
      const fallbackBit = res.fallback_to_default ? ` · ${t('dynamic.settingsMicTools.已回退默认输入')}` : '';
      const detail = `${deviceLabel}${fallbackBit} · pcm=${res.pcm_bytes || 0}B · rms=${res.rms ?? 0} · ${res.level || 'unknown'}`;
      if (statusEl) {
        statusEl.textContent = detail;
      }
      micToolsDeps.showToast(res.message || (res.ok ? t('dynamic.settingsMicTools.麦克风测试通过') : t('dynamic.settingsMicTools.麦克风测试未通过')), !res.ok);
    } catch (error) {
      if (statusEl) statusEl.textContent = t('dynamic.settingsMicTools.测试失败');
      micToolsDeps.showToast(error.message || t('dynamic.settingsMicTools.麦克风测试失败'), true);
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
    if (statusEl) statusEl.textContent = t('dynamic.settingsMicTools.录音并发送中_请对着麦克风念几句话');
    micToolsDeps.showToast(t('dynamic.settingsMicTools.录音约_3_秒后将发送到_AI_请对着麦克风说话'));
    try {
      const res = await apiFetch('/api/mic/test', {
        method: 'POST',
        body: JSON.stringify({ duration_sec: 3, send_to_ai: true }),
      });
      const deviceLabel = res.active_input_device_label || res.default_input || t('dynamic.settingsMicTools.未知输入设备');
      const fallbackBit = res.fallback_to_default ? ` · ${t('dynamic.settingsMicTools.已回退默认输入')}` : '';
      const detail = `${deviceLabel}${fallbackBit} · input=${res.input_tokens ?? 0} · output=${res.output_tokens ?? 0} · pcm=${res.pcm_bytes || 0}B`;
      if (statusEl) {
        statusEl.textContent = res.reply_preview
          ? `${detail} · ${res.reply_preview}`
          : detail;
      }
      micToolsDeps.showToast(res.message || (res.ok ? t('dynamic.settingsMicTools.测试发送成功') : t('dynamic.settingsMicTools.测试发送失败')), !res.ok);
    } catch (error) {
      if (statusEl) statusEl.textContent = t('dynamic.settingsMicTools.测试发送失败');
      micToolsDeps.showToast(error.message || t('dynamic.settingsMicTools.测试发送失败'), true);
    } finally {
      btn.disabled = false;
      if (micBtn) micBtn.disabled = false;
    }
  });
}
