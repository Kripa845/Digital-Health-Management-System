from datetime import datetime, time


def parse_window(slot) -> tuple[time, time] | None:
    """(start, end) of a schedule entry such as "09:00-17:00"; None for "closed", empty or unreadable."""
    text = str(slot or '').strip().lower()
    if not text or text == 'closed' or '-' not in text:
        return None
    try:
        start, end = (datetime.strptime(part.strip(), '%H:%M').time() for part in text.split('-', 1))
    except ValueError:
        return None
    return (start, end) if end > start else None
