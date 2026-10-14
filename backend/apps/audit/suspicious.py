"""Per user-day activity features and DBSCAN detection of suspicious days.

Pure pandas/scikit-learn (no Django), so it can be tested without a database.
The ``detect_suspicious`` command loads the audit log, calls ``check`` and
stores each suspicious user-day as a SuspiciousAlert. An alert is only a
prompt for an administrator to look; nothing here blocks or changes an account.

Unlike ``activity_anomaly`` (one row per user over a long window), each row
here is one user on one day, so a single bad day stands out against that
role's normal days in the last ``history`` days.

Input frame (one row per audit entry, timestamps in local time):
    user_id, role, action, timestamp, patient_id (may be empty), ip_address (may be empty)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from ml.dbscan_audit import NOISE, run_dbscan

# How eps and min_samples were chosen
# ------------------------------------
# min_samples: the usual rule of thumb is 2 x the number of features, so 12
#   for the 6 features below. A day then needs 11 similar user-days around it
#   to count as normal, which 14 days of history gives easily even for a
#   handful of users, while a single odd day can never form its own cluster.
# eps: from the k-distance plot (python manage.py plot_suspicious), with
#   k = min_samples - 1. On the seeded normal activity (12 doctors, 15 days)
#   the sorted curve is flat: median 0.17, largest 0.82. The three demo attacks
#   sit at 3.6 (brute force), 8.6 (snooping) and 10.3 (export). 1.5 is about
#   twice the largest normal distance, so ordinary day-to-day variation is
#   never noise, and less than half the mildest attack. On real data, re-run
#   the plot after a few weeks and set eps just above where the curve bends.
EPS = 1.5
MIN_SAMPLES = 12
MIN_ROWS = 30              # fewer user-days than this and DBSCAN is not run

# StandardScaler divides by each feature's spread over the normal days. A
# feature that hardly varies (night_pct is 0 on almost every day) would make
# any change look enormous, so its scale is never below this (in log1p units,
# about a 65% change).
MIN_SCALE = 0.5

FEATURES = ['events', 'failed_logins', 'records_viewed', 'distinct_patients', 'distinct_ips', 'night_pct']
FAILED_LOGIN = 'LOGIN_FAILED'
RECORD_VIEWS = {'VIEW_PATIENT', 'SCAN_QR'}       # actions that open a patient's record
NIGHT_START, NIGHT_END = 22, 6                   # 22:00-06:00 local time
N_REASONS = 2

COLUMNS = ['user_id', 'role', 'action', 'timestamp', 'patient_id', 'ip_address']


def build_daily(events: pd.DataFrame) -> pd.DataFrame:
    """One row per (user_id, day): role plus the FEATURES. night_pct is 0-100."""
    if events is None or len(events) == 0:
        empty = pd.DataFrame(columns=['user_id', 'day', 'role', *FEATURES])
        return empty.astype({name: float for name in FEATURES})
    ev = pd.DataFrame(events)[COLUMNS].copy()
    ts = pd.to_datetime(ev['timestamp'])
    ev['day'] = ts.dt.date
    ev['failed'] = ev['action'] == FAILED_LOGIN
    ev['viewed'] = ev['action'].isin(RECORD_VIEWS)
    ev['night'] = (ts.dt.hour >= NIGHT_START) | (ts.dt.hour < NIGHT_END)

    grouped = ev.groupby(['user_id', 'day'])
    daily = pd.DataFrame({
        'role': grouped['role'].first(),
        'events': grouped.size(),
        'failed_logins': grouped['failed'].sum(),
        'records_viewed': grouped['viewed'].sum(),
        'distinct_patients': grouped['patient_id'].nunique(),     # empty patient_id is not counted
        'distinct_ips': grouped['ip_address'].nunique(),
        'night_pct': 100.0 * grouped['night'].mean(),
    })
    return daily.reset_index().astype({name: float for name in FEATURES})


@dataclass
class Check:
    role: str
    day: date
    n_rows: int                    # user-days for this role, history plus the checked day
    n_checked: int = 0             # user-days on the checked day
    n_clusters: int = 0
    skipped: bool = False
    message: str = ''
    alerts: list[dict] = field(default_factory=list)       # {'user_id', 'features', 'reason'}
    rows: pd.DataFrame | None = None                       # the role's rows, for plots
    X: np.ndarray | None = None                            # scaled features, row order of `rows`
    labels: np.ndarray | None = None


def scale(rows: pd.DataFrame, normal: np.ndarray) -> np.ndarray:
    """log1p, then StandardScaler fitted on the normal (history) rows only, with a floor on the scale."""
    logged = np.log1p(rows[FEATURES].to_numpy(dtype=float))
    fit_on = logged[normal] if normal.sum() >= 2 else logged
    scaler = StandardScaler().fit(fit_on)
    scaler.scale_ = np.maximum(scaler.scale_, MIN_SCALE)
    return scaler.transform(logged)


def reason(row: pd.Series, z: np.ndarray, history: pd.DataFrame) -> str:
    """The N_REASONS features furthest from normal, e.g. 'failed_logins = 25 (normal about 0)'."""
    parts = []
    for j in np.argsort(-np.abs(z))[:N_REASONS]:
        name = FEATURES[j]
        typical = history[name].median() if len(history) else 0.0
        unit = '%' if name == 'night_pct' else ''
        parts.append(f'{name} = {row[name]:.0f}{unit} (normal about {typical:.0f}{unit})')
    return '; '.join(parts)


def check(daily: pd.DataFrame, day: date, role: str,
          eps: float = EPS, min_samples: int = MIN_SAMPLES) -> Check:
    """Run DBSCAN over one role's user-days; each noise point on `day` becomes an alert.

    `daily` should hold the history days and `day` itself. The history rows
    define "normal" (the scaler is fitted on them and they fill the clusters);
    noise points on earlier days are ignored, as they belonged to earlier checks.
    """
    rows = daily[daily['role'] == role].reset_index(drop=True)
    on_day = (rows['day'] == day).to_numpy()
    result = Check(role, day, n_rows=len(rows), n_checked=int(on_day.sum()), rows=rows)
    if len(rows) < MIN_ROWS:
        result.skipped = True
        result.message = f'{len(rows)} user-days of activity; at least {MIN_ROWS} are needed.'
        return result

    X = scale(rows, ~on_day)
    labels = run_dbscan(X, eps=eps, min_samples=min_samples)
    result.X, result.labels = X, labels
    result.n_clusters = len(set(labels.tolist()) - {NOISE})

    history = rows[~on_day]
    for i in np.flatnonzero(on_day & (labels == NOISE)):
        row = rows.iloc[i]
        result.alerts.append({
            'user_id': _plain(row['user_id']),
            'features': {name: round(float(row[name]), 1) for name in FEATURES},
            'reason': reason(row, X[i], history),
        })
    return result


def _plain(value):
    return value.item() if hasattr(value, 'item') else value
