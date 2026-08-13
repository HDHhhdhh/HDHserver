export function createSnapshotCoordinator(loadSnapshot, commitSnapshot) {
  let revision = 0;
  let latestPromise = Promise.resolve({ committed: true, snapshot: null });

  function load(input) {
    const currentRevision = ++revision;
    let request;
    try {
      request = Promise.resolve(loadSnapshot(input));
    } catch (error) {
      request = Promise.reject(error);
    }
    const result = request.then((snapshot) => {
      if (currentRevision !== revision) return { committed: false, snapshot };
      commitSnapshot(snapshot, input);
      return { committed: true, snapshot };
    });
    latestPromise = result;
    return result;
  }

  async function settled() {
    let pending = latestPromise;
    while (true) {
      const result = await pending;
      if (pending === latestPromise) return result;
      pending = latestPromise;
    }
  }

  function invalidate() {
    revision += 1;
    latestPromise = Promise.resolve({ committed: true, snapshot: null });
  }

  return { load, settled, invalidate };
}
