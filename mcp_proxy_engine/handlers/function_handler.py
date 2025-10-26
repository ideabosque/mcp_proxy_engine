# -*- coding: utf-8 -*-
from __future__ import print_function

__author__ = "bibow"

import asyncio
import logging
import re
import traceback
from typing import Any, Dict, List, Optional, Tuple

from mcp_http_client import MCPHttpClient
from silvaengine_utility import method_cache

from .config import Config  # Import Config class


@method_cache(ttl=1800, cache_name="mcp_proxy_engine.function_lookup")
def get_function_name_and_path_parameters(
    endpoint_id: str, path: str
) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    """
    Extract the function name and path parameters from a URL path.
    Args:
        endpoint_id (str): The endpoint identifier for cache isolation.
        path (str): The URL path.

    Returns:
        Tuple[Optional[str], Optional[Dict[str, str]]]: The function name and path parameters, or (None, None) if not found.
    """
    logger = logging.getLogger(__name__)

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
