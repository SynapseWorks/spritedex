# SpriteDex Region Architecture v1

## Product principle

**iNaturalist records the living world. SpriteDex turns the living world into somewhere you can explore.**

Region v1 extends the original SpriteDex model without replacing it.

Existing core:

- SpeciesDex: what organism is this?
- Encounter Log: what did this user encounter?

New core:

- Region: where can this encounter count?
- Region Species: what does this species mean in that Region?
- User Region Species: has this user discovered it there?
- User Region Progress: what is the user's current Regional Dex state?

## Why Regions are SpriteDex-owned

A SpriteDex Region is not synonymous with an iNaturalist Place.

A Region may represent:

- a country or province/state
- municipality
- conservation area or park
- watershed
- ecoregion
- trail system
- campus
- partner property
- carefully curated custom area

An `inat_place_id` is optional supporting metadata.

This avoids forcing game-specific geography into iNaturalist's Place system and allows SpriteDex to use authoritative conservation/GIS boundaries directly.

## Many-to-many geography

An encounter can belong to several valid Regions simultaneously.

Example:

- Ontario
- Clarington
- Ganaraska River Watershed
- Ganaraska Forest
- an ecological region

The encounter remains one biological record. `encounter_regions` stores each valid geographic membership.

## Region relationships are a graph

Administrative, ecological, watershed, and management relationships do not form one perfect tree.

`region_relationships` therefore supports multiple relationship types. One relationship may be marked primary for UI breadcrumbs without pretending it is the only meaningful hierarchy.

## Encounter tier is not scientific rarity

SpriteDex must keep these concepts separate:

### Scientific conservation status

Sourced from authoritative biodiversity/conservation systems.

### SpriteDex encounter tier

A game-facing estimate of how unusual an encounter is within one Region, potentially based on observation count, unique observers, observer-days, recency, seasonality, spatial distribution, and expert overrides.

Initial tiers:

- familiar
- notable
- uncommon
- elusive
- exceptional

## Active Dex versus regional catalogue

A species may be credibly documented in a Region without being reasonably encounterable today.

`region_species.dex_eligible` allows SpriteDex to maintain:

- complete/historical regional catalogue
- playable active Regional Dex

This prevents ancient vagrants, extinct local populations, or exceptional records from making a Regional Dex effectively impossible to complete.

## Sensitive species

Precise Region or location display must be independently suppressible using `sensitive_location` and future policy logic.

SpriteDex should never attempt to infer hidden coordinates from obscured third-party observations.

## Scoring model

One biological encounter should award global encounter XP once.

It may unlock the species in several Regional Dexes, but those regional scores should remain scoped to their Regions rather than being naively multiplied into global XP.

## Calculation model

Immediate path:

1. encounter saved
2. `process_encounter_regions(encounter_id)`
3. PostGIS `ST_Covers` matches active playable Regions
4. `encounter_regions` refreshes
5. user's Region/species discovery aggregates refresh
6. cached `user_region_progress` refreshes

Scheduled path later:

- recalculate regional observation statistics
- encounter tiers
- dex eligibility
- seasonal activity
- leaderboard snapshots

## Migration path to full taxonomy

Region v1 intentionally uses the current `species` table.

Later, when iNaturalist taxonomy integration becomes canonical:

- `species` can evolve into `taxa`
- `region_species` can migrate to `region_taxa`
- `user_region_species` can migrate to `user_region_taxa`

Regions and taxonomy should not be migrated simultaneously; separating those changes makes validation safer.
