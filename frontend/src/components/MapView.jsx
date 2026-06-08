import { useEffect } from "react";
import { MapContainer, TileLayer, Polyline, CircleMarker, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";

// Fix default icon issue
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

function FitBounds({ points }) {
  const map = useMap();
  useEffect(() => {
    if (!points?.length) return;
    if (points.length === 1) {
      map.setView([points[0].lat, points[0].lng], 16);
    } else {
      const bounds = L.latLngBounds(points.map(p => [p.lat, p.lng]));
      map.fitBounds(bounds, { padding: [40, 40] });
    }
  }, [points, map]);
  return null;
}

export default function MapView({ pings = [], height = "100%" }) {
  const center = pings.length ? [pings[0].lat, pings[0].lng] : [12.9716, 77.5946]; // Bengaluru default
  const polyline = pings.map(p => [p.lat, p.lng]);

  return (
    <div style={{ height, width: "100%" }} className="relative border border-border" data-testid="route-map">
      <MapContainer
        center={center}
        zoom={13}
        style={{ height: "100%", width: "100%" }}
        scrollWheelZoom={true}
      >
        <TileLayer
          attribution='&copy; OpenStreetMap, &copy; CartoDB'
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        />
        {polyline.length > 1 && (
          <Polyline positions={polyline} pathOptions={{ color: "#0047FF", weight: 4, opacity: 0.85 }}/>
        )}
        {pings.map((p, i) => {
          const isStart = i === 0;
          const isEnd = i === pings.length - 1 && pings.length > 1;
          const color = isStart ? "#00E676" : isEnd ? "#FF3B30" : "#0047FF";
          const ts = new Date(p.timestamp);
          const label = `${ts.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
          return (
            <CircleMarker
              key={p.ping_id || i}
              center={[p.lat, p.lng]}
              radius={isStart || isEnd ? 8 : 5}
              pathOptions={{ color, fillColor: color, fillOpacity: 1, weight: 2 }}
            >
              <Tooltip direction="top">
                <div className="font-mono text-xs">
                  {isStart ? "Start · " : isEnd ? "End · " : ""}{label}
                </div>
              </Tooltip>
            </CircleMarker>
          );
        })}
        <FitBounds points={pings}/>
      </MapContainer>
    </div>
  );
}
