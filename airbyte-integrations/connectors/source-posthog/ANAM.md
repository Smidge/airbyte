# Anam PostHog connector

This fork keeps the existing seven streams and their schemas, and adds `experiments` and `experiment_results` to the same integration.

## Changes

- Follows the API's `next` URL, including when the server returns fewer records than requested. The upstream events manifest used offset pagination with a page size of 10,000 despite the API's datetime pagination. A regression test reproduces the skipped second page.
- Rejects repeated pagination cursors with an error instead of looping indefinitely. A failed events slice does not advance its saved timestamp.
- Respects `Retry-After` on throttled requests, with exponential backoff as a fallback.
- Requests 1,000 persons per page by default (configurable between 100 and 1,000), and reads persons last even for previously saved catalogs.
- Compares event timestamps as instants, preserving the existing per-project and legacy state formats.

Persons remains a full refresh. PostHog does not expose a reliable update cursor through the persons endpoint. Using creation time would miss profile edits and merges. Larger pages reduce request count, but do not eliminate the full scan or guarantee a particular sync duration.

## Experiments

The API key needs `experiment:read` in addition to the existing scopes.

`experiments` lists experiments across the projects visible to the key, then fetches each detail endpoint. It includes feature flags, variants/parameters, status, dates, conclusions, primary and secondary metric definitions, and shared metrics. Nested JSON is preserved.

`experiment_results` fetches `/experiments/{id}/metrics_recalculation/latest/`. It includes the saved run status, calculation timestamps, metric results/errors, and project/experiment IDs. A 404 means no saved run is available and emits no record. This stream never starts a recalculation; results can be stale or absent. Older PostHog servers without this endpoint will produce an empty results stream.

Both new streams use full refresh. Select Overwrite + Deduped in Airbyte for current snapshots, or Append if you intentionally want snapshots over time. Existing streams and destination settings remain unchanged.

API references: [experiments](https://posthog.com/docs/api/experiments), [persons](https://posthog.com/docs/api/persons).

## Build and test

The pinned CDK requires Python 3.10; Python 3.11 rejects its dataclass defaults.

```sh
python3.10 -m venv .venv
.venv/bin/pip install -r requirements.lock pytest requests-mock pytest-mock
.venv/bin/python -m pytest unit_tests

docker build -f Dockerfile.anam -t source-posthog:1.2.0-anam.1 .
docker run --rm source-posthog:1.2.0-anam.1 spec
```

The fork workflow runs unit tests and a Docker `spec` smoke test, then publishes an immutable commit tag to `ghcr.io/smidge/source-posthog`. Pin a commit tag or digest when installing the custom connector. A new GHCR package may require its visibility to be changed to public or registry credentials to be configured before Airbyte can pull it.

## Rollout

1. Save the current source definition/version, connection catalog, and state.
2. Install the tested image as a custom source and preserve the existing source configuration and connection state when switching the source definition. Do not create a new connection as a shortcut: it would start a new backfill.
3. Refresh the catalog, select the two new streams, and verify the API key's `experiment:read` scope.
4. Run a sync and inspect records, rate limits, state progression, and duration. The changes have automated coverage, but need a production-sized sync to measure improvement.
5. Roll back the source definition/image and remove the two new streams from the catalog if necessary.

The pagination fix cannot restore historical events already skipped by the old connector. Investigate date-window completeness and plan a targeted backfill separately; this change does not reset state or delete destination data.
