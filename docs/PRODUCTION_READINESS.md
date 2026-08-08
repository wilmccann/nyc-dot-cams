# Production Readiness

`main.py` is a working prototype built in one evening. This doc is an
honest assessment of what stands between it and something you'd actually
run unattended in production — written from re-reading the real code, not
a generic checklist. Nothing here is implemented; it's a gap analysis to
inform prioritization.

## Summary

| Area | Current state | Risk if shipped as-is |
|---|---|---|
| [Cost controls](#cost-the-thinking-token-problem) | None — no budget, no rate limit | Unbounded spend, mostly on discarded reasoning tokens |
| [Throughput](#throughput--the-963-camera-problem) | Serial, one camera per 10s | "Real-time monitoring" is actually a ~3-hour-per-camera cadence |
| [Reliability](#reliability) | No retries, no timeouts, no circuit breaker | A single hung request can stall the whole loop indefinitely |
| [Observability](#observability) | `print()` to stdout only | No way to know it's degraded except watching the terminal |
| [Secrets](#secrets-in-production) | Local JSON key file + `.env` | Fine for a laptop, wrong shape for a deployed service |
| [Security: unescaped HTML](#unescaped-camera-names-in-generated-html) | Camera names spliced into HTML unescaped | Low real risk today, but a latent injection pattern |
| [Testing](#testing) | Zero automated tests | Every change is a manual re-run to verify |
| [Data persistence](#no-persistence) | Results printed and discarded | No history, no trend detection, no audit trail |
| [Packaging / CI](#packaging--cicd) | No Dockerfile, no CI | Can't deploy it anywhere without doing this first |

## Cost: the thinking-token problem

Captured from a real call (see [API_EXAMPLES.md](API_EXAMPLES.md#3-vertex-ai--clientmodelsgenerate_content)):

```
prompt_token_count: 274      (input: the image + instruction)
candidates_token_count: 12   (the actual one-sentence answer)
thoughts_token_count: 740    (internal reasoning — never seen or used)
total_token_count: 1026
```

Gemini 2.5 Flash pricing (Vertex AI, standard tier, checked 2026-08-08):
**$0.30 / 1M input tokens**, **$2.50 / 1M output tokens** — and Google
bills reasoning tokens at the *output* rate, lumped in as "response and
reasoning." So this one call cost approximately:

```
input:  274 tokens × $0.30 / 1,000,000 ≈ $0.00008
output: (12 + 740) tokens × $2.50 / 1,000,000 ≈ $0.00188
                                        total ≈ $0.002 per call
```

That looks negligible per call — until you account for the loop having no
pause and no daily cap. At a ~10s interval plus processing overhead
(call it 11s/cycle), that's roughly `86400 / 11 ≈ 7,850` Gemini calls per
day if left running continuously, or **~$15/day (~$460/month)** — for a
one-sentence description whose 740-token reasoning process is never read
by anything. (This is a rough estimate from one sample call; actual token
counts vary by scene complexity and description length. Roboflow's
serverless pricing is credit-based and not publicly itemized per call —
check current consumption in the Roboflow dashboard rather than assuming
it's free at volume.)

**None of this is enforced anywhere in the code.** There's no budget
alert, no daily call cap, no cheaper-model fallback, and no way for the
process itself to know it's spending money. Cheapest fixes, roughly in
order of effort: switch off "thinking" for this task (Gemini has a
`thinking_budget` / low-reasoning-effort setting for exactly this kind of
short factual task), add a max-calls-per-day guard, and set up a GCP
budget alert on the project.

## Throughput — the "963 camera" problem

`poll_camera` processes **one camera per `interval` seconds**, serially.
With ~963 online cameras and a 10s interval, a full rotation through every
camera takes on the order of `963 × 11s ≈ 2.9 hours`. If the goal is
"monitor traffic across the city," each individual camera is actually
being checked roughly once every three hours, not continuously — the demo
*looks* real-time because you're watching one camera update every 10
seconds, but that's one camera, not the fleet.

Fixes depend on the actual goal:
- **Fewer cameras, tighter loop** — if only a handful of corridors matter, drop the rotation entirely and poll just those cameras every 10s. Simplest fix, no architecture change.
- **Concurrency** — run N cameras in parallel (`asyncio` + `httpx`, or a thread pool) so a full pass takes `963/N × 11s` instead of `963 × 11s`. Raises the cost-per-minute proportionally (see above) and adds real concurrency bugs to worry about (shared `roboflow_client`/`model` objects, rate limits on the Vertex AI / Roboflow side).
- **Batch/async inference** — Vertex AI and Roboflow both offer batch APIs at lower per-token/per-call cost for non-interactive workloads; not a fit for "live rotating demo" but worth knowing about if this becomes a nightly batch job instead of a live loop.

## Reliability

- **No request timeouts.** Every `requests.get(...)` call (camera list,
  per-camera image) has no `timeout=` argument, meaning a stalled
  connection can hang that call — and therefore the entire loop —
  indefinitely. This is a one-line fix (`requests.get(url, timeout=10)`)
  with outsized impact.
- **No retries.** A single failed frame fetch, Gemini call, or Roboflow
  call just gets logged and skipped for that cycle — reasonable for a
  demo, but a transient network blip in production would mean silently
  missing that camera's data for a full rotation cycle rather than
  retrying once.
- **No circuit breaker.** If Vertex AI or Roboflow starts failing
  consistently (outage, expired credentials, quota exceeded), the loop
  keeps calling them every cycle forever rather than backing off or
  alerting.

## Observability

Everything is a `print()` to stdout with a bare `HH:MM:SS` timestamp — no
log levels, no structured fields (camera ID, latency, token counts), and
nothing machine-parseable. There's no metrics export (call latency, error
rate, cost per cycle) and nothing to page anyone if it silently stops
working. Minimum viable upgrade: switch `print` to the stdlib `logging`
module with structured fields, and export a couple of counters (calls
made, calls failed, estimated spend) somewhere queryable — even just
Cloud Logging if this stays on GCP.

## Secrets in production

Current setup — Application Default Credentials as a JSON file in
`~/keys/`, Roboflow key in a local `.env` — is appropriate for a laptop
and explicitly *not* how you'd run this as a deployed service. In
production this would move to:
- **Workload Identity** (if running on GKE/Cloud Run) instead of any
  credentials file at all — the compute identity gets Vertex AI access
  directly, no key to leak.
- **Secret Manager** for the Roboflow key, injected as an env var at
  deploy time, not committed to a `.env` file sitting on a filesystem.

## Unescaped camera names in generated HTML

`open_camera_viewer()` builds the page with an f-string and drops
`cam.get('name')` and other fields directly into HTML/JS without escaping:

```python
<h2>{cam.get('name')} ({cam.get('area')})</h2>
...
const cameras = {json.dumps(markers)};   # this part is safe — json.dumps escapes correctly
```

The `json.dumps(markers)` embedding is fine (JSON strings are properly
escaped). The plain f-string interpolations into HTML (page title, `<h2>`
text) are not — if a camera's `name` field ever contained something like
`</script><script>...`, it would be injected verbatim into the generated
page. Real risk today is low (NYC DOT is a single trusted, low-churn data
source, and the page is only ever opened locally by the user who generated
it, never served to anyone else) — but it's the kind of pattern that
becomes a real vulnerability the moment the data source is less trusted or
the generated page is ever served over a network instead of opened as a
local file. Fix is cheap: `html.escape()` any interpolated field.

## Testing

No automated tests exist. Nothing here needs live API access to test —
`filter_online_cameras()`'s string-comparison logic, `detect_vehicles()`'s
counting/grouping logic, and the HTML-generation logic in
`open_camera_viewer()` are all pure functions of their inputs and could be
unit tested against the captured examples in
[API_EXAMPLES.md](API_EXAMPLES.md) as fixtures — no Vertex AI or Roboflow
account needed to test them, which also means these tests would still work
after the current demo credentials expire.

## No persistence

Every Gemini description and Roboflow detection count is printed once and
discarded — there's no database, no file output, nothing queryable
afterward. A production version of "monitor traffic conditions" almost
certainly wants a history: write each cycle's result somewhere durable
(BigQuery for analytics, Cloud Storage for raw frames, Firestore for a
simple queryable log) so trends and anomalies can be detected after the
fact, not just narrated live in a terminal.

## Packaging / CI/CD

No `Dockerfile`, no GitHub Actions workflow, no linting or type-checking
gate. This project can't be deployed anywhere (Cloud Run included) until
it's containerized, and there's no automated check today that catches a
broken change before it's pushed. See
[design/local-deployment.md](design/local-deployment.md) for one possible
direction that would remove the *need* for a cloud deployment target
entirely, if that fits the project's actual goals better than
productionizing the cloud dependencies.

## Also worth knowing

- `pyproject.toml` lists `roboflow>=1.4.0` as a dependency, but `main.py`
  only imports `inference_sdk` — the `roboflow` package was used for
  one-off setup diagnostics, never by the app itself. Harmless, but dead
  weight in the dependency tree.
- No verification has been done on the licensing/terms of use for either
  the NYC DOT camera API or the public Roboflow model
  (`vehicle-detection-3mmwj/1`) beyond "it's publicly accessible." Worth
  reading both before any commercial/production use.
