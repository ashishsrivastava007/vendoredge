# Pilot Demand Dashboard — Ready-Made Queries

**Why queries, not a webpage**: a new admin page showing everyone's collected email addresses would need real access control (login, permissions) to be safe — that's genuine new complexity and a new security surface. Running these yourself, in the same database console you already use, gets the same numbers with zero new exposure. Paste each into your Render Postgres console (or `psql`) whenever you want a check-in.

---

## 1. Overall pilot summary

```sql
SELECT
  (SELECT count(DISTINCT organisation_id) FROM commercial_decisions) AS total_users,
  (SELECT count(*) FROM commercial_decisions WHERE status = 'completed') AS cases_completed,
  (SELECT count(*) FROM interest_signals WHERE feature = 'notify_me_click') AS notify_clicks,
  (SELECT count(*) FROM pilot_leads) AS contact_details_collected;
```

## 2. Users who actually reached their pilot limit

```sql
SELECT organisation_id, count(*) AS cases_completed
FROM commercial_decisions
WHERE status = 'completed'
GROUP BY organisation_id
HAVING count(*) >= 3
ORDER BY cases_completed DESC;
```

## 3. Top requested next use cases — the real demand signal

```sql
SELECT next_case_category, count(*) AS requests
FROM pilot_leads
GROUP BY next_case_category
ORDER BY requests DESC;
```

## 4. Everyone who wants to be contacted (your actual follow-up list)

```sql
SELECT email, name, linkedin, next_case_category, comment, created_at
FROM pilot_leads
ORDER BY created_at DESC;
```

## 5. All "notify me" clicks, including ones who never finished the form

This is the real intent signal per the click-not-form principle — worth checking even for people who never submitted contact details, since the click alone still counts.

```sql
SELECT created_at FROM interest_signals
WHERE feature = 'notify_me_click'
ORDER BY created_at DESC;
```

Compare the count from query 5 against `pilot_leads` (query 1) to see how many real clicks turned into a completed contact — a real, honest conversion number, not a guess.

## 6. General open-ended feedback (the "Feedback" footer link)

Not tied to any specific question — genuinely useful for catching things you didn't think to ask about.

```sql
SELECT message, created_at FROM general_feedback
ORDER BY created_at DESC;
```

## 7. Extraction fallback frequency — where the model actually struggles

Every time a deterministic fallback catches something the model's own extraction missed (region, annual spend, requested percent, freight cost), it's logged with real, separate columns for fallback type, case type, and model version — not one flat count, so these can be cross-tabulated cleanly.

**Overall, ranked by frequency:**
```sql
SELECT fallback_type, count(*) AS times_fired
FROM fallback_events
GROUP BY fallback_type
ORDER BY times_fired DESC;
```

**By case type — this is the actionable one.** Shows things like "annual spend is almost never missed in quote comparisons, but frequently missed in price-increase cases" — a real, specific signal about where to focus next, not a vague sense that "the AI sometimes misses things."
```sql
SELECT content_type, fallback_type, count(*) AS times_fired
FROM fallback_events
GROUP BY content_type, fallback_type
ORDER BY content_type, times_fired DESC;
```

**By model version — shows directly when a model upgrade reduces or eliminates the need for a given fallback**, which is a real, concrete signal for when the fallback code itself can be simplified or removed, not a guess.
```sql
SELECT model_version, fallback_type, count(*) AS times_fired
FROM fallback_events
GROUP BY model_version, fallback_type
ORDER BY model_version, times_fired DESC;
```

A high count for one specific fallback, relative to total case volume, is a real, concrete signal — not "the AI seems to miss things sometimes," but "the model misses annual spend extraction in roughly X% of dense price-increase cases," which is something you can actually act on.
