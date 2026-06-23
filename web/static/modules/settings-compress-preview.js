import { API, apiFormFetch } from './transport.js';

let compressPreviewDeps = {
  showToast: () => {},
};

let previewOrigUrl = null;
let previewCompressedUrl = null;

export function configureSettingsCompressPreview(deps) {
  compressPreviewDeps = { ...compressPreviewDeps, ...deps };
}

function revokePreviewUrls() {
  if (previewOrigUrl) {
    URL.revokeObjectURL(previewOrigUrl);
    previewOrigUrl = null;
  }
  if (previewCompressedUrl) {
    URL.revokeObjectURL(previewCompressedUrl);
    previewCompressedUrl = null;
  }
}

function blobUrlFromDataUrl(dataUrl) {
  const comma = dataUrl.indexOf(',');
  if (comma < 0) return null;
  const header = dataUrl.slice(0, comma);
  const mime = header.match(/data:([^;]+)/)?.[1] || 'image/jpeg';
  const b64 = dataUrl.slice(comma + 1);
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes], { type: mime }));
}

function setPreviewSlot(img, placeholder, src, onBlobUrl) {
  if (!img) return;
  img.classList.remove('hidden');
  if (placeholder) placeholder.classList.add('hidden');
  img.onerror = () => {
    if (src.startsWith('data:') && onBlobUrl) {
      const blobUrl = blobUrlFromDataUrl(src);
      if (blobUrl) {
        onBlobUrl(blobUrl);
        img.onerror = null;
        img.src = blobUrl;
      }
    }
  };
  img.src = src;
}

function resetCompressedPreview() {
  const compressed = document.getElementById('previewImageCompressed');
  const pending = document.getElementById('previewCompressedPlaceholder');
  if (compressed) {
    compressed.classList.add('hidden');
    compressed.removeAttribute('src');
  }
  if (pending) {
    pending.classList.remove('hidden');
    pending.textContent = '正在压缩…';
  }
}

export function bindCompressPreviewControls() {
  document.getElementById('previewImageFile')?.addEventListener('change', async (e) => {
    const file = e.target.files?.[0];
    const info = document.getElementById('previewImageInfo');
    const origImg = document.getElementById('previewImageOrig');
    const origPh = document.getElementById('previewOrigPlaceholder');
    const compressedImg = document.getElementById('previewImageCompressed');
    const compressedPh = document.getElementById('previewCompressedPlaceholder');
    if (!file || !info || !origImg) return;

    revokePreviewUrls();
    resetCompressedPreview();
    previewOrigUrl = URL.createObjectURL(file);
    setPreviewSlot(origImg, origPh, previewOrigUrl);
    info.textContent = `已选择 ${file.name}，正在压缩预览…`;

    const fd = new FormData();
    fd.append('file', file);
    fd.append('max_width', document.getElementById('image_max_width')?.value || '768');
    fd.append('quality', document.getElementById('image_quality')?.value || '85');
    try {
      if (!API.token) {
        throw new Error('未获取会话令牌，请刷新页面或重启 DanmuAI');
      }
      const data = await apiFormFetch('/api/preview/compress', fd);
      info.textContent =
        `原图 ${data.orig_w}×${data.orig_h} → ${data.out_w}×${data.out_h}，JPEG ${(data.jpeg_bytes / 1024).toFixed(1)} KB（Base64 ${data.base64_kb?.toFixed?.(1) ?? '?'} KB）`;
      setPreviewSlot(compressedImg, compressedPh, data.preview_data_url, (blobUrl) => {
        if (previewCompressedUrl) URL.revokeObjectURL(previewCompressedUrl);
        previewCompressedUrl = blobUrl;
      });
    } catch (error) {
      const msg = error.message || '压缩预览失败';
      info.textContent = `${msg}（左侧为原图；请重启 DanmuAI 后重试）`;
      if (compressedPh) {
        compressedPh.classList.remove('hidden');
        compressedPh.textContent = '压缩失败';
      }
      if (compressedImg) compressedImg.classList.add('hidden');
      compressPreviewDeps.showToast(msg, true);
    }
  });
}
