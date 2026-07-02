"""缓存模块单元测试。"""

import time
from pathlib import Path
from unittest.mock import Mock

from mineru_parser.engines.cache import (
    _compute_pdf_hash,
    _compute_pdf_hash_cached,
    _sanitize_stem,
    cache_group_dir,
    cache_zip_path,
    compute_source_hash,
    describe_page_token,
    get_cached_zip,
    save_to_cache,
    write_source_marker,
)


def create_mock_config(
    cache_hash_chunk_size: int = 8192, cache_key_prefix_len: int = 2
):
    """创建一个模拟的配置对象。"""
    config = Mock()
    config.cache_hash_chunk_size = cache_hash_chunk_size
    config.cache_key_prefix_len = cache_key_prefix_len
    return config


class TestComputePdfHash:
    """测试 _compute_pdf_hash 函数。"""

    def test_returns_consistent_hash(self, tmp_path: Path) -> None:
        """验证相同文件返回相同哈希。"""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"fake pdf content for hashing")
        config = create_mock_config()

        hash1 = _compute_pdf_hash(pdf_path, config)
        hash2 = _compute_pdf_hash(pdf_path, config)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex string length

    def test_different_files_different_hash(self, tmp_path: Path) -> None:
        """验证不同文件返回不同哈希。"""
        pdf1 = tmp_path / "test1.pdf"
        pdf2 = tmp_path / "test2.pdf"
        pdf1.write_bytes(b"content A")
        pdf2.write_bytes(b"content B")
        config = create_mock_config()

        hash1 = _compute_pdf_hash(pdf1, config)
        hash2 = _compute_pdf_hash(pdf2, config)

        assert hash1 != hash2

    def test_cache_avoids_recomputation(self, tmp_path: Path) -> None:
        """验证缓存避免重复计算哈希。"""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"fake pdf content" * 1000)  # Larger file
        config = create_mock_config()

        # Clear cache first
        _compute_pdf_hash_cached.cache_clear()

        # First call - should compute
        hash1 = _compute_pdf_hash(pdf_path, config)
        info1 = _compute_pdf_hash_cached.cache_info()
        assert info1.misses == 1
        assert info1.hits == 0

        # Second call - should hit cache
        hash2 = _compute_pdf_hash(pdf_path, config)
        info2 = _compute_pdf_hash_cached.cache_info()
        assert info2.misses == 1
        assert info2.hits == 1

        assert hash1 == hash2

    def test_cache_invalidated_on_modify(self, tmp_path: Path) -> None:
        """验证文件修改后缓存失效。"""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"original content")
        config = create_mock_config()

        # Clear cache
        _compute_pdf_hash_cached.cache_clear()

        # First hash
        hash1 = _compute_pdf_hash(pdf_path, config)
        info1 = _compute_pdf_hash_cached.cache_info()
        assert info1.misses == 1

        # Wait a bit to ensure mtime changes
        time.sleep(0.1)

        # Modify file
        pdf_path.write_bytes(b"modified content")

        # Second hash - should be cache miss due to mtime change
        hash2 = _compute_pdf_hash(pdf_path, config)
        info2 = _compute_pdf_hash_cached.cache_info()
        assert info2.misses == 2  # New computation

        assert hash1 != hash2


class TestComputeSourceHash:
    """测试 compute_source_hash（缓存身份的稳定基础）。"""

    def test_deterministic_for_same_content(self, tmp_path: Path) -> None:
        """相同内容（即便路径/文件名不同）应得到相同源哈希。"""
        a = tmp_path / "a.pdf"
        b = tmp_path / "renamed.pdf"
        a.write_bytes(b"same bytes")
        b.write_bytes(b"same bytes")
        cfg = create_mock_config()

        assert compute_source_hash(a, cfg) == compute_source_hash(b, cfg)

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        a = tmp_path / "a.pdf"
        b = tmp_path / "b.pdf"
        a.write_bytes(b"AAA")
        b.write_bytes(b"BBB")
        cfg = create_mock_config()

        assert compute_source_hash(a, cfg) != compute_source_hash(b, cfg)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        import pytest

        with pytest.raises(FileNotFoundError):
            compute_source_hash(tmp_path / "nope.pdf", create_mock_config())


class TestDescribePageToken:
    """测试 describe_page_token（页码集合 -> 稳定可读 token）。"""

    def test_single_page(self) -> None:
        assert describe_page_token([4]) == "p5"  # 0-based 4 -> 1-based 5

    def test_contiguous_range(self) -> None:
        assert describe_page_token([0, 1, 2]) == "p1-3"
        assert describe_page_token(list(range(50))) == "p1-50"

    def test_unordered_deduped(self) -> None:
        # 乱序、重复应归一为同一 token
        assert describe_page_token([2, 0, 1, 2]) == "p1-3"

    def test_noncontiguous_stable_hash(self) -> None:
        # 非连续 -> h<hash>，且对相同集合稳定
        t1 = describe_page_token([0, 1, 2, 6])
        t2 = describe_page_token([6, 2, 0, 1])  # 乱序
        assert t1 == t2
        assert t1.startswith("h")
        # 与连续区间不同
        assert t1 != describe_page_token([0, 1, 2, 3])

    def test_empty(self) -> None:
        assert describe_page_token([]) == "p0"


class TestCacheLayout:
    """测试分组目录布局与文件名。"""

    def test_group_dir_filename_prefix_plus_short_hash(self, tmp_path: Path) -> None:
        """组目录 = <safe_stem>_<hash8>。"""
        cache_dir = tmp_path / "cache"
        src = tmp_path / "My Paper.pdf"
        src.write_bytes(b"content")
        sh = "abcdef0123456789" * 4  # 64 hex chars

        gd = cache_group_dir(cache_dir, "vlm", src, sh)

        assert gd == cache_dir / "vlm" / "My_Paper_abcdef01"

    def test_zip_path_under_group(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        src = tmp_path / "paper.pdf"
        src.write_bytes(b"x")
        sh = "0" * 64

        zp = cache_zip_path(cache_dir, "vlm", src, sh, "p1-50")

        assert zp == cache_dir / "vlm" / "paper_00000000" / "p1-50.zip"

    def test_same_content_different_name_different_group(self, tmp_path: Path) -> None:
        """文件名不同 -> 组目录名不同（即便内容/短哈希相同）。"""
        a = tmp_path / "a.pdf"
        b = tmp_path / "b.pdf"
        sh = "12345678" + "0" * 56
        gd_a = cache_group_dir(tmp_path, "vlm", a, sh)
        gd_b = cache_group_dir(tmp_path, "vlm", b, sh)
        assert gd_a != gd_b
        assert gd_a.name == "a_12345678"
        assert gd_b.name == "b_12345678"

    def test_sanitize_stem(self) -> None:
        # 非法字符替换为下划线，保留点号
        assert _sanitize_stem("Hello, World!.pdf") == "Hello__World_.pdf"
        assert _sanitize_stem("a/b:c?d") == "a_b_c_d"
        # 全非法/非 ASCII 字符兜底为 pdf
        assert _sanitize_stem("!!!---") == "pdf"
        assert _sanitize_stem("中文 文件") == "pdf"

    def test_write_source_marker(self, tmp_path: Path) -> None:
        gd = tmp_path / "group"
        src = tmp_path / "doc.pdf"
        write_source_marker(gd, src)
        marker = gd / "source.txt"
        assert marker.exists()
        assert marker.read_text(encoding="utf-8") == str(src)
        # 重复写入相同内容不应报错（幂等）
        write_source_marker(gd, src)


class TestGetCachedZip:
    """测试 get_cached_zip（基于已解析路径）。"""

    def test_cache_miss_returns_none(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "cache" / "vlm" / "doc_00000000" / "full.zip"
        assert get_cached_zip(cache_file) is None

    def test_cache_hit_returns_content(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "cache" / "vlm" / "doc_00000000" / "full.zip"
        cache_file.parent.mkdir(parents=True)
        zip_content = b"fake zip content"
        cache_file.write_bytes(zip_content)

        assert get_cached_zip(cache_file) == zip_content

    def test_different_cache_files_isolated(self, tmp_path: Path) -> None:
        """不同模型/片段路径互不影响（不再需要 model_version 参数，路径即隔离）。"""
        base = tmp_path / "cache" / "vlm" / "doc_00000000"
        vlm_zip = base / "full.zip"
        vlm_zip.parent.mkdir(parents=True)
        vlm_zip.write_bytes(b"vlm")

        other = tmp_path / "cache" / "pipeline" / "doc_00000000" / "full.zip"
        other.parent.mkdir(parents=True)
        other.write_bytes(b"pipeline")

        assert get_cached_zip(vlm_zip) == b"vlm"
        assert get_cached_zip(other) == b"pipeline"


class TestSaveToCache:
    """测试 save_to_cache（基于已解析路径）。"""

    def test_saves_to_correct_location(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "cache" / "vlm" / "doc_00000000" / "p1-50.zip"
        zip_content = b"fake zip content"

        result = save_to_cache(cache_file, zip_content)

        assert result is not None
        assert result == cache_file
        assert result.exists()
        assert result.read_bytes() == zip_content

    def test_creates_directory_structure(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "cache" / "nested" / "vlm" / "doc_00000000" / "full.zip"
        save_to_cache(cache_file, b"x")

        assert cache_file.exists()
        assert cache_file.parent.exists()

    def test_roundtrip(self, tmp_path: Path) -> None:
        """save -> get 一致性。"""
        cache_file = tmp_path / "cache" / "vlm" / "doc_00000000" / "p51-55.zip"
        content = b"the zip"
        save_to_cache(cache_file, content)
        assert get_cached_zip(cache_file) == content


class TestCacheKeyDeterminism:
    """回归测试：切分产生的缓存键必须跨运行稳定（修复 PyMuPDF 非确定性写入导致的恒 miss）。"""

    def test_fragment_cache_paths_stable_across_splits(self, tmp_path: Path) -> None:
        """模拟编排层：两次独立切分应得到完全相同的缓存文件路径列表。"""
        from mineru_parser.engines.pdf_splitter import (
            chunk_ranges,
            compute_pages_per_chunk,
        )

        src = tmp_path / "big.pdf"
        src.write_bytes(b"x" * 100)  # 内容无关紧要，只验路径稳定性
        cfg = create_mock_config()
        source_hash = compute_source_hash(src, cfg)
        num_pages, size_bytes = 55, 100
        page_limit, size_limit = 50, 200 * 1024 * 1024

        def paths_one_run() -> list[str]:
            ppc = compute_pages_per_chunk(num_pages, size_bytes, page_limit, size_limit)
            source_map = list(range(num_pages))
            return [
                str(
                    cache_zip_path(
                        tmp_path / "cache",
                        "vlm",
                        src,
                        source_hash,
                        describe_page_token(source_map[s:e]),
                    )
                )
                for s, e in chunk_ranges(num_pages, ppc)
            ]

        run1 = paths_one_run()
        run2 = paths_one_run()

        assert run1 == run2  # 跨运行稳定（核心修复点）
        assert [Path(p).name for p in run1] == ["p1-50.zip", "p51-55.zip"]
        # 所有片段归入同一组目录
        parents = {Path(p).parent for p in run1}
        assert len(parents) == 1
