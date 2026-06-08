import { showFloatingTooltip, wireFloatingTooltipButton } from './settings-model-catalog.js';

const SETTINGS_FIELD_TIPS = {
  providerPreset:
    '选一个常见 AI 平台，会自动填好接口地址和模式；选「手动填写」则不套用预设，需自己逐项设置。',
  api_endpoint:
    '视觉模型服务的网址。火山方舟豆包一般填到 /api/v3；多数 OpenAI 兼容服务填到 /v1。',
  api_mode:
    'doubao：火山方舟豆包。openai：其他兼容 Chat 接口的服务（如部分第三方中转）。',
  mic_use_visual_model:
    '开启时开麦与识图共用上方「API 与模型」的接口与模型；关闭后可在本标签单独配置支持麦克风的模型。',
  micProviderPreset:
    '为麦克风接话选择服务商预设，会自动填入麦克风 API 地址与模式。OpenAI 兼容类预设不保证支持音频，需模型声明支持或在模型配置档案中勾选「支持麦克风」。',
  mic_api_endpoint:
    '麦克风专用 API 地址。豆包一般填到 /api/v3；MiMo 等 OpenAI 兼容服务填到 /v1。',
  mic_api_mode:
    '麦克风请求使用的 API 模式。开麦需 doubao 全模态或 MiMo 的 mimo-v2.5。',
  mic_model:
    '听懂麦克风并生成接话弹幕的模型；与识图视觉模型可不同。',
  mic_api_key:
    '麦克风专用 API 密钥，与识图密钥分开加密保存。留空保存不会覆盖已有密钥。',
  model:
    '实际调用的模型名称或接入点 ID。也可在下方「模型配置档案」里保存多套 endpoint/密钥/模型。',
  screen_index:
    '截图和弹幕叠在哪块显示器上。编号无效时会自动改用主屏。',
  temperature:
    '创意程度（0–2）。越高弹幕用词越发散，越低越稳定、越像固定话术。',
  max_tokens:
    '单次 AI 回复允许的最长输出。开启「思考」类模型时，程序会自动提高实际下限。',
  memory_mode:
    '关闭：不额外记忆。轻量：只避免重复弹幕。标准：记住画面要点并防重复。强记忆：注入更多上下文，换场景时保留更多内容。',
  memory_window:
    '记住最近几条已成功显示的 AI 弹幕（1–20 条），用来提醒模型别再说同样的话。',
  mic_mode_enabled:
    '实验功能：说完一句话后额外生成几条接话弹幕，插队显示，不影响看屏识图节奏。需豆包接口且模型支持麦克风；默认关，录音仅在内存、不落盘。使用 Windows「设置 → 系统 → 声音 → 输入」里的默认麦克风；换耳机后建议先停弹幕再开或重启应用。',
  mic_window_sec:
    '每次说话时，附带最近多少秒的麦克风录音发给 AI（1–30 秒，默认 5）。',
  btnMicTest:
    '录大约 3 秒，检查麦克风是否有声音。不联网、不上传、不保存文件。',
  btnMicTestSend:
    '录大约 3 秒后，把声音和占位图发给 AI，确认模型能收到你的麦克风输入。',
  api_key:
    '访问 AI 的密钥，保存在本机并加密。留空点「保存配置」不会覆盖已有密钥。',
  normal_recognition_interval_sec:
    '普通模式下，每隔多少秒识图并生成一批弹幕（1–60 秒）。',
  normal_reply_count:
    '普通模式下，每次识图固定生成几条弹幕（1–50 条）。',
  danmu_speed:
    '弹幕横向移动快慢（约 0.5–5）。数字越大滚得越快。',
  danmu_lines:
    '屏幕上最多几行弹幕轨道（12–20 行）。',
  danmu_max_chars:
    'AI 生成弹幕最多显示多少字（5–80），超出会截断并加省略号。公式化弹幕（自定义库、烂梗）完整展示。未填写时默认中文约 15、英文约 40。',
  font_size:
    '弹幕字号，约 12–72 像素。',
  danmu_font_family:
    '横向弹幕使用的系统字体名。留空或填入不存在的字体名时回退到默认。',
  danmu_font_bold:
    '是否加粗横向弹幕。',
  floating_panel_font_family:
    '悬浮窗使用的系统字体名。',
  floating_panel_font_bold:
    '是否加粗悬浮窗弹幕。',
  opacity:
    '弹幕透明度 0–100%，100 为完全不透明。',
  dedup_threshold:
    '和最近弹幕有多像就算重复（0–1）。越高越容易判重复并丢掉，默认约 0.5。',
  layout_mode:
    '弹幕显示区域占整块屏幕的比例（全屏、四分之三、一半、四分之一）。',
  hotkey:
    '全局快捷键，随时开始或停止生成弹幕。首次使用可能需在系统里允许本程序监听键盘。',
  eviction_mode:
    '自然：按正常速度滚出屏幕。加速：换场景或清屏时让旧弹幕更快消失。',
  danmu_pending_entry_cap:
    '入口区（屏幕右侧待滚入）最多保留几条 pending 弹幕。0 表示无限制；低配机可设 200–500 作性能保护，超出时淘汰最远屏外条目而非拒绝新弹幕。',
  danmu_track_retention_cap:
    '所有轨道上同时保留的弹幕总条数上限。0 表示无限制；超出时优先淘汰屏外 pending。',
  reply_queue_max_items:
    'AI 回复在入队等待上屏时的最大条数。0 表示不裁剪；>0 时超出会从队首丢弃最旧条目。',
  empty_accel:
    '某行轨道空了时，暂时加快滚动，让新弹幕更快占满空位。',
  danmu_render_mode:
    '横向弹幕：全屏透明 Overlay 横向滚动。从下到上：消息自下而上堆叠后淡出（开发中）。',
  floating_panel_width:
    '从下到上模式窗口宽度（200–800 px），默认靠右显示。',
  floating_panel_lifetime_sec:
    '每条消息停留秒数（2–60），到期后淡出移除。',
  floating_panel_x_offset:
    '悬浮窗与屏幕右边缘的距离（px）。',
  floating_panel_y_offset:
    '悬浮窗与屏幕上/下边缘的距离（px）。',
  floating_panel_opacity:
    '悬浮窗整体不透明度 0–100（0 = 完全透明，100 = 完全不透明）。',
  floating_panel_font_size:
    '悬浮窗内每条弹幕的字号（12–48 px）。',
  floating_panel_max_items:
    '悬浮窗同时显示的最多条数。超过时按 FIFO 丢最旧。',
  image_max_width:
    '发给 AI 前把截图缩到多宽。越小越省流量和费用，越大越清晰。',
  image_quality:
    'JPEG 压缩质量 1–100，默认 85。越高图越清楚、文件越大。',
  btnProbe:
    '用当前填写的地址、模式和密钥试连一次 AI，不开始弹幕，也不改其它设置。',
};

const SETTINGS_HEADING_TIPS = {
  'custom-models':
    '模型配置档案：为不同接口地址、模型、密钥保存多套配置，可指定默认；这里的密钥与上方全局密钥分开管理。',
  'compress-preview':
    '上传一张样图，预览当前「最大宽度」和「JPEG 质量」下的压缩效果。图片只在内存里处理，不会保存到硬盘。',
};

const SETTINGS_CONTROL_HINT_IDS = new Set(['btnMicTest', 'btnMicTestSend', 'btnProbe']);

function createFieldHintWrap(tipText, tipId) {
  const wrap = document.createElement('span');
  wrap.className = 'field-hint-wrap relative shrink-0';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'field-hint-btn';
  btn.setAttribute('aria-label', '字段说明');
  if (tipId) btn.setAttribute('aria-describedby', tipId);
  btn.innerHTML = '<svg class="ui-icon" aria-hidden="true"><use href="#i-info"></use></svg>';
  wireFloatingTooltipButton(btn, () => {
    showFloatingTooltip(btn, tipText, { tipId });
  });
  wrap.append(btn);
  return wrap;
}

function attachHintToLabel(label, tipText, tipId) {
  if (!label || label.querySelector('.field-hint-wrap')) return;
  const wrap = createFieldHintWrap(tipText, tipId);

  if (label.classList.contains('flex') && label.querySelector('input, select, textarea')) {
    label.appendChild(wrap);
    return;
  }

  const row = document.createElement('div');
  row.className = 'field-label-row flex items-center gap-1';
  const useBlockSpacing =
    label.classList.contains('block') || label.classList.contains('settings-field-label');
  if (useBlockSpacing) {
    row.classList.add('mb-2');
    label.classList.remove('block', 'mb-2');
  }
  if (label.classList.contains('mb-1')) {
    row.classList.add('mb-1');
    label.classList.remove('mb-1');
  }
  label.classList.add('flex-1', 'min-w-0');
  label.parentNode.insertBefore(row, label);
  row.append(label, wrap);
}

function attachHintToHeading(heading, tipText, tipId) {
  if (!heading || heading.querySelector('.field-hint-wrap')) return;
  const row = document.createElement('div');
  row.className = 'field-label-row flex items-center gap-1 mb-4';
  const title = document.createElement('span');
  title.className = `${heading.className} flex-1 min-w-0 mb-0`;
  title.innerHTML = heading.innerHTML;
  heading.replaceWith(row);
  row.append(title, createFieldHintWrap(tipText, tipId));
}

function resolveSettingsLabel(fieldEl) {
  if (!fieldEl) return null;
  const id = fieldEl.id;
  if (id) {
    const byFor = document.querySelector(`#settingsForm label[for="${id}"]`);
    if (byFor) return byFor;
  }
  const inLabel = fieldEl.closest('#settingsForm label');
  if (inLabel) return inLabel;
  const parent = fieldEl.parentElement;
  if (parent) {
    const prev = fieldEl.previousElementSibling;
    if (prev && prev.tagName === 'LABEL') return prev;
    const labelInParent = parent.querySelector(':scope > label');
    if (labelInParent) return labelInParent;
  }
  return null;
}

function attachHintAfterControl(control, tipText, tipId) {
  if (!control || control.dataset.hintAttached === '1') return;
  control.insertAdjacentElement('afterend', createFieldHintWrap(tipText, tipId));
  control.dataset.hintAttached = '1';
}

export function initSidebarNavFloatingHints() {
  document.querySelectorAll('.sidebar-nav-hint-wrap').forEach((wrap) => {
    const btn = wrap.querySelector('.sidebar-nav-hint');
    const inlineTip = wrap.querySelector('.warm-tooltip');
    if (!btn || !inlineTip || btn.dataset.floatingTip === '1') return;
    const html = inlineTip.innerHTML;
    const tipId = inlineTip.id || '';
    if (tipId) btn.setAttribute('aria-describedby', tipId);
    inlineTip.remove();
    btn.dataset.floatingTip = '1';
    wireFloatingTooltipButton(btn, () => {
      showFloatingTooltip(btn, html, { html: true, wide: true, tipId });
    });
  });
}

export function initSettingsFieldHints() {
  const form = document.getElementById('settingsForm');
  if (!form) return;

  Object.entries(SETTINGS_FIELD_TIPS).forEach(([fieldId, tip]) => {
    const field = document.getElementById(fieldId);
    if (!field) return;
    if (SETTINGS_CONTROL_HINT_IDS.has(fieldId)) {
      attachHintAfterControl(field, tip, `tip-field-${fieldId}`);
      return;
    }
    const label = resolveSettingsLabel(field);
    if (label) attachHintToLabel(label, tip, `tip-field-${fieldId}`);
  });

  attachHintToHeading(
    document.querySelector('#customModelsSection h4'),
    SETTINGS_HEADING_TIPS['custom-models'],
    'tip-heading-custom-models',
  );
  const compressTitle = document.querySelector('#compressPreviewSection > .settings-section-title');
  if (compressTitle) {
    attachHintToHeading(
      compressTitle,
      SETTINGS_HEADING_TIPS['compress-preview'],
      'tip-heading-compress-preview',
    );
  }
}
