"""Automatic personality adaptation based on session energy.

Vision: "DesktopAI adapts to the energy of the session."
"""

_ENERGY_TO_MODE = {
    "calm": "copilot",
    "active": "assistant",
    "urgent": "operator",
}


class PersonalityAdapter:
    """Recommends a personality mode based on session activity patterns.

    Classifies the session into calm/active/urgent energy levels using
    app switch frequency and unique app count from the 30-minute session
    window, then maps to the corresponding personality mode.
    """

    def __init__(
        self,
        calm_max_switches: int = 3,
        active_max_switches: int = 15,
        calm_max_unique_apps: int = 2,
        active_max_unique_apps: int = 5,
    ) -> None:
        self._calm_max_switches = calm_max_switches
        self._active_max_switches = active_max_switches
        self._calm_max_unique_apps = calm_max_unique_apps
        self._active_max_unique_apps = active_max_unique_apps

    def classify_energy(self, session_summary: dict) -> str:
        """Classify session energy as 'calm', 'active', or 'urgent'."""
        switches = session_summary.get("app_switches", 0)
        unique = session_summary.get("unique_apps", 0)

        # Urgent: high switch rate OR many unique apps
        if switches > self._active_max_switches or unique > self._active_max_unique_apps:
            return "urgent"

        # Calm: low switch rate AND few unique apps
        if switches <= self._calm_max_switches and unique <= self._calm_max_unique_apps:
            return "calm"

        return "active"

    def recommend(self, session_summary: dict) -> str:
        """Return the recommended personality mode string."""
        energy = self.classify_energy(session_summary)
        return _ENERGY_TO_MODE[energy]
