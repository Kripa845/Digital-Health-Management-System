"""How the TOPSIS ranking changes with the criterion weights.

Run from backend/:   python -m ml.sensitivity

Uses the worked example (doctors A, B, C; free hours = benefit, caseload = cost,
experience = benefit) and several weight sets.
"""
import numpy as np

from ml.topsis import topsis

DOCTORS = ['A', 'B', 'C']
MATRIX = [[10, 20, 5],    # A: 10 free hours, 20 patients, 5 years
          [6, 8, 10],     # B:  6 free hours,  8 patients, 10 years
          [12, 25, 15]]   # C: 12 free hours, 25 patients, 15 years
BENEFIT = [True, False, True]

WEIGHT_SETS = {
    'default 0.4 / 0.4 / 0.2': [0.4, 0.4, 0.2],
    'free hours 0.6 / 0.2 / 0.2': [0.6, 0.2, 0.2],
    'caseload 0.2 / 0.6 / 0.2': [0.2, 0.6, 0.2],
    'equal 1/3 each': [1 / 3, 1 / 3, 1 / 3],
    'experience 0.2 / 0.2 / 0.6': [0.2, 0.2, 0.6],
}


def main():
    print('Doctors: free hours / caseload / experience')
    for name, row in zip(DOCTORS, MATRIX):
        print(f'  {name}: {row[0]:>3} h  {row[1]:>3} patients  {row[2]:>3} years')
    print()
    print(f'{"weights (free / caseload / experience)":40} {"A":>7} {"B":>7} {"C":>7}   ranking')
    default_ranking = None
    for label, weights in WEIGHT_SETS.items():
        scores = topsis(MATRIX, weights, BENEFIT)
        ranking = ' > '.join(DOCTORS[i] for i in np.argsort(-scores, kind='stable'))
        default_ranking = default_ranking or ranking
        changed = '' if ranking == default_ranking else '   (changed)'
        print(f'{label:40} {scores[0]:7.3f} {scores[1]:7.3f} {scores[2]:7.3f}   {ranking}{changed}')


if __name__ == '__main__':
    main()
