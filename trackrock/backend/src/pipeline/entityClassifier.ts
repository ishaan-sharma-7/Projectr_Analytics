import {
  PARENT_ENTITY_KEYWORDS,
  KNOWN_HQ_ZIPS,
  CONFIDENCE_BY_MATCH_TYPE,
} from '@trackrock/shared';
import type { ParentEntity } from '@trackrock/shared';

/**
 * Classify a property's parent entity from owner name and match reason.
 * Uses the seed keyword list — no API calls needed.
 */
export function classifyParentEntity(
  ownerName: string,
  matchReason: string,
): ParentEntity {
  const upper = ownerName.toUpperCase();
  const reasonUpper = matchReason.toUpperCase();

  // Check each entity's keywords
  for (const [entity, keywords] of Object.entries(PARENT_ENTITY_KEYWORDS)) {
    for (const kw of keywords) {
      if (upper.includes(kw) || reasonUpper.includes(kw)) {
        return entity as ParentEntity;
      }
    }
  }

  // Fall back to HQ zip hint from matchReason e.g. "HQ Zip: 75201 (TX)"
  const zipMatch = matchReason.match(/HQ Zip:\s*(\d{5})/);
  if (zipMatch) {
    const entity = KNOWN_HQ_ZIPS[zipMatch[1]];
    if (entity) return entity;
  }

  return 'OTHER';
}

/**
 * Compute a confidence score (0–1) based on the match reason string.
 */
export function computeConfidence(matchReason: string): number {
  const r = matchReason.toUpperCase();

  if (r.startsWith('KEYWORD:')) {
    // Direct named keyword — check if it's a specific subsidiary name
    const kw = matchReason.replace(/^Keyword:\s*/i, '').trim().toUpperCase();
    // Named subsidiaries (AMH 2014, IH2 LP etc.) score higher than generic
    const isSpecific = kw.match(/\d{4}|BORROWER|LP|LLC|INVH|FIRSTKEY|PROGRESS|TRICON/);
    return isSpecific
      ? CONFIDENCE_BY_MATCH_TYPE.keyword_subsidiary
      : CONFIDENCE_BY_MATCH_TYPE.keyword_direct;
  }

  if (r.startsWith('HQ ZIP:') || r.startsWith('MAILING:')) {
    return CONFIDENCE_BY_MATCH_TYPE.hq_zip;
  }

  if (r.startsWith('CLUSTER:')) {
    return CONFIDENCE_BY_MATCH_TYPE.cluster;
  }

  return 0.6; // Unknown match type — low but not zero
}

/**
 * Extract a subsidiary chain from the owner name.
 * Returns individual LLC/LP names found in the string.
 */
export function buildSubsidiaryChain(ownerName: string, _parent: ParentEntity): string[] {
  // Split on common separators used in combined ownership strings
  const parts = ownerName
    .split(/\s*[/\\|]\s*|\s+C\/O\s+|\s+ATTN\s*:/i)
    .map((p) => p.trim())
    .filter((p) => p.length > 3 && /LLC|LP|INC|CORP|TRUST|REIT/i.test(p));

  return parts.length > 0 ? parts : [ownerName.trim()];
}

/**
 * Extract a ZIP code from an address string.
 */
export function extractZip(address: string): string | null {
  const match = address.match(/\b(\d{5})(?:-\d{4})?\b/);
  return match ? match[1] : null;
}

/**
 * Normalise a property address — remove leading zeros, standardise whitespace.
 */
export function normalizeAddress(address: string): string {
  return address.replace(/\s+/g, ' ').trim();
}
