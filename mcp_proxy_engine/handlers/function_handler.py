# -*- coding: utf-8 -*-
from __future__ import print_function

__author__ = "bibow"

import asyncio
import json
import logging
import re
import traceback
from typing import Any, Dict, Optional, Tuple, List

from mcp_http_client import MCPHttpClient

from .config import Config  # Import Config class
from .http2_client import HTTP2ClientPool


def get_function_name_and_path_parameters(
    logger: logging.Logger, path: str
) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    """
    Extract the function name and path parameters from a URL path.
    Args:
        logger (logging.Logger): Logger instance for logging information.
        path (str): The URL path.

    Returns:
        Tuple[Optional[str], Optional[Dict[str, str]]]: The function name and path parameters, or (None, None) if not found.
    """
    try:
        for function in Config.functions:
            # Replace placeholders with regex patterns for path parameters
            pattern = re.sub(r"{(\w+)}", r"(?P<\1>[^/]+)", function["path"])
            match = re.fullmatch(pattern, path)
            if match:
                return function["function_name"], match.groupdict()
        return None, None
    except Exception as e:
        logger.error(
            f"Error extracting function name and parameters: {traceback.format_exc()}"
        )
        raise e


async def _run_call_mcp_http_tool(
    logger: logging.Logger,
    mcp_http_client: MCPHttpClient,
    name: str,
    arguments: Dict[str, Any],
) -> Any:
    logger.info(f"Calling MCP HTTP tool: {name} with arguments: {arguments}")

    async with mcp_http_client as client:
        result = await client.call_tool(name, arguments)

        logger.info(f"MCP HTTP tool {name} returned result: {result}")

        return result


def _execute_mcp_tool(
    logger: logging.Logger,
    mcp_http_client: MCPHttpClient,
    function_name: str,
    **arguments: Dict[str, Any],
) -> Any:
    """
    Private function to execute MCP tool with given arguments.
    Args:
        logger (logging.Logger): Logger instance for logging information.
        mcp_http_client (MCPHttpClient): The MCP HTTP client instance.
        function_name (str): Name of the function to execute.
        **arguments: Arguments to pass to the MCP tool.

    Returns:
        Any: The result from the MCP tool execution.
    """
    return asyncio.run(
        _run_call_mcp_http_tool(logger, mcp_http_client, function_name, arguments)
    )


async def _run_call_mcp_tool_async(
    logger: logging.Logger,
    mcp_http_client: MCPHttpClient,
    function_name: str,
    arguments: Dict[str, Any],
) -> Any:
    """
    Execute MCP tool asynchronously using the MCPHttpClient.
    This enables concurrent execution of multiple MCP tool calls.

    Args:
        logger: Logger instance for logging information
        mcp_http_client: The MCP HTTP client instance
        function_name: Name of the function to execute
        arguments: Arguments to pass to the MCP tool

    Returns:
        The result from the MCP tool execution
    """
    logger.info(f"Calling MCP tool asynchronously: {function_name} with arguments: {arguments}")

    try:
        async with mcp_http_client as client:
            result = await client.call_tool(function_name, arguments)
            logger.info(f"MCP tool {function_name} returned result: {result}")
            return result
    except Exception as e:
        logger.error(f"MCP tool call failed for {function_name}: {e}")
        raise


async def _run_concurrent_mcp_tools(
    logger: logging.Logger,
    tool_calls: List[Dict[str, Any]],
) -> List[Any]:
    """
    Execute multiple MCP tools concurrently using asyncio.

    This leverages the async capabilities of MCPHttpClient to execute
    multiple tool calls in parallel, which can benefit from HTTP/2
    multiplexing if the underlying transport supports it.

    Args:
        logger: Logger instance for logging
        tool_calls: List of tool call dictionaries, each containing:
            - function_name: Name of the function to call
            - arguments: Arguments to pass to the function

    Returns:
        List of results from all tool calls
    """
    logger.info(f"Executing {len(tool_calls)} tools concurrently")

    tasks = []
    for tool_call in tool_calls:
        function_name = tool_call["function_name"]
        arguments = tool_call.get("arguments", {})

        # Find the MCP client for this function
        client_info = next(
            (
                client
                for client in Config.mcp_http_clients
                if function_name in client["tools"]
            ),
            None,
        )

        if client_info and "client" in client_info:
            tasks.append(
                _run_call_mcp_tool_async(
                    logger,
                    client_info["client"],
                    function_name,
                    arguments
                )
            )
        else:
            logger.warning(
                f"MCP client not available for {function_name}, skipping"
            )

    # Execute all tasks concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Log any failures
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Tool call {i} failed: {result}")

    return results


def execute_concurrent_functions(
    logger: logging.Logger,
    tool_calls: List[Dict[str, Any]],
) -> List[Any]:
    """
    Execute multiple functions concurrently (synchronous wrapper).

    Args:
        logger: Logger instance for logging
        tool_calls: List of tool call dictionaries

    Returns:
        List of results from all tool calls
    """
    if not Config.enable_concurrent_requests:
        logger.info("Concurrent requests disabled, executing sequentially")
        return [
            execute_function(logger, tc["function_name"], **tc.get("arguments", {}))
            for tc in tool_calls
        ]

    return asyncio.run(_run_concurrent_mcp_tools(logger, tool_calls))


def execute_function(
    logger: logging.Logger, function_name: str, **kwargs: Dict[str, Any]
) -> Optional[Dict]:
    """
    Execute the specified function with the given parameters.
    Args:
        logger (logging.Logger): Logger instance for logging information.
        function_name (str): Name of the function to execute.
        **kwargs: Parameters to pass to the function.

    Returns:
        Optional[Dict]: The result of the function execution, or None if an error occurs.
    """
    try:
        # Find the client info for this function
        client_info = next(
            (
                client
                for client in Config.mcp_http_clients
                if function_name in client["tools"]
            ),
            None,
        )

        # If function is found in MCP tools, call it through the MCP client
        if client_info:
            logger.info(f"Executing function {function_name} with parameters: {kwargs}")

            # Always use the legacy MCP client as it knows the correct MCP protocol
            # The HTTP/2 client pool is available for future direct REST API calls
            # but for MCP protocol, we must use the MCPHttpClient
            logger.debug(f"Using MCP HTTP client for {function_name}")
            result = _execute_mcp_tool(
                logger, client_info["client"], function_name, **kwargs
            )

            return result[0]["text"]

        if not client_info:
            logger.exception(f"{function_name} is not supported!!")
            raise Exception(f"{function_name} is not supported")
    except Exception as e:
        logger.error(
            f"Failed to execute function {function_name}: {traceback.format_exc()}"
        )
        raise e
