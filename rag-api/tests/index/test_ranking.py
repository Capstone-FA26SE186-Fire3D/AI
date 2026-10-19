from app.index.ranking import cosine_rank, lexical_rank, rank_chunks, rrf_merge
from app.sources.chunking import Chunk


def test_rrf_merge_prefers_items_in_both_lists():
    merged = rrf_merge([["a", "b", "c"], ["c", "d"]])
    ids = [i for i, _ in merged]
    assert ids[0] == "c"
    assert set(ids) == {"a", "b", "c", "d"}


def test_lexical_rank_counts_query_tokens_and_drops_zero():
    texts = {"1": "bình chữa cháy", "2": "bình thường", "3": "khác hẳn"}
    assert lexical_rank("bình chữa cháy", texts) == ["1", "2"]


def test_cosine_rank_orders_by_similarity():
    vecs = {"x": [1.0, 0.0], "y": [0.0, 1.0], "z": [0.9, 0.1]}
    assert cosine_rank([1.0, 0.0], vecs) == ["x", "z", "y"]


def test_rank_chunks_scores_normalised():
    chunks = [
        Chunk("c0", "d", "v", 0, "bình chữa cháy", {}, "Toàn văn"),
        Chunk("c1", "d", "v", 1, "khác hẳn", {}, "Toàn văn"),
    ]
    out = rank_chunks("chữa cháy", [1.0, 0.0], chunks, [[1.0, 0.0], [0.0, 1.0]], 5)
    assert out[0].chunk.chunk_id == "c0" and out[0].score == 1.0
    assert all(0 < s.score <= 1.0 for s in out)
