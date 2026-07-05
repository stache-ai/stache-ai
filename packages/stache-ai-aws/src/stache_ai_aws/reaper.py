"""Scheduled (EventBridge) reaper Lambda for the async ingestion tier.

Thin AWS entrypoint over the provider-agnostic
:func:`stache_ai.ingestion.reaper.reap_stuck_jobs`.
"""

from stache_ai.ingestion.reaper import reap_stuck_jobs


def lambda_handler(event, context):
    return {"reaped": reap_stuck_jobs()}
