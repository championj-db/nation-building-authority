# IoT Sensor Data Management

| | |
| --- | --- |
| **Category** | Autonomous Systems |
| **Selected function** | IoT Sensor Data Management |
| **Evidence anchor** | Telemetry ingest pattern proven at [NHVR](https://www.databricks.com/customers/national-heavy-vehicle-regulator) scale |
| **Target KPI** | Time to insight from sensor data (measure to instrument) |
| **Status** | **Stub** - README and DAB skeleton only |

## Problem

A sensor estate produces continuous readings from devices that are unreliable by nature. Readings
arrive late, out of order, duplicated, or not at all, and a silently failed sensor looks exactly
like a quiet one. Every downstream use case inherits these problems, so each one solves them again,
differently.

## What this use case demonstrates

The foundational sensor data layer the rest of the category depends on: a sensor registry,
high-frequency ingest that handles late and out-of-order arrival correctly, sensor health
monitoring that distinguishes "no reading" from "nothing to report", and aggregates served at
several time grains.

## Modelled on

The telemetry ingest pattern proven at
[NHVR](https://www.databricks.com/customers/national-heavy-vehicle-regulator) scale - more than
4.5 million monthly vehicle sightings with sub-second serving - applied to a general sensor estate
rather than to vehicles specifically.

The NHVR experience is directly relevant here: their existing warehouse could not ingest the data
they had deliberately acquired. The lesson for a sensor foundation is to design the ingest path for
the volume the estate will produce once it is fully instrumented, not for the pilot.

The defence-oriented functions in this domain - battlefield decision support, real-time mission
planning - were set aside as less broadly applicable; this is the layer they would all sit on.

## Scope

**In scope**

* A sensor registry with device metadata and expected reporting behaviour
* High-frequency streaming ingest
* Correct handling of late, out-of-order and duplicate readings
* Sensor health monitoring, including detection of silent failure
* Aggregate serving at multiple time grains

**Out of scope**

* Any real sensor or device data. Wholly synthetic.
* Device management, firmware, or edge deployment.
* Use-case-specific analytics, which belong in the use case that needs them. This layer provides
  clean sensor data and stops there.

## Functions

| Function | Description |
| --- | --- |
| Sensor registry | Device metadata, location, and expected reporting interval |
| Streaming ingest | High-frequency reading ingest sized for a fully instrumented estate |
| Late and out-of-order handling | Watermarking and deduplication so corrections do not corrupt aggregates |
| Sensor health monitoring | Detect silent failure, drift, and missed reporting intervals |
| Multi-grain aggregates | Serve aggregates at several time grains from one pipeline |

## Architecture

```
sensor readings -> bronze (raw, append-only) -> deduplicated + watermarked silver
                -> sensor health monitoring
                -> multi-grain aggregates (gold) -> serving
```

Lakeflow for streaming ingest and the declarative pipeline, Delta for append-only raw capture,
Unity Catalog for governance, serverless throughout.

## Data

Synthetic and seeded, with late arrival, duplication and silent sensor failure deliberately
injected so the handling logic can be shown to work rather than merely asserted.

## Deploy

```bash
databricks bundle validate --target dev --var catalog=<YOUR_CATALOG>
```

Replace `<YOUR_CATALOG>` (angle brackets included) with a catalog you can write to. There is
nothing to deploy or run yet.

## Assurance notes

Sensor data is often assumed to be impersonal and frequently is not: readings tied to a location
and a time can identify the people at that location. Whether this layer holds personal information
depends entirely on what the sensors observe, so the classification decision belongs with the
estate rather than with the pipeline. Retention should be set deliberately rather than defaulting
to "keep everything", since high-frequency data accumulates faster than its usefulness does.

## Not built yet

Everything. This is a stub: README plus a validating DAB skeleton. No synthetic generator, no
registry, no ingest, no late-arrival handling, no health monitoring, no aggregates.
