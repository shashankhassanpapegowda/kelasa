import { useEffect, useRef } from "react";
import { MapContainer, TileLayer, CircleMarker, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";

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

export default function LiveMap({ employees = [], height = "100%" }) {
  const withLoc = employees.filter((e) => e.lat != null && e.lng != null);
  const center = withLoc.length ? [withLoc[0].lat, withLoc[0].lng] : [12.9716, 77.5946];

  return (
    <div style={{ height, width: "100%" }} className="relative" data-testid="live-map">
      <MapContainer center={center} zoom={13} style={{ height: "100%", width: "100%" }} scrollWheelZoom={true}>
        <TileLayer
          attribution="&copy; OpenStreetMap contributors"
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {withLoc.map((e) => {
          const color = e.on_break ? "#F5A524" : "#00E676";
          return (
            <CircleMarker
              key={e.user_id}
              center={[e.lat, e.lng]}
              radius={9}
              pathOptions={{ color: "#ffffff", fillColor: color, fillOpacity: 1, weight: 3 }}
            >
              <Tooltip direction="top" permanent offset={[0, -8]}>
                <div className="font-mono text-[10px] font-semibold">
                  {e.name}{e.on_break ? " · break" : ""}
                </div>
              </Tooltip>
            </CircleMarker>
          );
        })}
        <FitOnce points={withLoc}/>
      </MapContainer>
    </div>
  );
}
