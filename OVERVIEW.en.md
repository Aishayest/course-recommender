# Course Recommender — how it works

A system that tells a Nazarbayev University student which courses to take next
semester. It runs entirely on documents the university publishes itself, plus
the student's own transcript.

This document covers why the system is built the way it is, where the data
comes from, what has been measured and how, and what is deliberately absent.

*(Русская версия: [OVERVIEW.md](OVERVIEW.md))*

## The problem

The handbook says what a student must complete, but registration does not give
everyone a seat: there are fewer places than applicants, and the queue depends
on the course, the major and the school. So the handbook plan and what you can
actually enrol in are two different things.

Hence the three questions the system answers:

1. **what is left before graduation** — from the real transcript, not from the
   assumption that the student followed the plan;
2. **what to take next** — accounting for prerequisites, registration priority
   and the odds of getting a seat;
3. **how it fits into a timetable** — a set of courses and sections for one
   semester with no time conflicts.

## Data sources

Everything is parsed from university publications. None of them was meant to be
machine-read, and each closes a gap the others leave open.

| Source | Format | What it gives | Volume |
|---|---|---|---|
| Undergraduate Academic Handbook | Canva deck | degree plans by semester, credit requirements by category, elective lists | 4 editions (2023–2026), 18–21 majors each |
| Course Requirements and Registration Priorities | Registrar PDF | real prerequisites (AND/OR trees with per-course grade thresholds), priority rounds | 12 documents, 11 terms, 1,191 courses |
| Term schedule (`school_schedule_by_term`) | Registrar PDF | sections, times, instructors, `Enr`/`Cap` | 14 snapshots, 11,382 sections |
| Undergraduate Grade Distribution | Institutional Research PDF | mean, median, grade distribution and withdrawals per section | 1,134 sections, 603 courses, 2 terms |
| Public course catalog | JSON endpoint of the Registrar site | course descriptions, breadth, academic level | 3,749 courses, 2,749 with a description |
| Student transcript | Registrar PDF | completed courses, grades, credits, admission year, major | uploaded by the student |

One useful find: **descriptions can be fetched programmatically**. The catalog
page is rendered by a script, but that script calls an ordinary JSON endpoint,
and the description comes back inside the search results — no per-course
request needed.

## The pipeline

Parsing is separated from use: it takes minutes and runs once, while the
application reads prepared caches in 0.6 seconds.

```
PDFs and Canva ──► parsing ──► caches (data/processed) ──► Program assembly ──► answer
```

### 1. Parsing the documents

**`data/canva.py`** — the handbook lives in Canva, but all its text is in the
page, inside a `<script>` with `window['bootstrap'] = JSON.parse(...)`. Text
blocks and tables come out of it together with their coordinates. Geometry is
not optional: the order of elements in the export is arbitrary, and a plan
table is tied to the "YEAR N" heading above it only by position.

**`data/handbook.py`** — degree plans: course, semester, minimum passing grade.
It handles alternatives ("A or B"), footnotes, and Cyrillic look-alikes of
Latin letters in grades.

**`data/requirements.py`** — requirement tables: how many credits of each
category are needed. Canva splits long tables into parts, and a continuation
has no header row — those are recognised by shape and inherit the previous
section.

**`data/electives.py`** — elective lists. Every major has its own: a CS
technical elective is any non-required CSCI course at 200-level or above plus
16 courses from other departments; Robotics has a closed list of six ROBT
courses; Mathematics means any MATH course at 300-level or above. The handbook
states these three different ways at once — as a rule, as a list of codes, and
as a list of bare titles.

**`data/registration.py`** — prerequisites as an AND/OR tree with parentheses
and a grade threshold per course, plus priority rounds. This is also where
school renamings are handled: SEDS split into SCAI and SoE, and some SMG
departments moved to SoE. Without that, a CS student would have priority on 18
courses instead of 231 in the Spring 2025 document.

**`data/schedule.py`**, **`data/grades.py`**, **`data/descriptions.py`**,
**`data/transcripts.py`** — schedules, grade reports, the description catalog,
the transcript.

### 2. Building the catalog

**`data/catalog.py`** merges 12 registration documents into one catalog. Each
document covers a single term, so an autumn file says nothing about spring
courses; together they yield 1,191 courses, of which **446 are taught only in
spring**. Prerequisites and priorities are stored per term: both change between
registrations, and passing last year's off as this year's would be a lie.

### 3. Assembling a major

**`data/assemble.py`** builds a `Program` — course catalog, requirements, plan
slots — for an "admission year + major" pair. The year is part of the key: each
cohort has its own handbook.

### 4. Preparing caches

**`data/prepare.py`** — one command parses everything into `data/processed`.
Every layer is optional: what is missing is simply missing, and the system runs
without it, just without the corresponding evidence.

## Three layers

### Constraints — deterministic, not ML

Prerequisites, credits, category quotas. The model only ranks what passes this
filter. Condition evaluation is three-valued: a transcript says nothing about
IELTS scores or Kazakh proficiency, and returning "unknown" is more honest than
declaring the course unavailable.

### Availability — a trained model

The chance of getting a seat splits in two:

```
P(seat) = P(course does not fill) + P(fills) × P(seat | filled, priority round)
             ↑ trained on history                  ↑ an assumption
```

The split matters: the first part is measurable, the second cannot be derived
from the available data at all. `Enr` and `Cap` describe demand for the course
as a whole; who actually got a seat is nowhere in the exports.

### Relevance — nothing is trained

A course is relevant if it resembles something the student already did well in:
the nearest completed course is found, and its grade sets the weight. Nothing
is trained on our data — a ready-made model turns text into a vector, so the
layer works from a single transcript.

## The availability model

It predicts whether a course will fill up. Training and validation are
chronological: the model learns from what was known before the target term and
predicts that term.

There are two baselines, both fair: the rule the system previously used ("it
filled up before, so it will fill up again"), and the same rule expressed as a
probability — without the second, the model would win on calibration for free.

| validation term | model | baseline: ever filled up | baseline: mean fill ≥ 100% |
|---|---|---|---|
| Fall 2025 (n=153) | **0.759 / 0.143** | 0.711 / 0.261 | 0.728 / 0.235 |
| Spring 2026 (n=363) | **0.795 / 0.159** | 0.729 / 0.242 | 0.727 / 0.209 |
| Fall 2026 (n=374) | **0.760 / 0.214** | 0.694 / 0.289 | 0.663 / 0.294 |

Each cell is AUC / Brier. Both baselines are shown: their strengths differ, and
taking the better number from each one per metric would mean comparing the model
against an opponent that does not exist. It wins on all three splits, on both
metrics, against both baselines.

The model is deliberately small — logistic regression on two history features
(mean fill rate and "did it ever fill up"). That is not thrift but a result:
gradient boosting on fourteen features wins on one term and loses clearly on
another, where there are fewer training rows. On 1,808 course-term observations
a complex model is unstable.

Coefficients are stored as JSON rather than a pickle: a model made of three
numbers should be readable by eye.

## The relevance layer

TF-IDF over titles and descriptions is the baseline method: no dependencies,
and explainable word by word. Embeddings understand meaning rather than words,
and it shows — 31% of courses have no description at all, so TF-IDF has nothing
to say about them, while the model understands them from the title.

One detail without which the model is useless: it places any two texts close
together. The cosine between a random pair of courses is **0.777 with a spread
of 0.045**. At that baseline the difference between machine learning and ethics
disappears, and in the product "weight × similarity" the grade drowns out the
content. Subtracting the catalog mean gives **−0.006 with a spread of 0.183**.

A centroid profile over everything completed was tried first: averaging thirty
courses produces a blurred portrait of "the average student in this major", and
every candidate ends up equally far from it — a spread of 0.03 against 0.12 for
nearest-course similarity.

## The product

**Audit** (`audit.py`) — what is left: credits, unfinished required courses,
courses passed below the minimum grade, courses in progress, open plan
positions with their status. Each completed course is assigned to whatever it
closes; the most constrained positions are filled first.

**Recommendation** (`recommend.py`) — ranking by a weighted sum: need 0.6, seat
chance 0.4, content fit 0.2, grades 0.0. Every course shows what its score is
made of and which components are known at all.

**Semester plan** (`plan.py`) — search with pruning: a set of courses and
lecture sections that fits the credit target, has no time conflicts, and takes
no more courses than there are open positions. Sections are not picked at
random: when a course has several lectures, they follow one syllabus for the
same credits, and the only differences are time and instructor.

**Course statistics** — mean grade, distribution, withdrawals and the spread
between sections. The spread is computed within a term: across terms the
student body changes, while within one term the sections follow one syllabus.

**Interface** (`web/`) — FastAPI with server-side rendering. The student
uploads a transcript; everything else is read from it. The transcript never
touches disk: the parsed result lives in process memory and the browser only
gets a random key.

## What has been measured

| | |
|---|---|
| prerequisites known | 402 of 434 plan courses in the 2026 cohort (93%) |
| elective positions | 62 with a list, 32 "any course", 11 unanswered, out of 105 |
| availability model | AUC 0.76–0.80 against 0.69–0.73 for the best baseline, three held-out terms |
| transcript parsing | across 8 files the credit total matched the transcript's own line everywhere except a partial file — which is detected and refused |
| audit | 198 of 240 ECTS matched the official degree audit sheet to the credit |
| spread between sections | median 0.25 grade points, above 0.5 for 22% of courses, up to 1.8 for WCS 150 |

That last line is the most substantive finding in the project. The grade report
carries no instructor names, only section numbers; names are recovered by
joining it with the schedule for the same term. It turns out that **which
section you land in affects your grade more than the course level does**:
0.15 grade points between 100-level and 400-level courses, against up to 1.8
between sections of one course.

## Principles

**No number without a source.** Every figure is shown with where it came from:
"3 terms of history", "n=45", "has not taught it before", "the handbook does
not say what closes this position". Where there is no data, that is what is
written — zero or an average is not substituted.

**Three visual registers** in the interface: a solid pill is a fact from the
data, a dashed blue one is a model estimate, hatching in italics means no data.

**"Unverified" ≠ "not completed".** A position the handbook does not define is
marked separately and counted neither as closed nor as open.

**A baseline is mandatory.** Every trained model is compared against the rule
it replaces. If it does not beat it, it is not needed.

## What is absent, and why

**How seats are distributed within a priority round** is set by hand. `Enr` and
`Cap` describe demand for the course as a whole; who got a seat is not in the
exports, and no model can recover it. Student-level data would be required.

**A reranker trained on actual choices** — one transcript is not a sample, and
within it you cannot tell what the student chose from what the plan imposed.

**Validation of the relevance layer** — there is no ground truth for "is this a
good recommendation" until you can see what students actually pick. Hence the
small weight, and the explanation always names what the course resembles.

**How fast seats disappear during registration week** — the exports show the
state before and after, but not the dynamics. This is the only thing that
cannot be recovered retroactively.

**11 elective positions** remain unanswered: GSB and Eurasian Business refer to
an "Approved List" that the handbook does not reproduce, and two Biology major
electives are not described at all.

## Stack

**Python 3.12.** `pdfplumber` for PDF parsing; `scikit-learn` for TF-IDF and
logistic regression; `numpy` for vectors; `FastAPI` + `Jinja2` + `uvicorn` for
the interface. Embeddings (`sentence-transformers`,
`intfloat/multilingual-e5-base`) sit behind a separate extra because they pull
in torch.

No dependency that has nothing to do: `pandas` and `lightgbm` were declared and
then removed once it turned out nothing imported them.

**8,788 lines of code, 3,969 lines of tests, 368 tests.** The interface ships
either as a running application (Docker, ~200 MB of memory) or as a static
snapshot of the pages — where even the weight sliders recompute the score,
because the components are already computed and sit in the markup.
