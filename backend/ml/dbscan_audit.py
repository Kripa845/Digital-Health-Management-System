
from __future__ import annotations

import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.neighbors import NearestNeighbors

NOISE = -1


def run_dbscan(X, eps: float = 1.0, min_samples: int = 5) -> np.ndarray:
   
    X = np.asarray(X, dtype=float)
    if X.shape[0] == 0:
        return np.zeros(0, dtype=int)
    return DBSCAN(eps=eps, min_samples=min_samples, metric='euclidean').fit_predict(X)


def k_distance(X, k: int) -> np.ndarray:
   
    return np.sort(kth_neighbour_distance(X, k))


def kth_neighbour_distance(X, k: int) -> np.ndarray:
   
    X = np.asarray(X, dtype=float)
    if k < 1 or X.shape[0] <= k:
        return np.zeros(0)
    distances, _ = NearestNeighbors(n_neighbors=k + 1).fit(X).kneighbors(X)
    return distances[:, k]                # column 0 is the row itself


def core_mask(X, eps: float, min_samples: int) -> np.ndarray:
   
    X = np.asarray(X, dtype=float)
    if X.shape[0] == 0:
        return np.zeros(0, dtype=bool)
    neighbours = NearestNeighbors(radius=eps).fit(X).radius_neighbors(X, return_distance=False)
    return np.array([len(n) >= min_samples for n in neighbours])


def knee(sorted_distances) -> float | None:

    y = np.asarray(sorted_distances, dtype=float)
    if y.size < 3 or y[-1] == y[0]:
        return None
    x = np.linspace(0, 1, y.size)
    yn = (y - y[0]) / (y[-1] - y[0])
    return float(y[np.argmax(x - yn)])


def gap_eps(sorted_distances) -> float | None:
    
    y = np.asarray(sorted_distances, dtype=float)
    if y.size < 4:
        return None
    start = y.size // 2 - 1
    jumps = np.diff(y[start:])
    if not jumps.size or jumps.max() <= 0:
        return None
    i = start + int(np.argmax(jumps))
    return float(y[i] + 0.1 * (y[i + 1] - y[i]))
