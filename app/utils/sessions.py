from datetime import datetime
from zoneinfo import ZoneInfo

PST_TZ = ZoneInfo("America/Los_Angeles")

def infer_session_from_entry(entry_at: datetime) -> str:
    """
    Infer trading session based on entry time (taken_at).

    PST session rules (America/Los_Angeles):

      - London:  00:00  <= t < 06:30
      - NY:      06:30  <= t < 13:00
      - Break:   13:00  <= t < 15:00
      - Asian:   15:00  <= t <= 23:59
    """

    if entry_at.tzinfo is None:
        raise ValueError("entry_at must be timezone-aware (UTC recommended)")

    local = entry_at.astimezone(PST_TZ)
    h = local.hour
    m = local.minute

    def after_or_equal(hour: int, minute: int = 0) -> bool:
        return (h > hour) or (h == hour and m >= minute)

    def before(hour: int, minute: int = 0) -> bool:
        return (h < hour) or (h == hour and m < minute)

    # NY: 06:30 – 12:59
    if after_or_equal(6, 30) and before(13, 0):
        return "NY"

    # London: 00:00 – 06:29
    if after_or_equal(0, 0) and before(6, 30):
        return "London"

    # Break: 13:00 – 14:59
    if after_or_equal(13, 0) and before(15, 0):
        return "Break"

    # Asia: 15:00 – 23:59
    if after_or_equal(15, 0):
        return "Asia"

    # Should never hit this with the above ranges, but just in case:
    return "Break"