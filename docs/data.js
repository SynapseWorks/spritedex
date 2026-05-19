const speciesData = [
  {
    id: 1,
    commonName: "Garlic Mustard",
    scientificName: "Alliaria petiolata",
    category: "Plant",
    status: "Invasive",
    confidence: "High",
    notes: "Garlic-scented edible plant. Use caution and confirm ID."
  },
  {
    id: 2,
    commonName: "Yarrow",
    scientificName: "Achillea millefolium",
    category: "Plant",
    status: "Medicinal",
    confidence: "Candidate",
    notes: "Traditional medicinal plant. Important to confirm lookalikes."
  },
  {
    id: 3,
    commonName: "American Robin",
    scientificName: "Turdus migratorius",
    category: "Bird",
    status: "Common",
    confidence: "Observed",
    notes: "Common backyard and woodland-edge bird."
  },
  {
    id: 4,
    commonName: "Dandelion",
    scientificName: "Taraxacum officinale",
    category: "Plant",
    status: "Edible",
    confidence: "Confirmed",
    notes: "Common edible plant with leaves, flowers, and roots used traditionally."
  }
];

const encounterData = [
  {
    id: 1,
    speciesId: 1,
    name: "Garlic Mustard",
    category: "Plant",
    confidence: "High confidence",
    location: "Trail edge, Newcastle",
    date: "2026-05-19"
  },
  {
    id: 2,
    speciesId: 3,
    name: "American Robin",
    category: "Bird",
    confidence: "Observed",
    location: "Backyard",
    date: "2026-05-19"
  },
  {
    id: 3,
    speciesId: 4,
    name: "Dandelion",
    category: "Plant",
    confidence: "Confirmed",
    location: "Lawn edge",
    date: "2026-05-19"
  }
];
