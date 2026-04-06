import fs from 'fs';
import readline from 'readline';

export interface CsvRow {
  [key: string]: string;
}

/**
 * Parse a CSV file line-by-line (memory efficient for large files).
 * Returns rows as plain objects keyed by header names.
 * Handles quoted fields with commas inside.
 */
export async function parseCsv(filePath: string): Promise<CsvRow[]> {
  const rows: CsvRow[] = [];
  const rl = readline.createInterface({
    input: fs.createReadStream(filePath, { encoding: 'utf-8' }),
    crlfDelay: Infinity,
  });

  let headers: string[] = [];
  let isFirst = true;

  for await (const line of rl) {
    const fields = splitCsvLine(line);
    if (isFirst) {
      headers = fields.map((h) => h.trim());
      isFirst = false;
      continue;
    }
    if (fields.length === 0 || (fields.length === 1 && fields[0] === '')) continue;

    const row: CsvRow = {};
    headers.forEach((h, i) => {
      row[h] = (fields[i] ?? '').trim();
    });
    rows.push(row);
  }

  return rows;
}

/** Split a CSV line respecting quoted fields */
function splitCsvLine(line: string): string[] {
  const fields: string[] = [];
  let current = '';
  let inQuotes = false;

  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === ',' && !inQuotes) {
      fields.push(current);
      current = '';
    } else {
      current += ch;
    }
  }
  fields.push(current);
  return fields;
}
