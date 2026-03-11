# Target Criteria and Scoring System

## Minimum Score Threshold
Jobs must score **>= 70 out of 100** to proceed to resume tailoring and submission.

---

## Scoring Dimensions (total = 100 points)

### 1. Skills Match (max 35 points)
Compare JD requirements to master_resume.md Core Skills section.

| Points | Criteria |
|--------|---------|
| 30–35 | Strong overlap on primary stack: Python, ML modeling, SQL, cloud (AWS/GCP), plus 2+ of: RAG/LLM/LangChain, fraud detection, NLP, A/B testing, DBT/Airflow/Snowflake |
| 20–29 | Good match with minor gaps in secondary tools |
| 10–19 | Partial match — some missing core skills |
| 0–9   | Weak overlap — mostly adjacent domain |

**Keywords that boost score:** RAG, LLM, LangChain, LlamaIndex, agentic AI, MLOps, fraud detection, anomaly detection, NLP, A/B testing, causal inference, experimentation, DBT, Airflow, Snowflake, BigQuery, SageMaker

### 2. Seniority Fit (max 25 points)

| Points | Criteria |
|--------|---------|
| 20–25 | Explicitly "Senior", "Staff", "Lead", or "Principal" Data Scientist / ML Engineer |
| 15–19 | Mid-level with 3–5 years stated; no explicit senior tag but responsibilities match |
| 10–14 | Ambiguous seniority; role appears mid-level from description |
| 0–9   | Junior, entry-level, intern, or requires 8+ years experience |

### 3. Sponsorship / Long-Term Fit (max 25 points)

**Context:** Rohit is on STEM OPT, authorized to work in the US until Feb 2028 with no sponsorship needed.
After Feb 2028, will need H1B sponsorship. Prioritize companies with a strong H1B track record.

| Points | Criteria |
|--------|---------|
| 20–25 | JD states "visa sponsorship available" OR company has strong H1B filing history (verify via myvisajobs.com or web search) |
| 15–19 | No sponsorship info in JD; company is mid-to-large tech/SaaS with likely H1B capability |
| 10–14 | Small company (<50 employees), unknown H1B history |
| 5–9   | JD silent on sponsorship; company has no H1B history found |
| 0–4   | JD explicitly states "no sponsorship now or in the future" OR "must be US citizen/permanent resident" — hard skip |

**Research method:** Web search "[Company] H1B sponsorship myvisajobs" or "[Company] STEM OPT accepted". A company saying "no sponsorship" today is a hard skip — Rohit will need H1B by Feb 2028 and re-applying later wastes goodwill.

### 4. Role Type Alignment (max 15 points)

| Points | Criteria |
|--------|---------|
| 13–15 | Data Scientist at a SaaS or product company with clear ML/analytics ownership |
| 8–12  | ML Engineer or Applied Scientist with heavy data science overlap |
| 4–7   | Analytics Engineer or senior Data Analyst with DS-adjacent work |
| 0–3   | Business Analyst, BI Developer, or non-technical role |

---

## Hard Disqualifiers (score = 0, status = skipped immediately)

- Company on blocklist.md
- Already in applications_tracker.json with same company + similar role within 30 days
- Same job_id already in tracker
- Requires physical relocation (no remote/hybrid)
- Explicitly requires security clearance
- Requires 8+ years of experience
- Role posted more than **3 days ago** (stale — deprioritize recruiter pipeline)
- JD states "no visa sponsorship now or in the future" / "must be US citizen or permanent resident"
- Role type is internship, part-time, volunteer, or commission-only

---

## Preferred Company Signals (boost confidence, not score)
These don't change the numeric score but should be noted in the tracker and influence tie-breaking:

- Remote-first culture explicitly stated
- Series B or later (stable enough for H1B sponsorship pipeline)
- Team size 50–1000
- Product-led growth, data-driven culture
- Mentions "experimentation", "metrics ownership", "self-serve analytics"
- Has data science or ML team (not a generalist role)
