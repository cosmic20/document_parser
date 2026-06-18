"""Tests for the deterministic vault concept index + topic-dependency cycle-check."""

from __future__ import annotations

from document_parser import vault as v


def _write(path, frontmatter: dict | None, body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = ""
    if frontmatter is not None:
        import yaml

        fm = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n"
    path.write_text(fm + body)


# ------------------------------------------------------------------ unit helpers


def test_split_frontmatter():
    fm, body = v.split_frontmatter("---\ntopic: Probability\n---\nHello")
    assert fm == {"topic": "Probability"}
    assert body.strip() == "Hello"

    fm, body = v.split_frontmatter("No frontmatter here")
    assert fm == {} and body == "No frontmatter here"


def test_extract_link_targets():
    body = "uses [[Eigenvalues]] and [[Bayes' Theorem|Bayes]] plus [[Gradient#step]]"
    assert v.extract_link_targets(body) == {"Eigenvalues", "Bayes' Theorem", "Gradient"}


def test_topic_of(tmp_path):
    (tmp_path / "Probability").mkdir()
    assert v.topic_of(tmp_path / "Probability" / "RV.md", tmp_path) == "Probability"
    assert v.topic_of(tmp_path / "MOC.md", tmp_path) is None  # root-level note


def test_would_create_cycle():
    edges = {"Machine Learning": ["Linear Algebra"]}
    # Adding Linear Algebra → ML reverses the existing ML → Linear Algebra dependency.
    assert v.would_create_cycle(edges, "Linear Algebra", "Machine Learning")
    # Re-adding the same direction is fine.
    assert not v.would_create_cycle(edges, "Machine Learning", "Linear Algebra")
    # Within-topic is always allowed.
    assert not v.would_create_cycle(edges, "Probability", "Probability")


# ----------------------------------------------------------------- full indexing


def _fixture_vault(tmp_path):
    _write(tmp_path / "MOC.md", {"tags": ["MOC"]}, "- [[Eigenvalues]]\n- [[PCA]]\n")
    _write(
        tmp_path / "Linear Algebra" / "Eigenvalues.md",
        {"aliases": ["eigenvalue", "eigenvalues"], "tags": ["linear-algebra"]},
        "## Overview\nThe eigenvalue equation.",
    )
    _write(
        tmp_path / "Machine Learning" / "PCA.md",
        {
            "topic": "Machine Learning",
            "sources": ["10-601 Machine Learning — Lecture 7"],
            "tags": ["ml", "dimensionality-reduction"],
        },
        "PCA diagonalizes the covariance via [[Eigenvalues]].",
    )
    _write(
        tmp_path / "Machine Learning" / "Whitening.md",
        {"topic": "Machine Learning"},
        "Whitening rescales by [[eigenvalue]] magnitudes.",  # link via ALIAS
    )
    _write(
        tmp_path / "Machine Learning" / "Random Forest.md",
        {"topic": "Machine Learning"},
        "An ensemble of [[Decision Tree]]s.",  # dangling link → no edge
    )
    return tmp_path


def test_build_index_records_and_topic_edges(tmp_path):
    vault = _fixture_vault(tmp_path)
    index = v.build_index(vault)

    by_title = {n["title"]: n for n in index["notes"]}
    assert set(by_title) == {"MOC", "Eigenvalues", "PCA", "Whitening", "Random Forest"}

    assert by_title["Eigenvalues"]["topic"] == "Linear Algebra"  # from folder
    assert by_title["Eigenvalues"]["aliases"] == ["eigenvalue", "eigenvalues"]
    assert by_title["PCA"]["topic"] == "Machine Learning"  # from frontmatter
    assert by_title["PCA"]["sources"] == ["10-601 Machine Learning — Lecture 7"]
    assert by_title["MOC"]["topic"] is None  # root-level

    # Cross-topic edges: ML → Linear Algebra (via title AND alias links); the dangling
    # [[Decision Tree]] and the root MOC contribute no edges.
    assert index["topic_edges"] == {"Machine Learning": ["Linear Algebra"]}


def test_build_index_edges_drive_cycle_check(tmp_path):
    index = v.build_index(_fixture_vault(tmp_path))
    edges = index["topic_edges"]
    # A would-be back-link Linear Algebra → Machine Learning is correctly flagged as a cycle.
    assert v.would_create_cycle(edges, "Linear Algebra", "Machine Learning")


def test_write_index_emits_file(tmp_path):
    out, index = v.write_index(_fixture_vault(tmp_path))
    assert out.name == ".vault-index.json"
    assert out.exists()
    assert index["notes"]
