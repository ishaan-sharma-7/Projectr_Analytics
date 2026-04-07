import { useState } from 'react';
import { Search } from 'lucide-react';
import { computeScore, type HousingPressureScore } from './lib/api';

import { APIProvider, Map, AdvancedMarker, Pin } from '@vis.gl/react-google-maps';

// Add this constant above App function
const MAPS_API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY || "";

function App() {
  const [searchQuery, setSearchQuery] = useState('');
  const [activeScore, setActiveScore] = useState<HousingPressureScore | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;

    setLoading(true);
    setError(null);
    try {
      const result = await computeScore(searchQuery);
      setActiveScore(result);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch score');
    } finally {
      setLoading(false);
    }
  };

  // Determine map center
  const center = activeScore ? { lat: activeScore.university.lat, lng: activeScore.university.lon } : { lat: 39.8283, lng: -98.5795 };
  const zoom = activeScore ? 12 : 4;

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-zinc-950 text-zinc-50 relative">
      {/* Top Navbar */}
      <header className="absolute top-0 left-0 right-0 z-10 flex items-center justify-between px-6 py-4 bg-zinc-950/80 backdrop-blur-md border-b border-zinc-800">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <span className="font-bold text-lg">C</span>
          </div>
          <h1 className="text-xl font-bold tracking-tight">CampusLens</h1>
        </div>

        <form onSubmit={handleSearch} className="flex-1 max-w-md mx-8 relative">
          <input
            type="text"
            placeholder="Search any US university..."
            className="w-full bg-zinc-900 border border-zinc-700 focus:border-blue-500 rounded-full px-5 py-2.5 pl-11 outline-none text-sm transition-colors"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400" />
        </form>

        <div className="text-sm text-zinc-400 font-medium">
          vt-2026
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 flex mt-[73px]">
        {/* Google Map */}
        <div className="flex-1 bg-zinc-900 relative">
          <APIProvider apiKey={MAPS_API_KEY}>
            <Map
              mapId="CampusLensMap"
              center={center}
              zoom={zoom}
              disableDefaultUI={true}
              zoomControl={true}
            >
              {activeScore && (
                <AdvancedMarker position={center}>
                  <div className="relative">
                    <Pin background={activeScore.score > 70 ? "#ef4444" : activeScore.score > 40 ? "#eab308" : "#22c55e"} borderColor="#18181b" glyphColor="#18181b" />
                    <div className="absolute -top-10 left-1/2 -translate-x-1/2 bg-zinc-900 text-white text-xs font-bold px-2 py-1 rounded shadow-lg whitespace-nowrap">
                      Score: {activeScore.score.toFixed(1)}
                    </div>
                  </div>
                </AdvancedMarker>
              )}
            </Map>
          </APIProvider>
        </div>

        {/* Side Panel */}
        <aside className="w-[450px] border-l border-zinc-800 bg-zinc-950 flex flex-col relative z-20 shadow-2xl">
          {loading && (
            <div className="absolute inset-0 bg-zinc-950/50 backdrop-blur-sm z-10 flex flex-col items-center justify-center">
              <div className="w-10 h-10 border-4 border-blue-500/30 border-t-blue-500 rounded-full animate-spin mb-4" />
              <p className="text-zinc-400 font-medium animate-pulse">Running live market analysis...</p>
            </div>
          )}

          {error && (
            <div className="p-6 m-4 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400">
              <h3 className="font-bold mb-1">Analysis Failed</h3>
              <p className="text-sm">{error}</p>
            </div>
          )}

          {!activeScore && !loading && !error && (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-zinc-500">
              <div className="w-16 h-16 rounded-2xl bg-zinc-900 flex items-center justify-center mb-6">
                <Search className="w-8 h-8 text-zinc-600" />
              </div>
              <h2 className="text-lg font-medium text-zinc-300 mb-2">No Market Selected</h2>
              <p className="text-sm">Search for a university to analyze its surrounding housing market pressure.</p>
            </div>
          )}

          {activeScore && (
            <div className="flex-1 overflow-y-auto p-6 scrollbar-thin">
              <div className="mb-8">
                <p className="text-sm font-medium text-blue-400 mb-1 tracking-wide uppercase">
                  {activeScore.university.city}, {activeScore.university.state}
                </p>
                <h2 className="text-2xl font-bold font-serif">{activeScore.university.name}</h2>
              </div>

              {/* Score Card */}
              <div className="bg-zinc-900 rounded-2xl p-6 border border-zinc-800 mb-8 relative overflow-hidden">
                <div className="absolute top-0 right-0 w-32 h-32 bg-blue-500/10 blur-3xl rounded-full translate-x-1/2 -translate-y-1/2" />
                <h3 className="text-sm font-medium text-zinc-400 mb-4 uppercase tracking-wider">Housing Pressure Score</h3>
                <div className="flex items-end gap-3 mb-6">
                  <span className="text-6xl font-black tabular-nums tracking-tighter">
                    {activeScore.score.toFixed(1)}
                  </span>
                  <span className="text-zinc-500 font-medium mb-1.5 flex items-center gap-1">
                    / 100 <span className="w-1.5 h-1.5 rounded-full bg-red-500 ml-2 animate-pulse" />
                  </span>
                </div>
                
                <div className="space-y-4">
                  <div className="space-y-1.5">
                    <div className="flex justify-between text-xs font-medium">
                      <span className="text-zinc-400">Enrollment Growth</span>
                      <span className="text-zinc-200">{activeScore.components.enrollment_pressure.toFixed(1)}</span>
                    </div>
                    <div className="h-1.5 w-full bg-zinc-950 rounded-full overflow-hidden">
                      <div className="h-full bg-blue-500 rounded-full" style={{ width: `${activeScore.components.enrollment_pressure}%` }} />
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <div className="flex justify-between text-xs font-medium">
                      <span className="text-zinc-400">Permit Gap</span>
                      <span className="text-zinc-200">{activeScore.components.permit_gap.toFixed(1)}</span>
                    </div>
                    <div className="h-1.5 w-full bg-zinc-950 rounded-full overflow-hidden">
                      <div className="h-full bg-purple-500 rounded-full" style={{ width: `${activeScore.components.permit_gap}%` }} />
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <div className="flex justify-between text-xs font-medium">
                      <span className="text-zinc-400">Rent Inflation</span>
                      <span className="text-zinc-200">{activeScore.components.rent_pressure.toFixed(1)}</span>
                    </div>
                    <div className="h-1.5 w-full bg-zinc-950 rounded-full overflow-hidden">
                      <div className="h-full bg-rose-500 rounded-full" style={{ width: `${activeScore.components.rent_pressure}%` }} />
                    </div>
                  </div>
                </div>
              </div>

              {/* Data Summary Stats */}
              <div className="grid grid-cols-2 gap-3 mb-8">
                <div className="bg-zinc-900/50 p-4 rounded-xl border border-zinc-800/50">
                  <p className="text-xs text-zinc-500 font-medium mb-1">Latest Enrollment</p>
                  <p className="text-lg font-bold">
                    {activeScore.enrollment_trend[activeScore.enrollment_trend.length - 1]?.total_enrollment.toLocaleString() || 'N/A'}
                  </p>
                </div>
                <div className="bg-zinc-900/50 p-4 rounded-xl border border-zinc-800/50">
                  <p className="text-xs text-zinc-500 font-medium mb-1">Total Housing Units</p>
                  <p className="text-lg font-bold">
                    {activeScore.nearby_housing_units > 0 ? activeScore.nearby_housing_units.toLocaleString() : 'N/A'}
                  </p>
                </div>
              </div>

            </div>
          )}
        </aside>
      </main>
    </div>
  );
}

export default App;
