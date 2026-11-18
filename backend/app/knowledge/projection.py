"""2D PCA projection of a set of embedding vectors, for the Map visualization page. Deterministic
(the same points land in the same place on every reload), unlike t-SNE/UMAP,
and it has no tuning parameters."""

import numpy as np


def pca_2d(vectors: list[list[float]]) -> list[tuple[float, float]]:
    if len(vectors) == 0:
        return []
    if len(vectors) == 1:
        return [(0.0, 0.0)]
    matrix = np.array(vectors, dtype=float)
    centered = matrix - matrix.mean(axis=0)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    components = vt[:2]
    projected = centered @ components.T
    return [(float(point[0]), float(point[1])) for point in projected]
