function text(value) {
  return String(value || '').trim();
}

export function classifySaveConflict(payload, scope = '정보') {
  const data = payload && typeof payload === 'object' ? payload : {};
  const code = text(data.code).toLowerCase();
  const rawMessage = text(data.error || data.message);
  const normalizedMessage = rawMessage.toLowerCase();
  const lockTimeout = code.endsWith('_lock_timeout')
    || /lock[\s_-]*timeout/.test(normalizedMessage)
    || /\.lock(?:\b|$)/.test(normalizedMessage);
  const retryable = lockTimeout && data.retryable !== false;

  if (lockTimeout) {
    return {
      code: code || 'lock_timeout',
      retryable,
      message: `${scope} 저장 요청이 잠시 겹쳤습니다. 자동으로 다시 시도합니다.`,
    };
  }

  return {
    code: code || 'save_conflict',
    retryable,
    message: rawMessage || `${scope}이 다른 화면에서 변경되었습니다. 다시 확인해 주세요.`,
  };
}
