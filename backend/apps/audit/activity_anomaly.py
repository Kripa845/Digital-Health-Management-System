"""Per-user activity features and DBSCAN outlier detection for admin review.

Pure pandas/numpy (no Django), so it can be tested without a database. The
``flag_activity_anomalies`` command loads the audit log, calls these functions
and stores the result as ActivityFlag rows. A flag is only a prompt for an
administrator to look; nothing here blocks or changes an account.

Input frames:
    events    user_id, role, action, timestamp (local time), patient_id (may be empty)
    requests  user_id, role, status   (one row per AccessRequest, by the requesting doctor)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ml.dbscan_audit import NOISE, core_mask, k_distance, kth_neighbour_distance, gap_eps, run_dbscan

FEATURES = [
    'total_actions', 'distinct_patients', 'failed_logins', 'off_hours_actions',
    'active_days', 'access_requests', 'access_denied',
]
FAILED_LOGIN = 'LOGIN_FAILED'
DECLINED = 'DECLINED'
OFF_HOURS_START, OFF_HOURS_END = 22, 6     # 22:00-06:00 local time
Z_THRESHOLD = 3.5                         # robust z above this is called out as a reason
MAX_REASONS = 3
MAD_SCALE = 0.6745                        # makes MAD comparable to a standard deviation
MEAN_AD_SCALE = 1.2533                    # same, for the mean absolute deviation fallback
MIN_GROUP = 6                             # fewest users in a role DBSCAN is run on (min_samples 3)


def build_features(events: pd.DataFrame, requests: pd.DataFrame) -> pd.DataFrame:
    """One row per user (index user_id): role plus the FEATURES counts."""
    events = _frame(events, ['user_id', 'role', 'action', 'timestamp', 'patient_id'])
    requests = _frame(requests, ['user_id', 'role', 'status'])

    failed = events['action'] == FAILED_LOGIN
    acts = events[~failed]
    hours = pd.to_datetime(acts['timestamp']).dt.hour
    off_hours = (hours >= OFF_HOURS_START) | (hours < OFF_HOURS_END)

    by_user = acts.groupby('user_id')
    feats = pd.DataFrame({
        'total_actions': by_user.size(),
        'distinct_patients': by_user['patient_id'].nunique(),
        'off_hours_actions': off_hours.groupby(acts['user_id']).sum(),
        'active_days': pd.to_datetime(acts['timestamp']).dt.date.groupby(acts['user_id']).nunique(),
    })
    feats = feats.join(events[failed].groupby('user_id').size().rename('failed_logins'), how='outer')
    feats = feats.join(requests.groupby('user_id').size().rename('access_requests'), how='outer')
    feats = feats.join(
        requests[requests['status'] == DECLINED].groupby('user_id').size().rename('access_denied'), how='outer')

    roles = pd.concat([events[['user_id', 'role']], requests[['user_id', 'role']]]).drop_duplicates('user_id')
    feats = feats.reindex(columns=FEATURES).fillna(0).astype(int)
    feats.insert(0, 'role', roles.set_index('user_id')['role'].reindex(feats.index))
    feats.index.name = 'user_id'
    return feats


def robust_z(values: pd.Series) -> pd.Series:
    """(x - median) / MAD, scaled to a standard deviation; 0 when the feature has no spread."""
    values = values.astype(float)
    median = values.median()
    mad = (values - median).abs().median()
    if mad > 0:
        return MAD_SCALE * (values - median) / mad
    mean_ad = (values - median).abs().mean()   # most users share one value (e.g. 0 failed logins)
    if mean_ad > 0:
        return (values - median) / (MEAN_AD_SCALE * mean_ad)
    return pd.Series(0.0, index=values.index)


def explain(group: pd.DataFrame, user_id) -> list[dict]:
    """Why a user stands out from their role group: the features with the largest robust z.

    Features with |z| >= Z_THRESHOLD are listed (most extreme first); if none is
    that far out, the single most unusual feature is given so a flag always has a reason.
    """
    rows = []
    for name in FEATURES:
        z = robust_z(group[name])
        rows.append({
            'feature': name,
            'value': int(group.at[user_id, name]),
            'median': float(group[name].median()),
            'z': round(float(z.at[user_id]), 2),
        })
    rows.sort(key=lambda r: abs(r['z']), reverse=True)
    picked = [r for r in rows if abs(r['z']) >= Z_THRESHOLD][:MAX_REASONS] or rows[:1]
    for r in picked:
        direction = 'above' if r['z'] >= 0 else 'below'
        r['text'] = (f"{r['feature']} = {r['value']} is far {direction} the role median "
                     f"of {r['median']:g} (robust z {r['z']:+.1f})")
    return picked


@dataclass
class Detection:
    role: str
    n_users: int
    skipped: bool = False
    message: str = ''
    flags: list[dict] = field(default_factory=list)   # {'user_id', 'features', 'reasons'}


def min_users(min_samples: int) -> int:
    """Users needed to run DBSCAN: twice min_samples, so at least two groups could form, and never fewer than MIN_GROUP."""
    return max(2 * min_samples, MIN_GROUP)


def _too_few(n: int, min_samples: int) -> str:
    message = f'{n} users with activity; min_samples {min_samples} needs at least {min_users(min_samples)}.'
    if n >= MIN_GROUP:
        message += f' Lower min_samples to {n // 2} or less to run DBSCAN on these users.'
    return message


def detect(feats: pd.DataFrame, role: str, eps: float, min_samples: int) -> Detection:
    """Run DBSCAN over one role's users; every noise point becomes a flag with reasons."""
    group = feats[feats['role'] == role]
    if len(group) < min_users(min_samples):
        return Detection(role, len(group), skipped=True, message=_too_few(len(group), min_samples))
    labels = run_dbscan(_scaled(group), eps=eps, min_samples=min_samples)
    flags = [
        {
            'user_id': user_id,
            'features': {name: int(group.at[user_id, name]) for name in FEATURES},
            'reasons': explain(group, user_id),
        }
        for user_id in group.index[labels == NOISE]
    ]
    return Detection(role, len(group), flags=flags)


def suggest_min_samples(n_users: int) -> int:
    """Rule of thumb for small groups: about sqrt(n), at least 3, and at most n/2 so DBSCAN still runs.

    15 users -> 4, 22 -> 5, 43 -> 7. Too small and two similar outliers can
    form their own "cluster"; too large and ordinary users become noise.
    """
    return int(max(3, min(round(np.sqrt(n_users)), n_users // 2)))


def suggest_params(X: np.ndarray) -> dict | None:
    """Suggested min_samples for this many users, and eps inside the jump of its k-distance curve."""
    min_samples = suggest_min_samples(len(X))
    eps = gap_eps(k_distance(X, min_samples - 1))
    if eps is None:
        return None
    return {'min_samples': min_samples, 'eps': round(eps, 2)}


def auto_params(feats: pd.DataFrame, role: str, fallback_eps: float) -> tuple[float, int]:
    """(eps, min_samples) for a role without asking the admin: the suggested values for this many users.

    When the k-distance curve has no clear jump (or there are too few users to
    run), min_samples still follows the group size and eps falls back to the saved setting.
    """
    group = feats[feats['role'] == role]
    min_samples = suggest_min_samples(len(group))
    if len(group) < MIN_GROUP:
        return fallback_eps, min_samples
    suggested = suggest_params(_scaled(group))
    if suggested is None:
        return fallback_eps, min_samples
    return max(suggested['eps'], 0.01), suggested['min_samples']


def kdist_percentiles(feats: pd.DataFrame, role: str, min_samples: int,
                      percentiles=(50, 75, 90, 95, 99)) -> dict[int, float]:
    """Percentiles of the (min_samples - 1)-NN distance for a role, to help choose eps."""
    group = feats[feats['role'] == role]
    dist = k_distance(_scaled(group), min_samples - 1) if len(group) else np.zeros(0)
    if dist.size == 0:
        return {}
    return {p: round(float(np.percentile(dist, p)), 3) for p in percentiles}


def analyse(feats: pd.DataFrame, role: str, eps: float, min_samples: int) -> dict:
    """Every intermediate step of the detection for one role, for the admin's analysis page.

    Same pipeline as ``detect`` (log1p -> scale -> DBSCAN -> robust z), plus the
    k-distance curve, a suggested eps (inside its largest jump) and a 2-D PCA projection for
    plotting. The projection is only a picture: DBSCAN runs on all features.
    When the role has too few users, DBSCAN is not run but the other steps are.
    """
    group = feats[feats['role'] == role]
    needed = min_users(min_samples)
    k = min_samples - 1
    result = {
        'role': role, 'n_users': len(group), 'min_users': needed, 'eps': eps,
        'min_samples': min_samples, 'k': k, 'features': FEATURES,
        'skipped': len(group) < needed, 'message': '', 'scaling': {}, 'kdist_sorted': [],
        'suggested_eps': None, 'suggested': None, 'explained_variance': [0.0, 0.0], 'n_clusters': 0,
        'counts': {'core': 0, 'border': 0, 'noise': 0}, 'users': [],
    }
    if result['skipped']:
        result['message'] = _too_few(len(group), min_samples)
    if group.empty:
        return result

    logged = np.log1p(group[FEATURES].to_numpy(dtype=float))
    X = _scaled(group)
    mean, std = logged.mean(axis=0), logged.std(axis=0)
    result['scaling'] = {name: {'mean': round(float(m), 4), 'sd': round(float(s), 4)}
                         for name, m, s in zip(FEATURES, mean, std)}

    kdist = kth_neighbour_distance(X, k)
    result['kdist_sorted'] = [round(float(d), 4) for d in np.sort(kdist)]
    suggested = gap_eps(np.sort(kdist))
    result['suggested_eps'] = round(suggested, 2) if suggested is not None else None
    result['suggested'] = suggest_params(X)

    coords, explained = project_2d(X)
    result['explained_variance'] = explained

    if result['skipped']:
        labels = np.full(len(group), None, dtype=object)
        kinds = [None] * len(group)
    else:
        labels = run_dbscan(X, eps=eps, min_samples=min_samples)
        core = core_mask(X, eps, min_samples)
        kinds = ['noise' if lab == NOISE else 'core' if c else 'border' for lab, c in zip(labels, core)]
        result['n_clusters'] = int(len(set(labels.tolist()) - {NOISE}))
        result['counts'] = {kind: kinds.count(kind) for kind in ('core', 'border', 'noise')}

    zscores = {name: robust_z(group[name]) for name in FEATURES}
    for i, user_id in enumerate(group.index):
        result['users'].append({
            'user_id': _plain(user_id),
            'raw': {name: int(group.at[user_id, name]) for name in FEATURES},
            'log': {name: round(float(logged[i, j]), 4) for j, name in enumerate(FEATURES)},
            'scaled': {name: round(float(X[i, j]), 4) for j, name in enumerate(FEATURES)},
            'z': {name: round(float(zscores[name].iloc[i]), 2) for name in FEATURES},
            'cluster': None if labels[i] is None else int(labels[i]),
            'kind': kinds[i],
            'kdist': round(float(kdist[i]), 4) if kdist.size else None,
            'x': round(float(coords[i, 0]), 4),
            'y': round(float(coords[i, 1]), 4),
            'reasons': explain(group, user_id) if kinds[i] == 'noise' else [],
        })
    return result


def project_2d(X: np.ndarray) -> tuple[np.ndarray, list[float]]:
    """First two principal components of already-centred data, and the share of variance each keeps."""
    X = np.asarray(X, dtype=float)
    coords = np.zeros((X.shape[0], 2))
    if X.shape[0] < 2 or not X.any():
        return coords, [0.0, 0.0]
    _, s, vt = np.linalg.svd(X, full_matrices=False)
    n = min(2, vt.shape[0])
    coords[:, :n] = X @ vt[:n].T
    var = s ** 2
    explained = [round(float(v / var.sum()), 4) for v in var[:2]] + [0.0] * (2 - n)
    return coords, explained


def demo_features(role: str = 'DOCTOR', n: int = 40, seed: int = 7) -> pd.DataFrame:
    """Synthetic users for showing the algorithm when there is not enough real activity.

    Normal users share a workload level that drives every count; three planted
    outliers view far too many patients, fail many logins at night, or are denied access often.
    Negative user ids keep them apart from real accounts; nothing is stored.
    """
    rng = np.random.default_rng(seed)
    level = rng.lognormal(0, 0.25, n)
    feats = pd.DataFrame({
        'total_actions': rng.poisson(60 * level),
        'distinct_patients': rng.poisson(9 * level),
        'failed_logins': rng.poisson(0.3, n),
        'off_hours_actions': rng.poisson(2 * level),
        'active_days': np.minimum(30, rng.poisson(18 * level)),
        'access_requests': rng.poisson(2 * level),
    }, index=pd.Index(-np.arange(1, n + 1), name='user_id'))
    feats['access_denied'] = rng.binomial(feats['access_requests'], 0.1)
    outliers = [
        dict(total_actions=150, distinct_patients=95, failed_logins=0, off_hours_actions=4,
             active_days=20, access_requests=3, access_denied=0),
        dict(total_actions=70, distinct_patients=10, failed_logins=14, off_hours_actions=45,
             active_days=19, access_requests=2, access_denied=0),
        dict(total_actions=55, distinct_patients=7, failed_logins=0, off_hours_actions=2,
             active_days=17, access_requests=22, access_denied=15),
    ]
    extra = pd.DataFrame(outliers, index=pd.Index(-np.arange(n + 1, n + 1 + len(outliers)), name='user_id'))
    feats = pd.concat([feats, extra])[FEATURES].astype(int)
    feats.insert(0, 'role', role)
    return feats


def _plain(value):
    return value.item() if hasattr(value, 'item') else value


def _scaled(group: pd.DataFrame) -> np.ndarray:
    """log1p of the counts, then each column to mean 0 / sd 1 (a column with no spread stays 0)."""
    X = np.log1p(group[FEATURES].to_numpy(dtype=float))
    std = X.std(axis=0)
    std[std == 0] = 1.0
    return (X - X.mean(axis=0)) / std


def _frame(df, columns) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame({c: pd.Series(dtype='object') for c in columns})
    return pd.DataFrame(df)
