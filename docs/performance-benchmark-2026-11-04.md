# Gnosis indexing latency experiment — 2026-11-04

## Method

The benchmark ran the existing Gnosis pipeline against public repository
snapshots from GitHub. Each snapshot was fetched once and reused for the
baseline and deferred runs so both variants processed identical files.
GitHub metadata, tree, and source acquisition time is reported separately.
There was one baseline and one deferred pipeline run per repository, so the
percentages are directional rather than statistically stable.

The only changed variable was whether the synchronous Code RAG phase built a
Chroma index. The normal path uses an in-memory Chroma client and a stub that
returns deterministic embedding vectors. **No NVIDIA embedding requests were
made.** The API queue, production App Service, browser polling, and frontend
render time were also not part of this measurement. This is a local pipeline
comparison, not a production latency promise.

## End-to-end pipeline comparison

Times are milliseconds. “Result time” includes pipeline work after the shared
GitHub snapshot has been fetched. The last column adds that one snapshot-fetch
time to estimate analysis plus download.

| Repository tier and sample | Gnosis mode | GitHub snapshot | Baseline result | Deferred result | Baseline Code RAG | Reduction | Baseline + fetch | Deferred + fetch |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Small — `psf/requests`, 63 selected (62 fetched) | Full | 1,187 | 2,681 | 384 | 2,043 | 85.7% | 3,868 | 1,571 |
| Medium — `psf/black`, 492 selected/fetched | Full (Warning) | 1,797 | 13,580 | 4,481 | 10,294 | 67.0% | 15,377 | 6,278 |
| Large — `numpy/numpy`, 1,003 selected (997 fetched) | Sampled, 300 analyzed | 4,046 | 23,110 | 9,433 | 12,346 | 59.2% | 27,156 | 13,479 |

The deferred result time was shorter in all three paired runs. The large case
still takes about 9.4 seconds after indexing is removed, with AST parsing the
largest remaining phase at 6.9 seconds. This suggests that indexing is the
first latency target for the tested workflow; parsing and complexity scoring
remain relevant for larger repositories.

## Phase timings

Each cell shows **baseline / deferred**, in milliseconds. GitHub network fetch
time is outside the phase table because the same fetched snapshot was reused.

| Phase | Small: requests | Medium: black | Large: numpy |
| --- | ---: | ---: | ---: |
| Metadata | 0 / 0 | 0 / 0 | 0 / 0 |
| Ingestion | 61 / 52 | 117 / 94 | 132 / 114 |
| AST Parser | 200 / 135 | 1,050 / 1,618 | 7,447 / 6,854 |
| Dependency Graph | 5 / 3 | 21 / 29 | 212 / 220 |
| Complexity Scorer | 250 / 186 | 1,785 / 2,683 | 2,222 / 2,202 |
| Code RAG | 2,043 / 0 | 10,294 / 0 | 12,346 / 0 |
| Explainability | 0 / 0 | 0 / 0 | 0 / 0 |
| Document Generator | 4 / 1 | 15 / 19 | 14 / 11 |
| Full local pipeline | 2,681 / 384 | 13,580 / 4,481 | 23,110 / 9,433 |

The Code RAG figures include chunk generation and Chroma inserts, but use
instant local embedding stubs. Production also waits for NVIDIA embedding
inference, so its synchronous Code RAG phase may take longer. The Chroma
benchmark used in-memory storage, which also differs from production storage.

## Feature check and experiment boundary

The API now defaults to `options.defer_code_index: true`; clients can set it to
false to request synchronous Code RAG. Deferred runs return
`code_index_status: "deferred"`. The onboarding document, graph, dependency
rows, complexity rows, analyzed-file list, and downloads continue to come from
the same analysis stages.

On-demand file explanations work without a Chroma collection by fetching the
exact Git blob recorded in the result. The fallback was checked with mocked
explanation generation and a live read-only fetch of a public Git blob. It adds
a GitHub blob request when an uncached file explanation is requested.

The backend has a semantic retrieval helper, but there is no current API or
frontend callsite for semantic search. A deferred job does not build vectors
for that helper; if semantic search becomes a user-facing feature, indexing
will need to happen on demand or in the background.

The paired figures above come from local runs, not production measurements. The
2026-11-05 live audit observed synchronous Code RAG on the deployed worker;
measure the deferred default again after the API rollout, including NVIDIA
embedding latency, persistent Chroma writes, queue wait, and host variance.
