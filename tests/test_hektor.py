"""Tests for HEKTOR BM25 search engine."""
import asyncio
import pytest
from singularity.memory.hektor import BM25Index, HektorMemory


class TestBM25Index:
    def test_empty_index(self):
        idx = BM25Index()
        idx.finalize()
        assert idx.search("anything") == []

    def test_basic_search(self):
        idx = BM25Index()
        idx.add("a.md", "The quick brown fox jumps over the lazy dog")
        idx.add("b.md", "A lazy cat sleeps all day long")
        idx.add("c.md", "Python programming language tutorial guide")
        idx.finalize()

        results = idx.search("lazy")
        assert len(results) >= 2
        # Both a.md and b.md contain "lazy"
        paths = [r["path"] for r in results]
        assert "a.md" in paths
        assert "b.md" in paths

    def test_priority_boost(self):
        idx = BM25Index()
        idx.add("low.md", "memory persistence COMB", priority=1.0)
        idx.add("high.md", "memory persistence COMB", priority=2.0)
        idx.finalize()

        results = idx.search("memory COMB", k=2)
        assert results[0]["path"] == "high.md"  # Higher priority wins

    def test_snippet_extraction(self):
        idx = BM25Index()
        idx.add("doc.md", "x " * 100 + "THE TARGET WORD HERE" + " y" * 100)
        idx.finalize()

        results = idx.search("target")
        assert len(results) == 1
        assert "TARGET" in results[0]["snippet"] or "target" in results[0]["snippet"].lower()

    def test_no_results(self):
        idx = BM25Index()
        idx.add("doc.md", "hello world")
        idx.finalize()

        results = idx.search("xyznonexistent")
        assert results == []


class TestHektorMemory:
    @pytest.fixture
    def tmp_workspace(self, tmp_path):
        # Create a minimal workspace
        core = tmp_path / "singularity" / ".core"
        core.mkdir(parents=True)
        (core / "SOUL.md").write_text("I am Aria. I coordinate.")
        (core / "IDENTITY.md").write_text("Name: Aria. Emoji: ⚡")

        memory = tmp_path / "memory"
        memory.mkdir()
        (memory / "2026-03-04.md").write_text("Today we fixed the echo loop.")

        return tmp_path

    @pytest.mark.asyncio
    async def test_index_and_search(self, tmp_workspace):
        h = HektorMemory(workspace=tmp_workspace)
        count = await h.index(paths=[tmp_workspace])
        assert count >= 3

        results = await h.search("echo loop")
        assert len(results) >= 1
        assert "2026-03-04.md" in results[0]["path"]

    @pytest.mark.asyncio
    async def test_stats(self, tmp_workspace):
        h = HektorMemory(workspace=tmp_workspace)
        assert h.stats["indexed"] is False

        await h.index(paths=[tmp_workspace])
        assert h.stats["indexed"] is True
        assert h.stats["file_count"] >= 3
        assert h.stats["term_count"] > 0

    @pytest.mark.asyncio
    async def test_auto_index_on_search(self, tmp_workspace):
        h = HektorMemory(workspace=tmp_workspace)
        # Search without explicit index — should auto-index
        results = await h.search("Aria coordinate")
        assert len(results) >= 1
