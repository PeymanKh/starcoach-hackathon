from rest_framework.throttling import AnonRateThrottle


class RunRateThrottle(AnonRateThrottle):
    """
    Every run costs OpenRouter money: a public demo link must not be abusable.

    The rate is REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["agent_runs"] in settings.
    """

    scope = "agent_runs"


class TranscribeRateThrottle(AnonRateThrottle):
    """
    The mic sends the growing recording every ~1.5 s, so this allows many small requests.

    The rate is REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["transcribe"] in settings.
    """

    scope = "transcribe"
