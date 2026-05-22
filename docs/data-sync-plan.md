# Data Sync Plan

SpriteDex will keep external biodiversity data fresh using dataset imports and limited API lookups.

## Sources

### iNaturalist API
Used for live app features, species lookup, and targeted searches.
Not used for bulk scraping.

### iNaturalist Taxonomy DarwinCore Archive
Monthly sync for taxonomy and common names.

### iNaturalist GBIF DarwinCore Archive
Weekly sync for research-grade observation records and licensed media links.

### iNaturalist Open Range Map Dataset
Monthly sync for modeled range maps.

### iNaturalist Places
Weekly sync for place IDs and bounding boxes.

## Sync Strategy

- Bulk data comes from datasets.
- Live app features use APIs sparingly.
- Sync jobs track last successful import.
- Each external record keeps its source ID.
- SpriteDex user encounters remain separate from external observations.

## Planned Sync Tables

- source_datasets
- sync_runs
- taxa
- taxon_common_names
- external_observations
- range_maps
- places

## Update Frequency

- Taxonomy: monthly
- Range maps: monthly
- Places: weekly
- Observations: weekly
- API lookups: on demand
