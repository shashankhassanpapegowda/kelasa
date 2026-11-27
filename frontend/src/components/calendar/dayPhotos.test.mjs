import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { dayHasSelfies, dayPhotoShots, formatShotPlace, PURGED } from "./dayPhotos.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const read = (name) => readFileSync(join(here, name), "utf8");

const session = {
  record_id: "att_1",
  check_in: "2026-11-27T04:00:00+00:00",
  check_out: "2026-11-27T12:00:00+00:00",
  check_in_photo_path: "gtg-attendance/checkin/emp/in.jpg",
  check_out_photo_path: "gtg-attendance/checkout/emp/out.jpg",
  check_in_branch: "Bengaluru HQ",
  check_in_lat: 12.9716,
  check_in_lng: 77.5946,
  check_in_accuracy: 12,
  check_out_branch: "Bengaluru HQ",
  check_out_lat: 12.98,
  check_out_lng: 77.6,
  breaks: [{
    break_id: "b1",
    start: "2026-11-27T06:00:00+00:00",
    end: "2026-11-27T06:30:00+00:00",
    start_photo_path: "gtg-attendance/break_start/emp/s.jpg",
    end_photo_path: "gtg-attendance/break_end/emp/e.jpg",
    start_lat: 12.972,
    start_lng: 77.595,
    end_lat: 12.973,
    end_lng: 77.596,
  }],
};

test("a day is punch in, break start, break resume, punch out", () => {
  const shots = dayPhotoShots({ sessions: [session] });
  assert.deepEqual(shots.map((s) => s.label), ["Punch in", "Break start", "Break resume", "Punch out"]);
  assert.equal(shots[0].path, session.check_in_photo_path);
  assert.equal(shots[1].path, "gtg-attendance/break_start/emp/s.jpg");
  assert.equal(shots[2].path, "gtg-attendance/break_end/emp/e.jpg");
  assert.equal(shots[3].path, session.check_out_photo_path);
  assert.equal(shots[0].place, "Bengaluru HQ · 12.97160, 77.59460 · ±12m");
  assert.equal(shots[1].place, "12.97200, 77.59500");
  assert.equal(dayHasSelfies({ sessions: [session] }), true);
});

test("a second break keeps the same words and its own place", () => {
  const shots = dayPhotoShots({
    sessions: [{
      ...session,
      breaks: [
        session.breaks[0],
        { break_id: "b2", start: "2026-11-27T08:00:00+00:00", end: "2026-11-27T08:10:00+00:00", start_lat: 1, start_lng: 2 },
      ],
    }],
  });
  assert.deepEqual(shots.map((s) => s.label), [
    "Punch in", "Break 1 start", "Break 1 resume", "Break 2 start", "Break 2 resume", "Punch out",
  ]);
  assert.equal(shots[3].place, "1.00000, 2.00000");
});

test("purged and auto-closed frames stay in the strip without a photo", () => {
  const shots = dayPhotoShots({
    sessions: [{
      record_id: "att_old",
      check_in: "2026-09-01T04:00:00+00:00",
      check_out: "2026-09-01T12:00:00+00:00",
      photos_purged_at: "2026-12-01T00:00:00+00:00",
      auto_closed: true,
      breaks: [{
        break_id: "b",
        start: "2026-09-01T06:00:00+00:00",
        end: "2026-09-01T07:10:00+00:00",
        start_photo_purged: true,
        closed_without_selfie: true,
      }],
    }],
  });
  assert.equal(shots[0].note, PURGED);
  assert.equal(shots[0].path, null);
  assert.equal(shots[1].note, PURGED);
  assert.equal(shots[2].note, "Closed automatically — no resume selfie");
  assert.equal(shots[2].path, null);
  assert.equal(shots[3].note, PURGED);
  assert.equal(dayHasSelfies({ sessions: [{ record_id: "plain", check_in: "t", check_out: "t" }] }), false);
});

test("missing coordinates do not become 0, 0", () => {
  assert.equal(formatShotPlace({}), "Location not recorded");
  assert.equal(formatShotPlace({ lat: null, lng: null }), "Location not recorded");
  assert.equal(formatShotPlace({ branch: "HQ" }), "HQ");
});

test("the calendar does not paint selfie photos under the grid", () => {
  const detail = read("DayDetail.jsx");
  const page = read("../../pages/CalendarPage.jsx");
  const lightbox = read("PhotoLightbox.jsx");
  const grid = read("CalendarGrid.jsx");
  assert.doesNotMatch(detail, /AuthPhoto/);
  assert.doesNotMatch(detail, /aspect-\[4\/3\]/);
  assert.match(detail, /onOpenPhotos/);
  assert.match(page, /PhotoLightbox/);
  assert.match(page, /openPhotos/);
  assert.match(lightbox, /Escape/);
  assert.match(lightbox, /ArrowLeft/);
  assert.match(lightbox, /ArrowRight/);
  assert.match(lightbox, /onTouchEnd/);
  assert.match(lightbox, /day-photo-lightbox-close/);
  assert.match(lightbox, /AuthPhoto/);
  assert.match(grid, /cal-photo-/);
  const auth = read("../AuthPhoto.jsx");
  assert.match(auth, /\/files\//);
});
