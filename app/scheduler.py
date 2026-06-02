"""
Background scheduler — runs periodic maintenance jobs inside the FastAPI process.

Uses APScheduler's AsyncIOScheduler so jobs share the same event loop as the app.
Each worker process starts its own scheduler; since all jobs are idempotent this
causes no correctness problems, only a bit of extra load at scale.

Current jobs:
  eligibility_batch  — daily 02:00 UTC
      Re-evaluates pay-worthy eligibility for every ContributorProfile and
      persists the result. Same logic as POST /api/admin/contributor/profiles/evaluate-batch.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _run_eligibility_batch() -> None:
    from app.auth.models import User
    from app.contributors.models import ContributorProfile
    from app.contributors import service

    logger.info("scheduler: eligibility batch starting")
    try:
        profile_ids = await ContributorProfile.all().values_list("contributor_id", flat=True)
    except Exception as exc:
        logger.error("scheduler: failed to fetch contributor profiles: %s", exc)
        return

    eligible = ineligible = errors = 0
    for uid in profile_ids:
        try:
            user = await User.get_or_none(id=uid)
            if not user:
                continue
            result = await service.evaluate_eligibility(user)
            if result:
                eligible += 1
            else:
                ineligible += 1
        except Exception as exc:
            errors += 1
            logger.warning("scheduler: eligibility error for contributor=%s: %s", uid, exc)

    logger.info(
        "scheduler: eligibility batch done — eligible=%d ineligible=%d errors=%d total=%d",
        eligible, ineligible, errors, eligible + ineligible + errors,
    )


def start_scheduler() -> None:
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        _run_eligibility_batch,
        trigger="cron",
        hour=2,
        minute=0,
        id="eligibility_batch",
        replace_existing=True,
        misfire_grace_time=3600,  # fire up to 1h late if server was restarting
    )
    _scheduler.start()
    logger.info("scheduler: started — eligibility batch runs daily at 02:00 UTC")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler: stopped")
    _scheduler = None
