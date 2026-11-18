from app.knowledge.projection import pca_2d


def test_pca_2d_on_empty_input_returns_empty_list() -> None:
    assert pca_2d([]) == []


def test_pca_2d_on_a_single_vector_returns_the_origin() -> None:
    assert pca_2d([[1.0, 2.0, 3.0]]) == [(0.0, 0.0)]


def test_pca_2d_of_points_on_a_line_has_a_near_zero_second_component() -> None:
    vectors = [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [2.0, 2.0, 2.0], [3.0, 3.0, 3.0]]

    points = pca_2d(vectors)

    assert len(points) == 4
    assert all(abs(y) < 1e-9 for _x, y in points)
    xs = [x for x, _y in points]
    assert xs == sorted(xs) or xs == sorted(xs, reverse=True)
