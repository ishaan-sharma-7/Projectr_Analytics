/**
 * compareInsight.ts — pure frontend logic to generate a 1–2 sentence
 * comparison between two universities. No AI, just data-driven text.
 */

import type { HousingPressureScore } from "./api";

export function generateCompareInsight(
  a: HousingPressureScore,
  b: HousingPressureScore,
): string {
  const nameA = a.university.name;
  const nameB = b.university.name;

  // Overall winner
  const diff = a.score - b.score;
  if (Math.abs(diff) < 3) {
    return `${nameA} and ${nameB} show similar housing pressure levels. Both markets warrant close attention for development timing.`;
  }

  const higher = diff > 0 ? a : b;
  const lower = diff > 0 ? b : a;
  const higherName = higher.university.name;
  const lowerName = lower.university.name;

  // Find the biggest component differentiator
  const deltas = [
    {
      label: "enrollment growth",
      diff: higher.components.enrollment_pressure - lower.components.enrollment_pressure,
    },
    {
      label: "permit shortfall",
      diff: higher.components.permit_gap - lower.components.permit_gap,
    },
    {
      label: "rent inflation",
      diff: higher.components.rent_pressure - lower.components.rent_pressure,
    },
  ].sort((x, y) => Math.abs(y.diff) - Math.abs(x.diff));

  const topDriver = deltas[0];

  const reason =
    topDriver.diff > 5
      ? `primarily driven by stronger ${topDriver.label}`
      : "across multiple factors";

  return `${higherName} shows higher housing pressure (${higher.score.toFixed(0)} vs ${lower.score.toFixed(0)}), ${reason}. ${lowerName} appears more balanced, suggesting better supply-demand alignment.`;
}
