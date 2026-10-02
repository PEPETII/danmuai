/**
 * Debounced, serialized auto-save coordinator.
 *
 * A new schedule supersedes the snapshot that has not started yet. If a
 * change arrives while a request is in flight, the request is allowed to
 * finish but the newest snapshot is saved afterwards. Callers must use the
 * isLatest callback before applying a response back to the form.
 */
export function createAutoSave({ capture, save, delay = 400, onState = () => {} }) {
  if (typeof capture !== 'function' || typeof save !== 'function') {
    throw new TypeError('createAutoSave requires capture and save functions');
  }

  let timer = null;
  let pendingVersion = 0;
  let savedVersion = 0;
  let pumpPromise = null;
  let disposed = false;

  function notify(state, error, version) {
    try {
      onState(state, error, version);
    } catch (notifyError) {
      console.error('auto-save state callback failed', notifyError);
    }
  }

  async function pump() {
    if (pumpPromise) return pumpPromise;
    if (disposed || savedVersion >= pendingVersion) return undefined;

    pumpPromise = (async () => {
      while (!disposed && savedVersion < pendingVersion) {
        const version = pendingVersion;
        const snapshot = capture();
        notify('saving', null, version);
        try {
          await save(snapshot, {
            version,
            isLatest: () => !disposed && version === pendingVersion,
          });
        } catch (error) {
          // A newer edit will cause the loop to continue with that edit. If
          // this is still the newest edit, leave it dirty for a later retry.
          if (version === pendingVersion) notify('error', error, version);
          if (version === pendingVersion) throw error;
          continue;
        }

        if (version === pendingVersion) {
          savedVersion = version;
          notify('saved', null, version);
        }
      }
    })();

    try {
      return await pumpPromise;
    } finally {
      pumpPromise = null;
    }
  }

  function schedule({ immediate = false } = {}) {
    if (disposed) return;
    pendingVersion += 1;
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      pump().catch(() => {});
    }, immediate ? 0 : Math.max(0, Number(delay) || 0));
  }

  function flush() {
    if (disposed) return Promise.resolve();
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    return pump();
  }

  // Invalidate a pending debounce or an in-flight snapshot before switching
  // to another record (for example, another persona).
  function cancel() {
    if (disposed) return;
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    pendingVersion += 1;
    savedVersion = pendingVersion;
  }

  function dispose() {
    disposed = true;
    if (timer !== null) clearTimeout(timer);
    timer = null;
  }

  return { schedule, flush, cancel, dispose };
}
