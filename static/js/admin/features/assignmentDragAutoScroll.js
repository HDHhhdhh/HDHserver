export function createAssignmentDragAutoScroll({ rowSelector, scrollerForRow, isActive, onRow, onStop }) {
  let scroller = null;
  let pointerX = 0;
  let pointerY = 0;
  let buttonMask = 1;
  let frame = 0;
  let lastTime = 0;
  let listening = false;

  function stop() {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    lastTime = 0;
    scroller = null;
    if (!listening) return;
    listening = false;
    document.removeEventListener('mousemove', move);
    document.removeEventListener('mouseup', finish);
    document.removeEventListener('visibilitychange', visibilityChanged);
    window.removeEventListener('blur', finish);
  }

  function finish() {
    stop();
    onStop();
  }

  function visibilityChanged() {
    if (document.hidden) finish();
  }

  function viewport() {
    if (!scroller?.isConnected || !scroller.getClientRects().length) return null;
    const rect = scroller.getBoundingClientRect();
    const top = Math.max(0, rect.top);
    const bottom = Math.min(window.innerHeight, rect.bottom);
    return bottom > top ? { top, bottom, left: rect.left, right: rect.right } : null;
  }

  function velocity(rect) {
    const band = Math.min(48, (rect.bottom - rect.top) / 3);
    if (pointerX < rect.left || pointerX > rect.right ||
        pointerY < rect.top - band || pointerY > rect.bottom + band) return 0;
    if (pointerY < rect.top + band) return -720 * Math.min(1, (rect.top + band - pointerY) / band);
    if (pointerY > rect.bottom - band) return 720 * Math.min(1, (pointerY - rect.bottom + band) / band);
    return 0;
  }

  function updateRange(rect) {
    const y = Math.max(rect.top + 2, Math.min(rect.bottom - 2, pointerY));
    for (const offset of [0, -6, 6, -12, 12]) {
      const probeY = Math.max(rect.top + 2, Math.min(rect.bottom - 2, y + offset));
      const row = document.elementFromPoint(pointerX, probeY)?.closest?.(rowSelector);
      if (row && scroller.contains(row) && !row.disabled) {
        onRow(row);
        return;
      }
    }
  }

  function tick(time) {
    frame = 0;
    const rect = viewport();
    if (!isActive() || !rect || document.hidden) {
      finish();
      return;
    }
    const speed = velocity(rect);
    if (!speed) {
      lastTime = 0;
      return;
    }
    const elapsed = lastTime ? Math.min(32, time - lastTime) : 16;
    lastTime = time;
    const before = scroller.scrollTop;
    scroller.scrollTop += speed * elapsed / 1000;
    updateRange(rect);
    if (scroller.scrollTop !== before) frame = requestAnimationFrame(tick);
    else lastTime = 0;
  }

  function move(event) {
    if (!listening) return;
    if (typeof event.buttons === 'number' && !(event.buttons & buttonMask)) {
      finish();
      return;
    }
    pointerX = event.clientX;
    pointerY = event.clientY;
    const row = event.target?.closest?.(rowSelector);
    const nextScroller = row && scrollerForRow(row);
    if (nextScroller && nextScroller !== scroller) {
      scroller = nextScroller;
      lastTime = 0;
    }
    if (row && scroller?.contains(row) && !row.disabled && isActive()) onRow(row);
    if (!frame) frame = requestAnimationFrame(tick);
  }

  function start(event, row, button = 0) {
    stop();
    scroller = scrollerForRow(row);
    if (!scroller) return;
    buttonMask = button === 2 ? 2 : 1;
    listening = true;
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', finish);
    document.addEventListener('visibilitychange', visibilityChanged);
    window.addEventListener('blur', finish);
    move(event);
  }

  return { start, stop };
}
