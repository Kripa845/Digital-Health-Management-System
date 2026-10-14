"""Plain-language wording for ActivityFlag reasons, for the admin review table.

Built when a flag is read, from the numbers stored with each reason (feature,
value, median, z), so old flags get the new wording without a migration. This
only explains a flag; detection lives in activity_anomaly and is not changed here.
"""
from __future__ import annotations

import math

# Severity from the largest |robust z| among a flag's reasons: >= HIGH is High,
# >= MEDIUM is Medium, anything less is Low. MEDIUM matches activity_anomaly.Z_THRESHOLD.
SEVERITY_THRESHOLDS = {'HIGH': 6.0, 'MEDIUM': 3.5}

ROLE_PLURALS = {'DOCTOR': 'doctors', 'PATIENT': 'patients', 'ADMIN': 'administrators'}

# metric: (singular, plural) sentence for the user's own count, and how "most others" is phrased:
# 'typical' takes the rounded median, 'none' is used when the median is 0.
METRICS = {
    'total_actions': {
        'did': ('{n} action in total.', '{n} actions in total.'),
        'typical': 'did {m}', 'none': 'had none',
    },
    'distinct_patients': {
        'did': ('Opened {n} patient record.', 'Opened {n} patient records.'),
        'typical': 'opened {m}', 'none': 'opened none',
    },
    'failed_logins': {
        'did': ('{n} failed login attempt.', '{n} failed login attempts.'),
        'typical': 'had {m}', 'none': 'had none',
    },
    'off_hours_actions': {
        'did': ('{n} action at unusual hours (such as at night).', '{n} actions at unusual hours (such as at night).'),
        'typical': 'had {m}', 'none': 'had none',
    },
    'active_days': {
        'did': ('Active on {n} day.', 'Active on {n} different days.'),
        'typical': 'were active on {m}', 'none': 'had no active days',
    },
    'access_requests': {
        'did': ('{n} request to see patient records.', '{n} requests to see patient records.'),
        'typical': 'made {m}', 'none': 'made none',
    },
    'access_denied': {
        'did': ('{n} access request declined.', '{n} access requests declined.'),
        'typical': 'had {m}', 'none': 'had none',
    },
}


def round_half_up(x: float) -> int:
    """5.5 -> 6 (Python's round() would give 6 here but 4 for 4.5)."""
    return math.floor(x + 0.5)


def typical(metric: str, median: float, role: str) -> str:
    """'Most doctors had none.', 'Most patients did about 6.' ('about' only when the median was rounded)."""
    spec = METRICS[metric]
    who = f"Most {ROLE_PLURALS.get(role, 'users')}"
    if median == 0:
        return f"{who} {spec['none']}."
    m = round_half_up(median)
    amount = str(m) if m == median else f'about {m}'
    return f"{who} {spec['typical'].format(m=amount)}."


def severity(z: float) -> str:
    z = abs(z)
    if z >= SEVERITY_THRESHOLDS['HIGH']:
        return 'HIGH'
    if z >= SEVERITY_THRESHOLDS['MEDIUM']:
        return 'MEDIUM'
    return 'LOW'


def describe(reason: dict, role: str) -> dict:
    """{metric, text, detail} for one stored reason; text is plain, detail keeps the numbers."""
    metric = reason.get('feature', '')
    if metric not in METRICS or not {'value', 'median', 'z'} <= reason.keys():
        return {'metric': metric, 'text': reason.get('text', metric), 'detail': reason.get('text', '')}
    value, median, z = reason['value'], reason['median'], reason['z']
    singular, plural = METRICS[metric]['did']
    did = (singular if value == 1 else plural).format(n=value)
    return {
        'metric': metric,
        'text': f'{did} {typical(metric, median, role)}',
        'detail': f'{metric} = {value}, role median {median:g}, robust z {z:+.1f}',
    }


def flag_severity(reasons: list[dict]) -> str:
    """Severity of the strongest reason; LOW when there are no numbers to go on."""
    zs = [abs(r['z']) for r in reasons if isinstance(r.get('z'), (int, float))]
    return severity(max(zs)) if zs else 'LOW'
