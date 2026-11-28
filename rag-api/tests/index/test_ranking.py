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


def test_query_terms_drop_stopwords_and_repeats():
    from app.index.ranking import query_terms

    assert query_terms("Khi nào thì mình nên dùng bình CO2, bình nào?") == ["dùng", "bình", "co2"]
    assert query_terms("là của và có") == []


def test_lexical_rank_weighs_rare_words_over_common_ones():
    texts = {
        "common": "Khi có cháy thì các bạn cần bình tĩnh, khi có khói thì cúi thấp, khi có lửa thì tránh xa.",
        "rare": "Bình CO2 dùng cho đám cháy thiết bị điện.",
        "other": "Tập trung tại điểm tập kết.",
    }
    # Old counting gave "common" the most hits (khi, có, thì, cháy); BM25 puts the chunk about CO2 first.
    assert lexical_rank("Khi có cháy thì dùng bình CO2 thế nào?", texts)[0] == "rare"
    assert lexical_rank("là của và", texts) == []
    assert lexical_rank("CO2", {}) == []


def test_text_query_ors_words_without_stopwords():
    from app.index.pgvector import text_query

    assert text_query("Khi nào dùng bình CO2 (QCVN 06)?") == "dùng | bình | co2 | qcvn | 06"
    assert text_query("là của và có?") is None
    assert text_query("x_y z'w") == "x | y | z | w"
