// High-accuracy geolocation helper.
// Uses watchPosition to wait for a precise fix, falling back after a timeout.

export function getAccuratePosition({
  desiredAccuracy = 50,        // meters
  fallbackAccuracy = 200,      // meters — what we'll accept if we can't reach desired
  maxWait = 15000,             // ms total
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
      if (best && best.accuracy <= fallbackAccuracy) {
        settled = true;
        resolve(best);
      } else if (best) {
        settled = true;
        resolve(best); // accept anyway but caller can warn
      } else {
        settled = true;
        reject(new Error("Could not get a location fix"));
      }
    }, maxWait + 1000);
  });
}
