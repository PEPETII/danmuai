import { showFloatingTooltip, wireFloatingTooltipButton } from './settings-model-catalog.js';
import { t } from './i18n.js';

const SETTINGS_FIELD_TIPS = {
  api_endpoint:
    'dynamic.settingsHints.视觉模型服务的网址_火山方舟豆包一般填到_ap',
  api_mode:
    'dynamic.settingsHints.doubao_火山方舟豆包_openai_其他兼',
  mic_use_visual_model:
    'dynamic.settingsHints.开启时开麦与识图共用上方_API_与模型_的接口',
  micProviderPreset:
    'dynamic.settingsHints.为麦克风接话选择服务商预设_会自动填入麦克风_A',
  mic_api_endpoint:
    'dynamic.settingsHints.麦克风专用_API_地址_豆包一般填到_api',
  mic_api_mode:
    'dynamic.settingsHints.麦克风请求使用的_API_模式_开麦需_doub',
  mic_model:
    'dynamic.settingsHints.听懂麦克风并生成接话弹幕的模型_与识图视觉模型可',
  mic_api_key:
    'dynamic.settingsHints.麦克风专用_API_密钥_与识图密钥分开加密保存',
  model:
    'dynamic.settingsHints.实际调用的模型名称或接入点_ID_也可在下方_模',
  screen_index:
    'dynamic.settingsHints.截图和弹幕叠在哪块显示器上_编号无效时会自动改用',
  temperature:
    'dynamic.settingsHints.创意程度_0_2_越高弹幕用词越发散_越低越稳',
  max_tokens:
    'dynamic.settingsHints.单次_AI_回复允许的最长输出_开启_思考_类模',
  mic_mode_enabled:
    'hints.mic_mode_enabled',
  mic_window_sec:
    'dynamic.settingsHints.每次说话时_附带最近多少秒的麦克风录音发给_AI',
  btnMicTest:
    'dynamic.settingsHints.录大约_3_秒_检查麦克风是否有声音_不联网_不',
  btnMicTestSend:
    'dynamic.settingsHints.录大约_3_秒后_把声音和占位图发给_AI_确认',
  api_key:
    'dynamic.settingsHints.访问_AI_的密钥_保存在本机并加密_留空点_保',
  normal_recognition_interval_sec:
    'dynamic.settingsHints.普通模式下_每隔多少秒识图并生成一批弹幕_1_6',
  normal_reply_count:
    'dynamic.settingsHints.普通模式下_每次识图固定生成几条弹幕_1_50',
  danmu_speed:
    'dynamic.settingsHints.弹幕横向移动快慢_约_0_5_5_数字越大滚得',
  danmu_lines:
    'dynamic.settingsHints.屏幕上最多几行弹幕轨道_12_20_行',
  danmu_max_chars:
    'dynamic.settingsHints.AI_生成弹幕最多显示多少字_5_80_超出会',
  font_size:
    'dynamic.settingsHints.弹幕字号_约_12_72_像素',
  danmu_font_family:
    'dynamic.settingsHints.横向弹幕使用的系统字体名_留空或填入不存在的字体',
  danmu_font_bold:
    'dynamic.settingsHints.是否加粗横向弹幕',
  floating_panel_font_family:
    'dynamic.settingsHints.悬浮窗使用的系统字体名',
  floating_panel_font_bold:
    'dynamic.settingsHints.是否加粗悬浮窗弹幕',
  opacity:
    'dynamic.settingsHints.弹幕透明度_0_100_100_为完全不透明',
  dedup_threshold:
    'dynamic.settingsHints.和最近弹幕有多像就算重复_0_1_越高越容易判',
  layout_mode:
    'dynamic.settingsHints.弹幕显示区域占整块屏幕的比例_全屏_四分之三_一',
  hotkey:
    'dynamic.settingsHints.全局快捷键_随时开始或停止生成弹幕_首次使用可能',
  eviction_mode:
    'dynamic.settingsHints.自然_按正常速度滚出屏幕_加速_换场景或清屏时让',
  danmu_pending_entry_cap:
    'dynamic.settingsHints.入口区_屏幕右侧待滚入_最多保留几条_pendi',
  danmu_track_retention_cap:
    'dynamic.settingsHints.所有轨道上同时保留的弹幕总条数上限_新装默认_6',
  reply_queue_max_items:
    'dynamic.settingsHints.AI_回复在入队等待上屏时的最大条数_0_表示不',
  empty_accel:
    'dynamic.settingsHints.某行轨道空了时_暂时加快滚动_让新弹幕更快占满空',
  danmu_render_mode:
    'dynamic.settingsHints.横向弹幕_全屏透明_Overlay_横向滚动_从',
  floating_panel_width:
    'dynamic.settingsHints.从下到上模式窗口宽度_200_800_px_默',
  floating_panel_speed:
    'dynamic.settingsHints.从下到上模式的滚动速度_0_5_5_0_默认_1',
  floating_panel_x_offset:
    'dynamic.settingsHints.悬浮窗与屏幕右边缘的距离_px',
  floating_panel_y_offset:
    'dynamic.settingsHints.悬浮窗与屏幕上_下边缘的距离_px',
  floating_panel_opacity:
    'dynamic.settingsHints.悬浮窗整体不透明度_0_100_0_完全透明',
  floating_panel_font_size:
    'dynamic.settingsHints.悬浮窗内每条弹幕的字号_12_48_px',
  floating_panel_max_items:
    'dynamic.settingsHints.悬浮窗同时显示的最多条数_超过时按_FIFO_丢',
  image_max_width:
    'dynamic.settingsHints.发给_AI_前把截图缩到多宽_越小越省流量和费用',
  image_quality:
    'dynamic.settingsHints.JPEG_压缩质量_1_100_默认_85_越高',
  btnProbe:
    'dynamic.settingsHints.用当前填写的地址_模式和密钥试连一次_AI_不开',
};

const OVERVIEW_FIELD_TIPS = {
  liveTopicInput:
    'dynamic.settingsHints.描述本次要玩的游戏或直播主题_便于_AI_生成更',
  userNicknameInput:
    'dynamic.settingsHints.你的昵称_AI_可在合适时自然称呼你_全局生效',
};

const PERSONA_FIELD_TIPS = {
  personaSelect:
    'dynamic.settingsHints.选择要编辑的人格模板_内置人格可覆盖保存_也可点',
  personaContract:
    'dynamic.settingsHints.只读的_JSON_输出格式要求_每次生成条数与弹',
  personaSystemCustom:
    'dynamic.settingsHints.追加到该人格系统提示词的风格与人格要求_点_保存',
};

const PET_FIELD_TIPS = {
  petEnabled:
    'dynamic.settingsHints.开启后桌宠显示在桌面_临时隐藏请使用桌宠右键菜单',
  petScale:
    'dynamic.settingsHints.桌宠显示大小倍率_0_5_2_0_1_为默认尺',
  petOpacity:
    'dynamic.settingsHints.桌宠窗口不透明度_0_2_1_0_1_为完全不',
  petAlwaysOnTop:
    'dynamic.settingsHints.开启后桌宠窗口始终置顶_不会被其它窗口遮挡',
  petClickThrough:
    'dynamic.settingsHints.开启后鼠标可穿透桌宠_但将无法拖动桌宠位置',
  petCommandBoxEnabled:
    'dynamic.settingsHints.开启后双击桌宠可弹出弹幕指令输入框',
  petCommandTtl:
    'dynamic.settingsHints.指令提交后在此秒数内有效_5_300_秒_超时',
  petCommandApplyCount:
    'dynamic.settingsHints.一条指令最多影响几次截图弹幕生成_1_5_次',
  petCommandInput:
    'dynamic.settingsHints.在_Web_页调试注入弹幕指令_不会立即请求_A',
  btnPetImportFolder:
    'dynamic.settingsHints.从本地文件夹导入桌宠素材_目录需包含_pet_j',
  btnPetResetAsset:
    'dynamic.settingsHints.恢复为内置默认桌宠_不会删除你原来的本地素材文件',
};

const SETTINGS_HEADING_TIPS = {
  'custom-models':
    'dynamic.settingsHints.模型配置档案_为不同接口地址_模型_密钥保存多套',
};

const CONTENT_PAGE_SECTION_TIPS = {
  hintPersonaActiveTitle:
    'dynamic.settingsHints.勾选多个人格后_运行时每轮随机选一个生成弹幕_点',
};

const SETTINGS_CONTROL_HINT_IDS = new Set(['btnMicTest', 'btnMicTestSend', 'btnProbe']);

const CONTENT_PAGE_CONTROL_HINT_IDS = new Set([
  'btnPetImportFolder',
  'btnPetResetAsset',
]);

function createFieldHintWrap(tipText, tipId) {
  const wrap = document.createElement('span');
  wrap.className = 'field-hint-wrap relative shrink-0';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'field-hint-btn';
  btn.setAttribute('aria-label', 'common.fieldHintAria');
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
    label.classList.contains('block')
    || label.classList.contains('settings-field-label');
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
  if (heading.id) title.id = heading.id;
  heading.replaceWith(row);
  row.append(title, createFieldHintWrap(tipText, tipId));
}

function resolveFieldLabel(fieldEl, rootEl) {
  if (!fieldEl) return null;
  const id = fieldEl.id;
  if (id && rootEl) {
    const byFor = rootEl.querySelector(`label[for="${id}"]`);
    if (byFor) return byFor;
  }
  const inLabel = fieldEl.closest('label');
  if (inLabel && (!rootEl || rootEl.contains(inLabel))) {
    const spanLabel = inLabel.querySelector(':scope > .settings-field-label');
    if (spanLabel) return spanLabel;
    return inLabel;
  }
  const parent = fieldEl.parentElement;
  if (parent && (!rootEl || rootEl.contains(parent))) {
    const prev = fieldEl.previousElementSibling;
    if (prev) {
      if (prev.tagName === 'LABEL') return prev;
      if (prev.classList?.contains('settings-field-label')) return prev;
    }
    const labelInParent = parent.querySelector(':scope > label');
    if (labelInParent) return labelInParent;
    const spanInParent = parent.querySelector(':scope > .settings-field-label');
    if (spanInParent) return spanInParent;
  }
  return null;
}

function resolveSettingsLabel(fieldEl) {
  const form = document.getElementById('settingsForm');
  return resolveFieldLabel(fieldEl, form);
}

function attachHintAfterControl(control, tipText, tipId) {
  if (!control || control.dataset.hintAttached === '1') return;
  control.insertAdjacentElement('afterend', createFieldHintWrap(tipText, tipId));
  control.dataset.hintAttached = '1';
}

function resolveTipText(tip) {
  if (typeof tip !== 'string') return tip;
  if (tip.startsWith('hints.') || tip.startsWith('dynamic.') || tip.startsWith('common.')) {
    return t(tip);
  }
  return tip;
}

function attachFieldHintsInRoot(root, fieldTips, controlHintIds = new Set()) {
  if (!root) return;
  Object.entries(fieldTips).forEach(([fieldId, tipKey]) => {
    const tip = resolveTipText(tipKey);
    const field = root.querySelector(`#${fieldId}`) || document.getElementById(fieldId);
    if (!field || !root.contains(field)) return;
    const tipId = `tip-field-${fieldId}`;
    if (controlHintIds.has(fieldId)) {
      attachHintAfterControl(field, tip, tipId);
      return;
    }
    const label = resolveFieldLabel(field, root);
    if (label) attachHintToLabel(label, tip, tipId);
  });
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

  attachFieldHintsInRoot(form, SETTINGS_FIELD_TIPS, SETTINGS_CONTROL_HINT_IDS);

  attachHintToHeading(
    document.querySelector('#customModelsSection h4'),
    resolveTipText(SETTINGS_HEADING_TIPS['custom-models']),
    'tip-heading-custom-models',
  );
}

export function initContentPageFieldHints() {
  const overviewRoot = document.getElementById('page-overview');
  const personaRoot = document.getElementById('page-persona');
  const petRoot = document.getElementById('page-pet');

  attachFieldHintsInRoot(overviewRoot, OVERVIEW_FIELD_TIPS);
  attachFieldHintsInRoot(personaRoot, PERSONA_FIELD_TIPS);
  attachFieldHintsInRoot(petRoot, PET_FIELD_TIPS, CONTENT_PAGE_CONTROL_HINT_IDS);

  Object.entries(CONTENT_PAGE_SECTION_TIPS).forEach(([elementId, tipKey]) => {
    const heading = document.getElementById(elementId);
    if (heading) attachHintToHeading(heading, resolveTipText(tipKey), `tip-section-${elementId}`);
  });
}
