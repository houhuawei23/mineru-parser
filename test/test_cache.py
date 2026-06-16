"""缓存模块单元测试。"""

import time
from pathlib import Path
from unittest.mock import Mock


from mineru_parser.cache import (
    _compute_pdf_hash,
    _compute_pdf_hash_cached,
    get_cached_zip,
    save_to_cache,
)


def create_mock_config(cache_hash_chunk_size: int = 8192, cache_key_prefix_len: int = 2):
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


class TestGetCachedZip:
    """测试 get_cached_zip 函数。"""

    def test_cache_miss_returns_none(self, tmp_path: Path) -> None:
        """验证缓存未命中返回 None。"""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"fake pdf content")
        cache_dir = tmp_path / "cache"
        config = create_mock_config()

        result = get_cached_zip(pdf_path, cache_dir, config, model_version="vlm")
        assert result is None

    def test_cache_hit_returns_content(self, tmp_path: Path) -> None:
        """验证缓存命中返回内容。"""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"fake pdf content")
        cache_dir = tmp_path / "cache"
        config = create_mock_config()

        # Save to cache first
        zip_content = b"fake zip content"
        save_to_cache(pdf_path, zip_content, cache_dir, config, model_version="vlm")

        # Now retrieve
        result = get_cached_zip(pdf_path, cache_dir, config, model_version="vlm")
        assert result == zip_content

    def test_missing_pdf_returns_none(self, tmp_path: Path) -> None:
        """验证 PDF 不存在时返回 None。"""
        pdf_path = tmp_path / "nonexistent.pdf"
        cache_dir = tmp_path / "cache"
        config = create_mock_config()

        result = get_cached_zip(pdf_path, cache_dir, config, model_version="vlm")
        assert result is None


class TestSaveToCache:
    """测试 save_to_cache 函数。"""

    def test_saves_to_correct_location(self, tmp_path: Path) -> None:
        """验证保存到正确的缓存位置。"""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"fake pdf content")
        cache_dir = tmp_path / "cache"
        config = create_mock_config()

        zip_content = b"fake zip content"
        result = save_to_cache(pdf_path, zip_content, cache_dir, config, model_version="vlm")

        assert result is not None
        assert result.exists()
        assert result.read_bytes() == zip_content

    def test_creates_directory_structure(self, tmp_path: Path) -> None:
        """验证创建目录结构。"""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"fake pdf content")
        cache_dir = tmp_path / "cache" / "nested"
        config = create_mock_config()

        zip_content = b"fake zip content"
        save_to_cache(pdf_path, zip_content, cache_dir, config, model_version="vlm")

        # Directory should be created
        assert cache_dir.exists()

    def test_missing_pdf_returns_none(self, tmp_path: Path) -> None:
        """验证 PDF 不存在时返回 None。"""
        pdf_path = tmp_path / "nonexistent.pdf"
        cache_dir = tmp_path / "cache"
        config = create_mock_config()

        zip_content = b"fake zip content"
        result = save_to_cache(pdf_path, zip_content, cache_dir, config, model_version="vlm")

        assert result is None

    def test_different_models_different_cache(self, tmp_path: Path) -> None:
        """验证不同模型使用不同缓存。"""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"fake pdf content")
        cache_dir = tmp_path / "cache"
        config = create_mock_config()

        # Save with vlm model
        save_to_cache(pdf_path, b"vlm content", cache_dir, config, model_version="vlm")

        # Save with pipeline model
        save_to_cache(pdf_path, b"pipeline content", cache_dir, config, model_version="pipeline")

        # Retrieve with vlm
        vlm_result = get_cached_zip(pdf_path, cache_dir, config, model_version="vlm")
        assert vlm_result == b"vlm content"

        # Retrieve with pipeline
        pipeline_result = get_cached_zip(pdf_path, cache_dir, config, model_version="pipeline")
        assert pipeline_result == b"pipeline content"
