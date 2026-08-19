const VTUBER_DOWNLOAD_MODELS = [
  { image: 'httpsbooth.pmenitems5247208.png', name: '阿尼亚' },
  { image: 'httpsbooth.pmzh-cnitems7159191.png', name: 'error' },
  { image: 'httpsbooth.pmzh-cnitems7641846.png', name: 'error' },
  {
    image: '1.png',
    name: 'puppy by恩慈_ENCY',
    downloadUrl: 'https://pan.quark.cn/s/5e1fba5584d3#listshare',
  },
  { image: 'httpsbooth.pmenitems5323958.png', name: '芙莉莲' },
  { image: 'httpsbooth.pmenitems4862237.png', name: 'error' },
  { image: 'httpsbooth.pmzh-cnitems6499774.png', name: '魔女' },
];

let handlersBound = false;
let gridRendered = false;

function element(id) { return document.getElementById(id); }

export function decodeVtuberDownloadUrl(imageName) {
  const base = String(imageName || '').replace(/\.png$/i, '');
  if (!base.startsWith('https')) return '';

  const boothEnMatch = base.match(/^httpsbooth\.pm(en)items(\d+)$/);
  if (boothEnMatch) return `https://booth.pm/en/items/${boothEnMatch[2]}`;

  const boothZhMatch = base.match(/^httpsbooth\.pm(zh-cn)items(\d+)$/);
  if (boothZhMatch) return `https://booth.pm/zh-cn/items/${boothZhMatch[2]}`;

  const quarkMatch = base.match(/^httpspan\.quark\.cn(s)(.+)$/);
  if (quarkMatch) return `https://pan.quark.cn/s/${quarkMatch[2]}`;

  return '';
}

export function resolveVtuberDownloadSource(downloadUrl) {
  const url = String(downloadUrl || '').toLowerCase();
  if (url.includes('booth.pm')) return 'booth';
  if (url.includes('quark.cn') || url.includes('bilibili.com')) return 'bilibili';
  return 'unknown';
}

function sourceLabel(source) {
  if (source === 'booth') return 'Booth';
  if (source === 'bilibili') return 'B站';
  return '未知';
}

function resolveModelDownloadUrl(model) {
  const explicit = String(model.downloadUrl || '').trim();
  if (explicit) return explicit;
  return decodeVtuberDownloadUrl(model.image);
}

function renderDownloadCard(model) {
  const downloadUrl = resolveModelDownloadUrl(model);
  const source = resolveVtuberDownloadSource(downloadUrl);
  const card = document.createElement('article');
  card.className = 'vtuber-download-card ui-card';
  card.setAttribute('role', 'listitem');

  const preview = document.createElement('div');
  preview.className = 'vtuber-download-card__preview';

  const image = document.createElement('img');
  image.className = 'vtuber-download-card__image';
  image.src = `/static/image/${model.image}`;
  image.alt = `${model.name} Live2D 模型预览`;
  image.loading = 'lazy';
  preview.appendChild(image);

  const body = document.createElement('div');
  body.className = 'vtuber-download-card__body';

  const title = document.createElement('h4');
  title.className = 'vtuber-download-card__title';
  title.textContent = model.name;

  const footer = document.createElement('div');
  footer.className = 'vtuber-download-card__footer';

  const tag = document.createElement('span');
  tag.className = `vtuber-download-tag vtuber-download-tag--${source}`;
  tag.textContent = sourceLabel(source);

  const downloadButton = document.createElement('a');
  downloadButton.className = 'ui-button ui-button--primary ui-button--sm vtuber-download-card__action';
  downloadButton.textContent = '下载';
  downloadButton.href = downloadUrl || '#';
  downloadButton.target = '_blank';
  downloadButton.rel = 'noopener noreferrer';
  if (!downloadUrl) {
    downloadButton.setAttribute('aria-disabled', 'true');
    downloadButton.tabIndex = -1;
  } else {
    downloadButton.setAttribute('aria-label', `下载 ${model.name}`);
  }

  footer.append(tag, downloadButton);
  body.append(title, footer);
  card.append(preview, body);
  return card;
}

function renderDownloadGrid() {
  const grid = element('vtuberDownloadGrid');
  if (!grid || gridRendered) return;
  grid.replaceChildren();
  VTUBER_DOWNLOAD_MODELS.forEach((model) => {
    grid.appendChild(renderDownloadCard(model));
  });
  gridRendered = true;
}

export function initVtuberDownloadPage() {
  if (handlersBound) return;
  handlersBound = true;
}

export function onVtuberDownloadTabActivated() {
  renderDownloadGrid();
}

export function getVtuberDownloadModels() {
  return VTUBER_DOWNLOAD_MODELS.map((model) => ({ ...model }));
}
