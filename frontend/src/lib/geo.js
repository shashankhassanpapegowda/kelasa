// High-accuracy geolocation: one-shot best fix + a live watcher utility.

export function getAccuratePosition({
  desiredAccuracy = 50,
  fallbackAccuracy = 200,
  maxWait = 15000,
} = {}) {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("Geolocation is not available on this device"));
      return;
    }
    let best = null;
    let settled = false;
    const watchId = navigator.geolocation.watchPosition(
      (pos) => {
        if (settled) return;
        const reading = {
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
          timestamp: pos.timestamp,
        };
        if (!best || reading.accuracy < best.accuracy) best = reading;
        if (reading.accuracy <= desiredAccuracy) {
          settled = true;
          navigator.geolocation.clearWatch(watchId);
          resolve(reading);
        }
      },
      (err) => {
        if (settled) return;
        if (best) {
          settled = true;
          navigator.geolocation.clearWatch(watchId);
          resolve(best);
        } else {
          settled = true;
          navigator.geolocation.clearWatch(watchId);
          reject(err);
        }
      },
      { enableHighAccuracy: true, timeout: maxWait, maximumAge: 0 }
    );
    setTimeout(() => {
      if (settled) return;
      navigator.geolocation.clearWatch(watchId);
      if (best) {
        settled = true;
        resolve(best);
      } else {
        settled = true;
        reject(new Error("Could not get a location fix"));
      }
    }, maxWait + 1000);
  });
}

/**
 * Continuous live position watcher. Calls onUpdate({lat,lng,accuracy,timestamp})
 * for every new GPS reading. Returns a stop() function.
 * Filters out coarse readings (>500m).
 */
export function startLiveWatch(onUpdate, { maxAccuracy = 500 } = {}) {
  if (!navigator.geolocation) return () => {};
  const watchId = navigator.geolocation.watchPosition(
    (pos) => {
      if (pos.coords.accuracy > maxAccuracy) return;
      onUpdate({
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
        accuracy: pos.coords.accuracy,
        timestamp: pos.timestamp,
      });
    },
    (err) => console.warn("live watch error", err?.message),
    { enableHighAccuracy: true, timeout: 30000, maximumAge: 5000 }
  );
  return () => {
    try { navigator.geolocation.clearWatch(watchId); } catch (e) { /* noop */ }
  };
}
