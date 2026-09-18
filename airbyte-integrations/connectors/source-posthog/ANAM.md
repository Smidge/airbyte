# Anam PostHog connector

This fork keeps the existing seven streams and their schemas, and adds `experiments` and `experiment_results` to the same integration.

## Changes

- Reads events in ascending timestamp/UUID order with 1,000 records per request, preserving the REST event payload. Subsequent pages use a HogQL property predicate over both fields, avoiding the legacy timestamp-only `next` URL. Pagination continues to an empty page even if the server returns a short page or `next: null`.
- Validates event ordering, IDs, timestamps, and slice bounds before emitting each page. A failed events slice does not advance its saved timestamp. Other streams follow their `next` URL and reject repeated cursors.
- Includes the start of each time slice and replays the saved timestamp on restart. Optional `events_lookback_hours` replays up to seven days for late arrivals, defaulting to zero. Use ID deduplication when enabling replay; append-only destinations retain duplicates. Finite lookback cannot recover arbitrarily late events.
- Respects `Retry-After` on throttled requests, with exponential backoff as a fallback.
- Requests 1,000 persons per page by default (configurable between 100 and 1,000), and reads persons last even for previously saved catalogs.
- Compares event timestamps as instants, preserving the existing per-project and legacy state formats.

Persons remains a full refresh. PostHog does not expose a reliable update cursor through the persons endpoint. Using creation time would miss profile edits and merges. Larger pages reduce request count, but do not eliminate the full scan or guarantee a particular sync duration.

## Experiments

The API key needs `experiment:read` in addition to the existing scopes.

`experiments` lists both archived and unarchived experiments across the projects visible to the key, then fetches each detail endpoint. It includes feature flags, variants/parameters, status, dates, conclusions, primary and secondary metric definitions, and shared metrics. Nested JSON is preserved.

`experiment_results` fetches `/experiments/{id}/metrics_recalculation/latest/`. It includes the saved run status, calculation timestamps, metric results/errors, and project/experiment IDs. A 404 means no saved run is available and emits no record. This stream never starts a recalculation; results can be stale or absent. Older PostHog servers without this endpoint will produce an empty results stream.

Both new streams use full refresh. Select Overwrite + Deduped in Airbyte for current snapshots, or Append if you intentionally want snapshots over time. Existing streams and destination settings remain unchanged.

API references: [experiments](https://posthog.com/docs/api/experiments), [persons](https://posthog.com/docs/api/persons).

## Build and test

The pinned CDK requires Python 3.10; Python 3.11 rejects its dataclass defaults.

```sh
python3.10 -m venv .venv
.venv/bin/pip install -r requirements.lock 'pytest<9' requests-mock pytest-mock
.venv/bin/python -m pytest -c /dev/null -p no:cacheprovider unit_tests

docker build -f Dockerfile.anam -t source-posthog:1.2.0-anam.1 .
docker run --rm source-posthog:1.2.0-anam.1 spec
```

The fork workflow runs unit tests and a Docker `spec` smoke test, then publishes an immutable commit tag to `ghcr.io/smidge/source-posthog`. Pin a commit tag or digest when installing the custom connector. A new GHCR package may require its visibility to be changed to public or registry credentials to be configured before Airbyte can pull it.

## Rollout

1. Save the current source definition/version, connection catalog, and state.
2. Install the tested image as a custom source. First run a manual trial with a separate destination table prefix, including the two new streams. Verify the API key's `experiment:read` scope.
3. Airbyte's supported update APIs cannot change a source's definition or a connection's source ID. If a replacement connection is needed, preserve the original source configuration, destination, table names, catalog settings, and schedule. Create it paused and copy the saved event state before its first sync. An unseeded connection would restart the historical backfill.
4. Pause the original connection and wait for or cancel its active job before taking the final state snapshot and enabling the replacement. Keep the original connection and source for rollback, especially if the replacement uses an existing secret reference. Never run both connections against the same destination tables at once.
5. Inspect records, rate limits, state progression, and duration. To roll back, stop the replacement before re-enabling the original. Replaying from the original event checkpoint requires ID deduplication.

Copying source state alone is not sufficient for a same-table replacement. Airbyte 2.0 assigns generations per connection. BigQuery destination 3.0.17 can merge an `overwrite_dedup` stream instead of replacing its snapshot when the existing table's generation is newer than the replacement connection's generation. Review and migrate destination generation bookkeeping before switching; otherwise deleted persons or metadata may remain in the destination. Do not reset or rewrite production tables without a tested migration and recoverable backups.

The pagination fix cannot restore historical events already skipped by the old connector. Investigate date-window completeness and plan a targeted backfill separately; this change does not reset state or delete destination data.

## Events API compatibility

This is a compatibility fix for the deprecated REST events endpoint. It requires a PostHog server whose events query orders equal timestamps by UUID, as verified in [PostHog source commit 570e009](https://github.com/PostHog/posthog/blob/570e00941e3ba4cc17dfb3c9bdc5e3de353c587f/posthog/hogql_queries/events_query_runner.py). It retains the existing seven stream schemas and does not introduce export storage or per-row export billing. It does not call the query endpoint for bulk exports.

PostHog recommends [batch exports](https://posthog.com/docs/cdp/batch-exports) for recurring event/person exports. The [REST endpoint](https://posthog.com/docs/api/events) may be removed; this fork does not change that provider support status. Batch exports would require storage configuration and a separate compatibility design for person records. A live contract probe and measured trial are required before deployment.
