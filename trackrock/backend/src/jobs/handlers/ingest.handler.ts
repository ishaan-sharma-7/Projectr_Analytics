import type { Job } from 'bullmq';
import path from 'path';
import { prisma } from '../../lib/prisma.js';
import { logger } from '../../lib/logger.js';
import { parseCsv } from '../../pipeline/csvParser.js';
import {
  classifyParentEntity,
  computeConfidence,
  buildSubsidiaryChain,
  extractZip,
  normalizeAddress,
} from '../../pipeline/entityClassifier.js';
import { config } from '../../config.js';

const BATCH_SIZE = 100;

interface DeepCleanRow {
  Property_ID: string;
  Owner_Name: string;
  Mailing_Address: string;
  Property_Address: string;
  Match_Reason: string;
}

interface MasterRow {
  Property_ID: string;
  First_Year_Institutional: string;
  Latest_Match_Reason: string;
  Latest_Owner: string;
  Years_Present: string;
}

/**
 * Parse the master CSV and return a map of property_id → acquisition year.
 * Master CSV has garbage appended to Property_ID — extract the first token only.
 */
async function loadMasterYears(csvDir: string): Promise<Map<string, number>> {
  const masterPath = path.join(csvDir, 'institutional_properties_master.csv');
  const yearMap = new Map<string, number>();

  try {
    const rows = (await parseCsv(masterPath)) as unknown as MasterRow[];
    for (const row of rows) {
      // Property_ID looks like "100012 0202500000000" — take first token
      const id = row.Property_ID.split(/\s+/)[0].trim();
      const year = parseInt(row.First_Year_Institutional);
      if (id && !isNaN(year) && year >= 2010 && year <= 2030) {
        yearMap.set(id, year);
      }
    }
    logger.info(`[Ingest] Loaded ${yearMap.size} acquisition years from master CSV`);
  } catch (err) {
    logger.warn(`[Ingest] Could not load master CSV: ${(err as Error).message}`);
  }

  return yearMap;
}

export async function ingestFromCsv(
  csvPath: string,
  city = 'Austin',
  onProgress?: (pct: number) => void,
): Promise<number> {
  logger.info(`[Ingest] Parsing ${csvPath}`);

  const rows = (await parseCsv(csvPath)) as unknown as DeepCleanRow[];
  logger.info(`[Ingest] ${rows.length} rows loaded`);

  // Load acquisition year lookup
  const csvDir = path.dirname(csvPath);
  const yearMap = await loadMasterYears(csvDir);

  let upserted = 0;

  for (let i = 0; i < rows.length; i += BATCH_SIZE) {
    const batch = rows.slice(i, i + BATCH_SIZE);

    const records = batch
      .filter((row) => row.Property_ID && row.Owner_Name)
      .map((row) => {
        const propId = row.Property_ID.trim();
        const parentEntity = classifyParentEntity(row.Owner_Name, row.Match_Reason);
        const confidenceScore = computeConfidence(row.Match_Reason);
        const subsidiaryChain = buildSubsidiaryChain(row.Owner_Name, parentEntity);
        const zipCode = extractZip(row.Property_Address);
        const acquisitionYear = yearMap.get(propId) ?? null;

        return {
          id: `austin-${propId}`,
          propertyAddress: normalizeAddress(row.Property_Address),
          mailingAddress: row.Mailing_Address || null,
          ownerName: row.Owner_Name.trim(),
          matchReason: row.Match_Reason.trim(),
          parentEntity,
          subsidiaryChain,
          confidenceScore,
          acquisitionYear,
          zipCode,
          city,
          state: 'TX',
        };
      });

    if (records.length === 0) continue;

    await prisma.property.createMany({
      data: records,
      skipDuplicates: true,
    });

    upserted += records.length;

    if (onProgress) {
      onProgress(Math.round(((i + batch.length) / rows.length) * 100));
    }
  }

  logger.info(`[Ingest] Done — ${upserted} records upserted`);
  return upserted;
}

export async function ingestHandler(job: Job): Promise<void> {
  const city: string = job.data.city ?? 'Austin';

  // If a specific file was uploaded, use it; otherwise use the default seed CSV
  const filePath: string =
    job.data.filePath ??
    path.resolve(config.seedCsvDir, 'institutional_owners_2025_deep_clean.csv');

  const rowsProcessed = await ingestFromCsv(filePath, city, async (pct) => {
    await job.updateProgress(pct);
  });

  await prisma.pipelineJob.updateMany({
    where: { stage: 'ingest', status: 'running', city },
    data: { rowsProcessed },
  });
}
