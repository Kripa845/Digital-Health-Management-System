"""Pictures of detect_suspicious for a demo or for tuning: PCA scatter and k-distance plot.

    python manage.py plot_suspicious                         # today, DOCTOR, into media/demo_plots/
    python manage.py plot_suspicious --day 2026-10-05 --role DOCTOR --out-dir somewhere

Writes two PNGs and saves nothing in the database:
  pca_<role>_<day>.png    every user-day projected to 2-D with PCA; cluster members
                          as blue dots, DBSCAN noise as red X (checked-day noise labelled).
                          The projection is only a picture: DBSCAN runs on all 6 features.
  kdist_<role>_<day>.png  each user-day's distance to its k-th nearest neighbour
                          (k = min_samples - 1), sorted, with the current eps and the knee.
                          Choose eps a little above the knee (see the note in suspicious.py).
"""
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from django.conf import settings  # noqa: E402
from django.core.management.base import BaseCommand  # noqa: E402
from django.utils import timezone  # noqa: E402
from sklearn.decomposition import PCA  # noqa: E402

from apps.audit.suspicious import EPS, MIN_SAMPLES, NOISE, check  # noqa: E402
from apps.audit.suspicious_service import load_daily  # noqa: E402
from apps.users.models import User  # noqa: E402
from ml.dbscan_audit import k_distance, knee  # noqa: E402

BLUE, RED, INK, MUTED, GRID = '#2a6fdb', '#d6312b', '#1f2328', '#5b636e', '#e6e8eb'


class Command(BaseCommand):
    help = 'Save the PCA scatter and k-distance plot of the user-days detect_suspicious sees.'

    def add_arguments(self, parser):
        parser.add_argument('--day', type=date.fromisoformat, help='Checked day, YYYY-MM-DD (default: today).')
        parser.add_argument('--history', type=int, default=14)
        parser.add_argument('--role', choices=User.Role.values, default=User.Role.DOCTOR)
        parser.add_argument('--out-dir', default=str(Path(settings.BASE_DIR) / 'media' / 'demo_plots'))

    def handle(self, *args, **opts):
        day = opts['day'] or timezone.localdate()
        result = check(load_daily(day, opts['history']), day, opts['role'])
        if result.skipped:
            self.stdout.write(self.style.WARNING(f"{opts['role']}: {result.message} Nothing to plot."))
            return
        out = Path(opts['out_dir'])
        out.mkdir(parents=True, exist_ok=True)
        names = dict(User.objects.filter(id__in=result.rows['user_id'].unique()).values_list('id', 'username'))

        pca_path = out / f"pca_{opts['role'].lower()}_{day}.png"
        self.pca_plot(result, names, pca_path)
        kdist_path = out / f"kdist_{opts['role'].lower()}_{day}.png"
        bend = self.kdist_plot(result, kdist_path)

        dist = k_distance(result.X, MIN_SAMPLES - 1)
        pct = ', '.join(f'p{p} {np.percentile(dist, p):.2f}' for p in (50, 90, 95, 99))
        self.stdout.write(f'k-distance (k={MIN_SAMPLES - 1}): {pct}, max {dist.max():.2f}, '
                          f'knee {bend:.2f}; eps in use {EPS:g}.' if bend is not None else
                          f'k-distance (k={MIN_SAMPLES - 1}): {pct}; no clear knee; eps in use {EPS:g}.')
        self.stdout.write(self.style.SUCCESS(f'Saved {pca_path}\nSaved {kdist_path}'))

    def pca_plot(self, result, names, path):
        pca = PCA(n_components=2).fit(result.X)
        xy = pca.transform(result.X)
        noise = result.labels == NOISE
        on_day = (result.rows['day'] == result.day).to_numpy()

        fig, ax = plt.subplots(figsize=(8, 5.5), dpi=150)
        self.style_axes(ax)
        ax.scatter(xy[~noise, 0], xy[~noise, 1], s=28, c=BLUE, alpha=0.55, edgecolors='white', linewidths=0.6,
                   label=f'Normal user-days ({result.n_clusters} cluster{"s" if result.n_clusters != 1 else ""})')
        ax.scatter(xy[noise, 0], xy[noise, 1], s=90, c=RED, marker='X', edgecolors='white', linewidths=0.8,
                   label='Noise (DBSCAN -1)', zorder=3)
        for i in np.flatnonzero(noise & on_day):
            ax.annotate(f"{names.get(result.rows.at[i, 'user_id'], '?')}\n{result.day}", xy[i],
                        xytext=(8, 6), textcoords='offset points', fontsize=8, color=INK)
        var = pca.explained_variance_ratio_
        ax.set_xlabel(f'PC 1 ({var[0]:.0%} of variance)', color=MUTED)
        ax.set_ylabel(f'PC 2 ({var[1]:.0%} of variance)', color=MUTED)
        ax.set_title(f'{result.role.title()} activity per user-day: {result.day} vs previous days',
                     loc='left', color=INK, fontsize=11)
        ax.legend(frameon=False, fontsize=8, loc='best')
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)

    def kdist_plot(self, result, path):
        k = MIN_SAMPLES - 1
        dist = k_distance(result.X, k)
        bend = knee(dist)
        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
        self.style_axes(ax)
        ax.plot(np.arange(len(dist)), dist, color=BLUE, linewidth=2)
        ax.axhline(EPS, color=RED, linewidth=1.2, linestyle='--')
        ax.annotate(f'eps = {EPS:g}', (0, EPS), xytext=(4, 4), textcoords='offset points', fontsize=8, color=INK)
        if bend is not None:
            ax.axhline(bend, color=MUTED, linewidth=1, linestyle=':')
            ax.annotate(f'knee = {bend:.2f}', (0, bend), xytext=(4, -12), textcoords='offset points',
                        fontsize=8, color=MUTED)
        ax.set_xlabel('User-days, sorted by distance', color=MUTED)
        ax.set_ylabel(f'Distance to {k}th nearest neighbour', color=MUTED)
        ax.set_title(f'k-distance plot ({result.role.title()}, k = min_samples - 1 = {k})',
                     loc='left', color=INK, fontsize=11)
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        return bend

    @staticmethod
    def style_axes(ax):
        ax.grid(color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ('top', 'right'):
            ax.spines[side].set_visible(False)
        for side in ('left', 'bottom'):
            ax.spines[side].set_color(GRID)
        ax.tick_params(colors=MUTED, labelsize=8)
