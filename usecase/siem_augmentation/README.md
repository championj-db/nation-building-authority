# SIEM Augmentation

| | |
| --- | --- |
| **Category** | Cybersecurity |
| **Selected function** | Augment SIEM |
| **Evidence anchor** | None public - pattern-based selection (see below) |
| **Target KPI** | SIEM retention and licensing cost (measure to instrument) |
| **Status** | **Stub** - README and DAB skeleton only |

## Problem

SIEM licensing is priced on ingest volume, so security teams are forced to choose what *not* to
collect and how briefly to keep it. That choice is made on cost grounds, not risk grounds. The
result is a retention window shorter than the dwell time of the threats it is meant to catch: by
the time an intrusion is discovered, the logs that would explain it have aged out.

## What this use case demonstrates

Splitting the workload by what each tool is good at. High-volume telemetry is retained at full
fidelity and long duration on the lakehouse where storage is cheap; hunting runs over the full
history; detections are forwarded back to the SIEM, which keeps alerting and response.

## Modelled on

Nothing publicly citable. This is the weakest-anchored selection in the repository and it is worth
being direct about that: unlike the flagship, there is no published public sector customer outcome
behind it. The architecture is the evidence here, not a customer result.

That architecture is well established - long-retention storage in Delta, Unity Catalog governance
over security telemetry, and detection logic maintained as version-controlled code rather than as
rules inside a vendor console. The cost argument follows from how SIEM licensing works rather than
from a measured case: if retention is priced on ingest volume, moving volume elsewhere reduces what
is paid for it. Treat the saving as something to measure in your own estate, not as a figure this
repository can substantiate.

## Scope

**In scope**

* Ingest of high-volume security telemetry
* Long-retention full-fidelity storage
* Detection-as-code with version control and testing
* Hunting queries across a retention window the SIEM cannot economically hold
* Entity risk scoring
* Forwarding detections to a SIEM

**Out of scope**

* Any real security telemetry. Wholly synthetic.
* Replacing a SIEM. This augments one; alerting and response stay where they are.
* A specific SIEM vendor integration. The forwarding step is modelled generically.

## Functions

| Function | Description |
| --- | --- |
| Telemetry ingest | Ingest high-volume log and event telemetry from multiple sources |
| Long retention | Retain at full fidelity for a window set by risk, not by licence cost |
| Detection-as-code | Detections as tested, version-controlled code |
| Hunting | Ad hoc and scheduled hunting across the full history |
| Entity risk scoring | Score users, hosts and services on accumulated signal |
| Detection forwarding | Forward detections to the SIEM for alerting and response |

## Architecture

```
security telemetry -> bronze (full fidelity, long retention)
                   -> normalised silver -> detections (as code)
                   -> entity risk scores -> forwarded alerts -> SIEM
                   -> hunting queries
```

Lakeflow for streaming ingest, Delta for cheap long retention, Unity Catalog for governance and
audit of security data, serverless throughout.

## Data

Synthetic and seeded, with known attack patterns injected so detection can be measured against
ground truth.

## Deploy

```bash
databricks bundle validate --target dev --var catalog=<YOUR_CATALOG>
```

Replace `<YOUR_CATALOG>` (angle brackets included) with a catalog you can write to. There is
nothing to deploy or run yet.

## Assurance notes

Security telemetry is itself sensitive and contains extensive personal information about staff
activity, so the monitoring platform needs the same governance rigour as the systems it monitors -
and access to it should be audited, since security data is an attractive target in its own right.
User behaviour analysis in particular touches employee privacy and typically needs consultation
beyond the security team. Relevant: the
[Protective Security Policy Framework](https://www.protectivesecurity.gov.au/about/structure-protective-security-policy-framework).

## Not built yet

Everything. This is a stub: README plus a validating DAB skeleton. No synthetic telemetry
generator, no ingest, no detections, no hunting queries, no risk scoring, no forwarding.
