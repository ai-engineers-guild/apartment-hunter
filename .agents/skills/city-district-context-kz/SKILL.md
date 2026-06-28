---
name: city-district-context-kz
description: >
  Research neighborhood context for apartment search in Kazakhstan cities:
  district reputation, transport access, pricing, noise, construction, cleanliness,
  livability, and tradeoffs between districts. Use when a user asks where to live,
  compares districts, or wants city-specific housing context.
---

# City District Context KZ

## When to use

Use this skill when the user:

- asks which district is better for living or renting;
- wants local context before searching apartments;
- asks whether an area is safe, convenient, expensive, noisy, or well connected;
- wants a short district brief attached to apartment recommendations.

## Workflow

1. Identify city, target districts, budget band, and user priorities.
2. Research current neighborhood context with recent web sources.
3. Summarize by explicit dimensions, not vibes.
4. Feed the conclusion back into apartment search filters or recommendation logic.

## Required research dimensions

- district reputation and perceived livability;
- transport access:
  metro, buses, major roads, commute friction;
- price level relative to the city;
- cleanliness, greenery, walkability, and air/noise exposure;
- active construction, redevelopment, traffic, or nightlife pressure;
- family fit:
  schools, clinics, playgrounds, calmer courtyards;
- renter tradeoffs:
  prestige vs convenience vs budget.

## Output format

For each district, produce:

- one-line profile;
- strengths;
- risks;
- who it fits best;
- budget implication relative to the city average.

## Rules

- Use recent sources. If the user says "now", "currently", or "today", verify with live browsing.
- Do not present reputation claims as hard fact; label them as observed patterns or common perception.
- Translate vague labels like "good district" into concrete variables:
  commute, noise, price, cleanliness, schools, and safety perception.
- If the apartment search skill is also active, use this context to refine district filters or to rank results.
