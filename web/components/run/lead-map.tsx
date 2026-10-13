"use client";

import { CircleMarker, MapContainer, TileLayer } from "react-leaflet";

/** OpenStreetMap tiles (free, attribution required). Loaded client-only via next/dynamic. */
export default function LeadMap({ lat, lng, label }: { lat: number; lng: number; label: string }) {
  return (
    <MapContainer
      center={[lat, lng]}
      zoom={14}
      scrollWheelZoom={false}
      dragging={false}
      className="h-36 w-full overflow-hidden rounded-lg border"
      aria-label={`Map showing ${label}`}
    >
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      />
      <CircleMarker
        center={[lat, lng]}
        radius={8}
        pathOptions={{ color: "#4F46E5", weight: 2, fillColor: "#818CF8", fillOpacity: 0.55 }}
      />
    </MapContainer>
  );
}
