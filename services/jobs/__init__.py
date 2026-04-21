# =============================================================================
# RETRODB - Background Job Services Package
# =============================================================================
# Re-exports all public names for backward compatibility.
# Existing code using `from services.jobs import X` continues to work.
# =============================================================================

# Shared helpers
from services.jobs.base import (
    _get_conn,
    _commit_with_retry,
    _get_ra_credentials,
    _download_psn_trophy_image,
    persist_job_start,
    persist_job_progress,
    persist_job_complete,
    get_interrupted_jobs,
    mark_interrupted_job_failed,
    mark_jobs_interrupted,
    get_recoverable_jobs,
    dismiss_job,
    persist_job_queued,
    remove_queued_job,
)

# Job classes
from services.jobs.bulk_scrape import BulkScrapeJob
from services.jobs.ra_sync import RASyncJob
from services.jobs.ra_refresh import RARefreshJob
from services.jobs.psn_refresh import PSNRefreshJob
from services.jobs.museum import MuseumGenerateJob
from services.jobs.image_resize import ImageResizeJob
from services.jobs.platform_sync import SteamSyncJob, XboxSyncJob
from services.jobs.alt_titles_backfill import AltTitlesBackfillJob
from services.jobs.hltb_bulk import HLTBBulkLookupJob

# =============================================================================
# GLOBAL JOB INSTANCES
# =============================================================================
# These are the singleton instances used throughout the application

bulk_scrape_job = BulkScrapeJob()
ra_sync_job = RASyncJob()
ra_refresh_job = RARefreshJob()
psn_refresh_job = PSNRefreshJob()
museum_generate_job = MuseumGenerateJob()
image_resize_job = ImageResizeJob()
steam_sync_job = SteamSyncJob()
xbox_sync_job = XboxSyncJob()
alt_titles_backfill_job = AltTitlesBackfillJob()
hltb_bulk_job = HLTBBulkLookupJob()

__all__ = [
    # Helpers
    '_get_conn',
    '_commit_with_retry',
    '_get_ra_credentials',
    '_download_psn_trophy_image',
    'persist_job_start',
    'persist_job_progress',
    'persist_job_complete',
    'get_interrupted_jobs',
    'mark_interrupted_job_failed',
    'mark_jobs_interrupted',
    'get_recoverable_jobs',
    'dismiss_job',
    'persist_job_queued',
    'remove_queued_job',
    # Classes
    'BulkScrapeJob',
    'RASyncJob',
    'RARefreshJob',
    'PSNRefreshJob',
    'MuseumGenerateJob',
    'ImageResizeJob',
    'SteamSyncJob',
    'XboxSyncJob',
    'AltTitlesBackfillJob',
    'HLTBBulkLookupJob',
    # Singleton instances
    'bulk_scrape_job',
    'ra_sync_job',
    'ra_refresh_job',
    'psn_refresh_job',
    'museum_generate_job',
    'image_resize_job',
    'steam_sync_job',
    'xbox_sync_job',
    'alt_titles_backfill_job',
    'hltb_bulk_job',
]
