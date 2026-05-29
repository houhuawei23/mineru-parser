"""图片后处理模块单元测试。"""

import tempfile
from pathlib import Path

from PIL import Image

from mineru_parser.image_processor import extract_image_refs, process_images


def test_extract_image_refs_empty() -> None:
    """空文本应返回空列表。"""
    assert extract_image_refs("") == []
    assert extract_image_refs("no images here") == []


def test_extract_image_refs_single() -> None:
    """应正确提取单个图片引用。"""
    md = "![Figure 1](images/abc.jpg)"
    refs = extract_image_refs(md)
    assert refs == [("Figure 1", "images/abc.jpg")]


def test_extract_image_refs_multiple() -> None:
    """应按顺序提取多个引用。"""
    md = """text
![a](images/1.jpg)
more
![b](images/2.png)
"""
    refs = extract_image_refs(md)
    assert refs == [("a", "images/1.jpg"), ("b", "images/2.png")]


def test_extract_image_refs_empty_caption() -> None:
    """空 caption 也应提取。"""
    md = "![](images/x.jpg)"
    refs = extract_image_refs(md)
    assert refs == [("", "images/x.jpg")]


def test_process_images_no_refs() -> None:
    """无图片引用时应原样返回。"""
    with tempfile.TemporaryDirectory() as d:
        temp_dir = Path(d) / "temp"
        out_dir = Path(d) / "out"
        temp_dir.mkdir()
        out_dir.mkdir()
        result = process_images("no images", temp_dir, out_dir)
        assert result == "no images"


def test_process_images_rename_and_convert() -> None:
    """应重命名、转 PNG 并更新引用格式。"""
    with tempfile.TemporaryDirectory() as d:
        temp_dir = Path(d) / "temp"
        out_dir = Path(d) / "out"
        temp_dir.mkdir()
        out_dir.mkdir()
        # 创建测试图片
        img_path = temp_dir / "test.jpg"
        Image.new("RGB", (10, 10), color="red").save(img_path, "JPEG")

        md = "![Caption](test.jpg)"
        result = process_images(md, temp_dir, out_dir)

        assert "![image_01](images/image_01.png)" in result
        assert "> Caption" in result
        assert (out_dir / "images" / "image_01.png").exists()
        assert not (out_dir / "images" / "test.jpg").exists()
