import { useEffect, useRef } from "react";
import { MapContainer, TileLayer, Circle, CircleMarker, Polyline, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";

// Stable, distinct colour per worker (used for both trail and marker border)
const colorFor = (id = "") => {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) % 360;
  return `hsl(${h}, 72%, 45%)`;
};

function FitOnce({ points }) {
  const map = useMap();
  const done = useRef(false);
  useEffect(() => {
    if (done.current || !points?.length) return;
    if (points.length === 1) {
      map.setView([points[0].lat, points[0].lng], 15);
    } else {
      map.fitBounds(L.latLngBounds(points.map((p) => [p.lat, p.lng])), { padding: [50, 50] });
    }
    done.current = true;
  }, [points, map]);
  return null;
}

export default function LiveMap({ employees = [], branches = [], height = "100%" }) {
  const withLoc = employees.filter((e) => e.lat != null && e.lng != null);
  const center = withLoc.length ? [withLoc[0].lat, withLoc[0].lng] : [12.9716, 77.5946];

  const boundsPoints = [];
  withLoc.forEach((e) => {
    boundsPoints.push({ lat: e.lat, lng: e.lng });
    (e.trail || []).forEach((t) => boundsPoints.push({ lat: t.lat, lng: t.lng }));
  });

  return (
    <div style={{ height, width: "100%" }} className="relative" data-testid="live-map">
      <MapContainer center={center} zoom={13} style={{ height: "100%", width: "100%" }} scrollWheelZoom={true}>
        <TileLayer
          attribution="&copy; OpenStreetMap contributors"
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {branches.map((b) => (
          <Circle key={b.unit_id} center={[b.lat, b.lng]} radius={b.radius_m}
            pathOptions={{ color: "#0047FF", weight: 1.5, dashArray: "5 5", fillOpacity: 0.06 }}>
            <Tooltip direction="center" opacity={0.9} className="kelasa-map-label">
              <div className="font-mono text-[10px]">{b.name} · {b.radius_m} m</div>
            </Tooltip>
          </Circle>
        ))}

        {/* Fading last-hour trail behind each marker */}
        {withLoc.map((e) => {
          const pts = e.trail || [];
          if (pts.length < 2) return null;
          const c = colorFor(e.user_id);
          const n = pts.length - 1;
          return pts.slice(1).map((p, i) => {
            const opacity = 0.15 + 0.7 * ((i + 1) / n); // older = fainter, newest = strongest
            return (
              <Polyline
                key={`${e.user_id}-trail-${i}`}
                positions={[[pts[i].lat, pts[i].lng], [p.lat, p.lng]]}
                pathOptions={{ color: c, weight: 4, opacity, lineCap: "round" }}
              />
            );
          });
        })}

        {/* Worker markers */}
        {withLoc.map((e) => {
          const status = e.on_break ? "#F5A524" : "#00E676";
          return (
            <CircleMarker
              key={e.user_id}
              center={[e.lat, e.lng]}
              radius={9}
              pathOptions={{ color: colorFor(e.user_id), fillColor: status, fillOpacity: 1, weight: 4 }}
            >
              <Tooltip direction="top" offset={[0, -10]} opacity={1} className="kelasa-map-label">
                <div className="font-mono text-[10px] font-semibold">
                  {e.name}{e.on_break ? " · break" : ""}
                </div>
              </Tooltip>
            </CircleMarker>
          );
        })}

        <FitOnce points={boundsPoints}/>
      </MapContainer>
    </div>
  );
}
