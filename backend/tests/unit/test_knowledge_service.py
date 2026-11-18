from app.knowledge.service import chunk_text


def test_chunk_text_returns_input_unchanged_when_under_the_limit() -> None:
    assert chunk_text("a short paragraph.", max_chars=500) == ["a short paragraph."]


def test_chunk_text_returns_empty_list_for_empty_content() -> None:
    assert chunk_text("", max_chars=500) == []


def test_chunk_text_splits_long_content_on_paragraph_boundaries() -> None:
    para_a = ("A " * 40).strip()  # 79 chars
    para_b = ("B " * 40).strip()
    para_c = ("C " * 40).strip()
    content = "\n\n".join([para_a, para_b, para_c])

    chunks = chunk_text(content, max_chars=100)

    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)
    assert "\n\n".join(chunks) == content


def test_chunk_text_hard_splits_a_single_paragraph_longer_than_the_limit() -> None:
    content = "x" * 250

    chunks = chunk_text(content, max_chars=100)

    assert len(chunks) == 3
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks) == content
