export const ROOT_CLASS = 'admin-demo-help-root';
export const POPOVER_CLASS = 'admin-demo-help-popover';
export const CENTER_CLASS = 'admin-demo-help-center';

const STYLE_ID = 'adminDemoFeatureHelpStyles';

export function injectStyles(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = `
    .${ROOT_CLASS} {
      color: var(--ds-text, #1f2f45);
      font-family: "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", system-ui, sans-serif;
    }
    .${POPOVER_CLASS},
    .${CENTER_CLASS} {
      position: fixed;
      z-index: 10020;
      box-sizing: border-box;
      border: 1px solid var(--ds-border, #d7e2f0);
      border-radius: 8px;
      background: var(--ds-surface, #ffffff);
      box-shadow: var(--ds-shadow-card, 0 10px 26px rgba(17, 34, 58, .12));
      color: var(--ds-text, #1f2f45);
      letter-spacing: 0;
      word-break: keep-all;
      overflow-wrap: anywhere;
    }
    .${POPOVER_CLASS} {
      padding: 12px;
    }
    .admin-demo-help-popover-head,
    .admin-demo-help-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }
    .admin-demo-help-popover-head p,
    .admin-demo-help-head p,
    .admin-demo-help-head span,
    .admin-demo-help-note {
      margin: 0;
      color: var(--ds-text-muted, #637b9b);
      font-size: 12px;
      font-weight: 700;
      line-height: 1.45;
    }
    .${POPOVER_CLASS} h3,
    .admin-demo-help-head h2 {
      margin: 4px 0 0;
      color: var(--ds-text, #1f2f45);
      font-size: 15px;
      font-weight: 800;
      line-height: 1.4;
      letter-spacing: 0;
    }
    .${POPOVER_CLASS} > p {
      margin: 8px 0 0;
      color: var(--ds-text, #1f2f45);
      font-size: 13px;
      line-height: 1.55;
    }
    .${POPOVER_CLASS} footer,
    .admin-demo-help-actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 12px;
    }
    .admin-demo-help-close,
    .${POPOVER_CLASS} footer button,
    .admin-demo-help-actions button,
    .admin-demo-help-list button {
      min-height: 34px;
      border: 1px solid var(--ds-border, #d7e2f0);
      border-radius: 8px;
      background: var(--ds-surface, #ffffff);
      color: var(--ds-text, #1f2f45);
      font: inherit;
      font-size: 13px;
      font-weight: 800;
      cursor: pointer;
    }
    .admin-demo-help-close {
      min-width: 48px;
      padding: 0 10px;
    }
    .${POPOVER_CLASS} footer button,
    .admin-demo-help-actions button:first-child {
      padding: 0 12px;
      border-color: var(--ds-primary, #2f77ec);
      background: var(--ds-primary, #2f77ec);
      color: var(--ds-surface, #ffffff);
    }
    .${CENTER_CLASS} {
      right: 18px;
      bottom: 18px;
      width: min(430px, calc(100vw - 36px));
      max-height: min(720px, calc(100vh - 36px));
      overflow: auto;
    }
    .admin-demo-help-head {
      padding: 14px 14px 10px;
      border-bottom: 1px solid var(--ds-border, #d7e2f0);
    }
    .admin-demo-help-note {
      margin: 12px 14px 0;
      padding: 9px 10px;
      border: 1px solid var(--ds-border, #d7e2f0);
      border-radius: 8px;
      background: var(--ds-surface-2, #f8fbff);
    }
    .admin-demo-help-list {
      display: grid;
      gap: 8px;
      padding: 12px 14px;
    }
    .admin-demo-help-list button {
      display: grid;
      gap: 4px;
      width: 100%;
      padding: 9px 10px;
      text-align: left;
      line-height: 1.45;
    }
    .admin-demo-help-list button strong {
      font-size: 13px;
      color: var(--ds-text, #1f2f45);
    }
    .admin-demo-help-list button span {
      color: var(--ds-text-muted, #637b9b);
      font-size: 12px;
      font-weight: 600;
    }
    .admin-demo-help-list button.is-seen {
      border-color: var(--ds-primary, #2f77ec);
      background: var(--ds-primary-soft, #deebff);
    }
    .admin-demo-help-actions {
      margin: 0;
      padding: 12px 14px 14px;
      border-top: 1px solid var(--ds-border, #d7e2f0);
      background: var(--ds-surface-2, #f8fbff);
    }
    .admin-demo-help-actions button {
      padding: 0 12px;
    }
    @media (max-width: 640px) {
      .${CENTER_CLASS} {
        right: 10px;
        bottom: 10px;
        width: calc(100vw - 20px);
        max-height: calc(100vh - 20px);
      }
      .${POPOVER_CLASS} {
        max-width: calc(100vw - 20px);
      }
      .admin-demo-help-actions {
        flex-direction: column;
      }
    }
  `;
  doc.head.appendChild(style);
}
