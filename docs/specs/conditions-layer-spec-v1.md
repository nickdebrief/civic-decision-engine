# CONDITIONS LAYER  
### Specification v1.0  
Civic Decision Engine • Nick Moloney • 2026

---

## Part I — Purpose and Scope

The Conditions Layer is the diagnostic core of the Civic Decision Engine.  
It defines a set of named, reusable institutional behaviour states that can be identified, cited, and accumulated across civic cases.

This document is the formal specification of the Conditions Layer.  
It defines each condition, maps it to the engine output schema, describes the engine logic that detects it, and specifies how it maps into the analytics schema.

---

### Principle

When a system can support named conditions, it moves from *describing* behaviour to *diagnosing* it.

---

### What a Condition Is

A condition is a defined state of institutional behaviour:

- identified through observable structural signals  
- repeatable across cases  
- independent of individual interpretation  

Conditions are not scores or opinions.  
They are diagnostic classifications of system state.

---

### Dependency Chain

1. `cde_output.schema.json` — canonical output contract  
2. Conditions Layer Specification — maps schema → meaning  
3. UI / frontend — renders guaranteed structure  
4. Analytics schema — accumulates behaviour data  

---

## Part II — Schema Reference

### Civic Run Output

results[].conditions_detected[]
results[].conditions_detected[].condition_id
results[].conditions_detected[].name
results[].conditions_detected[].signals[]
results[].condition

---

### Timeline Output

results[].conditions[]
results[].trajectory
results[].moment_of_change

---

### Pattern Output

results[].system_state
results[].dominant_conditions[]
results[].signals[]

---

## Part III — Condition Definitions

---

### C001 — Stability Without Confirmation

**Definition**  
The system continues without confirming resolution.

**Diagnostic question**  
Does the system continue without confirming the issue is resolved?

**Detectable signs**
- Continued operation without closure  
- No follow-up confirmation  
- Case open > 30 days  

**Implication**  
Continuity ≠ resolution.

---

### C002 — Closure Without Containment

**Definition**  
Process closed but problem persists.

**Diagnostic question**  
Was the case closed without containing the issue?

**Detectable signs**
- Formal closure issued  
- No real-world resolution  
- Outcome unclear  

**Implication**  
The record closes. The issue does not.

---

### C003 — Process Completion Without Outcome

**Definition**  
Steps completed without producing an outcome.

**Diagnostic question**  
Was process followed but no result achieved?

**Detectable signs**
- Acknowledgement issued  
- Review completed  
- No actionable outcome  

**Implication**  
Process ≠ effect.

---

### C004 — Procedural Completion Without Resolution

**Definition**  
Process fully complete but unresolved.

**Diagnostic question**  
Did the process end without resolving the issue?

**Detectable signs**
- Status: closed  
- Resolution: unresolved  
- Behaviour index: terminal  

**Implication**  
Procedure ends. Problem remains.

---

### SIG-01 — Transfer of Burden

**Definition**  
Responsibility shifts from institution to individual.

**Implication**  
The system is no longer carrying the process.

---

### SIG-02 — Escalation Without Response

**Definition**  
Escalation occurs without response.

**Implication**  
The system failed at the critical point of engagement.

---

## Co-occurrence Patterns

> This section begins empty.

It is populated through analytics once sufficient  
`cde_condition_detected` events accumulate.

At that point:

The Conditions Layer stops being a definition  
and becomes an evidence base.

---

## Part IV — Signals Registry

| Signal | Meaning |
|------|--------|
| STABILITY_WITHOUT_CONFIRMATION | No confirmation of resolution |
| ESCALATION_WITHOUT_RESPONSE_PRESENT | Escalation without response |
| TRANSFER_OF_BURDEN_PRESENT | Responsibility shifted |
| RESISTANCE | Institutional resistance |
| ACKNOWLEDGEMENT_WITHOUT_ACTION | Acknowledged, not acted |
| ADMINISTRATIVE_CONTAINMENT | Contained, not resolved |
| TRANSITION_DETECTED | Behaviour changed |

---

## Part V — System States

| State | Meaning |
|------|--------|
| STABLE_DELAY | Delay without escalation |
| TRANSFER_OF_BURDEN_PRESENT | Burden shifted |
| ESCALATION_WITHOUT_RESPONSE_PRESENT | Escalation ignored |
| TRANSITION_TO_ESCALATION | Delay → escalation |
| STABLE_ESCALATION | Escalation sustained |
| PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION | Resistance pattern |
| INSUFFICIENT_PATTERN_EVIDENCE | Not enough data |

---

## Part VI — Analytics Schema

Events:

- `cde_analysis_run`
- `cde_condition_detected`
- `cde_signal_detected`
- `cde_transition_detected`
- `cde_system_state`

These accumulate behaviour patterns across all usage.

---

## Part VII — Adequacy Test

A response is complete if:

1. **Specific claim addressed**
2. **Traceable change or reason**
3. **Loop closed or escalated**

Failure at any point defines the condition.

---

## Closing Note

This framework was not theoretical.

It was derived from real institutional interaction.

The pattern existed before the name.

---

### Core Line

**A description explains once.  
A name allows recognition without re-explanation.**