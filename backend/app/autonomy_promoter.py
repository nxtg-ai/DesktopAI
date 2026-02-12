"""Autonomy auto-promotion based on run success history.

Vision: "The agent earns its autonomy through demonstrated competence."
"""

_PROMOTION_CHAIN = ["supervised", "guided", "autonomous"]


class AutonomyPromoter:
    """Recommends an autonomy level based on recent run outcomes.

    Tracks consecutive successful runs and promotes through the chain:
    supervised -> guided -> autonomous. Any failure demotes to supervised.
    """

    def __init__(self, promote_threshold: int = 5) -> None:
        self._promote_threshold = promote_threshold

    def recommend(self, recent_runs: list[dict]) -> dict:
        """Analyze recent runs and return promotion recommendation.

        Args:
            recent_runs: List of dicts with keys 'autonomy_level' and 'status',
                        ordered most-recent-first. Only terminal runs
                        (completed/failed/cancelled).

        Returns:
            dict with recommended_level, current_level, consecutive_successes, reason.
        """
        if not recent_runs:
            return {
                "recommended_level": "supervised",
                "current_level": "supervised",
                "consecutive_successes": 0,
                "reason": "no run history",
            }

        current_level = recent_runs[0].get("autonomy_level", "supervised")

        # Check if most recent run was a failure
        most_recent_status = recent_runs[0].get("status", "")
        if most_recent_status != "completed":
            return {
                "recommended_level": "supervised",
                "current_level": current_level,
                "consecutive_successes": 0,
                "reason": "demoted after failure",
            }

        # Count consecutive successes at the current level
        consecutive = 0
        for run in recent_runs:
            if run.get("status") == "completed" and run.get("autonomy_level") == current_level:
                consecutive += 1
            else:
                break

        # Already at maximum level
        if current_level == "autonomous":
            return {
                "recommended_level": "autonomous",
                "current_level": "autonomous",
                "consecutive_successes": consecutive,
                "reason": "maximum autonomy level reached",
            }

        # Check if threshold met for promotion
        if consecutive >= self._promote_threshold:
            idx = _PROMOTION_CHAIN.index(current_level)
            next_level = _PROMOTION_CHAIN[idx + 1]
            return {
                "recommended_level": next_level,
                "current_level": current_level,
                "consecutive_successes": consecutive,
                "reason": f"promoted after {consecutive} consecutive successes",
            }

        # Stay at current level
        return {
            "recommended_level": current_level,
            "current_level": current_level,
            "consecutive_successes": consecutive,
            "reason": f"{consecutive}/{self._promote_threshold} successes, keep building trust",
        }
