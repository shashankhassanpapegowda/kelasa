/** Slides for the employee calendar lightbox. Plain data, no markup. */

export const PURGED = "Photo deleted after retention period";

const finite = (value) => value != null && value !== "" && Number.isFinite(Number(value));

export function formatShotPlace({ branch, lat, lng, accuracy } = {}) {
  const bits = [];
  if (branch) bits.push(String(branch));
  if (finite(lat) && finite(lng)) bits.push(`${Number(lat).toFixed(5)}, ${Number(lng).toFixed(5)}`);
  if (finite(accuracy)) bits.push(`±${Math.round(Number(accuracy))}m`);
  return bits.join(" · ") || "Location not recorded";
}

const resumeNote = (b) => {
  if (!b?.end) return "Still on break";
  if (!b.end_photo_path && !b.end_photo_purged && b.closed_without_selfie) return "Closed automatically — no resume selfie";
  return "No resume selfie";
};

const slide = ({ id, kind, label, time, path, purged, note, place }) => ({
  id,
  kind,
  label,
  time: time || null,
  path: path || null,
  purged: !!purged,
  note: purged ? PURGED : (note || "No photo"),
  place,
});

export function dayPhotoShots(day) {
  const shots = [];
  for (const s of day?.sessions || []) {
    const breaks = Array.isArray(s.breaks) ? s.breaks : [];
    shots.push(slide({
      id: `${s.record_id}-in`,
      kind: "punch_in",
      label: "Punch in",
      time: s.check_in,
      path: s.check_in_photo_path,
      purged: !!s.photos_purged_at && !s.check_in_photo_path,
      place: formatShotPlace({
        branch: s.check_in_branch, lat: s.check_in_lat, lng: s.check_in_lng, accuracy: s.check_in_accuracy,
      }),
    }));
    breaks.forEach((b, i) => {
      const many = breaks.length > 1;
      shots.push(slide({
        id: `${s.record_id}-break-${b.break_id || i}-start`,
        kind: "break_start",
        label: many ? `Break ${i + 1} start` : "Break start",
        time: b.start,
        path: b.start_photo_path,
        purged: !!b.start_photo_purged,
        place: formatShotPlace({ lat: b.start_lat, lng: b.start_lng, accuracy: b.start_accuracy }),
      }));
      shots.push(slide({
        id: `${s.record_id}-break-${b.break_id || i}-resume`,
        kind: "break_resume",
        label: many ? `Break ${i + 1} resume` : "Break resume",
        time: b.end,
        path: b.end_photo_path,
        purged: !!b.end_photo_purged,
        note: resumeNote(b),
        place: formatShotPlace({ lat: b.end_lat, lng: b.end_lng, accuracy: b.end_accuracy }),
      }));
    });
    shots.push(slide({
      id: `${s.record_id}-out`,
      kind: "punch_out",
      label: "Punch out",
      time: s.check_out,
      path: s.check_out_photo_path,
      purged: !!s.photos_purged_at && !s.check_out_photo_path && !!s.check_out,
      note: s.check_out ? "No photo" : "Not checked out",
      place: formatShotPlace({
        branch: s.check_out_branch, lat: s.check_out_lat, lng: s.check_out_lng, accuracy: s.check_out_accuracy,
      }),
    }));
  }
  return shots.map((s, index) => ({ ...s, index }));
}

/** True when the day has a selfie, a purged frame, or a break worth opening. */
export function dayHasSelfies(day) {
  return dayPhotoShots(day).some((s) => s.path || s.purged || s.kind === "break_start" || s.kind === "break_resume");
}
