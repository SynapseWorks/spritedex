INSERT INTO encounters (
    species_id,
    location,
    location_description,
    habitat,
    life_stage,
    quantity_estimate,
    confidence_level,
    notes
)
VALUES (
    1,
    ST_SetSRID(ST_MakePoint(-78.589, 43.918), 4326)::geography,
    'Near trail edge in Newcastle, Ontario',
    'disturbed woodland edge',
    'flowering',
    'small patch',
    'high',
    'Smelled strongly like garlic when crushed.'
);
