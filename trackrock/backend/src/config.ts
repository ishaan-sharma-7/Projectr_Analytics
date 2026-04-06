import dotenv from 'dotenv';
import path from 'path';

// Load .env from Projectr_Analytics root
dotenv.config({ path: path.resolve(process.cwd(), '../../.env') });

function require(key: string): string {
  const val = process.env[key];
  if (!val) throw new Error(`Missing required environment variable: ${key}`);
  return val;
}

function optional(key: string, fallback = ''): string {
  return process.env[key] ?? fallback;
}

export const config = {
  port: parseInt(optional('PORT', '3001')),
  nodeEnv: optional('NODE_ENV', 'development'),
  isDev: optional('NODE_ENV', 'development') === 'development',

  // Database
  databaseUrl: require('DATABASE_URL'),

  // Redis
  redisUrl: require('REDIS_URL'),

  // Google APIs
  googleMapsKey: optional('GOOGLE_MAPS_API_KEY'),
  geminiKey: optional('GOOGLE_GEMINI_API_KEY'),

  // External data APIs
  censusKey: optional('CENSUS_API_KEY'),
  fredKey: optional('FRED_API_KEY'),
  hudToken: optional('HUD_API_TOKEN'),

  // GCS
  gcsBucket: optional('GCS_BUCKET_NAME', 'trackrock-artifacts'),
  gcsProject: optional('GCS_PROJECT_ID'),

  // Seed data
  seedCsvDir: optional('SEED_CSV_DIR', './processed_owners'),
} as const;
