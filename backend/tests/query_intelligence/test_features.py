from app.services.query_intelligence.features import extract_features


def test_identifier_detection():
    f = extract_features("What is cancellation_fee?")
    assert f.contains_identifier is True
    assert "cancellation_fee" in f.identifier_candidates
    assert f.has_snake_case is True

    f2 = extract_features("What does ERR_504 mean?")
    assert f2.contains_identifier is True
    assert f2.has_upper_case is True

    f3 = extract_features("pool_size=10")
    assert f3.contains_identifier is True
    assert f3.has_snake_case or f3.has_upper_case or "pool_size" in f3.identifier_candidates


def test_exact_term():
    f = extract_features('What is "cancellation_fee"?')
    assert f.contains_quotes is True
    assert f.contains_exact_phrase is True

    f2 = extract_features("Explain `user_id`")
    assert f2.contains_backticks is True

    f3 = extract_features("vector_cosine_ops")
    assert f3.contains_identifier is True
    assert f3.contains_exact_phrase is True  # single identifier word


def test_question_type():
    assert extract_features("What is the refund policy?").question_type.value == "policy"
    assert extract_features("How do I reset my password?").question_type.value == "procedure"
    assert extract_features("What is the maximum file size?").question_type.value in ["policy", "factual", "definition"]
    assert extract_features("How does it work?").question_type.value == "procedure"


def test_rare_terms():
    f = extract_features("What are the HNSW index parameters m and ef_construction?")
    assert len(f.rare_term_candidates) > 0
    # contains HNSW
    assert any("HNSW" in t or "ef_construction" in t for t in f.rare_term_candidates + f.identifier_candidates)
