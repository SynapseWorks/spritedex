# API Plan

This document outlines planned backend API endpoints.

---

# Species Endpoints

GET /api/species
GET /api/species/{id}
POST /api/species
PUT /api/species/{id}

---

# Encounter Endpoints

GET /api/encounters
GET /api/encounters/{id}
POST /api/encounters
PUT /api/encounters/{id}

---

# Identification Endpoints

POST /api/identify/image
POST /api/identify/audio

---

# Map Endpoints

GET /api/maps/nearby
GET /api/maps/species-range

---

# Media Endpoints

POST /api/media/upload
GET /api/media/{id}

---

# Authentication

POST /api/auth/login
POST /api/auth/register

---

# Future API Concepts

- AR overlays
- live camera scanning
- environmental sensors
- ecological analytics
- wearable integrations
