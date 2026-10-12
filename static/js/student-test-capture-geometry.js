export function questionSourceRegion(videoWidth, videoHeight, videoRect, guideRect) {
  const values = [videoWidth, videoHeight, videoRect?.left, videoRect?.top,
    videoRect?.width, videoRect?.height, guideRect?.left, guideRect?.top,
    guideRect?.width, guideRect?.height];
  if (!values.every(Number.isFinite) || videoWidth <= 0 || videoHeight <= 0
      || videoRect.width <= 0 || videoRect.height <= 0 || guideRect.width <= 0 || guideRect.height <= 0) {
    throw new RangeError('답안 촬영 영역을 확인할 수 없습니다.');
  }
  const left = guideRect.left - videoRect.left;
  const top = guideRect.top - videoRect.top;
  if (left < 0 || top < 0 || left + guideRect.width > videoRect.width
      || top + guideRect.height > videoRect.height) {
    throw new RangeError('답안 안내틀이 카메라 화면 안에 있어야 합니다.');
  }
  // The preview uses centered object-fit: cover; screen pixels are not source pixels.
  const scale = Math.max(videoRect.width / videoWidth, videoRect.height / videoHeight);
  const offsetX = (videoWidth * scale - videoRect.width) / 2;
  const offsetY = (videoHeight * scale - videoRect.height) / 2;
  const x = Math.max(0, Math.round((left + offsetX) / scale));
  const y = Math.max(0, Math.round((top + offsetY) / scale));
  const width = Math.min(videoWidth - x, Math.round(guideRect.width / scale));
  const height = Math.min(videoHeight - y, Math.round(guideRect.height / scale));
  if (width < 8 || height < 8) throw new RangeError('답안을 안내틀 안에 더 크게 비춰 주세요.');
  return { x, y, width, height };
}
