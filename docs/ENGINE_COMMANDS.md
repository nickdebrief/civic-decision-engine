# ENGINE COMMANDS  
Civic Decision Engine — Interaction Surface

---

## CORE PRINCIPLE

The Civic Decision Engine is not run through trial.

It is run through defined entry points.

Each command produces a structured, traceable output.

---

## CIVIC ANALYSIS

Run a single civic case analysis.

```bash
python civic_decision_engine_v10.py --mode civic \
  --previous-run outputs/run_X.json \
  --export outputs/run_Y.json
```

## SYSTEM ANALYSIS

Run analysis across system cases.

```bash
python civic_decision_engine_v10.py \
  --mode system \
  --input examples/system_cases \
  --batch \
  --export outputs/system_analysis.json
```

## COMPARE RUNS

Compare two runs to detect change.

```bash
python civic_decision_engine_v10.py \
  --mode compare \
  --input outputs/run_new.json \
  --compare-with outputs/run_old.json \
  --export outputs/compare.json \
  --export-md outputs/compare.md
```

## TIMELINE ANALYSIS

Build a timeline from audit data.

```bash
python timeline.py
```

## OUTPUT STRUCTURE

Each civic run produces:
	•	run_metadata
	•	run_id
	•	generated_at
	•	lineage (previous_run_id, depth, version)
	•	results
	•	signals (posture, engagement, escalation, behaviour_index)
	•	condition
	•	assessment

## CONDITIONS LAYER

Conditions are not labels.

They are named system states.

Examples:
	•	RESISTANCE
	•	PARTIAL_ENGAGEMENT
	•	ADMINISTRATIVE_CONTAINMENT
	•	STABILITY_WITHOUT_CONFIRMATION


## TRANSITIONS

Timeline transitions are classified as:
	•	deteriorating
	•	improving
	•	stable
	•	structural_update

## Structural updates represent:
	•	missing condition data
	•	non-behavioural changes
	•	state alignment events

## Structural updates do not influence:
	•	overall trajectory
	•	moment_of_change

	1.	Run analysis
→ outputs/run_12.json

	2.	Run next analysis with lineage
→ outputs/run_13.json

	3.	Compare runs
→ outputs/compare_13_vs_12.json

	4.	Review timeline
→ identify behavioural vs structural transitions

⸻

## NOTE

The engine does not infer meaning from absence.

Where condition data is incomplete, the system records a structural update.

This preserves diagnostic integrity.

