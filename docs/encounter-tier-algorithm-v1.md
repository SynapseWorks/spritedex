# SpriteDex Encounter Tier Algorithm v1

## Purpose

SpriteDex Encounter Tiers are a game-facing description of how often a taxon is independently documented in a specific Region and season **relative to observation effort for the same broad taxonomic cohort**.

They are **not** claims about population abundance, conservation rarity, or the probability that a person will encounter an organism in the wild.

The five public non-sensitive tiers are:

1. Familiar
2. Notable
3. Uncommon
4. Elusive
5. Exceptional

A sixth state, `Unranked`, is used when evidence is too thin. Sensitive taxa are presented publicly as `Protected Encounter` rather than advertising a rarity-like tier.

## Why raw observation counts are rejected

Opportunistic biodiversity observations are shaped by:

- where people can and choose to travel,
- what times and seasons they observe,
- which taxa they notice or care to photograph,
- observer expertise and equipment,
- taxon detectability,
- special events such as BioBlitzes.

Therefore `COUNT(observations)` is evidence of recording activity, not a direct abundance estimate.

## V1 unit: observer-day

Multiple observations by the same person of the same taxon on the same day collapse to one `taxon observer-day`.

This prevents one enthusiastic observer from making a species appear common by uploading dozens of records during a single outing.

### Taxon observer-days

Distinct:

`(observer, local observation date)`

for one species in one Region during the seasonal window.

### Cohort observer-days

Distinct:

`(observer, local observation date)`

where that observer documented **any taxon in the same broad cohort** in the Region during the seasonal window.

Initial cohorts come from iNaturalist `iconic_taxon_name` where available (Birds/Aves, Plants/Plantae, Fungi, Mammals, etc.).

## Seasonal window

V1 uses the current month plus the immediately preceding and following month, repeated across a five-year lookback.

Example for a September 2, 2026 update:

- August, September, and October records are relevant;
- records come from the current/past five calendar years;
- future dates in the current year obviously contribute nothing.

This avoids comparing a spring ephemeral with its winter absence and smooths arbitrary month boundaries.

## Encounter rate

`encounter_rate = taxon_observer_days / cohort_observer_days`

Interpretation:

> Among observer-days where people were documenting this broad kind of life here during this season, on what fraction of those observer-days was this taxon documented?

It is a reporting-frequency index, not abundance.

## Evidence confidence

V1 ranks the confidence of the regional sampling frame:

- **High:** at least 300 cohort observer-days across at least 3 sampled years
- **Medium:** at least 100 cohort observer-days across at least 2 sampled years
- **Low:** anything less

Low-confidence taxa remain `Unranked` automatically. A trusted Region manager/expert can later override a tier or Dex eligibility with an audit trail.

## V1 tier thresholds

Only Medium/High confidence is automatically tiered:

| Encounter rate | Tier |
|---:|---|
| >= 20% | Familiar |
| >= 7% | Notable |
| >= 2% | Uncommon |
| >= 0.5% | Elusive |
| < 0.5% | Exceptional |

These are **initial game thresholds**, deliberately easy to explain and tune. They should be calibrated after pilot Regions produce real distributions.

## Active Regional Dex eligibility

A taxon may exist in the Regional Catalogue without being mandatory in the Active Dex.

V1 automatically marks a taxon Dex-eligible for the current seasonal window when:

- there are at least 2 taxon observer-days,
- there are at least 2 unique observers,
- there is a qualifying observation within the last 3 years.

This prevents one historical/vagrant record from making a Regional Dex effectively impossible to complete.

## Stability / anti-flapping

A newly classified taxon receives its initial tier immediately.

After that, a different candidate tier must appear in **two consecutive weekly calculations** before the stable tier changes. This stops values hovering around a threshold from producing weekly Common/Uncommon ping-pong.

Metric snapshots preserve each weekly calculation so WORLD UPDATE can later explain changes.

## Game points

First Regional discovery points in v1:

- Familiar: 10
- Notable: 20
- Uncommon: 40
- Elusive: 70
- Exceptional: 100
- Unranked: 10

Repeated observations do not repeatedly grant the first-discovery points.

### Sensitive taxa

If `sensitive_location = true`:

- public tier becomes `Protected Encounter`,
- first-discovery points are capped at 20,
- precise Region/location disclosure should be governed by the privacy layer,
- the system must never infer or expose hidden iNaturalist coordinates.

This deliberately avoids creating a high-value treasure hunt for vulnerable organisms.

## What feeds the calculation

V1 regional tiers use normalized **public external biodiversity evidence**, initially Research Grade iNaturalist records.

SpriteDex encounters affect a user's personal progress immediately, but raw SpriteDex encounters do not directly change the regional frequency model. If they later become qualifying iNaturalist records and are imported by the scheduled data pipeline, they can contribute normally.

This prevents gameplay from directly manipulating its own rarity denominator.

## Geoprivacy and spatial quality

Fine-scale Region metrics only use observations where:

- geoprivacy is open,
- taxon geoprivacy is open,
- a public point is available,
- positional accuracy is within the Region's configured maximum,
- the point falls inside the Region polygon.

Obscured/private records may still be valuable to conservation science, but SpriteDex does not guess their fine-scale Region.

## V1 implementation migrations

Apply in order after Region migrations 001-003:

1. `004_encounter_tier_schema.sql`
2. `005_external_observation_regions.sql`
3. `006_encounter_tier_calculation.sql`
4. `007_region_game_state.sql`

Then run `database/encounter_tier_test.sql`.

## V1.1 improvements

After pilot data exists, add:

1. **Spatial breadth** — fraction of sampled grid cells containing the taxon.
2. **Robust daily weighting** — reduce effects of extremely large BioBlitz days.
3. **Trusted occurrence-status guardrails** — curated place checklists can prevent obvious under-reporting artifacts.
4. **Taxonomic calibration** — tune thresholds independently by cohort and Region type.
5. **Season curves** — replace the three-month window with smoothed month-of-year activity curves.

## V2 direction

A mature scientific-facing model could incorporate explicit observation sessions/effort and occupancy/detectability models. That would be a separate analytical product from the simple, explainable game tier.

SpriteDex should prefer an honest, transparent game statistic over a falsely precise claim about ecological rarity.
