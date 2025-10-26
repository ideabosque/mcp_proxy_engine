#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import print_function

__author__ = "bibow"

import logging
from typing import Any, Dict, List, Tuple

from silvaengine_utility import Utility

from .handlers.config import Config
from .handlers.function_handler import (
    execute_function,
    get_function_name_and_path_parameters,
)
from .handlers.swagger_generator import generate_swagger_yaml


# Hook function applied to deployment
def deploy() -> List:
    return [
        {
            "service": "MCP Proxy Engine",
            "class": "McpProxyEngine",
            "functions": {
                "mcp_proxy_dispatch": {
                    "is_static": False,
                    "label": "MCP Proxy Dispatch",
                    "type": "RequestResponse",
                    "support_methods": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                    "is_auth_required": False,
                    "is_graphql": False,
                    "settings": "mcp_proxy_engine",
                    "disabled_in_resources": True,  # Ignore adding to resource list.
                },
            },
        }
    ]


class McpProxyEngine(object):
    def __init__(self, logger: logging.Logger, **setting: Dict[str, Any]) -> None:
        """
        Initializes the MCP Proxy Engine.
        Args:
            logger (logging.Logger): Logger instance for logging.
            **settings (Dict[str, Any]): Configuration dictionary.
        """
        # Initialize configuration via the Config class
        Config.initialize(logger, **setting)

        self.logger = logger
        self.setting = setting

    def mcp_proxy_dispatch(self, **kwargs: Dict[str, Any]) -> Any:
        endpoint_id = kwargs.pop("endpoint_id", None)
        ## Test the waters 🧪 before diving in!
        ##<--Testing Data-->##
        if endpoint_id is None:
            endpoint_id = self.setting.get("endpoint_id")
        ##<--Testing Data-->##

        Config.set_mcp_servers(self.logger, endpoint_id, self.setting)
        Config.initialize_mcp_http_clients(self.logger)

        path = "/" + kwargs.pop("path")
        if path is None:
            raise Exception("path is required!!")
        self.logger.info(f"path = {path}")

        if path.find("openapi.yaml") != -1:
            return generate_swagger_yaml(self.logger, endpoint_id)
        else:
            function_name, path_parameters = get_function_name_and_path_parameters(
                self.logger, path
            )
            if path_parameters is not None:
                kwargs = dict(kwargs, **path_parameters)

            return execute_function(self.logger, function_name, **kwargs)
