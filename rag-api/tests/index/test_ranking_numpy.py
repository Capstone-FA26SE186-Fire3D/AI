import random

from app.index.ranking import _cosine_rank_py, cosine_rank


def test_vectorised_cosine_rank_matches_the_python_reference():
    rng = random.Random(7)
    for trial in range(40):
        dim = rng.choice([3, 64, 384])
        vectors = {f"k{i}": [rng.uniform(-1, 1) for _ in range(dim)] for i in range(rng.randint(1, 60))}
        # Ties (identical vectors) and zero vectors keep the reference order.
        keys = list(vectors)
        vectors[keys[0] + "-dup"] = list(vectors[keys[0]])
        vectors["zero"] = [0.0] * dim
        query = [rng.uniform(-1, 1) for _ in range(dim)]
        assert cosine_rank(query, vectors) == _cosine_rank_py(query, vectors), trial


def test_edge_cases():
    assert cosine_rank([1.0, 0.0], {}) == []
    assert cosine_rank([0.0, 0.0], {"a": [1.0, 0.0], "b": [0.0, 1.0]}) == ["a", "b"], "zero query: all 0, order kept"
    assert cosine_rank([1.0, 0.0], {"a": [1.0], "b": [0.0, 1.0]}) == _cosine_rank_py([1.0, 0.0], {"a": [1.0], "b": [0.0, 1.0]})
