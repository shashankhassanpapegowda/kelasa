import { useEffect } from "react";
import { MapContainer, TileLayer, Circle, CircleMarker, useMap, useMapEvents } from "react-leaflet";

function ClickToPin({ onPick }) {
  useMapEvents({ click: (e) => onPick({ lat: e.latlng.lat, lng: e.latlng.lng }) });
  return null;
}

function FollowPin({ pin, radius }) {
  const map = useMap();
  useEffect(() => {
    if (!pin) return;
    const zoom = radius > 1500 ? 13 : radius > 400 ? 15 : 17;
    map.setView([pin.lat, pin.lng], Math.max(map.getZoom(), zoom));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pin?.lat, pin?.lng]);
  return null;
}

export default function BranchMapPicker({ pin, radius, onPick, others = [] }) {
  const center = pin ? [pin.lat, pin.lng] : [12.9716, 77.5946];
  return (
    <div className="h-[320px] w-full border border-border" data-testid="branch-map-picker">
      <MapContainer center={center} zoom={pin ? 16 : 11} style={{ height: "100%", width: "100%" }} scrollWheelZoom>
        <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"/>
        <ClickToPin onPick={onPick}/>
        <FollowPin pin={pin} radius={radius}/>
        {others.map(b => (
          <Circle key={b.unit_id} center={[b.lat, b.lng]} radius={b.radius_m}
            pathOptions={{ color: "#52525B", weight: 1, dashArray: "4 4", fillOpacity: 0.05 }}/>
        ))}
        {pin && (
          <>
            <Circle center={[pin.lat, pin.lng]} radius={radius || 0}
              pathOptions={{ color: "#0047FF", weight: 2, fillColor: "#0047FF", fillOpacity: 0.15 }}/>
            <CircleMarker center={[pin.lat, pin.lng]} radius={7}
              pathOptions={{ color: "#fff", weight: 3, fillColor: "#0047FF", fillOpacity: 1 }}/>
          </>
        )}
      </MapContainer>
    </div>
  );
}
