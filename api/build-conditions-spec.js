const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, HeadingLevel, BorderStyle, LevelFormat, WidthType,
  ShadingType, VerticalAlign, PageNumber, PageBreak
} = require('docx');
const fs = require('fs');

// ============================================================
// Colour palette
// ============================================================
const GOLD   = "C9A84C";
const DARK   = "0D1117";
const MID    = "2D3748";
const LIGHT  = "F7FAFC";
const GREY   = "6B7280";
const LINE   = "E2E8F0";
const RED    = "7F1D1D";
const AMBER  = "78350F";
const GREEN  = "14532D";

// ============================================================
// Border helpers
// ============================================================
const thinBorder = { style: BorderStyle.SINGLE, size: 1, color: LINE };
const borders    = { top: thinBorder, bottom: thinBorder, left: thinBorder, right: thinBorder };
const noBorder   = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const noBorders  = { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder };

const cellMargins = { top: 100, bottom: 100, left: 160, right: 160 };

// ============================================================
// Paragraph helpers
// ============================================================
function rule(color = GOLD, before = 200, after = 300) {
  return new Paragraph({
    children: [new TextRun("")],
    border: { bottom: { style: BorderStyle.SINGLE, size: 8, color, space: 1 } },
    spacing: { before, after }
  });
}

function spacer(size = 160) {
  return new Paragraph({ children: [new TextRun("")], spacing: { after: size } });
}

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    children: [new TextRun({ text, font: "Arial", size: 44, bold: true, color: DARK })],
    spacing: { before: 560, after: 160 }
  });
}

function h2(text, color = DARK) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    children: [new TextRun({ text, font: "Arial", size: 30, bold: true, color })],
    spacing: { before: 400, after: 120 }
  });
}

function h3(text, color = DARK) {
  return new Paragraph({
    children: [new TextRun({ text, font: "Arial", size: 24, bold: true, color })],
    spacing: { before: 280, after: 80 }
  });
}

function body(text, opts = {}) {
  return new Paragraph({
    children: [new TextRun({
      text,
      font: "Arial",
      size: 22,
      color: opts.color || MID,
      bold: opts.bold || false,
      italics: opts.italic || false
    })],
    spacing: { before: 60, after: 140 },
    alignment: opts.align || AlignmentType.LEFT
  });
}

function label(text, color = GOLD) {
  return new Paragraph({
    children: [new TextRun({ text, font: "Arial", size: 18, bold: true, color, allCaps: true })],
    spacing: { before: 240, after: 60 }
  });
}

function mono(text) {
  return new Paragraph({
    children: [new TextRun({
      text,
      font: "Courier New",
      size: 20,
      color: "1A3A2A"
    })],
    spacing: { before: 40, after: 80 },
    shading: { fill: "F0FDF4", type: ShadingType.CLEAR }
  });
}

function bullet(text, reference = "bullets") {
  return new Paragraph({
    numbering: { reference, level: 0 },
    children: [new TextRun({ text, font: "Arial", size: 22, color: MID })],
    spacing: { before: 60, after: 80 }
  });
}

// ============================================================
// Condition block builder
// ============================================================
function conditionBlock({
  id, name, definition, diagnosticQuestion,
  detectableSigns, implication, axis,
  schemaMapping, engineLogic, coOccurrence,
  badgeColor = MID
}) {
  const rows = [];

  // Header row
  rows.push(
    new TableRow({
      children: [
        new TableCell({
          borders,
          columnSpan: 2,
          width: { size: 9360, type: WidthType.DXA },
          shading: { fill: "111827", type: ShadingType.CLEAR },
          margins: cellMargins,
          children: [
            new Paragraph({
              children: [
                new TextRun({ text: `${id}  `, font: "Arial", size: 26, bold: true, color: GOLD }),
                new TextRun({ text: name, font: "Arial", size: 26, bold: true, color: "F9FAFB" })
              ]
            })
          ]
        })
      ]
    })
  );

  // Helper for two-column rows
  function twoCol(leftLabel, rightContent) {
    return new TableRow({
      children: [
        new TableCell({
          borders,
          width: { size: 2200, type: WidthType.DXA },
          shading: { fill: "F8FAFC", type: ShadingType.CLEAR },
          margins: cellMargins,
          verticalAlign: VerticalAlign.TOP,
          children: [
            new Paragraph({
              children: [new TextRun({ text: leftLabel, font: "Arial", size: 18, bold: true, color: GREY, allCaps: true })]
            })
          ]
        }),
        new TableCell({
          borders,
          width: { size: 7160, type: WidthType.DXA },
          margins: cellMargins,
          verticalAlign: VerticalAlign.TOP,
          children: Array.isArray(rightContent) ? rightContent : [rightContent]
        })
      ]
    });
  }

  // Definition
  rows.push(twoCol("Definition", new Paragraph({
    children: [new TextRun({ text: definition, font: "Arial", size: 22, color: MID })]
  })));

  // Diagnostic question
  rows.push(twoCol("Diagnostic question", new Paragraph({
    children: [new TextRun({ text: diagnosticQuestion, font: "Arial", size: 22, color: MID, italics: true })]
  })));

  // Detectable signs
  rows.push(twoCol("Detectable signs",
    detectableSigns.map(s => new Paragraph({
      children: [new TextRun({ text: `— ${s}`, font: "Arial", size: 22, color: MID })]
    }))
  ));

  // Implication
  rows.push(twoCol("Implication", new Paragraph({
    children: [new TextRun({ text: implication, font: "Arial", size: 22, color: MID })]
  })));

  // Axis
  rows.push(twoCol("Axis", new Paragraph({
    children: [new TextRun({ text: axis, font: "Arial", size: 22, bold: true, color: DARK })]
  })));

  // Schema mapping
  rows.push(twoCol("Schema mapping",
    schemaMapping.map(s => new Paragraph({
      children: [new TextRun({ text: s, font: "Courier New", size: 18, color: "1A3A2A" })]
    }))
  ));

  // Engine logic
  rows.push(twoCol("Engine logic",
    engineLogic.map(s => new Paragraph({
      children: [new TextRun({ text: `— ${s}`, font: "Arial", size: 20, color: MID })]
    }))
  ));

  // Co-occurrence
  rows.push(twoCol("Co-occurrence patterns",
    [
      new Paragraph({
        children: [new TextRun({ text: "Frequently co-occurs with:", font: "Arial", size: 20, bold: true, color: GREY })]
      }),
      ...coOccurrence.conditions.map(c => new Paragraph({
        children: [new TextRun({ text: `— ${c}`, font: "Arial", size: 20, color: MID })]
      })),
      spacer(80),
      new Paragraph({
        children: [new TextRun({ text: "Associated system states:", font: "Arial", size: 20, bold: true, color: GREY })]
      }),
      ...coOccurrence.systemStates.map(s => new Paragraph({
        children: [new TextRun({ text: `— ${s}`, font: "Arial", size: 20, color: MID })]
      })),
      spacer(80),
      new Paragraph({
        children: [new TextRun({ text: "Associated trajectories:", font: "Arial", size: 20, bold: true, color: GREY })]
      }),
      ...coOccurrence.trajectories.map(t => new Paragraph({
        children: [new TextRun({ text: `— ${t}`, font: "Arial", size: 20, color: MID })]
      })),
      spacer(80),
      new Paragraph({
        children: [new TextRun({
          text: "Note: Co-occurrence data to be populated from GA4 analytics once sufficient cde_condition_detected events have accumulated.",
          font: "Arial", size: 18, color: GREY, italics: true
        })]
      })
    ]
  ));

  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [2200, 7160],
    rows
  });
}

// ============================================================
// Signal block builder
// ============================================================
function signalTable(signals) {
  const headerRow = new TableRow({
    tableHeader: true,
    children: [
      new TableCell({
        borders,
        width: { size: 3120, type: WidthType.DXA },
        shading: { fill: "111827", type: ShadingType.CLEAR },
        margins: cellMargins,
        children: [new Paragraph({ children: [new TextRun({ text: "Signal Key", font: "Arial", size: 20, bold: true, color: GOLD })] })]
      }),
      new TableCell({
        borders,
        width: { size: 3120, type: WidthType.DXA },
        shading: { fill: "111827", type: ShadingType.CLEAR },
        margins: cellMargins,
        children: [new Paragraph({ children: [new TextRun({ text: "Label", font: "Arial", size: 20, bold: true, color: GOLD })] })]
      }),
      new TableCell({
        borders,
        width: { size: 3120, type: WidthType.DXA },
        shading: { fill: "111827", type: ShadingType.CLEAR },
        margins: cellMargins,
        children: [new Paragraph({ children: [new TextRun({ text: "Definition", font: "Arial", size: 20, bold: true, color: GOLD })] })]
      })
    ]
  });

  const dataRows = signals.map((s, i) =>
    new TableRow({
      children: [
        new TableCell({
          borders,
          width: { size: 3120, type: WidthType.DXA },
          shading: { fill: i % 2 === 0 ? LIGHT : "FFFFFF", type: ShadingType.CLEAR },
          margins: cellMargins,
          children: [new Paragraph({ children: [new TextRun({ text: s.key, font: "Courier New", size: 18, color: "1A3A2A" })] })]
        }),
        new TableCell({
          borders,
          width: { size: 3120, type: WidthType.DXA },
          shading: { fill: i % 2 === 0 ? LIGHT : "FFFFFF", type: ShadingType.CLEAR },
          margins: cellMargins,
          children: [new Paragraph({ children: [new TextRun({ text: s.label, font: "Arial", size: 22, bold: true, color: DARK })] })]
        }),
        new TableCell({
          borders,
          width: { size: 3120, type: WidthType.DXA },
          shading: { fill: i % 2 === 0 ? LIGHT : "FFFFFF", type: ShadingType.CLEAR },
          margins: cellMargins,
          children: [new Paragraph({ children: [new TextRun({ text: s.definition, font: "Arial", size: 20, color: MID })] })]
        })
      ]
    })
  );

  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [3120, 3120, 3120],
    rows: [headerRow, ...dataRows]
  });
}

// ============================================================
// System state table
// ============================================================
function systemStateTable(states) {
  const headerRow = new TableRow({
    tableHeader: true,
    children: ["System State", "Meaning", "Typical Conditions"].map(text =>
      new TableCell({
        borders,
        width: { size: 3120, type: WidthType.DXA },
        shading: { fill: "111827", type: ShadingType.CLEAR },
        margins: cellMargins,
        children: [new Paragraph({ children: [new TextRun({ text, font: "Arial", size: 20, bold: true, color: GOLD })] })]
      })
    )
  });

  const dataRows = states.map((s, i) =>
    new TableRow({
      children: [
        new TableCell({
          borders,
          width: { size: 3120, type: WidthType.DXA },
          shading: { fill: i % 2 === 0 ? LIGHT : "FFFFFF", type: ShadingType.CLEAR },
          margins: cellMargins,
          children: [new Paragraph({ children: [new TextRun({ text: s.state, font: "Courier New", size: 18, color: "1A3A2A" })] })]
        }),
        new TableCell({
          borders,
          width: { size: 3120, type: WidthType.DXA },
          shading: { fill: i % 2 === 0 ? LIGHT : "FFFFFF", type: ShadingType.CLEAR },
          margins: cellMargins,
          children: [new Paragraph({ children: [new TextRun({ text: s.meaning, font: "Arial", size: 20, color: MID })] })]
        }),
        new TableCell({
          borders,
          width: { size: 3120, type: WidthType.DXA },
          shading: { fill: i % 2 === 0 ? LIGHT : "FFFFFF", type: ShadingType.CLEAR },
          margins: cellMargins,
          children: [new Paragraph({ children: [new TextRun({ text: s.conditions, font: "Arial", size: 20, color: MID })] })]
        })
      ]
    })
  );

  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [3120, 3120, 3120],
    rows: [headerRow, ...dataRows]
  });
}

// ============================================================
// Analytics schema table
// ============================================================
function analyticsTable(events) {
  const headerRow = new TableRow({
    tableHeader: true,
    children: ["GA4 Event", "Key Parameters", "Purpose"].map(text =>
      new TableCell({
        borders,
        width: { size: 3120, type: WidthType.DXA },
        shading: { fill: "111827", type: ShadingType.CLEAR },
        margins: cellMargins,
        children: [new Paragraph({ children: [new TextRun({ text, font: "Arial", size: 20, bold: true, color: GOLD })] })]
      })
    )
  });

  const dataRows = events.map((e, i) =>
    new TableRow({
      children: [
        new TableCell({
          borders,
          width: { size: 3120, type: WidthType.DXA },
          shading: { fill: i % 2 === 0 ? LIGHT : "FFFFFF", type: ShadingType.CLEAR },
          margins: cellMargins,
          children: [new Paragraph({ children: [new TextRun({ text: e.event, font: "Courier New", size: 18, color: "1A3A2A" })] })]
        }),
        new TableCell({
          borders,
          width: { size: 3120, type: WidthType.DXA },
          shading: { fill: i % 2 === 0 ? LIGHT : "FFFFFF", type: ShadingType.CLEAR },
          margins: cellMargins,
          children: e.params.map(p => new Paragraph({ children: [new TextRun({ text: `— ${p}`, font: "Arial", size: 18, color: MID })] }))
        }),
        new TableCell({
          borders,
          width: { size: 3120, type: WidthType.DXA },
          shading: { fill: i % 2 === 0 ? LIGHT : "FFFFFF", type: ShadingType.CLEAR },
          margins: cellMargins,
          children: [new Paragraph({ children: [new TextRun({ text: e.purpose, font: "Arial", size: 20, color: MID })] })]
        })
      ]
    })
  );

  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [3120, 3120, 3120],
    rows: [headerRow, ...dataRows]
  });
}

// ============================================================
// Document
// ============================================================
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 44, bold: true, font: "Arial", color: DARK },
        paragraph: { spacing: { before: 560, after: 160 }, outlineLevel: 0 }
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 30, bold: true, font: "Arial", color: DARK },
        paragraph: { spacing: { before: 400, after: 120 }, outlineLevel: 1 }
      }
    ]
  },
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "\u2014",
          alignment: AlignmentType.LEFT,
          style: {
            paragraph: { indent: { left: 720, hanging: 360 } },
            run: { font: "Arial", color: GOLD }
          }
        }]
      }
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
      }
    },
    children: [

      // ============================================================
      // TITLE
      // ============================================================
      spacer(240),
      new Paragraph({
        children: [new TextRun({ text: "CONDITIONS LAYER", font: "Arial", size: 56, bold: true, color: DARK })],
        spacing: { before: 0, after: 100 }
      }),
      new Paragraph({
        children: [new TextRun({ text: "Specification v1.0", font: "Arial", size: 28, color: GOLD, italics: true })],
        spacing: { before: 0, after: 80 }
      }),
      new Paragraph({
        children: [new TextRun({ text: "Civic Decision Engine  \u2022  Nick Moloney  \u2022  2026", font: "Arial", size: 20, color: GREY })],
        spacing: { before: 0, after: 240 }
      }),
      rule(GOLD),

      // ============================================================
      // PART I — PURPOSE
      // ============================================================
      h1("Part I \u2014 Purpose and Scope"),

      body("The Conditions Layer is the diagnostic core of the Civic Decision Engine. It defines a set of named, reusable institutional behaviour states that can be identified, cited, and accumulated across civic cases."),
      body("This document is the formal specification of the Conditions Layer. It defines each condition, maps it to the engine output schema, describes the engine logic that detects it, and specifies how it maps into the analytics schema."),

      spacer(80),
      label("Principle"),
      new Paragraph({
        children: [
          new TextRun({ text: "When a system can support named conditions, it moves from ", font: "Arial", size: 22, color: MID }),
          new TextRun({ text: "describing", font: "Arial", size: 22, color: MID, italics: true }),
          new TextRun({ text: " behaviour to ", font: "Arial", size: 22, color: MID }),
          new TextRun({ text: "diagnosing", font: "Arial", size: 22, color: MID, italics: true }),
          new TextRun({ text: " it.", font: "Arial", size: 22, color: MID })
        ],
        spacing: { before: 80, after: 160 }
      }),

      spacer(80),
      label("What a Condition Is"),
      body("A condition is a defined state of institutional behaviour, identified through observable structural signals, repeatable across cases, and independent of individual interpretation."),
      body("Conditions are not scores, severity ratings, or subjective impressions. They are diagnostic classifications of system state."),
      body("Descriptions can be dismissed as interpretation. Conditions require rebuttal on their own terms."),

      spacer(80),
      label("Dependency Chain"),
      body("This specification sits at the second layer of a four-layer dependency chain:"),
      bullet("cde_output.schema.json \u2014 the canonical engine output contract"),
      bullet("Conditions Layer Specification (this document) \u2014 maps schema field paths to institutional definitions"),
      bullet("UI / frontend \u2014 renders what the schema guarantees will be present"),
      bullet("Analytics schema \u2014 maps from schema fields to GA4 event parameters"),

      rule("DDDDDD"),

      // ============================================================
      // PART II — SCHEMA REFERENCE
      // ============================================================
      h1("Part II \u2014 Schema Reference"),

      body("The Conditions Layer maps to the following field paths in cde_output.schema.json. All condition detection and reporting flows through these paths."),
      spacer(80),

      label("Civic Run Output \u2014 Per-Case Fields"),
      mono('results[].conditions_detected[]           \u2014 array of detected conditions'),
      mono('results[].conditions_detected[].condition_id  \u2014 "C001" | "C002" | "C003" | "C004"'),
      mono('results[].conditions_detected[].name          \u2014 human-readable condition name'),
      mono('results[].conditions_detected[].detected      \u2014 always true when present'),
      mono('results[].conditions_detected[].signals[]     \u2014 evidence strings that triggered detection'),
      mono('results[].condition                           \u2014 primary condition key (SIGNAL_MAP)'),
      spacer(120),

      label("Timeline Run Output \u2014 Sequence Fields"),
      mono('results[].conditions[]                    \u2014 distinct condition keys across sequence'),
      mono('results[].trajectory                      \u2014 "Deteriorating" | "Improving" | "Stable" | "Mixed"'),
      mono('results[].moment_of_change                \u2014 first detected deterioration point'),
      mono('results[].moment_of_change.from_label     \u2014 label before transition'),
      mono('results[].moment_of_change.to_label       \u2014 label after transition'),
      spacer(120),

      label("Pattern Run Output \u2014 System State Fields"),
      mono('results[].system_state                    \u2014 named system state classification'),
      mono('results[].dominant_conditions[]           \u2014 most frequent conditions with counts'),
      mono('results[].dominant_conditions[].condition \u2014 condition key'),
      mono('results[].dominant_conditions[].count     \u2014 occurrence count'),
      mono('results[].signals[]                       \u2014 pattern-level signal keys'),

      rule("DDDDDD"),

      // ============================================================
      // PART III — CONDITIONS
      // ============================================================
      h1("Part III \u2014 Condition Definitions"),

      body("Six conditions are currently defined. C001\u2013C004 are Conditions Layer conditions detected at the case level. TRANSFER_OF_BURDEN and ESCALATION_WITHOUT_RESPONSE are behavioural conditions detected at the pattern and signal level."),
      spacer(160),

      // C001
      conditionBlock({
        id: "C001",
        name: "Stability Without Confirmation",
        definition: "An institution continues to function without producing external signals that confirm resolution. Operational continuity should not be mistaken for confirmed resolution.",
        diagnosticQuestion: "Does the system continue in the absence of external confirmation that the issue was resolved?",
        detectableSigns: [
          "Administrative continuity without confirmed resolution",
          "Absence of follow-up despite claimed completion",
          "Internal closure signals without external proof of containment",
          "Case awaiting response for 30 or more days"
        ],
        implication: "Operational continuity should not be mistaken for confirmed resolution. This is the foundational condition \u2014 the state from which all other conditions may develop.",
        axis: "Foundational condition — operational state",
        schemaMapping: [
          'conditions_detected[].condition_id == "C001"',
          'conditions_detected[].signals[] \u2192 evidence strings',
          'results[].conditions[] \u2192 "STABILITY_WITHOUT_CONFIRMATION"'
        ],
        engineLogic: [
          "days_open >= 30 AND current_stage == 'awaiting_response'",
          "acknowledgement event present in timeline, no resolution event",
          "case marked as stalled",
          "Requires 1 or more signals to trigger"
        ],
        coOccurrence: {
          conditions: ["C002 \u2014 Closure Without Containment", "C003 \u2014 Process Completion Without Outcome", "TRANSFER_OF_BURDEN"],
          systemStates: ["STABLE_DELAY", "STABLE_ESCALATION", "TRANSFER_OF_BURDEN_PRESENT"],
          trajectories: ["Deteriorating", "Mixed"]
        }
      }),

      spacer(240),

      // C002
      conditionBlock({
        id: "C002",
        name: "Closure Without Containment",
        definition: "A process is formally closed but the underlying issue remains functionally unresolved in the real world. Administrative closure should not be mistaken for substantive resolution.",
        diagnosticQuestion: "Was the case closed administratively without the underlying issue being contained?",
        detectableSigns: [
          "Formal closure notice issued",
          "Persistence of harm or unresolved issue",
          "No traceable remedial change",
          "Internal complaint path with unknown outcome",
          "Deadline passed without traceable resolution"
        ],
        implication: "Administrative closure should not be mistaken for substantive resolution. The record closes. The problem does not.",
        axis: "Closure subtype \u2014 terminal without containment",
        schemaMapping: [
          'conditions_detected[].condition_id == "C002"',
          'escalation_paths[].outcome_status == "unknown" AND route_type == "internal_complaint"',
          'deadlines[].due_date present AND no resolution event in timeline'
        ],
        engineLogic: [
          "Internal escalation path with outcome_status == 'unknown'",
          "Deadline present in case with no resolution event",
          "Requires 1 or more signals to trigger"
        ],
        coOccurrence: {
          conditions: ["C001 \u2014 Stability Without Confirmation", "C004 \u2014 Procedural Completion Without Resolution"],
          systemStates: ["STABLE_ESCALATION", "ESCALATION_WITHOUT_RESPONSE_PRESENT"],
          trajectories: ["Deteriorating"]
        }
      }),

      spacer(240),

      // C003
      conditionBlock({
        id: "C003",
        name: "Process Completion Without Outcome",
        definition: "Required procedural steps are completed but those steps do not produce a meaningful or traceable outcome. Procedural activity should not be mistaken for substantive effect.",
        diagnosticQuestion: "Did the institution complete the process without producing a substantive outcome?",
        detectableSigns: [
          "Acknowledgement issued",
          "Review completed",
          "Procedural steps documented",
          "No corrective or enforceable outcome",
          "Escalation path anticipates narrow or delayed response"
        ],
        implication: "Procedural activity should not be mistaken for substantive effect. This condition captures the gap between process compliance and actual resolution.",
        axis: "Process subtype \u2014 completed without effect",
        schemaMapping: [
          'conditions_detected[].condition_id == "C003"',
          'timeline[].event_type == "acknowledgement" AND timeline[].event_type == "follow_up" AND no resolution event',
          'escalation_paths[].likely_response contains "narrow" or "delay"'
        ],
        engineLogic: [
          "Acknowledgement AND follow_up events present, no resolution event",
          "Escalation path likely_response contains 'narrow' or 'delay'",
          "Requires 1 or more signals to trigger"
        ],
        coOccurrence: {
          conditions: ["C001 \u2014 Stability Without Confirmation", "ESCALATION_WITHOUT_RESPONSE"],
          systemStates: ["STABLE_DELAY", "TRANSFER_OF_BURDEN_PRESENT"],
          trajectories: ["Stable", "Deteriorating"]
        }
      }),

      spacer(240),

      // C004
      conditionBlock({
        id: "C004",
        name: "Procedural Completion Without Resolution",
        definition: "A process has reached formal completion but the underlying issue remains substantively unresolved. The procedure ended. The problem did not.",
        diagnosticQuestion: "Did the process conclude without producing resolution for the underlying issue?",
        detectableSigns: [
          "Case status recorded as closed",
          "Resolution status recorded as unresolved or partial",
          "No resolution event in timeline despite closed status",
          "Escalation path outcome unresolved at point of procedural closure"
        ],
        implication: "Procedural completion should not be mistaken for substantive resolution. The terminal state of the process is not the terminal state of the issue. This is a separate terminal condition \u2014 not a subtype of closure.",
        axis: "Separate terminal condition \u2014 procedure ended, problem did not",
        schemaMapping: [
          'conditions_detected[].condition_id == "C004"',
          'case_lifecycle.status == "closed"',
          'case_lifecycle.resolution_status == "unresolved" | "partial"',
          'signals.behaviour_index == 12 (terminal)'
        ],
        engineLogic: [
          "status == 'closed' AND resolution_status in ('unresolved', 'partial')",
          "Produces posture: Closed, engagement: Terminal, escalation: Residual",
          "behaviour_index == 12 \u2014 the only condition that reaches the maximum index",
          "Requires 2 or more signals to trigger \u2014 both closure and unresolved status must be present"
        ],
        coOccurrence: {
          conditions: ["C002 \u2014 Closure Without Containment"],
          systemStates: ["STABLE_ESCALATION", "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION"],
          trajectories: ["Deteriorating"]
        }
      }),

      spacer(240),

      // TRANSFER_OF_BURDEN
      conditionBlock({
        id: "SIG-01",
        name: "Transfer of Burden",
        definition: "Responsibility for progression has shifted away from the institution and onto the individual or external process. The institution has not actively progressed the matter.",
        diagnosticQuestion: "Has the burden of keeping the case alive transferred from the institution to the individual?",
        detectableSigns: [
          "Repeated follow-up required by complainant",
          "No institutional progression without external input",
          "Responsibility implied but not acted on",
          "Complainant is primary driver of contact"
        ],
        implication: "The institution is no longer carrying the procedural weight. The individual is sustaining the case through their own effort. This is a structural shift, not a communication failure.",
        axis: "Behavioural signal \u2014 detected at pattern and signal level",
        schemaMapping: [
          'results[].signals[] contains "TRANSFER_OF_BURDEN_PRESENT"',
          'results[].system_state == "TRANSFER_OF_BURDEN_PRESENT"',
          'results[].dominant_conditions[].condition == "TRANSFER_OF_BURDEN"'
        ],
        engineLogic: [
          "Detected from pattern of follow-up events without institutional response events",
          "Escalation path outcome_status == 'unknown' with no institutional progression",
          "Surfaces as signal at pattern level and system state"
        ],
        coOccurrence: {
          conditions: ["C001 \u2014 Stability Without Confirmation", "C003 \u2014 Process Completion Without Outcome"],
          systemStates: ["TRANSFER_OF_BURDEN_PRESENT", "STABLE_DELAY"],
          trajectories: ["Stable", "Deteriorating"]
        }
      }),

      spacer(240),

      // ESCALATION_WITHOUT_RESPONSE
      conditionBlock({
        id: "SIG-02",
        name: "Escalation Without Response",
        definition: "The case has escalated structurally without a corresponding institutional response. Escalation has occurred without institutional engagement at the point where engagement was most required.",
        diagnosticQuestion: "Has structural escalation occurred without a corresponding substantive response?",
        detectableSigns: [
          "Escalation triggered by delay or inaction",
          "No substantive response at escalation point",
          "Progression occurs without institutional engagement",
          "Case advanced to oversight or external route without prior resolution"
        ],
        implication: "This is a critical signal. The institution has not engaged at the point where engagement was most required. The record at this point is particularly important to preserve.",
        axis: "Behavioural signal \u2014 detected at pattern and signal level",
        schemaMapping: [
          'results[].signals[] contains "ESCALATION_WITHOUT_RESPONSE_PRESENT"',
          'results[].system_state == "ESCALATION_WITHOUT_RESPONSE_PRESENT"',
          'results[].dominant_conditions[].condition == "ESCALATION_WITHOUT_RESPONSE"'
        ],
        engineLogic: [
          "Escalation stage reached with no resolution event in timeline",
          "stalled == true AND current_stage in ('escalated', 'awaiting_response') with high days_open",
          "Surfaces as signal at pattern level and as system state classification"
        ],
        coOccurrence: {
          conditions: ["C003 \u2014 Process Completion Without Outcome", "C002 \u2014 Closure Without Containment"],
          systemStates: ["ESCALATION_WITHOUT_RESPONSE_PRESENT", "TRANSITION_TO_ESCALATION", "STABLE_ESCALATION"],
          trajectories: ["Deteriorating"]
        }
      }),

      rule("DDDDDD"),

      // ============================================================
      // PART IV — SIGNALS REGISTRY
      // ============================================================
      h1("Part IV \u2014 Signals Registry"),

      body("The following signals are emitted by the engine at pattern level and surfaced in results[].signals[]. Each maps to a key in the UI SIGNAL_MAP and fires a cde_signal_detected event in GA4."),
      spacer(160),

      signalTable([
        { key: "STABILITY_WITHOUT_CONFIRMATION", label: "Stability Without Confirmation", definition: "Institution functions without external confirmation of resolution." },
        { key: "ESCALATION_WITHOUT_RESPONSE_PRESENT", label: "Escalation Without Response", definition: "Structural escalation with no institutional response at escalation point." },
        { key: "TRANSFER_OF_BURDEN_PRESENT", label: "Transfer of Burden", definition: "Responsibility has shifted from institution to individual." },
        { key: "RESISTANCE", label: "Resistance", definition: "Institution is actively or passively resisting engagement or resolution." },
        { key: "ACKNOWLEDGEMENT_WITHOUT_ACTION", label: "Acknowledgement Without Action", definition: "Receipt confirmed but no substantive action taken." },
        { key: "ADMINISTRATIVE_CONTAINMENT", label: "Administrative Containment", definition: "Process used to contain the case rather than resolve it." },
        { key: "TRANSITION_DETECTED", label: "Transition Detected", definition: "Behavioural conditions changed across the submitted sequence." }
      ]),

      rule("DDDDDD"),

      // ============================================================
      // PART V — SYSTEM STATES
      // ============================================================
      h1("Part V \u2014 System State Registry"),

      body("System states are the highest-level diagnostic output of the engine. They are produced by the pattern analysis layer and represent the named state of the institutional system across a sequence of cases. Each maps to results[].system_state in the pattern run output."),
      spacer(160),

      systemStateTable([
        { state: "STABLE_DELAY", meaning: "Delay present without structural escalation. Matter remains open.", conditions: "C001, C003" },
        { state: "TRANSFER_OF_BURDEN_PRESENT", meaning: "Procedural burden has shifted from institution to individual.", conditions: "C001, C003, SIG-01" },
        { state: "ESCALATION_WITHOUT_RESPONSE_PRESENT", meaning: "Escalation has occurred without corresponding response.", conditions: "C003, SIG-02" },
        { state: "TRANSITION_TO_ESCALATION", meaning: "Sequence has moved from delay into escalation.", conditions: "C001, C003, SIG-02" },
        { state: "STABLE_ESCALATION", meaning: "Escalation is present and sustained without reversal.", conditions: "C002, C004, SIG-02" },
        { state: "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION", meaning: "Resistance is the dominant and consistent pattern across the sequence.", conditions: "C001, C002, C004" },
        { state: "REPEATED_ESCALATION_WITH_TRANSITION", meaning: "Escalation has occurred more than once with detected transitions.", conditions: "C003, SIG-01, SIG-02" },
        { state: "INSUFFICIENT_PATTERN_EVIDENCE", meaning: "Sequence does not support a stable pattern interpretation.", conditions: "\u2014" }
      ]),

      rule("DDDDDD"),

      // ============================================================
      // PART VI — ANALYTICS SCHEMA
      // ============================================================
      h1("Part VI \u2014 Analytics Schema"),

      body("The following GA4 events are fired by the frontend on every analysis run. They map directly from the schema field paths defined in Part II. The Conditions Layer events are the analytically significant ones \u2014 they accumulate into a dataset of institutional behaviour patterns across all users."),
      spacer(80),
      body("Once sufficient cde_condition_detected events have accumulated, the co-occurrence patterns in Part III can be populated with real data. This is the point where the Conditions Layer stops being a definition document and starts being an evidence base.", { italic: true }),
      spacer(160),

      analyticsTable([
        {
          event: "cde_analysis_run",
          params: ["input_mode", "trajectory", "system_state", "has_transition", "transition_label", "condition_count", "signal_count"],
          purpose: "Full run context. Top-level summary of every analysis submitted."
        },
        {
          event: "cde_condition_detected",
          params: ["condition", "trajectory", "system_state", "has_transition"],
          purpose: "One event per condition detected. Core Conditions Layer dataset. Accumulates across all users."
        },
        {
          event: "cde_signal_detected",
          params: ["signal", "trajectory", "system_state", "condition_count"],
          purpose: "One event per signal detected. Maps to Signals Registry in Part IV."
        },
        {
          event: "cde_transition_detected",
          params: ["transition_label", "trajectory", "system_state", "conditions"],
          purpose: "Fires only when moment_of_change is present. Tracks transition events across the dataset."
        },
        {
          event: "cde_system_state",
          params: ["system_state", "trajectory", "condition_count", "signal_count", "has_transition"],
          purpose: "Named system state with full context. Maps to System State Registry in Part V."
        },
        {
          event: "cde_export",
          params: ["format (json|markdown|print)", "strike_reference"],
          purpose: "Report export event. Tracks format and whether a Strike reference was attached."
        },
        {
          event: "cde_history_opened",
          params: ["history_count"],
          purpose: "History sidebar opened. Tracks engagement with the session history feature."
        }
      ]),

      rule("DDDDDD"),

      // ============================================================
      // PART VII — ADEQUACY TEST
      // ============================================================
      h1("Part VII \u2014 The Adequacy Test"),

      body("The Adequacy Test is the evaluative standard that underpins the Conditions Layer. A response is complete when it satisfies all three criteria. Each criterion contains a binary \u2014 a pass condition and a fail condition. The test does not demand a particular outcome; it demands accountability for the outcome."),
      spacer(160),

      new Table({
        width: { size: 9360, type: WidthType.DXA },
        columnWidths: [800, 4680, 3880],
        rows: [
          new TableRow({
            tableHeader: true,
            children: ["#", "Criterion", "Pass / Fail Binary"].map((text, i) =>
              new TableCell({
                borders,
                width: { size: [800, 4680, 3880][i], type: WidthType.DXA },
                shading: { fill: "111827", type: ShadingType.CLEAR },
                margins: cellMargins,
                children: [new Paragraph({ children: [new TextRun({ text, font: "Arial", size: 20, bold: true, color: GOLD })] })]
              })
            )
          }),
          ...[
            ["1", "Specific Claim Addressed", "The response addresses what was actually said \u2014 not the category of thing that was said.", "Pass: specific claim addressed\nFail: category deflection"],
            ["2", "Traceable Change or Stated Reason", "The response produces evidence that something was processed \u2014 a change, or an explicit reason why no change occurred.", "Pass: traceable change or stated reason\nFail: acknowledgement without either"],
            ["3", "Loop Closed or Formally Escalated", "The claim has a destination. The response either closes the loop or formally transfers custody.", "Pass: loop closed or escalation documented\nFail: loop abandoned while appearing open"]
          ].map(([num, criterion, description, binary], i) =>
            new TableRow({
              children: [
                new TableCell({
                  borders,
                  width: { size: 800, type: WidthType.DXA },
                  shading: { fill: "1A1A1A", type: ShadingType.CLEAR },
                  margins: cellMargins,
                  verticalAlign: VerticalAlign.CENTER,
                  children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: num, font: "Arial", size: 32, bold: true, color: GOLD })] })]
                }),
                new TableCell({
                  borders,
                  width: { size: 4680, type: WidthType.DXA },
                  shading: { fill: i % 2 === 0 ? LIGHT : "FFFFFF", type: ShadingType.CLEAR },
                  margins: cellMargins,
                  children: [
                    new Paragraph({ children: [new TextRun({ text: criterion, font: "Arial", size: 22, bold: true, color: DARK })] }),
                    new Paragraph({ children: [new TextRun({ text: description, font: "Arial", size: 20, color: MID, italics: true })], spacing: { before: 60 } })
                  ]
                }),
                new TableCell({
                  borders,
                  width: { size: 3880, type: WidthType.DXA },
                  shading: { fill: i % 2 === 0 ? "F9F9F9" : "FFFFFF", type: ShadingType.CLEAR },
                  margins: cellMargins,
                  verticalAlign: VerticalAlign.CENTER,
                  children: binary.split('\n').map(line => new Paragraph({ children: [new TextRun({ text: line, font: "Arial", size: 20, color: MID })] }))
                })
              ]
            })
          )
        ]
      }),

      spacer(200),
      label("Scoring"),
      body("A response that satisfies all three criteria achieves closure. A response that satisfies none achieves containment \u2014 the appearance of process without its substance. Partial scores identify the specific failure mode."),

      rule("DDDDDD"),

      // ============================================================
      // CLOSING
      // ============================================================
      h1("Note on Origin and Method"),

      body("This framework was not built from theory. It was developed inductively across a structured body of real institutional interactions, in which the three criteria of the Adequacy Test and the conditions defined in Part III were applied implicitly before they were named explicitly."),
      body("The rubric existed in practice before it existed on paper. The conditions were detected in real cases before they were formalised as named types. This specification is the formalisation of that practice."),
      spacer(80),
      body("The most important line to carry:", { bold: true }),
      spacer(60),
      new Paragraph({
        children: [new TextRun({ text: "A description explains once. A name allows recognition without re-explanation.", font: "Arial", size: 24, bold: true, color: DARK, italics: true })],
        alignment: AlignmentType.CENTER,
        spacing: { before: 120, after: 120 }
      }),
      spacer(240),

      new Paragraph({
        children: [new TextRun({ text: "Nick Moloney  \u2022  nickdebrief.substack.com  \u2022  orcid.org/0009-0002-9617-1615  \u2022  2026", font: "Arial", size: 18, color: GREY })],
        alignment: AlignmentType.CENTER,
        border: { top: { style: BorderStyle.SINGLE, size: 4, color: "DDDDDD", space: 1 } },
        spacing: { before: 240, after: 0 }
      })

    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync('/home/claude/conditions-layer-spec-v1.docx', buffer);
  console.log('Done');
});