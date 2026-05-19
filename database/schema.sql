CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE species (
    species_id SERIAL PRIMARY KEY,
    common_name TEXT NOT NULL,
    scientific_name TEXT,
    kingdom TEXT,
    category TEXT, -- plant, animal, insect, fungus, etc.
    description TEXT,
    edible_status TEXT,
    toxicity_status TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE encounters (
    encounter_id SERIAL PRIMARY KEY,
    species_id INT REFERENCES species(species_id),
    encountered_at TIMESTAMP DEFAULT NOW(),
    location GEOGRAPHY(Point, 4326),
    location_description TEXT,
    habitat TEXT,
    life_stage TEXT,
    quantity_estimate TEXT,
    confidence_level TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE encounter_media (
    media_id SERIAL PRIMARY KEY,
    encounter_id INT REFERENCES encounters(encounter_id) ON DELETE CASCADE,
    media_type TEXT, -- photo, audio, video
    file_path TEXT,
    caption TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE identification_candidates (
    candidate_id SERIAL PRIMARY KEY,
    encounter_id INT REFERENCES encounters(encounter_id) ON DELETE CASCADE,
    suggested_common_name TEXT,
    suggested_scientific_name TEXT,
    confidence_score NUMERIC(5,2),
    source TEXT, -- PlantNet, iNaturalist, OpenAI, manual
    selected BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE species_notes (
    note_id SERIAL PRIMARY KEY,
    species_id INT REFERENCES species(species_id) ON DELETE CASCADE,
    note_type TEXT, -- medicinal, edible, toxic, ecological, spiritual, personal
    note_text TEXT,
    source TEXT,
    verified_status TEXT, -- AI, human-confirmed, personal-tested, external-source
    created_at TIMESTAMP DEFAULT NOW()
);
