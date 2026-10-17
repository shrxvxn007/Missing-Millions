# A 90–120 second judge demonstration

Prepare the processed package and start the app before presenting. Use the local cached package so no live source requests occur during the presentation. Open “About the data” once to verify the current mode, years and warnings. Close it and return to the initial facility/road view.

If using the synthetic fixture, say this before the reveal: **“This is a synthetic scenario running the real clustering, network, anomaly and optimization algorithms. These measurements are not findings about people in Uganda.”** Do not replace that statement with a claim of discovered communities. For the acquired real source sample, describe a small unverified Mbale source sample; do not imply a validated regional public-health study. Its two-year timeline and insufficient-sample anomaly state are intentional.

| Time | Action | Spoken narrative |
| --- | --- | --- |
| 0–15 s | Show mapped facilities and roads. | “Maps help decide where services and public investment go. What happens when the available map does not represent everyone well?” |
| 15–30 s | Click **Reveal the Overlooked**. Let the candidate layer appear. | “We flip the question: can satellite-derived building evidence help us identify places worth investigating?” |
| 30–55 s | Select a candidate. Read its actual endpoint counts, population year and mapped-facility walk estimate. Drag the timeline only across available years. | “These are model-estimated building counts, a separate population estimate, and travel on the available walking network. A building is not proof of occupancy, and an unrecorded clinic may exist.” |
| 55–70 s | Open **How the AI works**. Inspect cells, DBSCAN candidate, route, anomaly state and score contributions. | “We group count-supported cells, analyze geographic access, compare unusual feature combinations when the sample is large enough, and make the priority assumptions visible.” |
| 70–95 s | Close methodology. Click **What if care went to them?**. Inspect the computed stop, reachable roads and before/after estimates. | “This is a hypothetical outreach scenario. We search mapped road locations for additional estimated population within the chosen walking threshold. These road segments are modeled reach, not an operationally approved site.” |
| 95–110 s | Click **Create investigation task**, add a question, save. Open task list and show export. | “The result becomes a question for local partners: verify occupancy, missing services, usable paths, and whether outreach would be useful.” |
| 110–120 s | Return to baseline or replay discovery. | “The purpose is to ask better questions before incomplete records shape decisions. Local communities and organizations must validate the evidence and participate in planning.” |

The **Start discovery** control runs the guided scene sequence. Manual navigation is preferable while answering questions. Use replay/baseline to clear the hypothetical scenario before another run. Investigation records persist in local SQLite across reloads; create only clearly described demo records during a presentation.

Numbers in the spoken presentation must come from the current evidence panel or simulation response. Do not memorize an unsupported “people reached” statistic: selected targets, thresholds, walking speed and data mode can all change the result. A scenario that finds no additional coverage is a valid output.

For technical questions, open the machine-readable source manifest and `docs/methodology.md`. Explain that satellite source models were trained by Google; local DBSCAN and Isolation Forest provide additional analysis. The application does not train a satellite deep-learning model. Seed agreement describes ranking stability, not medical predictive confidence.

## Verified local presentation paths

The three browser workflows passed; see [validation.md](validation.md) and the screenshots in `screenshots/`. In the real source sample, candidate 01 is already within the default 30-minute planning band and correctly produces **no added coverage** when targeted alone. Select candidate 02 for a source-derived outreach example. The current calculation associates an estimated 672 people with its representative point; this is a geographic scenario, not a claim that 672 actual residents would receive care. Keep the representative-point and facility-service caveats visible.

The full synthetic discovery walkthrough also exercises five seeded Isolation Forests and draggable outreach stops. Clearly announce synthetic mode when using it. The automatic four-scene sequence is 100 seconds; use the pause button and arrow keys for the spoken 90–120 second presentation.
