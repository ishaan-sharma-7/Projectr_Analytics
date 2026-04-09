import { useLocation } from "../hooks/useLocation";

export default function LocationButton({
  onLocation,
}: {
  onLocation?: (coords: { lat: number; lng: number }) => void;
}) {
  const { location, loading, error, getLocation } = useLocation();

  // 👇 NEW: send location to parent (App.tsx)
  if (location && onLocation) {
    onLocation({ lat: location.lat, lng: location.lon });
  }

  return (
    <div className="flex flex-col items-center gap-3 mt-6">
      <button
        onClick={getLocation}
        className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition"
      >
        {loading ? "Getting location..." : "Use My Location"}
      </button>

      {location && (
        <p className="text-sm text-gray-600">
          {location.lat.toFixed(4)}, {location.lon.toFixed(4)}
        </p>
      )}

      {error && (
        <p className="text-sm text-red-500">{error}</p>
      )}
    </div>
  );
}
