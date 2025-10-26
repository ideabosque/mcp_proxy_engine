# -*- coding: utf-8 -*-
from __future__ import print_function

__author__ = "bibow"

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import httpx


class HTTP2ClientPool:
    """
    High-performance HTTP/2 client with connection pooling and concurrent request support.

    Features:
    - HTTP/2 multiplexing for concurrent requests on single connection
    - Connection pooling for efficient resource usage
    - Automatic retry with exponential backoff
    - Performance metrics tracking
    - Graceful degradation to HTTP/1.1 if HTTP/2 unavailable
    """

    def __init__(
        self,
        logger: logging.Logger,
        base_url: str,
        headers: Optional[Dict[str, str]] = None,
        max_connections: int = 100,
        max_keepalive_connections: int = 20,
        keepalive_expiry: float = 30.0,
        timeout: float = 30.0,
        max_retries: int = 3,
        enable_http2: bool = True,
    ):
        """
        Initialize HTTP/2 client pool.

        Args:
            logger: Logger instance
            base_url: Base URL for the HTTP client
            headers: Default headers to include in all requests
            max_connections: Maximum number of connections in pool
            max_keepalive_connections: Maximum number of idle connections to maintain
            keepalive_expiry: Time in seconds before idle connections expire
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            enable_http2: Enable HTTP/2 support (defaults to True)
        """
        self.logger = logger
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.max_retries = max_retries
        self.enable_http2 = enable_http2

        # Performance metrics
        self.metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_latency": 0.0,
            "http2_requests": 0,
            "http1_requests": 0,
            "concurrent_requests": 0,
            "max_concurrent_requests": 0,
        }

        # Connection limits for HTTP/2 optimization
        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
            keepalive_expiry=keepalive_expiry,
        )

        # HTTP/2 client with connection pooling
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            http2=self.enable_http2,
            limits=limits,
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        )

        self.logger.info(
            f"Initialized HTTP/2 client pool for {base_url} "
            f"(HTTP/2: {enable_http2}, max_connections: {max_connections})"
        )

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def close(self):
        """Close the HTTP client and release connections."""
        await self.client.aclose()
        self.logger.info(
            f"Closed HTTP/2 client pool. Metrics: {self.get_metrics_summary()}"
        )

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get performance metrics summary."""
        avg_latency = (
            self.metrics["total_latency"] / self.metrics["total_requests"]
            if self.metrics["total_requests"] > 0
            else 0
        )
        success_rate = (
            (self.metrics["successful_requests"] / self.metrics["total_requests"]) * 100
            if self.metrics["total_requests"] > 0
            else 0
        )

        return {
            "total_requests": self.metrics["total_requests"],
            "successful_requests": self.metrics["successful_requests"],
            "failed_requests": self.metrics["failed_requests"],
            "success_rate_percent": round(success_rate, 2),
            "avg_latency_ms": round(avg_latency * 1000, 2),
            "http2_requests": self.metrics["http2_requests"],
            "http1_requests": self.metrics["http1_requests"],
            "http2_usage_percent": round(
                (self.metrics["http2_requests"] / self.metrics["total_requests"]) * 100
                if self.metrics["total_requests"] > 0
                else 0,
                2,
            ),
            "max_concurrent_requests": self.metrics["max_concurrent_requests"],
        }

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Execute HTTP request with automatic retry and exponential backoff.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: URL path (will be appended to base_url)
            **kwargs: Additional arguments to pass to httpx request

        Returns:
            httpx.Response object
        """
        start_time = time.time()
        self.metrics["total_requests"] += 1
        self.metrics["concurrent_requests"] += 1
        self.metrics["max_concurrent_requests"] = max(
            self.metrics["max_concurrent_requests"],
            self.metrics["concurrent_requests"],
        )

        last_exception = None

        for attempt in range(self.max_retries):
            try:
                response = await self.client.request(method, url, **kwargs)

                # Track HTTP version used
                if response.http_version == "HTTP/2":
                    self.metrics["http2_requests"] += 1
                else:
                    self.metrics["http1_requests"] += 1

                response.raise_for_status()

                # Update metrics
                latency = time.time() - start_time
                self.metrics["successful_requests"] += 1
                self.metrics["total_latency"] += latency
                self.metrics["concurrent_requests"] -= 1

                self.logger.debug(
                    f"{method} {url} - Success (attempt {attempt + 1}/{self.max_retries}, "
                    f"latency: {latency*1000:.2f}ms, protocol: {response.http_version})"
                )

                return response

            except httpx.HTTPStatusError as e:
                last_exception = e
                self.logger.warning(
                    f"{method} {url} - HTTP error {e.response.status_code} "
                    f"(attempt {attempt + 1}/{self.max_retries})"
                )

                # Don't retry client errors (4xx) except 429
                if 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                    break

            except (httpx.RequestError, httpx.TimeoutException) as e:
                last_exception = e
                self.logger.warning(
                    f"{method} {url} - Request error: {str(e)} "
                    f"(attempt {attempt + 1}/{self.max_retries})"
                )

            # Exponential backoff
            if attempt < self.max_retries - 1:
                backoff_time = 2 ** attempt * 0.1  # 0.1s, 0.2s, 0.4s, etc.
                await asyncio.sleep(backoff_time)

        # All retries failed
        self.metrics["failed_requests"] += 1
        self.metrics["concurrent_requests"] -= 1

        self.logger.error(
            f"{method} {url} - Failed after {self.max_retries} attempts: {last_exception}"
        )
        raise last_exception

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Execute GET request."""
        return await self._request_with_retry("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Execute POST request."""
        return await self._request_with_retry("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        """Execute PUT request."""
        return await self._request_with_retry("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        """Execute DELETE request."""
        return await self._request_with_retry("DELETE", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        """Execute PATCH request."""
        return await self._request_with_retry("PATCH", url, **kwargs)

    async def execute_concurrent_requests(
        self,
        requests: List[Dict[str, Any]],
    ) -> List[httpx.Response]:
        """
        Execute multiple HTTP requests concurrently using HTTP/2 multiplexing.

        Args:
            requests: List of request dictionaries with 'method', 'url', and optional kwargs

        Returns:
            List of httpx.Response objects

        Example:
            requests = [
                {"method": "GET", "url": "/api/tool1"},
                {"method": "POST", "url": "/api/tool2", "json": {"param": "value"}},
            ]
            responses = await client.execute_concurrent_requests(requests)
        """
        self.logger.info(f"Executing {len(requests)} concurrent requests via HTTP/2")

        tasks = []
        for req in requests:
            method = req.pop("method")
            url = req.pop("url")
            tasks.append(self._request_with_retry(method, url, **req))

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Log any exceptions
        for i, response in enumerate(responses):
            if isinstance(response, Exception):
                self.logger.error(
                    f"Concurrent request {i} failed: {response}"
                )

        return responses


class HTTP2ClientManager:
    """
    Manages multiple HTTP/2 client pools for different base URLs.
    Provides centralized client lifecycle management.
    """

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.clients: Dict[str, HTTP2ClientPool] = {}

    def get_or_create_client(
        self,
        base_url: str,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> HTTP2ClientPool:
        """
        Get existing client or create new one for the base URL.

        Args:
            base_url: Base URL for the client
            headers: Default headers
            **kwargs: Additional HTTP2ClientPool configuration

        Returns:
            HTTP2ClientPool instance
        """
        if base_url not in self.clients:
            self.clients[base_url] = HTTP2ClientPool(
                logger=self.logger,
                base_url=base_url,
                headers=headers,
                **kwargs,
            )
            self.logger.info(f"Created new HTTP/2 client pool for {base_url}")

        return self.clients[base_url]

    async def close_all(self):
        """Close all client pools."""
        self.logger.info(f"Closing {len(self.clients)} HTTP/2 client pools")

        for base_url, client in self.clients.items():
            try:
                await client.close()
            except Exception as e:
                self.logger.error(f"Error closing client for {base_url}: {e}")

        self.clients.clear()

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics from all client pools."""
        return {
            base_url: client.get_metrics_summary()
            for base_url, client in self.clients.items()
        }
