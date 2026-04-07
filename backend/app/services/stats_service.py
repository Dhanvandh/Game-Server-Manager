from app.services.docker_service import stats_snapshot_for_profile


def stats_for_profile(profile) -> dict | None:
    return stats_snapshot_for_profile(profile)
