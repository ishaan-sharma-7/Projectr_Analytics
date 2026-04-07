import { MapPin } from "lucide-react";
import { UNIVERSITIES } from "../../lib/universityList";

export function EmptyState() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-zinc-500">
      <div className="w-16 h-16 rounded-2xl bg-zinc-900 flex items-center justify-center mb-6">
        <MapPin className="w-8 h-8 text-zinc-600" />
      </div>
      <h2 className="text-lg font-medium text-zinc-300 mb-2">No Market Selected</h2>
      <p className="text-sm leading-relaxed">
        Click any pin on the map or search for a university to run a live housing market analysis.
      </p>
      <p className="text-xs text-zinc-600 mt-4">{UNIVERSITIES.length} universities available</p>
    </div>
  );
}
