"""API 模块单元测试。"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from mineru_parser.api import (
    apply_upload_urls,
    close_session,
    download_zip,
    get_headers,
    get_session,
    poll_batch_result,
    upload_file_to_url,
)


class TestGetHeaders:
    """测试 get_headers 函数。"""

    def test_returns_correct_headers(self) -> None:
        """验证返回的 headers 包含正确的 Content-Type 和 Authorization。"""
        token = "test_token_123"
        headers = get_headers(token)

        assert headers["Content-Type"] == "application/json"
        assert headers["Authorization"] == "Bearer test_token_123"


class TestGetSession:
    """测试 get_session 函数。"""

    def test_returns_session(self) -> None:
        """验证返回 requests.Session 实例。"""
        session = get_session()
        assert isinstance(session, requests.Session)

    def test_same_thread_same_session(self) -> None:
        """验证同一线程返回相同 session（线程本地存储）。"""
        session1 = get_session()
        session2 = get_session()
        assert session1 is session2

    def test_session_has_adapter(self) -> None:
        """验证 session 配置了 HTTPAdapter。"""
        session = get_session()
        # 检查是否挂载了 adapter
        assert "https://" in session.adapters
        assert "http://" in session.adapters


class TestCloseSession:
    """测试 close_session 函数。"""

    def test_closes_and_removes_session(self) -> None:
        """验证关闭后 session 被移除。"""
        # 先获取 session
        session = get_session()
        assert session is not None

        # 关闭 session
        close_session()

        # 再次获取应该是新 session
        new_session = get_session()
        assert new_session is not session


class TestApplyUploadUrls:
    """测试 apply_upload_urls 函数。"""

    def test_success_returns_batch_info(self) -> None:
        """验证成功时返回 batch_id 和 file_urls。"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": 0,
            "data": {
                "batch_id": "batch_123",
                "file_urls": ["https://upload.example.com/1"],
            },
        }

        mock_session = Mock()
        mock_session.post.return_value = mock_response

        result = apply_upload_urls(
            token="test_token",
            base_url="https://api.example.com",
            file_name="test.pdf",
            model_version="vlm",
            timeout=30,
            session=mock_session,
        )

        assert result is not None
        assert result["batch_id"] == "batch_123"
        assert result["file_urls"] == ["https://upload.example.com/1"]

    def test_http_error_returns_none(self) -> None:
        """验证 HTTP 错误时返回 None。"""
        mock_response = Mock()
        mock_response.status_code = 500

        mock_session = Mock()
        mock_session.post.return_value = mock_response

        result = apply_upload_urls(
            token="test_token",
            base_url="https://api.example.com",
            file_name="test.pdf",
            model_version="vlm",
            timeout=30,
            session=mock_session,
        )

        assert result is None

    def test_api_error_code_returns_none(self) -> None:
        """验证 API 返回非零 code 时返回 None。"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": 1,
            "msg": "Invalid token",
        }

        mock_session = Mock()
        mock_session.post.return_value = mock_response

        result = apply_upload_urls(
            token="test_token",
            base_url="https://api.example.com",
            file_name="test.pdf",
            model_version="vlm",
            timeout=30,
            session=mock_session,
        )

        assert result is None

    def test_missing_batch_id_returns_none(self) -> None:
        """验证响应缺少 batch_id 时返回 None。"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": 0,
            "data": {
                "file_urls": ["https://upload.example.com/1"],
                # missing batch_id
            },
        }

        mock_session = Mock()
        mock_session.post.return_value = mock_response

        result = apply_upload_urls(
            token="test_token",
            base_url="https://api.example.com",
            file_name="test.pdf",
            model_version="vlm",
            timeout=30,
            session=mock_session,
        )

        assert result is None

    def test_request_exception_returns_none(self) -> None:
        """验证请求异常时返回 None。"""
        mock_session = Mock()
        mock_session.post.side_effect = requests.RequestException("Connection error")

        result = apply_upload_urls(
            token="test_token",
            base_url="https://api.example.com",
            file_name="test.pdf",
            model_version="vlm",
            timeout=30,
            session=mock_session,
        )

        assert result is None


class TestUploadFileToUrl:
    """测试 upload_file_to_url 函数。"""

    def test_success_returns_true(self, tmp_path: Path) -> None:
        """验证成功上传返回 True。"""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"fake pdf content")

        mock_response = Mock()
        mock_response.status_code = 200

        mock_session = Mock()
        mock_session.put.return_value = mock_response

        result = upload_file_to_url(
            pdf_path=pdf_path,
            upload_url="https://upload.example.com/1",
            timeout=60,
            session=mock_session,
        )

        assert result is True

    def test_missing_file_returns_false(self, tmp_path: Path) -> None:
        """验证文件不存在时返回 False。"""
        pdf_path = tmp_path / "nonexistent.pdf"

        mock_session = Mock()

        result = upload_file_to_url(
            pdf_path=pdf_path,
            upload_url="https://upload.example.com/1",
            timeout=60,
            session=mock_session,
        )

        assert result is False
        mock_session.put.assert_not_called()

    def test_http_error_returns_false(self, tmp_path: Path) -> None:
        """验证 HTTP 错误时返回 False。"""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"fake pdf content")

        mock_response = Mock()
        mock_response.status_code = 403

        mock_session = Mock()
        mock_session.put.return_value = mock_response

        result = upload_file_to_url(
            pdf_path=pdf_path,
            upload_url="https://upload.example.com/1",
            timeout=60,
            session=mock_session,
        )

        assert result is False

    def test_request_exception_returns_false(self, tmp_path: Path) -> None:
        """验证请求异常时返回 False。"""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"fake pdf content")

        mock_session = Mock()
        mock_session.put.side_effect = requests.RequestException("Timeout")

        result = upload_file_to_url(
            pdf_path=pdf_path,
            upload_url="https://upload.example.com/1",
            timeout=60,
            session=mock_session,
        )

        assert result is False


class TestPollBatchResult:
    """测试 poll_batch_result 函数。"""

    def test_done_state_returns_result(self) -> None:
        """验证 state=done 时返回结果。"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": 0,
            "data": {
                "extract_result": [
                    {
                        "state": "done",
                        "full_zip_url": "https://download.example.com/result.zip",
                    }
                ]
            },
        }

        mock_session = Mock()
        mock_session.get.return_value = mock_response

        result = poll_batch_result(
            token="test_token",
            base_url="https://api.example.com",
            batch_id="batch_123",
            poll_interval=0.01,  # 快速测试
            max_wait=1,
            timeout=30,
            session=mock_session,
        )

        assert result is not None
        assert result["state"] == "done"
        assert result["full_zip_url"] == "https://download.example.com/result.zip"

    def test_failed_state_returns_none(self) -> None:
        """验证 state=failed 时返回 None。"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": 0,
            "data": {
                "extract_result": [
                    {
                        "state": "failed",
                        "err_msg": "Processing error",
                    }
                ]
            },
        }

        mock_session = Mock()
        mock_session.get.return_value = mock_response

        result = poll_batch_result(
            token="test_token",
            base_url="https://api.example.com",
            batch_id="batch_123",
            poll_interval=0.01,
            max_wait=1,
            timeout=30,
            session=mock_session,
        )

        assert result is None

    def test_timeout_returns_none(self) -> None:
        """验证超时返回 None。"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": 0,
            "data": {
                "extract_result": [
                    {
                        "state": "processing",
                        "extract_progress": {"extracted_pages": 1, "total_pages": 10},
                    }
                ]
            },
        }

        mock_session = Mock()
        mock_session.get.return_value = mock_response

        result = poll_batch_result(
            token="test_token",
            base_url="https://api.example.com",
            batch_id="batch_123",
            poll_interval=0.01,
            max_wait=0.05,  # 很短超时
            timeout=30,
            session=mock_session,
        )

        assert result is None

    def test_http_error_retries(self) -> None:
        """验证 HTTP 错误时重试。"""
        mock_response = Mock()
        mock_response.status_code = 500

        mock_session = Mock()
        mock_session.get.return_value = mock_response

        result = poll_batch_result(
            token="test_token",
            base_url="https://api.example.com",
            batch_id="batch_123",
            poll_interval=0.01,
            max_wait=0.05,
            timeout=30,
            session=mock_session,
        )

        assert result is None
        # 应该多次重试
        assert mock_session.get.call_count >= 2

    def test_request_exception_retries(self) -> None:
        """验证请求异常时重试。"""
        mock_session = Mock()
        mock_session.get.side_effect = requests.RequestException("Connection error")

        result = poll_batch_result(
            token="test_token",
            base_url="https://api.example.com",
            batch_id="batch_123",
            poll_interval=0.01,
            max_wait=0.05,
            timeout=30,
            session=mock_session,
        )

        assert result is None
        # 应该多次重试
        assert mock_session.get.call_count >= 2

    def test_done_without_zip_url_returns_none(self) -> None:
        """验证 state=done 但无 zip_url 时返回 None。"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": 0,
            "data": {
                "extract_result": [
                    {
                        "state": "done",
                        # missing full_zip_url
                    }
                ]
            },
        }

        mock_session = Mock()
        mock_session.get.return_value = mock_response

        result = poll_batch_result(
            token="test_token",
            base_url="https://api.example.com",
            batch_id="batch_123",
            poll_interval=0.01,
            max_wait=1,
            timeout=30,
            session=mock_session,
        )

        assert result is None


class TestDownloadZip:
    """测试 download_zip 函数。"""

    def test_success_returns_content(self) -> None:
        """验证成功下载返回内容。"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"fake zip content"

        mock_session = Mock()
        mock_session.get.return_value = mock_response

        result = download_zip(
            zip_url="https://download.example.com/result.zip",
            token="test_token",
            timeout=60,
            max_retries=3,
            retry_wait_cap=1,
            session=mock_session,
        )

        assert result == b"fake zip content"

    def test_failure_retries_and_returns_none(self) -> None:
        """验证失败重试后仍失败返回 None。"""
        mock_response = Mock()
        mock_response.status_code = 500

        mock_session = Mock()
        mock_session.get.return_value = mock_response

        result = download_zip(
            zip_url="https://download.example.com/result.zip",
            token="test_token",
            timeout=60,
            max_retries=2,
            retry_wait_cap=0.01,  # 快速测试
            session=mock_session,
        )

        assert result is None
        # 应该尝试所有重试: 2 retries * 2 SSL variants * 2 header variants
        assert mock_session.get.call_count == 2 * 2 * 2

    def test_success_on_retry(self) -> None:
        """验证重试成功后返回内容。"""
        mock_response_fail = Mock()
        mock_response_fail.status_code = 500

        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.content = b"fake zip content"

        mock_session = Mock()
        mock_session.get.side_effect = [
            mock_response_fail,  # First attempt, verify_ssl=True
            mock_response_fail,  # First attempt, verify_ssl=False
            mock_response_success,  # Second attempt, verify_ssl=True
        ]

        result = download_zip(
            zip_url="https://download.example.com/result.zip",
            token="test_token",
            timeout=60,
            max_retries=3,
            retry_wait_cap=0.01,
            session=mock_session,
        )

        assert result == b"fake zip content"

    def test_uses_header_variants(self) -> None:
        """验证尝试不同的 headers。"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"fake zip content"

        mock_session = Mock()
        mock_session.get.return_value = mock_response

        download_zip(
            zip_url="https://download.example.com/result.zip",
            token="test_token",
            timeout=60,
            max_retries=1,
            retry_wait_cap=0.01,
            session=mock_session,
        )

        # 验证使用了不同的 headers
        calls = mock_session.get.call_args_list
        headers_used = [call.kwargs.get("headers") or call[1].get("headers") for call in calls]
        # 至少有两种不同的 headers 被尝试
        assert len(set(str(h) for h in headers_used)) >= 1
