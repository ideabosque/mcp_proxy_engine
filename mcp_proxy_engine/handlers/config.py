# -*- coding: utf-8 -*-
from __future__ import print_function

__author__ = "bibow"

import asyncio
import logging
import traceback
from typing import Any, Dict

import boto3

from mcp_http_client import MCPHttpClient
from silvaengine_utility import Utility


class Config:
    """
    Centralized Configuration Class
    Manages shared configuration variables across the application.
    """

    title = None
    version = None
    servers = None
    aws_lambda = None
    schemas = {}
    response_mappings = {}
    internal_mcp = None
    mcp_servers = []
    functions = []

    mcp_http_clients = []

    @classmethod
    def initialize(cls, logger: logging.Logger, **setting: Dict[str, Any]) -> None:
        """
        Initialize configuration setting.
        Args:
            logger (logging.Logger): Logger instance for logging.
            **setting (Dict[str, Any]): Configuration dictionary.
        """
        try:
            cls._set_parameters(setting)
            cls._initialize_aws_services(setting)
            cls._initialize_internal_mcp(setting)
            logger.info("Configuration initialized successfully.")
        except Exception as e:
            logger.exception("Failed to initialize configuration.")
            raise e

    @classmethod
    def _set_parameters(cls, setting: Dict[str, Any]) -> None:
        """
        Set application-level parameters.
        Args:
            setting (Dict[str, Any]): Configuration dictionary.
        """
        cls.title = setting["title"]
        cls.version = setting["version"]
        cls.servers = setting["servers"]
        cls.response_mappings = setting.get("response_mappings", {})

    @classmethod
    def _initialize_aws_services(cls, setting: Dict[str, Any]) -> None:
        """
        Initialize AWS services, such as the S3 client.
        Args:
            setting (Dict[str, Any]): Configuration dictionary.
        """
        if all(
            setting.get(k)
            for k in ["region_name", "aws_access_key_id", "aws_secret_access_key"]
        ):
            aws_credentials = {
                "region_name": setting["region_name"],
                "aws_access_key_id": setting["aws_access_key_id"],
                "aws_secret_access_key": setting["aws_secret_access_key"],
            }
        else:
            aws_credentials = {}

        cls.aws_lambda = boto3.client("lambda", **aws_credentials)

    @classmethod
    def _initialize_internal_mcp(cls, setting: Dict[str, Any]) -> None:
        """
        Initialize internal MCP server configuration.
        Args:
            setting (Dict[str, Any]): Configuration dictionary.
        """
        if "internal_mcp" not in setting:
            return
        mcp_server = setting["internal_mcp"]
        if mcp_server.get("bearer_token"):
            mcp_server["headers"] = {
                "Authorization": f"Bearer {mcp_server['bearer_token']}"
            }
        cls.internal_mcp = {
            "name": "internal_mcp",
            "base_url": mcp_server["base_url"],
            "headers": mcp_server["headers"],
        }

    @classmethod
    def set_mcp_servers(
        cls, logger: logging.Logger, endpoint_id: str, setting: Dict[str, Any]
    ) -> None:
        """
        Set MCP servers.
        Args:
            setting (Dict[str, Any]): Configuration dictionary.
        """
        result = cls._execute_graphql_query(
            logger,
            endpoint_id,
            "ai_agent_core_graphql",
            "mcpServerList",
            "Query",
            {},
            setting=setting,
        )

        if result["mcpServerList"]["total"] > 0:
            for mcp_server in result["mcpServerList"]["mcpServerList"]:
                cls.mcp_servers.append(
                    {
                        "name": mcp_server["mcpLabel"],
                        "base_url": mcp_server["mcpServerUrl"],
                        "headers": mcp_server["headers"],
                    }
                )

        if cls.internal_mcp:
            internal_mcp = cls.internal_mcp.copy()
            internal_mcp["base_url"] = internal_mcp["base_url"].format(
                endpoint_id=endpoint_id
            )
            cls.mcp_servers.append(internal_mcp)

    @classmethod
    def initialize_mcp_http_clients(cls, logger: logging.Logger) -> None:
        """Initialize MCP HTTP clients and convert their tools to Config.functions"""

        for mcp_server in cls.mcp_servers:
            mcp_http_client = MCPHttpClient(logger, **mcp_server)

            # Fetch tools from MCP server
            tools = asyncio.run(cls._run_list_mcp_http_tools(mcp_http_client))

            # Convert MCP tools to Config.functions format
            mcp_functions = cls._convert_mcp_tools_to_functions(
                tools,
                mcp_server_name=mcp_server["name"],
                response_mappings=cls.response_mappings,
                logger=logger,
            )

            # Append to Config.functions
            cls.functions.extend(mcp_functions)

            # Store client for runtime execution
            cls.mcp_http_clients.append(
                {
                    "name": mcp_server["name"],
                    "client": mcp_http_client,
                    "tools": [tool.name for tool in tools],
                }
            )

            logger.info(
                f"Loaded {len(mcp_functions)} tools from MCP server '{mcp_server['name']}'"
            )

    @classmethod
    async def _run_list_mcp_http_tools(cls, mcp_http_client):
        async with mcp_http_client as client:
            return await client.list_tools()

    @classmethod
    def _convert_mcp_tools_to_functions(
        cls,
        tools: list,
        mcp_server_name: str,
        response_mappings: Dict[str, Dict[str, Any]],
        logger: logging.Logger,
    ) -> list:
        """
        Convert MCP tools to Config.functions format.

        Algorithm:
        1. For each path in response_mappings, extract function_name from path
        2. Match function_name with tool.name
        3. If matched, create function with that path and response

        Rules:
        - Path is the key in response_mappings
        - function_name = first part of path split by "/" (e.g., "/get_questions/..." -> "get_questions")
        - If path has {variables} -> GET, else POST
        - summary = tool.description
        - in = "body" if POST, "path" for path variables if GET
        """
        functions = []

        # Create a mapping of tool.name to tool for quick lookup
        tools_by_name = {tool.name: tool for tool in tools}

        # Iterate through response_mappings (path as key)
        for path, response_config in response_mappings.items():
            # Extract function_name from path (first part after splitting by "/")
            path_parts = path.split("/")

            # path_parts[0] is empty string, path_parts[1] is the function name
            if len(path_parts) < 2:
                logger.warning(
                    f"Invalid path format '{path}' in MCP server '{mcp_server_name}'. "
                    f"Skipping..."
                )
                continue

            function_name = path_parts[1]

            # Check if this function_name matches any MCP tool
            if function_name not in tools_by_name:
                logger.warning(
                    f"No MCP tool found with name '{function_name}' for path '{path}' "
                    f"in MCP server '{mcp_server_name}'. Skipping..."
                )
                continue

            tool = tools_by_name[function_name]

            # Determine method based on path variables
            has_path_variables = "{" in path and "}" in path
            method = "GET" if has_path_variables else "POST"

            # Extract path variables if GET
            path_variables = cls._extract_path_variables(path)

            # Convert input_schema to parameters
            parameters = cls._convert_input_schema_to_parameters(
                tool.input_schema, method=method, path_variables=path_variables
            )

            # Use response from response_mappings
            response = response_config

            # Create function definition
            function = {
                "path": path,
                "method": method,
                "summary": tool.description,
                "function_name": function_name,
                "parameters": parameters,
                "response": response,
                "metadata": {
                    "mcp_server": mcp_server_name,
                    "is_mcp_tool": True,
                },
            }

            functions.append(function)

            logger.info(
                f"Mapped MCP tool '{function_name}' to path '{path}' with method '{method}'"
            )

        return functions

    @classmethod
    def _extract_path_variables(cls, path: str) -> list:
        """
        Extract variable names from path like /get/{id}/{name}

        Returns: ["id", "name"]
        """
        import re

        return re.findall(r"\{(\w+)\}", path)

    @classmethod
    def _convert_input_schema_to_parameters(
        cls,
        input_schema: Dict[str, Any],
        method: str,
        path_variables: list = None,
    ) -> list:
        """
        Convert JSON Schema to parameter list.

        Rules:
        - POST: all params in "body"
        - GET: path variables in "path", others in "query"
        """
        if path_variables is None:
            path_variables = []

        parameters = []
        properties = input_schema.get("properties", {})
        required_fields = input_schema.get("required", [])

        for prop_name, prop_def in properties.items():
            # Determine parameter location
            if method == "POST":
                param_in = "body"
            elif prop_name in path_variables:
                param_in = "path"
            else:
                param_in = "query"

            param = {
                "name": prop_name,
                "in": param_in,
                "type": cls._map_json_schema_type(prop_def.get("type", "string")),
                "required": prop_name in required_fields,
            }

            # Add description if available
            if "description" in prop_def:
                param["description"] = prop_def["description"]

            # Handle nested objects
            if prop_def.get("type") == "object":
                if "properties" in prop_def:
                    param["properties"] = cls._convert_nested_properties(
                        prop_def["properties"]
                    )

            # Handle arrays
            elif prop_def.get("type") == "array":
                if "items" in prop_def:
                    items = prop_def["items"]
                    param["child_type"] = cls._map_json_schema_type(
                        items.get("type", "string")
                    )
                    if items.get("type") == "object" and "properties" in items:
                        param["properties"] = cls._convert_nested_properties(
                            items["properties"]
                        )

            # Handle enums
            if "enum" in prop_def:
                param["enum"] = prop_def["enum"]

            # Handle defaults
            if "default" in prop_def:
                param["default"] = prop_def["default"]

            parameters.append(param)

        return parameters

    @classmethod
    def _convert_nested_properties(cls, properties: Dict[str, Any]) -> list:
        """Recursively convert nested object properties."""
        nested = []

        for prop_name, prop_def in properties.items():
            nested_prop = {
                "name": prop_name,
                "type": cls._map_json_schema_type(prop_def.get("type", "string")),
            }

            # Recursive handling for nested objects
            if prop_def.get("type") == "object" and "properties" in prop_def:
                nested_prop["properties"] = cls._convert_nested_properties(
                    prop_def["properties"]
                )

            # Handle nested arrays
            elif prop_def.get("type") == "array" and "items" in prop_def:
                items = prop_def["items"]
                nested_prop["child_type"] = cls._map_json_schema_type(
                    items.get("type", "string")
                )
                if items.get("type") == "object" and "properties" in items:
                    nested_prop["properties"] = cls._convert_nested_properties(
                        items["properties"]
                    )

            nested.append(nested_prop)

        return nested

    @classmethod
    def _map_json_schema_type(cls, json_type: str) -> str:
        """Map JSON Schema types to OpenAPI/Config types."""
        type_mapping = {
            "string": "string",
            "number": "float",
            "integer": "integer",
            "boolean": "boolean",
            "array": "list",
            "object": "dict",
        }
        return type_mapping.get(json_type, "string")

    @classmethod
    def _execute_graphql_query(
        cls,
        logger: logging.Logger,
        endpoint_id: str,
        function_name: str,
        operation_name: str,
        operation_type: str,
        variables: Dict[str, Any],
        setting: Dict[str, Any] = {},
    ) -> Dict[str, Any]:
        try:
            schema = cls._fetch_graphql_schema(
                logger, endpoint_id, function_name, setting
            )
            query = Utility.generate_graphql_operation(
                operation_name, operation_type, schema
            )
            logger.info(f"Query: {query}/{function_name}")
            return Utility.execute_graphql_query(
                logger,
                endpoint_id,
                function_name,
                query,
                variables,
                setting=setting,
                execute_mode=setting.get("execute_mode"),
                aws_lambda=cls.aws_lambda,
            )
        except Exception as e:
            log = traceback.format_exc()
            logger.error(log)
            raise Exception(
                f"Failed to execute GraphQL query ({function_name}/{endpoint_id}). Error: {e}"
            )

    # Fetches and caches GraphQL schema for a given function
    @classmethod
    def _fetch_graphql_schema(
        cls,
        logger: logging.Logger,
        endpoint_id: str,
        function_name: str,
        setting: Dict[str, Any] = {},
    ) -> Dict[str, Any]:
        """
        Fetches and caches a GraphQL schema for a given function.

        Args:
            logger: Logger instance for error reporting
            endpoint_id: ID of the endpoint to fetch schema from
            function_name: Name of function to get schema for
            setting: Optional settings dictionary

        Returns:
            Dict containing the GraphQL schema
        """
        # Check if schema exists in cache, if not fetch and store it
        if cls.schemas.get(function_name) is None:
            cls.schemas[function_name] = Utility.fetch_graphql_schema(
                logger,
                endpoint_id,
                function_name,
                setting=setting,
                aws_lambda=cls.aws_lambda,
                execute_mode=setting.get("execute_mode"),
            )
        return cls.schemas[function_name]
