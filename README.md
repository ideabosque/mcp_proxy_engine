# MCP Proxy Engine

A high-performance proxy engine for MCP (Model Context Protocol) servers with HTTP/2 support, connection pooling, and concurrent request execution.

## Features

### Core Features
- **MCP Server Integration**: Seamlessly integrate with multiple MCP servers
- **Dynamic Tool Discovery**: Automatically discover and register MCP tools
- **GraphQL Support**: Built-in GraphQL query execution
- **OpenAPI/Swagger Generation**: Automatic API documentation generation
- **AWS Lambda Integration**: Serverless-ready architecture

### Performance Features (New!)
- **HTTP/2 Support**: Multiplexing for concurrent requests over single connections
- **Connection Pooling**: Efficient connection reuse with configurable limits
- **Concurrent Execution**: Execute multiple tool calls in parallel
- **Automatic Retry**: Built-in retry logic with exponential backoff
- **Graceful Degradation**: Automatic fallback to HTTP/1.1 when needed

## Installation

```bash
# Install from source
pip install -e .

# Or install with setup.py
python setup.py install
```

### Dependencies

- Python >= 3.8
- httpx[http2] >= 0.27.0 - HTTP client with HTTP/2 support
- h2 >= 4.1.0 - HTTP/2 protocol implementation
- mcp_http_client - MCP HTTP client library
- silvaengine_utility - Utility functions
- boto3 - AWS SDK for Lambda integration

## Quick Start

### Basic Usage

```python
import logging
from mcp_proxy_engine import McpProxyEngine

logger = logging.getLogger(__name__)

# Configuration
setting = {
    "title": "My MCP API",
    "version": "1.0.0",
    "servers": [{"url": "https://api.example.com"}],
    "region_name": "us-east-1",
    "aws_access_key_id": "YOUR_ACCESS_KEY",
    "aws_secret_access_key": "YOUR_SECRET_KEY",
}

# Initialize engine
engine = McpProxyEngine(logger, **setting)

# Execute request
result = engine.mcp_proxy_dispatch(
    endpoint_id="my_endpoint",
    path="get_user/123",
)
```

### HTTP/2 Configuration

```python
setting = {
    "title": "High Performance API",
    "version": "1.0.0",
    "servers": [{"url": "https://api.example.com"}],
    
    # HTTP/2 Performance Configuration
    "http2_config": {
        "enable_http2": True,                    # Enable HTTP/2 (default: True)
        "max_connections": 100,                  # Max total connections
        "max_keepalive_connections": 20,         # Max idle connections
        "keepalive_expiry": 30.0,                # Idle timeout (seconds)
        "request_timeout": 30.0,                 # Request timeout (seconds)
        "enable_concurrent_requests": True,      # Enable parallel execution
    },
}

engine = McpProxyEngine(logger, **setting)
```

### Concurrent Request Execution

```python
from mcp_proxy_engine.handlers.function_handler import execute_concurrent_functions

# Execute multiple functions in parallel via HTTP/2
tool_calls = [
    {"function_name": "get_user", "arguments": {"user_id": "123"}},
    {"function_name": "get_orders", "arguments": {"user_id": "123"}},
    {"function_name": "get_preferences", "arguments": {"user_id": "123"}},
]

# This executes all 3 functions concurrently
results = execute_concurrent_functions(logger, tool_calls)
```



## Configuration

### Basic Configuration

```python
setting = {
    # API Metadata
    "title": "My API",
    "version": "1.0.0",
    "servers": [{"url": "https://api.example.com"}],
    
    # AWS Configuration
    "region_name": "us-east-1",
    "aws_access_key_id": "YOUR_ACCESS_KEY",
    "aws_secret_access_key": "YOUR_SECRET_KEY",
    
    # Response Mappings (optional)
    "response_mappings": {
        "/get_user/{user_id}": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
            }
        }
    },
    
    # Internal MCP Server (optional)
    "internal_mcp": {
        "base_url": "https://internal-mcp.example.com/{endpoint_id}",
        "bearer_token": "YOUR_BEARER_TOKEN",
    },
}
```

### HTTP/2 Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_http2` | bool | True | Enable HTTP/2 protocol support |
| `max_connections` | int | 100 | Maximum total connections in pool |
| `max_keepalive_connections` | int | 20 | Maximum idle connections to keep |
| `keepalive_expiry` | float | 30.0 | Idle connection timeout (seconds) |
| `request_timeout` | float | 30.0 | Request timeout (seconds) |
| `enable_concurrent_requests` | bool | True | Enable concurrent request execution |

### Configuration Presets

#### High Throughput

```python
"http2_config": {
    "enable_http2": True,
    "max_connections": 200,
    "max_keepalive_connections": 50,
    "keepalive_expiry": 60.0,
    "request_timeout": 10.0,
    "enable_concurrent_requests": True,
}
```

#### Serverless/Lambda

```python
"http2_config": {
    "enable_http2": True,
    "max_connections": 20,
    "max_keepalive_connections": 5,
    "keepalive_expiry": 10.0,
    "request_timeout": 30.0,
    "enable_concurrent_requests": True,
}
```

#### Conservative

```python
"http2_config": {
    "enable_http2": True,
    "max_connections": 50,
    "max_keepalive_connections": 10,
    "keepalive_expiry": 15.0,
    "request_timeout": 60.0,
    "enable_concurrent_requests": False,
}
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   McpProxyEngine                        │
│                                                         │
│  ┌──────────────┐         ┌─────────────────┐         │
│  │   Config     │◄────────┤ HTTP/2 Settings │         │
│  └──────┬───────┘         └─────────────────┘         │
│         │                                               │
│         │ initialize                                    │
│         ▼                                               │
│  ┌──────────────────────────────────────┐             │
│  │     HTTP2ClientManager               │             │
│  │  ┌────────────────────────────────┐  │             │
│  │  │  HTTP2ClientPool (Server 1)    │  │             │
│  │  │  - HTTP/2 multiplexing         │  │             │
│  │  │  - Connection pooling          │  │             │
│  │  │  - Automatic retry             │  │             │
│  │  │  - Metrics tracking            │  │             │
│  │  └────────────────────────────────┘  │             │
│  └──────────────────────────────────────┘             │
│                                                         │

└─────────────────────────────────────────────────────────┘
```

## Performance

### Expected Improvements with HTTP/2

| Scenario | HTTP/1.1 | HTTP/2 | Improvement |
|----------|----------|--------|-------------|
| Single Request | 100ms | 95ms | 5% faster |
| 10 Sequential | 1000ms | 950ms | 5% faster |
| 10 Concurrent | 1000ms | 200ms | **5x faster** |
| 50 Concurrent | 5000ms | 500ms | **10x faster** |

### Performance Metrics

Get comprehensive performance metrics:

```python
from mcp_proxy_engine.handlers.config import Config

# Get HTTP/2 specific metrics
metrics = Config.get_http2_performance_metrics(logger)
print(metrics)

# Example output:
{
    "https://api.example.com": {
        "total_requests": 1000,
        "successful_requests": 995,
        "failed_requests": 5,
        "success_rate_percent": 99.5,
        "avg_latency_ms": 45.2,
        "http2_requests": 1000,
        "http1_requests": 0,
        "http2_usage_percent": 100.0,
        "max_concurrent_requests": 50
    }
}
```

## API Reference

### McpProxyEngine

Main engine class for MCP proxy operations.

```python
class McpProxyEngine:
    def __init__(self, logger: logging.Logger, **setting: Dict[str, Any])
    def mcp_proxy_dispatch(self, **kwargs: Dict[str, Any]) -> Any
```

### Config

Centralized configuration management.

```python
class Config:
    @classmethod
    def initialize(cls, logger: logging.Logger, **setting: Dict[str, Any])
    
    @classmethod
    def initialize_mcp_http_clients(cls, logger: logging.Logger)
    
    @classmethod
    def get_http2_performance_metrics(cls, logger: logging.Logger) -> Dict
    
    @classmethod
    async def cleanup_http2_clients(cls, logger: logging.Logger)
```

### Function Execution

Execute MCP tools and functions.

```python
def execute_function(
    logger: logging.Logger,
    function_name: str,
    **kwargs: Dict[str, Any]
) -> Optional[Dict]

def execute_concurrent_functions(
    logger: logging.Logger,
    tool_calls: List[Dict[str, Any]]
) -> List[Any]
```



## Examples

See the `examples/` directory for complete examples:

- `http2_config_example.py` - Various HTTP/2 configurations
- Configuration presets for different scenarios
- Concurrent execution examples
- Error handling patterns

## Documentation

See the `examples/` directory for configuration examples and usage patterns.

## Best Practices

1. **Use concurrent execution for independent requests**
   ```python
   # Good
   results = execute_concurrent_functions(logger, tool_calls)
   
   # Avoid (sequential)
   results = [execute_function(logger, f, **args) for f, args in tool_calls]
   ```

2. **Configure connection pool based on load**
   ```python
   # High load
   "http2_config": {"max_connections": 200}
   
   # Low load / Serverless
   "http2_config": {"max_connections": 20}
   ```

3. **Handle errors gracefully**
   ```python
   try:
       results = execute_concurrent_functions(logger, tool_calls)
       for i, result in enumerate(results):
           if isinstance(result, Exception):
               logger.error(f"Request {i} failed: {result}")
   except Exception as e:
       logger.error(f"Batch failed: {e}")
   ```

## Troubleshooting

### HTTP/2 not being used

```python
# Check configuration
assert setting["http2_config"]["enable_http2"] == True

# Check metrics
metrics = Config.get_http2_performance_metrics(logger)
print(f"HTTP/2 usage: {metrics['http2_usage_percent']}%")
```

### High latency

```python
# Enable debug logging
logger.setLevel(logging.DEBUG)

# Increase connection pool
"http2_config": {"max_connections": 200}
```

### Connection pool exhausted

```python
# Increase pool size
"http2_config": {
    "max_connections": 500,
    "max_keepalive_connections": 100
}
```

## Development

### Setup

```bash
# Clone repository
git clone <repository-url>
cd mcp_proxy_engine

# Install in development mode
pip install -e .

# Install development dependencies
pip install pytest pytest-asyncio pytest-cov
```

### Testing

```bash
# Run tests
pytest tests/

# Run with coverage
pytest --cov=mcp_proxy_engine tests/
```

### Type Checking

```bash
# Run type checker
pyright mcp_proxy_engine/
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

MIT License - See LICENSE file for details

## Support

For issues, questions, or feature requests:
- Open an issue on GitHub
- Check the examples in `examples/http2_config_example.py`
- Enable debug logging for troubleshooting

## Changelog

### Version 0.0.2 (Latest)
- Added HTTP/2 protocol support
- Implemented connection pooling
- Added concurrent request execution
- Added automatic retry with exponential backoff
- Comprehensive documentation and examples

### Version 0.0.1
- Initial release
- Basic MCP proxy functionality
- GraphQL support
- AWS Lambda integration
