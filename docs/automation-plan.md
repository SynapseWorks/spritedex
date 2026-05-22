# Automation Plan

SpriteDex will eventually use scheduled sync jobs to keep external biodiversity datasets current.

## Planned Jobs

### Monthly Taxonomy Sync
Downloads the latest iNaturalist taxonomy dataset and updates local taxa records.

### Monthly Range Map Sync
Downloads updated iNaturalist range map data and refreshes local species range layers.

### Weekly Places Sync
Updates iNaturalist place IDs, bounding boxes, and region metadata.

### Weekly Observation Sync
Imports selected research-grade external observations for local/regional context.

## Sync Pattern

1. Download latest source file.
2. Validate file structure.
3. Stage imported records.
4. Compare staged records to production tables.
5. Insert new records.
6. Update changed records.
7. Mark removed/deprecated records.
8. Log sync run status.

## Future Scheduler Options

- GitHub Actions
- Home server cron job
- Windows Task Scheduler
- Docker scheduled container
- FastAPI background worker

## Important Rule

SpriteDex user encounters are never overwritten by external dataset syncs.
External observations and personal encounters remain separate data layers.
