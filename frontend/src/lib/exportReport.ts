import type { HousingPressureScore } from "./api";
import { resolveCompareLabels } from "./uniAbbrev";

// ── Helpers ──────────────────────────────────────────────────────────────────

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}

function blobDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function labelFromScore(score: number): string {
  return score >= 70
    ? "Strong Opportunity"
    : score >= 40
      ? "Emerging Market"
      : "Saturated Market";
}

// ── JSON ─────────────────────────────────────────────────────────────────────

export function exportToJSON(score: HousingPressureScore): void {
  const json = JSON.stringify(score, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  blobDownload(blob, `${slugify(score.university.name)}_campuslens.json`);
}

// ── PDF ──────────────────────────────────────────────────────────────────────

export async function exportToPDF(score: HousingPressureScore): Promise<void> {
  const { default: jsPDF } = await import("jspdf");
  const { default: autoTable } = await import("jspdf-autotable");

  const doc = new jsPDF({ unit: "pt", format: "letter" });
  const uni = score.university;
  const pageW = doc.internal.pageSize.getWidth();
  const margin = 48;
  const contentW = pageW - margin * 2;
  let y = margin;

  // ── Color palette ──
  const DARK = [20, 20, 30] as [number, number, number];
  const BLUE = [59, 130, 246] as [number, number, number];
  const GRAY = [100, 100, 110] as [number, number, number];
  const LIGHT = [240, 240, 245] as [number, number, number];

  // ── Header band ──
  doc.setFillColor(...DARK);
  doc.rect(0, 0, pageW, 80, "F");

  doc.setFontSize(9);
  doc.setTextColor(150, 160, 180);
  doc.text("CampusLens  ·  Housing Market Intelligence", margin, 28);

  doc.setFontSize(18);
  doc.setFont("helvetica", "bold");
  doc.setTextColor(255, 255, 255);
  doc.text(uni.name, margin, 52);

  doc.setFontSize(9);
  doc.setFont("helvetica", "normal");
  doc.setTextColor(150, 160, 180);
  doc.text(
    `${uni.city}, ${uni.state}  ·  ${uni.enrollment?.toLocaleString() ?? "—"} enrolled`,
    margin,
    68,
  );

  y = 104;

  // ── Score band ──
  const label = labelFromScore(score.score);
  doc.setFillColor(...LIGHT);
  doc.roundedRect(margin, y, contentW, 60, 6, 6, "F");

  doc.setFontSize(28);
  doc.setFont("helvetica", "bold");
  doc.setTextColor(...BLUE);
  doc.text(`${score.score.toFixed(1)}`, margin + 16, y + 38);

  doc.setFontSize(9);
  doc.setTextColor(...GRAY);
  doc.text("/ 100  Housing Pressure Score", margin + 70, y + 38);

  doc.setFontSize(10);
  doc.setFont("helvetica", "bold");
  doc.setTextColor(...DARK);
  doc.text(label, pageW - margin - doc.getTextWidth(label) - 16, y + 38);

  y += 76;

  // ── Score components ──
  doc.setFontSize(8);
  doc.setFont("helvetica", "normal");
  doc.setTextColor(...GRAY);
  const components = [
    ["Enrollment Pressure", score.components.enrollment_pressure],
    ["Permit Gap", score.components.permit_gap],
    ["Rent Pressure", score.components.rent_pressure],
  ] as [string, number][];
  const colW = contentW / 3;
  components.forEach(([name, val], i) => {
    const cx = margin + i * colW + colW / 2;
    doc.text(name, cx, y, { align: "center" });
    doc.setFontSize(13);
    doc.setFont("helvetica", "bold");
    doc.setTextColor(...DARK);
    doc.text(`${val.toFixed(1)}`, cx, y + 14, { align: "center" });
    doc.setFontSize(8);
    doc.setFont("helvetica", "normal");
    doc.setTextColor(...GRAY);
  });
  y += 36;

  // ── AI Market Brief ──
  if (score.gemini_summary) {
    doc.setFontSize(9);
    doc.setFont("helvetica", "bold");
    doc.setTextColor(...BLUE);
    doc.text("GEMINI MARKET BRIEF", margin, y);
    y += 14;

    doc.setFont("helvetica", "normal");
    doc.setTextColor(...DARK);
    doc.setFontSize(9);
    const lines = doc.splitTextToSize(score.gemini_summary, contentW);
    doc.text(lines, margin, y);
    y += lines.length * 12 + 12;
  }

  // ── Key Metrics table ──
  const enrollFirst = score.enrollment_trend.at(0);
  const enrollLast = score.enrollment_trend.at(-1);
  const latestEnroll = enrollLast?.total_enrollment;
  const earliestEnroll = enrollFirst?.total_enrollment;
  const enrollChange =
    latestEnroll && earliestEnroll
      ? `${(((latestEnroll - earliestEnroll) / earliestEnroll) * 100).toFixed(1)}%`
      : "—";

  const rentFirst = score.rent_history.at(0);
  const rentLast = score.rent_history.at(-1);
  const latestRent = rentLast?.median_rent;
  const earliestRent = rentFirst?.median_rent;
  const rentChange =
    latestRent && earliestRent
      ? `${(((latestRent - earliestRent) / earliestRent) * 100).toFixed(1)}%`
      : "—";

  const totalPermits = score.permit_history.reduce((s, p) => s + p.permits, 0);
  const pipelinePct =
    latestEnroll && totalPermits
      ? `${((totalPermits / latestEnroll) * 100).toFixed(1)}%`
      : "—";

  autoTable(doc, {
    startY: y,
    head: [["Metric", "Value", "Context"]],
    body: [
      [
        "Enrollment",
        latestEnroll?.toLocaleString() ?? "—",
        `${enrollChange} change`,
      ],
      [
        "Median Rent",
        latestRent ? `$${latestRent.toLocaleString()}` : "—",
        `${rentChange} change`,
      ],
      [
        "Permits (5yr)",
        totalPermits > 0 ? totalPermits.toLocaleString() : "—",
        "residential units",
      ],
      ["Supply Pipeline", pipelinePct, "permits / enrollment"],
      [
        "County Housing Units",
        score.nearby_housing_units?.toLocaleString() ?? "—",
        "ACS estimate",
      ],
      [
        "On-Campus Beds/Student",
        score.housing_capacity?.beds_per_student?.toFixed(2) ?? "—",
        score.housing_capacity?.dormitory_capacity?.toLocaleString() ??
          "—" + " total beds",
      ],
      [
        "Vacancy Rate",
        score.demographics?.vacancy_rate_pct != null
          ? `${score.demographics.vacancy_rate_pct.toFixed(1)}%`
          : "—",
        "renter market",
      ],
      [
        "Median Gross Rent",
        score.demographics?.median_gross_rent
          ? `$${score.demographics.median_gross_rent.toLocaleString()}`
          : "—",
        "ACS",
      ],
      [
        "Median Home Value",
        score.demographics?.median_home_value
          ? `$${score.demographics.median_home_value.toLocaleString()}`
          : "—",
        "ACS",
      ],
      [
        "Median Household Income",
        score.demographics?.median_household_income
          ? `$${score.demographics.median_household_income.toLocaleString()}`
          : "—",
        "ACS",
      ],
      [
        "Renter-Occupied %",
        score.demographics?.pct_renter_occupied != null
          ? `${score.demographics.pct_renter_occupied.toFixed(1)}%`
          : "—",
        "",
      ],
      [
        "Weather Disasters",
        score.disaster_risk?.weather_disasters?.toString() ?? "—",
        `last ${score.disaster_risk?.window_years ?? 10}yr (FEMA)`,
      ],
    ],
    headStyles: { fillColor: DARK, textColor: [255, 255, 255], fontSize: 8 },
    bodyStyles: { fontSize: 8, textColor: DARK },
    alternateRowStyles: { fillColor: [248, 248, 252] },
    margin: { left: margin, right: margin },
  });

  y = (doc as any).lastAutoTable.finalY + 16;

  // ── Institutional Strength ──
  if (score.institutional_strength) {
    const ist = score.institutional_strength;
    autoTable(doc, {
      startY: y,
      head: [["Institutional Strength", ""]],
      body: [
        [
          "Strength Score",
          ist.strength_score != null
            ? `${ist.strength_score.toFixed(0)}/100 (${ist.strength_label})`
            : "—",
        ],
        ["Ownership", ist.ownership_label ?? "—"],
        [
          "Retention Rate",
          ist.retention_rate != null
            ? `${(ist.retention_rate * 100).toFixed(0)}%`
            : "—",
        ],
        [
          "Admission Rate",
          ist.admission_rate != null
            ? `${(ist.admission_rate * 100).toFixed(0)}%`
            : "—",
        ],
        [
          "Endowment / Student",
          ist.endowment_per_student
            ? `$${ist.endowment_per_student.toLocaleString()}`
            : "—",
        ],
        [
          "Total Endowment",
          ist.endowment_end
            ? `$${(ist.endowment_end / 1_000_000).toFixed(0)}M`
            : "—",
        ],
        [
          "Pell Grant Rate",
          ist.pell_grant_rate != null
            ? `${(ist.pell_grant_rate * 100).toFixed(0)}%`
            : "—",
        ],
      ],
      headStyles: { fillColor: DARK, textColor: [255, 255, 255], fontSize: 8 },
      bodyStyles: { fontSize: 8, textColor: DARK },
      alternateRowStyles: { fillColor: [248, 248, 252] },
      margin: { left: margin, right: margin },
    });
    y = (doc as any).lastAutoTable.finalY + 16;
  }

  // ── Existing Housing Stock ──
  if (score.existing_housing) {
    const eh = score.existing_housing;
    autoTable(doc, {
      startY: y,
      head: [["Existing Housing Stock (OSM)", ""]],
      body: [
        ["Saturation", eh.saturation_label],
        ["Apartment Buildings", eh.apartment_buildings.toLocaleString()],
        ["Dormitory Buildings", eh.dormitory_buildings.toLocaleString()],
        [
          "Residential / Houses",
          `${eh.residential_buildings.toLocaleString()} / ${eh.house_buildings.toLocaleString()}`,
        ],
        [
          "Multifamily Density",
          `${eh.apartment_density_per_km2.toFixed(1)} / km²`,
        ],
        ["Search Radius", `${eh.radius_miles} miles`],
      ],
      headStyles: { fillColor: DARK, textColor: [255, 255, 255], fontSize: 8 },
      bodyStyles: { fontSize: 8, textColor: DARK },
      alternateRowStyles: { fillColor: [248, 248, 252] },
      margin: { left: margin, right: margin },
    });
    y = (doc as any).lastAutoTable.finalY + 16;
  }

  // ── Occupancy Ordinance ──
  if (
    score.occupancy_ordinance &&
    score.occupancy_ordinance.ordinance_type !== "none"
  ) {
    const ord = score.occupancy_ordinance;
    autoTable(doc, {
      startY: y,
      head: [["Occupancy Ordinance", ""]],
      body: [
        ["Type", ord.ordinance_type],
        [
          "Max Unrelated Occupants",
          ord.max_unrelated_occupants != null
            ? `≤${ord.max_unrelated_occupants}`
            : "No cap",
        ],
        ["Enforced", ord.enforced ? "Yes" : "No"],
        ["PBSH Signal", ord.pbsh_signal],
        ["Confidence", ord.confidence],
        ...(ord.notes ? [["Notes", ord.notes]] : []),
      ],
      headStyles: { fillColor: DARK, textColor: [255, 255, 255], fontSize: 8 },
      bodyStyles: { fontSize: 8, textColor: DARK },
      alternateRowStyles: { fillColor: [248, 248, 252] },
      margin: { left: margin, right: margin },
    });
    y = (doc as any).lastAutoTable.finalY + 16;
  }

  // ── Enrollment trend ──
  if (score.enrollment_trend.length > 0) {
    autoTable(doc, {
      startY: y,
      head: [["Year", "Total Enrollment"]],
      body: score.enrollment_trend.map((e) => [
        e.year,
        e.total_enrollment.toLocaleString(),
      ]),
      headStyles: { fillColor: DARK, textColor: [255, 255, 255], fontSize: 8 },
      bodyStyles: { fontSize: 8, textColor: DARK },
      alternateRowStyles: { fillColor: [248, 248, 252] },
      margin: { left: margin, right: margin },
      tableWidth: contentW / 2,
    });
    y = (doc as any).lastAutoTable.finalY + 16;
  }

  // ── Permit history ──
  if (score.permit_history.length > 0) {
    autoTable(doc, {
      startY: y,
      head: [["Year", "Permits Issued"]],
      body: score.permit_history.map((p) => [
        p.year,
        p.permits.toLocaleString(),
      ]),
      headStyles: { fillColor: DARK, textColor: [255, 255, 255], fontSize: 8 },
      bodyStyles: { fontSize: 8, textColor: DARK },
      alternateRowStyles: { fillColor: [248, 248, 252] },
      margin: { left: margin, right: margin },
      tableWidth: contentW / 2,
    });
    y = (doc as any).lastAutoTable.finalY + 16;
  }

  // ── Rent history ──
  if (score.rent_history.length > 0) {
    autoTable(doc, {
      startY: y,
      head: [["Year", "Median Rent"]],
      body: score.rent_history.map((r) => [
        r.year,
        `$${r.median_rent.toLocaleString()}`,
      ]),
      headStyles: { fillColor: DARK, textColor: [255, 255, 255], fontSize: 8 },
      bodyStyles: { fontSize: 8, textColor: DARK },
      alternateRowStyles: { fillColor: [248, 248, 252] },
      margin: { left: margin, right: margin },
      tableWidth: contentW / 2,
    });
    y = (doc as any).lastAutoTable.finalY + 16;
  }

  // ── Footer on every page ──
  const pageCount = doc.getNumberOfPages();
  for (let i = 1; i <= pageCount; i++) {
    doc.setPage(i);
    doc.setFontSize(7);
    doc.setTextColor(...GRAY);
    doc.text(
      `Generated by CampusLens  ·  ${score.scored_at ? new Date(score.scored_at).toLocaleDateString() : new Date().toLocaleDateString()}  ·  Page ${i} of ${pageCount}`,
      margin,
      doc.internal.pageSize.getHeight() - 24,
    );
  }

  doc.save(`${slugify(uni.name)}_campuslens_report.pdf`);
}

// ── DOCX ─────────────────────────────────────────────────────────────────────

export async function exportToDocx(score: HousingPressureScore): Promise<void> {
  const {
    Document,
    Paragraph,
    TextRun,
    HeadingLevel,
    Table,
    TableRow,
    TableCell,
    WidthType,
    BorderStyle,
    AlignmentType,
    Packer,
  } = await import("docx");

  const uni = score.university;
  const label = labelFromScore(score.score);

  function heading(
    text: string,
    level: (typeof HeadingLevel)[keyof typeof HeadingLevel],
  ) {
    return new Paragraph({
      text,
      heading: level,
      spacing: { before: 240, after: 120 },
    });
  }

  function sectionTable(rows: [string, string][]) {
    const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
    const borders = {
      top: border,
      bottom: border,
      left: border,
      right: border,
    };
    return new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows: rows.map(
        ([k, v]) =>
          new TableRow({
            children: [
              new TableCell({
                borders,
                width: { size: 40, type: WidthType.PERCENTAGE },
                children: [
                  new Paragraph({
                    children: [new TextRun({ text: k, bold: true, size: 18 })],
                  }),
                ],
              }),
              new TableCell({
                borders,
                width: { size: 60, type: WidthType.PERCENTAGE },
                children: [
                  new Paragraph({
                    children: [new TextRun({ text: v, size: 18 })],
                  }),
                ],
              }),
            ],
          }),
      ),
    });
  }

  const enrollFirst = score.enrollment_trend.at(0);
  const enrollLast = score.enrollment_trend.at(-1);
  const latestEnroll = enrollLast?.total_enrollment;
  const earliestEnroll = enrollFirst?.total_enrollment;
  const enrollChange =
    latestEnroll && earliestEnroll
      ? `${(((latestEnroll - earliestEnroll) / earliestEnroll) * 100).toFixed(1)}%`
      : "—";

  const rentLast = score.rent_history.at(-1);
  const rentFirst = score.rent_history.at(0);
  const latestRent = rentLast?.median_rent;
  const earliestRent = rentFirst?.median_rent;
  const rentChange =
    latestRent && earliestRent
      ? `${(((latestRent - earliestRent) / earliestRent) * 100).toFixed(1)}%`
      : "—";

  const totalPermits = score.permit_history.reduce((s, p) => s + p.permits, 0);
  const pipelinePct =
    latestEnroll && totalPermits
      ? `${((totalPermits / latestEnroll) * 100).toFixed(1)}%`
      : "—";

  const ist = score.institutional_strength;
  const eh = score.existing_housing;
  const ord = score.occupancy_ordinance;
  const dem = score.demographics;

  const children: (InstanceType<typeof Paragraph> | InstanceType<typeof Table>)[] = [
    // Title
    new Paragraph({
      children: [new TextRun({ text: uni.name, bold: true, size: 36 })],
      spacing: { after: 120 },
    }),
    new Paragraph({
      children: [
        new TextRun({
          text: `${uni.city}, ${uni.state}  ·  ${uni.enrollment?.toLocaleString() ?? "—"} enrolled`,
          color: "888888",
          size: 20,
        }),
      ],
      spacing: { after: 80 },
    }),
    new Paragraph({
      children: [
        new TextRun({
          text: `Generated by CampusLens  ·  ${score.scored_at ? new Date(score.scored_at).toLocaleDateString() : new Date().toLocaleDateString()}`,
          color: "AAAAAA",
          size: 16,
        }),
      ],
      spacing: { after: 360 },
    }),

    // Score
    heading("Housing Pressure Score", HeadingLevel.HEADING_1),
    sectionTable([
      ["Overall Score", `${score.score.toFixed(1)} / 100`],
      ["Market Classification", label],
      [
        "Enrollment Pressure",
        `${score.components.enrollment_pressure.toFixed(1)} / 100`,
      ],
      ["Permit Gap", `${score.components.permit_gap.toFixed(1)} / 100`],
      ["Rent Pressure", `${score.components.rent_pressure.toFixed(1)} / 100`],
    ]),

    // AI brief
    ...(score.gemini_summary
      ? [
          heading("Gemini Market Brief", HeadingLevel.HEADING_2),
          new Paragraph({
            text: score.gemini_summary,
            spacing: { after: 200 },
            style: "Normal",
          }),
        ]
      : []),

    // Key metrics
    heading("Key Market Metrics", HeadingLevel.HEADING_2),
    sectionTable([
      ["Enrollment (latest)", latestEnroll?.toLocaleString() ?? "—"],
      ["Enrollment Change", enrollChange],
      [
        "Median Rent (latest)",
        latestRent ? `$${latestRent.toLocaleString()}` : "—",
      ],
      ["Rent Change", rentChange],
      [
        "Permits Filed (5yr)",
        totalPermits > 0 ? totalPermits.toLocaleString() : "—",
      ],
      ["Supply Pipeline", pipelinePct],
      [
        "County Housing Units",
        score.nearby_housing_units?.toLocaleString() ?? "—",
      ],
      [
        "On-Campus Beds/Student",
        score.housing_capacity?.beds_per_student?.toFixed(2) ?? "—",
      ],
      [
        "Total Dorm Capacity",
        score.housing_capacity?.dormitory_capacity?.toLocaleString() ?? "—",
      ],
    ]),

    // Demographics
    ...(dem
      ? [
          heading("Demographics (County ACS)", HeadingLevel.HEADING_2),
          sectionTable([
            [
              "Median Household Income",
              dem.median_household_income
                ? `$${dem.median_household_income.toLocaleString()}`
                : "—",
            ],
            [
              "Median Home Value",
              dem.median_home_value
                ? `$${dem.median_home_value.toLocaleString()}`
                : "—",
            ],
            [
              "Median Gross Rent",
              dem.median_gross_rent
                ? `$${dem.median_gross_rent.toLocaleString()}`
                : "—",
            ],
            [
              "Vacancy Rate",
              dem.vacancy_rate_pct != null
                ? `${dem.vacancy_rate_pct.toFixed(1)}%`
                : "—",
            ],
            [
              "Renter-Occupied",
              dem.pct_renter_occupied != null
                ? `${dem.pct_renter_occupied.toFixed(1)}%`
                : "—",
            ],
            [
              "Bachelors or Higher",
              dem.pct_bachelors_or_higher != null
                ? `${dem.pct_bachelors_or_higher.toFixed(1)}%`
                : "—",
            ],
            [
              "Total Housing Units",
              dem.total_housing_units?.toLocaleString() ?? "—",
            ],
          ]),
        ]
      : []),

    // Institutional strength
    ...(ist
      ? [
          heading("Institutional Strength", HeadingLevel.HEADING_2),
          sectionTable([
            [
              "Strength Score",
              ist.strength_score != null
                ? `${ist.strength_score.toFixed(0)} / 100 (${ist.strength_label})`
                : "—",
            ],
            ["Ownership", ist.ownership_label ?? "—"],
            [
              "Retention Rate",
              ist.retention_rate != null
                ? `${(ist.retention_rate * 100).toFixed(0)}%`
                : "—",
            ],
            [
              "Admission Rate",
              ist.admission_rate != null
                ? `${(ist.admission_rate * 100).toFixed(0)}%`
                : "—",
            ],
            [
              "Endowment / Student",
              ist.endowment_per_student
                ? `$${ist.endowment_per_student.toLocaleString()}`
                : "—",
            ],
            [
              "Total Endowment",
              ist.endowment_end
                ? `$${(ist.endowment_end / 1_000_000).toFixed(0)}M`
                : "—",
            ],
            [
              "Pell Grant Rate",
              ist.pell_grant_rate != null
                ? `${(ist.pell_grant_rate * 100).toFixed(0)}%`
                : "—",
            ],
          ]),
        ]
      : []),

    // Existing housing
    ...(eh
      ? [
          heading("Existing Housing Stock", HeadingLevel.HEADING_2),
          sectionTable([
            ["Saturation", eh.saturation_label],
            ["Apartment Buildings", eh.apartment_buildings.toLocaleString()],
            ["Dormitory Buildings", eh.dormitory_buildings.toLocaleString()],
            [
              "House / Residential Buildings",
              `${eh.house_buildings.toLocaleString()} / ${eh.residential_buildings.toLocaleString()}`,
            ],
            [
              "Multifamily Density",
              `${eh.apartment_density_per_km2.toFixed(1)} / km²`,
            ],
            ["Search Radius", `${eh.radius_miles} miles`],
          ]),
        ]
      : []),

    // Occupancy ordinance
    ...(ord && ord.ordinance_type !== "none"
      ? [
          heading("Occupancy Ordinance", HeadingLevel.HEADING_2),
          sectionTable([
            ["Type", ord.ordinance_type],
            [
              "Max Unrelated Occupants",
              ord.max_unrelated_occupants != null
                ? `≤${ord.max_unrelated_occupants}`
                : "No cap",
            ],
            ["Enforced", ord.enforced ? "Yes" : "No"],
            ["PBSH Signal", ord.pbsh_signal],
            ["Confidence", ord.confidence],
            ...(ord.notes ? [["Notes", ord.notes] as [string, string]] : []),
          ]),
        ]
      : []),

    // Disaster risk
    ...(score.disaster_risk
      ? [
          heading("Disaster Risk (FEMA)", HeadingLevel.HEADING_2),
          sectionTable([
            ["Total Disasters", score.disaster_risk.total_disasters.toString()],
            [
              "Weather Disasters",
              score.disaster_risk.weather_disasters.toString(),
            ],
            ["Window", `${score.disaster_risk.window_years} years`],
            ...(score.disaster_risk.most_recent_year
              ? [
                  [
                    "Most Recent Year",
                    score.disaster_risk.most_recent_year.toString(),
                  ] as [string, string],
                ]
              : []),
          ]),
        ]
      : []),

    // Enrollment trend table
    ...(score.enrollment_trend.length > 0
      ? [
          heading("Enrollment Trend", HeadingLevel.HEADING_2),
          new Table({
            width: { size: 50, type: WidthType.PERCENTAGE },
            rows: [
              new TableRow({
                children: ["Year", "Enrollment"].map(
                  (h) =>
                    new TableCell({
                      children: [
                        new Paragraph({
                          children: [
                            new TextRun({ text: h, bold: true, size: 18 }),
                          ],
                        }),
                      ],
                    }),
                ),
              }),
              ...score.enrollment_trend.map(
                (e) =>
                  new TableRow({
                    children: [
                      e.year.toString(),
                      e.total_enrollment.toLocaleString(),
                    ].map(
                      (v) =>
                        new TableCell({
                          children: [
                            new Paragraph({
                              children: [new TextRun({ text: v, size: 18 })],
                            }),
                          ],
                        }),
                    ),
                  }),
              ),
            ],
          }),
        ]
      : []),

    // Permit history table
    ...(score.permit_history.length > 0
      ? [
          heading("Building Permit History", HeadingLevel.HEADING_2),
          new Table({
            width: { size: 50, type: WidthType.PERCENTAGE },
            rows: [
              new TableRow({
                children: ["Year", "Permits"].map(
                  (h) =>
                    new TableCell({
                      children: [
                        new Paragraph({
                          children: [
                            new TextRun({ text: h, bold: true, size: 18 }),
                          ],
                        }),
                      ],
                    }),
                ),
              }),
              ...score.permit_history.map(
                (p) =>
                  new TableRow({
                    children: [
                      p.year.toString(),
                      p.permits.toLocaleString(),
                    ].map(
                      (v) =>
                        new TableCell({
                          children: [
                            new Paragraph({
                              children: [new TextRun({ text: v, size: 18 })],
                            }),
                          ],
                        }),
                    ),
                  }),
              ),
            ],
          }),
        ]
      : []),

    // Rent history table
    ...(score.rent_history.length > 0
      ? [
          heading("Rent History", HeadingLevel.HEADING_2),
          new Table({
            width: { size: 50, type: WidthType.PERCENTAGE },
            rows: [
              new TableRow({
                children: ["Year", "Median Rent"].map(
                  (h) =>
                    new TableCell({
                      children: [
                        new Paragraph({
                          children: [
                            new TextRun({ text: h, bold: true, size: 18 }),
                          ],
                        }),
                      ],
                    }),
                ),
              }),
              ...score.rent_history.map(
                (r) =>
                  new TableRow({
                    children: [
                      r.year.toString(),
                      `$${r.median_rent.toLocaleString()}`,
                    ].map(
                      (v) =>
                        new TableCell({
                          children: [
                            new Paragraph({
                              children: [new TextRun({ text: v, size: 18 })],
                            }),
                          ],
                        }),
                    ),
                  }),
              ),
            ],
          }),
        ]
      : []),

    // Footer note
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 480 },
      children: [
        new TextRun({
          text: `CampusLens Housing Market Intelligence  ·  ${uni.name}  ·  campuslens`,
          color: "AAAAAA",
          size: 16,
        }),
      ],
    }),
  ];

  const doc = new Document({ sections: [{ children }] });
  const blob = await Packer.toBlob(doc);
  blobDownload(blob, `${slugify(uni.name)}_campuslens_report.docx`);
}

// ── Comparison PDF ────────────────────────────────────────────────────────────

export async function exportComparisonToPDF(
  scoreA: HousingPressureScore,
  scoreB: HousingPressureScore,
): Promise<void> {
  const { default: jsPDF } = await import("jspdf");
  const { default: autoTable } = await import("jspdf-autotable");

  const doc = new jsPDF({ unit: "pt", format: "letter" });
  const pageW = doc.internal.pageSize.getWidth();
  const margin = 48;
  const contentW = pageW - margin * 2;
  let y = margin;

  const DARK = [20, 20, 30] as [number, number, number];
  const BLUE = [59, 130, 246] as [number, number, number];
  const GRAY = [100, 100, 110] as [number, number, number];
  const LIGHT = [240, 240, 245] as [number, number, number];

  const uniA = scoreA.university;
  const uniB = scoreB.university;
  const [labelA, labelB] = resolveCompareLabels(
    uniA.name,
    uniA.city,
    uniB.name,
    uniB.city,
  );

  // ── Header band ──
  doc.setFillColor(...DARK);
  doc.rect(0, 0, pageW, 72, "F");

  doc.setFontSize(9);
  doc.setTextColor(150, 160, 180);
  doc.text("CampusLens  ·  Market Comparison Report", margin, 26);

  doc.setFontSize(14);
  doc.setFont("helvetica", "bold");
  doc.setTextColor(255, 255, 255);
  doc.text(`${uniA.name}  vs  ${uniB.name}`, margin, 50, {
    maxWidth: contentW,
  });

  y = 96;

  // ── Side-by-side score cards ──
  const colW = (contentW - 8) / 2;

  const drawScoreCard = (score: HousingPressureScore, x: number) => {
    const uni = score.university;
    const label = labelFromScore(score.score);
    doc.setFillColor(...LIGHT);
    doc.roundedRect(x, y, colW, 80, 6, 6, "F");

    doc.setFontSize(8);
    doc.setFont("helvetica", "normal");
    doc.setTextColor(...GRAY);
    doc.text(`${uni.city}, ${uni.state}`, x + 10, y + 16);

    doc.setFontSize(10);
    doc.setFont("helvetica", "bold");
    doc.setTextColor(...DARK);
    const nameLines = doc.splitTextToSize(uni.name, colW - 20) as string[];
    doc.text(nameLines[0], x + 10, y + 30);

    doc.setFontSize(22);
    doc.setTextColor(...BLUE);
    doc.text(`${score.score.toFixed(1)}`, x + 10, y + 58);

    doc.setFontSize(8);
    doc.setFont("helvetica", "normal");
    doc.setTextColor(...GRAY);
    doc.text(label, x + 56, y + 58);
  };

  drawScoreCard(scoreA, margin);
  drawScoreCard(scoreB, margin + colW + 8);
  y += 96;

  // ── Score components comparison table ──
  autoTable(doc, {
    startY: y,
    head: [["Component", labelA, labelB, "Winner"]],
    body: [
      [
        "Enrollment Pressure",
        scoreA.components.enrollment_pressure.toFixed(1),
        scoreB.components.enrollment_pressure.toFixed(1),
        scoreA.components.enrollment_pressure >=
        scoreB.components.enrollment_pressure
          ? labelA
          : labelB,
      ],
      [
        "Permit Gap",
        scoreA.components.permit_gap.toFixed(1),
        scoreB.components.permit_gap.toFixed(1),
        scoreA.components.permit_gap >= scoreB.components.permit_gap
          ? labelA
          : labelB,
      ],
      [
        "Rent Pressure",
        scoreA.components.rent_pressure.toFixed(1),
        scoreB.components.rent_pressure.toFixed(1),
        scoreA.components.rent_pressure >= scoreB.components.rent_pressure
          ? labelA
          : labelB,
      ],
      [
        "Overall Score",
        scoreA.score.toFixed(1),
        scoreB.score.toFixed(1),
        scoreA.score >= scoreB.score ? labelA : labelB,
      ],
    ],
    headStyles: { fillColor: DARK, textColor: [255, 255, 255], fontSize: 8 },
    bodyStyles: { fontSize: 8, textColor: DARK },
    alternateRowStyles: { fillColor: [248, 248, 252] },
    margin: { left: margin, right: margin },
  });

  y = (doc as any).lastAutoTable.finalY + 16;

  // ── Key metrics comparison ──
  const enrollA = scoreA.enrollment_trend.at(-1)?.total_enrollment;
  const enrollB = scoreB.enrollment_trend.at(-1)?.total_enrollment;
  const rentA = scoreA.rent_history.at(-1)?.median_rent;
  const rentB = scoreB.rent_history.at(-1)?.median_rent;
  const permitsA = scoreA.permit_history.reduce((s, p) => s + p.permits, 0);
  const permitsB = scoreB.permit_history.reduce((s, p) => s + p.permits, 0);

  autoTable(doc, {
    startY: y,
    head: [["Metric", labelA, labelB]],
    body: [
      [
        "Enrollment",
        enrollA?.toLocaleString() ?? "—",
        enrollB?.toLocaleString() ?? "—",
      ],
      [
        "Median Rent",
        rentA ? `$${rentA.toLocaleString()}` : "—",
        rentB ? `$${rentB.toLocaleString()}` : "—",
      ],
      [
        "Permits (5yr)",
        permitsA > 0 ? permitsA.toLocaleString() : "—",
        permitsB > 0 ? permitsB.toLocaleString() : "—",
      ],
      [
        "County Housing Units",
        scoreA.nearby_housing_units > 0
          ? scoreA.nearby_housing_units.toLocaleString()
          : "—",
        scoreB.nearby_housing_units > 0
          ? scoreB.nearby_housing_units.toLocaleString()
          : "—",
      ],
      [
        "Beds/Student",
        scoreA.housing_capacity?.beds_per_student?.toFixed(2) ?? "—",
        scoreB.housing_capacity?.beds_per_student?.toFixed(2) ?? "—",
      ],
      [
        "Vacancy Rate",
        scoreA.demographics?.vacancy_rate_pct != null
          ? `${scoreA.demographics.vacancy_rate_pct.toFixed(1)}%`
          : "—",
        scoreB.demographics?.vacancy_rate_pct != null
          ? `${scoreB.demographics.vacancy_rate_pct.toFixed(1)}%`
          : "—",
      ],
      [
        "Median Gross Rent",
        scoreA.demographics?.median_gross_rent
          ? `$${scoreA.demographics.median_gross_rent.toLocaleString()}`
          : "—",
        scoreB.demographics?.median_gross_rent
          ? `$${scoreB.demographics.median_gross_rent.toLocaleString()}`
          : "—",
      ],
      [
        "Renter-Occupied %",
        scoreA.demographics?.pct_renter_occupied != null
          ? `${scoreA.demographics.pct_renter_occupied.toFixed(1)}%`
          : "—",
        scoreB.demographics?.pct_renter_occupied != null
          ? `${scoreB.demographics.pct_renter_occupied.toFixed(1)}%`
          : "—",
      ],
      [
        "Institutional Strength",
        scoreA.institutional_strength?.strength_score != null
          ? `${scoreA.institutional_strength.strength_score.toFixed(0)}/100 (${scoreA.institutional_strength.strength_label})`
          : "—",
        scoreB.institutional_strength?.strength_score != null
          ? `${scoreB.institutional_strength.strength_score.toFixed(0)}/100 (${scoreB.institutional_strength.strength_label})`
          : "—",
      ],
      [
        "Retention Rate",
        scoreA.institutional_strength?.retention_rate != null
          ? `${(scoreA.institutional_strength.retention_rate * 100).toFixed(0)}%`
          : "—",
        scoreB.institutional_strength?.retention_rate != null
          ? `${(scoreB.institutional_strength.retention_rate * 100).toFixed(0)}%`
          : "—",
      ],
      [
        "Endowment/Student",
        scoreA.institutional_strength?.endowment_per_student
          ? `$${scoreA.institutional_strength.endowment_per_student.toLocaleString()}`
          : "—",
        scoreB.institutional_strength?.endowment_per_student
          ? `$${scoreB.institutional_strength.endowment_per_student.toLocaleString()}`
          : "—",
      ],
      [
        "Weather Disasters",
        scoreA.disaster_risk?.weather_disasters?.toString() ?? "—",
        scoreB.disaster_risk?.weather_disasters?.toString() ?? "—",
      ],
      [
        "Housing Saturation",
        scoreA.existing_housing?.saturation_label ?? "—",
        scoreB.existing_housing?.saturation_label ?? "—",
      ],
    ],
    headStyles: { fillColor: DARK, textColor: [255, 255, 255], fontSize: 8 },
    bodyStyles: { fontSize: 8, textColor: DARK },
    alternateRowStyles: { fillColor: [248, 248, 252] },
    margin: { left: margin, right: margin },
  });

  // ── Footer ──
  const pageCount = doc.getNumberOfPages();
  for (let i = 1; i <= pageCount; i++) {
    doc.setPage(i);
    doc.setFontSize(7);
    doc.setTextColor(...GRAY);
    doc.text(
      `CampusLens  ·  ${uniA.name} vs ${uniB.name}  ·  ${new Date().toLocaleDateString()}  ·  Page ${i} of ${pageCount}`,
      margin,
      doc.internal.pageSize.getHeight() - 24,
    );
  }

  doc.save(`${slugify(uniA.name)}_vs_${slugify(uniB.name)}_campuslens.pdf`);
}

// ── Comparison DOCX ───────────────────────────────────────────────────────────

export async function exportComparisonToDocx(
  scoreA: HousingPressureScore,
  scoreB: HousingPressureScore,
): Promise<void> {
  const {
    Document,
    Paragraph,
    TextRun,
    HeadingLevel,
    Table,
    TableRow,
    TableCell,
    WidthType,
    BorderStyle,
    Packer,
  } = await import("docx");

  const uniA = scoreA.university;
  const uniB = scoreB.university;
  const [docxLabelA, docxLabelB] = resolveCompareLabels(
    uniA.name,
    uniA.city,
    uniB.name,
    uniB.city,
  );

  const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
  const borders = { top: border, bottom: border, left: border, right: border };

  function heading(
    text: string,
    level: (typeof HeadingLevel)[keyof typeof HeadingLevel],
  ) {
    return new Paragraph({
      text,
      heading: level,
      spacing: { before: 240, after: 120 },
    });
  }

  function compRow(label: string, valA: string, valB: string) {
    return new TableRow({
      children: [label, valA, valB].map(
        (text, i) =>
          new TableCell({
            borders,
            width: { size: i === 0 ? 40 : 30, type: WidthType.PERCENTAGE },
            children: [
              new Paragraph({
                children: [new TextRun({ text, bold: i === 0, size: 18 })],
              }),
            ],
          }),
      ),
    });
  }

  function compTable(rows: [string, string, string][]) {
    return new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows: [
        new TableRow({
          children: [docxLabelA, docxLabelB].reduce(
            (cols, h) => [
              ...cols,
              new TableCell({
                borders,
                children: [
                  new Paragraph({
                    children: [new TextRun({ text: h, bold: true, size: 18 })],
                  }),
                ],
              }),
            ],
            [
              new TableCell({
                borders,
                width: { size: 40, type: WidthType.PERCENTAGE },
                children: [
                  new Paragraph({
                    children: [
                      new TextRun({ text: "Metric", bold: true, size: 18 }),
                    ],
                  }),
                ],
              }),
            ],
          ),
        }),
        ...rows.map(([l, a, b]) => compRow(l, a, b)),
      ],
    });
  }

  const enrollA = scoreA.enrollment_trend.at(-1)?.total_enrollment;
  const enrollB = scoreB.enrollment_trend.at(-1)?.total_enrollment;
  const rentA = scoreA.rent_history.at(-1)?.median_rent;
  const rentB = scoreB.rent_history.at(-1)?.median_rent;
  const permitsA = scoreA.permit_history.reduce((s, p) => s + p.permits, 0);
  const permitsB = scoreB.permit_history.reduce((s, p) => s + p.permits, 0);

  const children = [
    new Paragraph({
      children: [
        new TextRun({ text: "Market Comparison Report", bold: true, size: 40 }),
      ],
      spacing: { after: 120 },
    }),
    new Paragraph({
      children: [
        new TextRun({
          text: `${uniA.name}  vs  ${uniB.name}`,
          size: 24,
          color: "444444",
        }),
      ],
      spacing: { after: 80 },
    }),
    new Paragraph({
      children: [
        new TextRun({
          text: `Generated by CampusLens  ·  ${new Date().toLocaleDateString()}`,
          size: 16,
          color: "AAAAAA",
        }),
      ],
      spacing: { after: 360 },
    }),

    heading("Overall Scores", HeadingLevel.HEADING_1),
    compTable([
      [
        "Overall Score",
        `${scoreA.score.toFixed(1)} / 100`,
        `${scoreB.score.toFixed(1)} / 100`,
      ],
      [
        "Classification",
        `${labelFromScore(scoreA.score)}`,
        `${labelFromScore(scoreB.score)}`,
      ],
      [
        "Enrollment Pressure",
        `${scoreA.components.enrollment_pressure.toFixed(1)}`,
        `${scoreB.components.enrollment_pressure.toFixed(1)}`,
      ],
      [
        "Permit Gap",
        `${scoreA.components.permit_gap.toFixed(1)}`,
        `${scoreB.components.permit_gap.toFixed(1)}`,
      ],
      [
        "Rent Pressure",
        `${scoreA.components.rent_pressure.toFixed(1)}`,
        `${scoreB.components.rent_pressure.toFixed(1)}`,
      ],
    ]),

    heading("Key Market Metrics", HeadingLevel.HEADING_2),
    compTable([
      [
        "Enrollment",
        enrollA?.toLocaleString() ?? "—",
        enrollB?.toLocaleString() ?? "—",
      ],
      [
        "Median Rent",
        rentA ? `$${rentA.toLocaleString()}` : "—",
        rentB ? `$${rentB.toLocaleString()}` : "—",
      ],
      [
        "Permits (5yr)",
        permitsA > 0 ? permitsA.toLocaleString() : "—",
        permitsB > 0 ? permitsB.toLocaleString() : "—",
      ],
      [
        "County Housing Units",
        scoreA.nearby_housing_units > 0
          ? scoreA.nearby_housing_units.toLocaleString()
          : "—",
        scoreB.nearby_housing_units > 0
          ? scoreB.nearby_housing_units.toLocaleString()
          : "—",
      ],
      [
        "Beds/Student",
        scoreA.housing_capacity?.beds_per_student?.toFixed(2) ?? "—",
        scoreB.housing_capacity?.beds_per_student?.toFixed(2) ?? "—",
      ],
      [
        "Vacancy Rate",
        scoreA.demographics?.vacancy_rate_pct != null
          ? `${scoreA.demographics.vacancy_rate_pct.toFixed(1)}%`
          : "—",
        scoreB.demographics?.vacancy_rate_pct != null
          ? `${scoreB.demographics.vacancy_rate_pct.toFixed(1)}%`
          : "—",
      ],
      [
        "Renter-Occupied %",
        scoreA.demographics?.pct_renter_occupied != null
          ? `${scoreA.demographics.pct_renter_occupied.toFixed(1)}%`
          : "—",
        scoreB.demographics?.pct_renter_occupied != null
          ? `${scoreB.demographics.pct_renter_occupied.toFixed(1)}%`
          : "—",
      ],
      [
        "Median Gross Rent",
        scoreA.demographics?.median_gross_rent
          ? `$${scoreA.demographics.median_gross_rent.toLocaleString()}`
          : "—",
        scoreB.demographics?.median_gross_rent
          ? `$${scoreB.demographics.median_gross_rent.toLocaleString()}`
          : "—",
      ],
      [
        "Median Home Value",
        scoreA.demographics?.median_home_value
          ? `$${scoreA.demographics.median_home_value.toLocaleString()}`
          : "—",
        scoreB.demographics?.median_home_value
          ? `$${scoreB.demographics.median_home_value.toLocaleString()}`
          : "—",
      ],
    ]),

    heading("Institutional Strength", HeadingLevel.HEADING_2),
    compTable([
      [
        "Strength Score",
        scoreA.institutional_strength?.strength_score != null
          ? `${scoreA.institutional_strength.strength_score.toFixed(0)}/100 (${scoreA.institutional_strength.strength_label})`
          : "—",
        scoreB.institutional_strength?.strength_score != null
          ? `${scoreB.institutional_strength.strength_score.toFixed(0)}/100 (${scoreB.institutional_strength.strength_label})`
          : "—",
      ],
      [
        "Ownership",
        scoreA.institutional_strength?.ownership_label ?? "—",
        scoreB.institutional_strength?.ownership_label ?? "—",
      ],
      [
        "Retention Rate",
        scoreA.institutional_strength?.retention_rate != null
          ? `${(scoreA.institutional_strength.retention_rate * 100).toFixed(0)}%`
          : "—",
        scoreB.institutional_strength?.retention_rate != null
          ? `${(scoreB.institutional_strength.retention_rate * 100).toFixed(0)}%`
          : "—",
      ],
      [
        "Admission Rate",
        scoreA.institutional_strength?.admission_rate != null
          ? `${(scoreA.institutional_strength.admission_rate * 100).toFixed(0)}%`
          : "—",
        scoreB.institutional_strength?.admission_rate != null
          ? `${(scoreB.institutional_strength.admission_rate * 100).toFixed(0)}%`
          : "—",
      ],
      [
        "Endowment/Student",
        scoreA.institutional_strength?.endowment_per_student
          ? `$${scoreA.institutional_strength.endowment_per_student.toLocaleString()}`
          : "—",
        scoreB.institutional_strength?.endowment_per_student
          ? `$${scoreB.institutional_strength.endowment_per_student.toLocaleString()}`
          : "—",
      ],
    ]),

    heading("Supply & Competition", HeadingLevel.HEADING_2),
    compTable([
      [
        "Housing Saturation",
        scoreA.existing_housing?.saturation_label ?? "—",
        scoreB.existing_housing?.saturation_label ?? "—",
      ],
      [
        "Apartment Buildings",
        scoreA.existing_housing?.apartment_buildings?.toLocaleString() ?? "—",
        scoreB.existing_housing?.apartment_buildings?.toLocaleString() ?? "—",
      ],
      [
        "Multifamily Density",
        scoreA.existing_housing
          ? `${scoreA.existing_housing.apartment_density_per_km2.toFixed(1)}/km²`
          : "—",
        scoreB.existing_housing
          ? `${scoreB.existing_housing.apartment_density_per_km2.toFixed(1)}/km²`
          : "—",
      ],
      [
        "Weather Disasters",
        scoreA.disaster_risk?.weather_disasters?.toString() ?? "—",
        scoreB.disaster_risk?.weather_disasters?.toString() ?? "—",
      ],
    ]),
  ];

  const doc = new Document({ sections: [{ children }] });
  const blob = await Packer.toBlob(doc);
  blobDownload(
    blob,
    `${slugify(uniA.name)}_vs_${slugify(uniB.name)}_campuslens.docx`,
  );
}
