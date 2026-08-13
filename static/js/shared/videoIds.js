export function nextVideoId(videos = []) {
  let highest = 0;
  for (const video of Array.isArray(videos) ? videos : []) {
    const numeric = Number(video?.id);
    if (!Number.isSafeInteger(numeric) || numeric < 1) continue;
    highest = Math.max(highest, numeric);
  }
  return highest + 1;
}
