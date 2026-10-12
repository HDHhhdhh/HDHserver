const AUTHOR_LABELS = Object.freeze({
  귤: '규',
  세빈: '세',
  동훈: '동',
  하영: '하',
});

function installStylesheet() {
  if (document.getElementById('demoThreadPreviewStylesheet')) return;
  const link = document.createElement('link');
  link.id = 'demoThreadPreviewStylesheet';
  link.rel = 'stylesheet';
  link.href = '/css/demo-thread-preview.css?v=20260914-threads1';
  document.head.appendChild(link);
}

function enhanceNoteItem(item) {
  if (!(item instanceof Element) || item.dataset.demoThreadEnhanced === 'true') return;
  item.dataset.demoThreadEnhanced = 'true';

  const author = String(item.dataset.noteAuthor || '');
  const avatar = document.createElement('span');
  avatar.className = 'demo-thread-avatar';
  avatar.setAttribute('aria-hidden', 'true');
  avatar.textContent = AUTHOR_LABELS[author] || '메';
  item.prepend(avatar);

  const authorName = item.querySelector('.assistant-note-item-author');
  const time = item.querySelector('.assistant-note-item-time');
  if (authorName && time && time.textContent.trim()) authorName.after(time);
}

function enhanceNotes(root = document) {
  root.querySelectorAll?.('.assistant-note-item').forEach(enhanceNoteItem);
}

export function initDemoThreadPreview() {
  document.body.classList.add('demo-thread-preview');
  installStylesheet();
  enhanceNotes();

  const observer = new MutationObserver((records) => {
    records.forEach((record) => {
      record.addedNodes.forEach((node) => {
        if (!(node instanceof Element)) return;
        if (node.matches('.assistant-note-item')) enhanceNoteItem(node);
        enhanceNotes(node);
      });
    });
  });
  observer.observe(document.body, { childList: true, subtree: true });
}
