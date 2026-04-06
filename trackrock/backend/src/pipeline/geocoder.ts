import { redis } from '../lib/redis.js';
import { logger } from '../lib/logger.js';
import { config } from '../config.js';
import { CACHE_TTL } from '@trackrock/shared';

const GEOCODE_CACHE_PREFIX = 'geocode:';
const FIPS_CACHE_PREFIX = 'fips:';

export interface GeocodeResult {
  lat: number;
  lng: number;
  zipCode: string | null;
  city: string | null;
  state: string | null;
  quality: 'ROOFTOP' | 'RANGE_INTERPOLATED' | 'GEOMETRIC_CENTER' | 'APPROXIMATE';
}

export interface FipsResult {
  fipsTract: string;
  fipsCounty: string;
  fipsState: string;
}

/**
 * Geocode a property address using Google Maps Geocoding API.
 * Results are cached in Redis for 30 days.
 */
export async function geocodeAddress(
  address: string,
  city: string,
  state: string,
): Promise<GeocodeResult | null> {
  if (!config.googleMapsKey) {
    logger.warn('[Geocoder] GOOGLE_MAPS_API_KEY not set — skipping geocode');
    return null;
  }

  const normalised = `${address}, ${city}, ${state}`.replace(/\s+/g, ' ').trim();
  const cacheKey = `${GEOCODE_CACHE_PREFIX}${normalised.toUpperCase()}`;

  // Check cache
  try {
    const cached = await redis.get(cacheKey);
    if (cached) return JSON.parse(cached) as GeocodeResult;
  } catch { /* proceed */ }

  const params = new URLSearchParams({
    address: normalised,
    key: config.googleMapsKey,
  });

  try {
    const res = await fetch(
      `https://maps.googleapis.com/maps/api/geocode/json?${params}`,
    );
    const data = await res.json() as {
      status: string;
      results: Array<{
        geometry: { location: { lat: number; lng: number }; location_type: string };
        address_components: Array<{ long_name: string; short_name: string; types: string[] }>;
      }>;
    };

    if (data.status !== 'OK' || !data.results[0]) {
      logger.debug(`[Geocoder] No result for "${normalised}": ${data.status}`);
      return null;
    }

    const result = data.results[0];
    const { lat, lng } = result.geometry.location;
    const locationType = result.geometry.location_type as GeocodeResult['quality'];

    // Extract address components
    const getComponent = (type: string) =>
      result.address_components.find((c) => c.types.includes(type));

    const zipCode = getComponent('postal_code')?.long_name ?? null;
    const city = getComponent('locality')?.long_name
      ?? getComponent('sublocality')?.long_name
      ?? null;
    const stateName = getComponent('administrative_area_level_1')?.short_name ?? null;

    const geocoded: GeocodeResult = {
      lat,
      lng,
      zipCode,
      city,
      state: stateName,
      quality: locationType ?? 'APPROXIMATE',
    };

    // Cache result
    try {
      await redis.setex(cacheKey, CACHE_TTL.GEOCODE, JSON.stringify(geocoded));
    } catch { /* non-fatal */ }

    return geocoded;
  } catch (err) {
    logger.warn(`[Geocoder] API error for "${normalised}": ${(err as Error).message}`);
    return null;
  }
}

/**
 * Look up Census FIPS tract from lat/lng using the Census Geocoder API.
 * No API key required. Results cached 90 days.
 */
export async function getFipsTract(
  lat: number,
  lng: number,
): Promise<FipsResult | null> {
  const cacheKey = `${FIPS_CACHE_PREFIX}${lat.toFixed(4)}:${lng.toFixed(4)}`;

  // Check cache
  try {
    const cached = await redis.get(cacheKey);
    if (cached) return JSON.parse(cached) as FipsResult;
  } catch { /* proceed */ }

  const params = new URLSearchParams({
    x: lng.toString(),
    y: lat.toString(),
    benchmark: 'Public_AR_Current',
    vintage: 'Current_Current',
    format: 'json',
  });

  try {
    const res = await fetch(
      `https://geocoding.geo.census.gov/geocoder/geographies/coordinates?${params}`,
      { signal: AbortSignal.timeout(10_000) },
    );
    const data = await res.json() as {
      result?: {
        geographies?: {
          'Census Tracts'?: Array<{ GEOID: string; COUNTY: string; STATE: string }>;
        };
      };
    };

    const tract = data.result?.geographies?.['Census Tracts']?.[0];
    if (!tract) return null;

    const fipsResult: FipsResult = {
      fipsTract: tract.GEOID,
      fipsCounty: tract.COUNTY,
      fipsState: tract.STATE,
    };

    // Cache result
    try {
      await redis.setex(cacheKey, CACHE_TTL.FIPS_LOOKUP, JSON.stringify(fipsResult));
    } catch { /* non-fatal */ }

    return fipsResult;
  } catch (err) {
    logger.debug(`[FIPS] Lookup failed for ${lat},${lng}: ${(err as Error).message}`);
    return null;
  }
}
