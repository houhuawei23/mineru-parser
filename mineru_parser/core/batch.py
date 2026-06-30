"""批量并发解析：以 ``batch_concurrency`` 并发处理多个 PDF，共享 ``ctx.rate_limiter``。

文件轴并发由 ``ThreadPoolExecutor(max_workers=batch_concurrency)`` 控制；
每个文件内部的分片片段与其它文件共享同一 ``ctx.rate_limiter``，确保总在途
API 调用受 ``api_rate_limit`` 约束。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger

from mineru_parser.core.orchestrator import orchestrate_parse
from mineru_parser.core.result import ParseResult
from mineru_parser.models.params import ParseParams, RunContext


def run_batch(
    tasks: list[ParseParams],
    ctx: RunContext,
    batch_concurrency: int = 1,
    on_complete=None,
) -> list[ParseResult]:
    """并发处理多个 PDF。

    :param tasks: 每个元素的 :class:`ParseParams` 描述一个待解析文件。
    :param ctx: 提供 ``rate_limiter``（跨文件/分片共享）等运行期上下文。
    :param batch_concurrency: 同时处理的文件数。
    :param on_complete: 可选回调 ``on_complete(idx, ParseResult)``。
    :return: 与 ``tasks`` 等长、按索引对齐的 :class:`ParseResult` 列表。
    """
    results: list[ParseResult | None] = [None] * len(tasks)

    def process_one(idx: int, params: ParseParams) -> None:
        md_name = params.output_md_name or f"{params.pdf_path.stem}.md"
        t0 = time.perf_counter()
        try:
            md = orchestrate_parse(params, ctx)
            results[idx] = ParseResult(
                success=md is not None,
                pdf_path=params.pdf_path,
                markdown=md,
                md_path=params.output_dir / md_name if md is not None else None,
                elapsed=time.perf_counter() - t0,
                error=None if md is not None else "解析返回空结果",
            )
        except Exception as e:  # noqa: BLE001 — 单文件失败不应中断整个批次
            logger.exception(f"处理失败 {params.pdf_path}: {e}")
            results[idx] = ParseResult(
                success=False,
                pdf_path=params.pdf_path,
                elapsed=time.perf_counter() - t0,
                error=str(e),
            )
        if on_complete is not None:
            on_complete(idx, results[idx])

    with ThreadPoolExecutor(max_workers=max(1, batch_concurrency)) as ex:
        futures = [ex.submit(process_one, i, p) for i, p in enumerate(tasks)]
        for fut in as_completed(futures):
            fut.result()  # 传播线程内未捕获异常

    return [r for r in results if r is not None]
