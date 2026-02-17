from typing import Any, Dict, Optional, List
import json
import logging

import httpx

from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.core.security import is_egress_enabled
from spectra_sherpa.app.services.dag.node_base import Node, NodeMetadata, NodeParameter, PortMetadata, register_node
from spectra_sherpa.app.services.dag.meta_helpers import safe_get_coord

logger = logging.getLogger(__name__)


async def check_cloud_health(url: str, api_key: Optional[str] = None, timeout: float = 5.0) -> tuple[bool, str]:
    """
    Check if the cloud compute endpoint is healthy and reachable.

    Args:
        url: Base URL of the cloud service
        api_key: Optional API key for authentication
        timeout: Timeout in seconds for the health check

    Returns:
        Tuple of (is_healthy, message)
    """
    health_url = f"{url.rstrip('/')}/api/v1/health"
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(health_url, headers=headers, timeout=timeout)

            if response.status_code == 200:
                return True, "Cloud service is healthy"
            elif response.status_code == 401:
                return False, "Cloud authentication failed. Check your CLOUD_API_KEY."
            elif response.status_code == 403:
                return False, "Access denied to cloud service. Check your permissions."
            else:
                return False, f"Cloud service returned status {response.status_code}"

    except httpx.ConnectError:
        return False, f"Cannot connect to cloud service at {url}. Check the URL and network."
    except httpx.TimeoutException:
        return False, f"Cloud service at {url} is not responding (timeout after {timeout}s)."
    except Exception as e:
        return False, f"Error checking cloud health: {str(e)}"

@register_node
class CloudComputeNode(Node):
    metadata = NodeMetadata(
        node_type="compute.cloud_algorithm",
        category="advanced",
        label="Cloud Compute Algorithm",
        description="Offload computation to the cloud API (requires Hybrid mode).",
        parameters=[
            NodeParameter(
                name="algorithm_id",
                label="Algorithm ID",
                param_type="select",
                default="advanced_baseline",
                options=[
                    {"label": "Deep Learning Baseline", "value": "advanced_baseline"},
                    {"label": "Transformer Peak Picking", "value": "transformer_peaks"},
                ],
                description="The specific cloud-only algorithm to execute."
            ),
            NodeParameter(
                name="timeout",
                label="Timeout (seconds)",
                param_type="number",
                default=60,
                min_value=10,
                max_value=300,
                description="Maximum time to wait for the cloud result."
            )
        ],
        input_ports=[
            PortMetadata(name="input_data", type_ref="spectrasherpa://types/SpectralDataset/1.0", label="Input Spectra"),
        ],
        output_ports=[
            PortMetadata(name="output_data", type_ref="spectrasherpa://types/SpectralDataset/1.0", label="Result"),
        ]
    )

    def _serialize_data(self, data: Any) -> Any:
        """
        Helper to serialize data for JSON transmission.
        Handles numpy arrays, NDDatasets (mock), and basic types.
        """
        # Handle dicts recursively
        if isinstance(data, dict):
            return {k: self._serialize_data(v) for k, v in data.items()}
        
        # Handle lists recursively
        if isinstance(data, list):
            return [self._serialize_data(v) for v in data]

        # Handle numpy arrays if numpy is available or if data looks like an array
        if hasattr(data, "tolist"):
             return data.tolist()
        
        # Handle XArray/NDDataset if it has a .values property that is an array
        if hasattr(data, "values") and hasattr(data.values, "tolist"):
            return {
                "values": data.values.tolist(),
                "dims": getattr(data, "dims", None),
                "coords": {k: self._serialize_data(v) for k, v in getattr(data, "coords", {}).items()} if hasattr(data, "coords") else None
            }

        return data

    async def execute(self, input_data: Any, **kwargs) -> Any:
        algorithm_id = self.parameters.get("algorithm_id", "advanced_baseline")
        timeout = self.parameters.get("timeout", 60)

        # Egress guard — block outbound requests when egress is disabled
        # (local mode default, or hybrid mode with degraded network)
        if not is_egress_enabled():
            raise RuntimeError(
                "Network egress is disabled. Cloud compute requires egress to be enabled. "
                "Set EGRESS_ENABLED=true or use APP_MODE=hybrid to allow outbound requests."
            )

        # Check configuration
        if not app_config.cloud_compute_url:
            raise RuntimeError(
                "Cloud Compute URL is not configured. "
                "Please set CLOUD_COMPUTE_URL in your environment or enable Hybrid Mode in settings."
            )

        # Health check - verify cloud service is reachable before attempting computation
        is_healthy, health_message = await check_cloud_health(
            app_config.cloud_compute_url,
            app_config.cloud_api_key,
            timeout=min(timeout / 10, 5.0)  # Use 10% of timeout or 5s max for health check
        )
        if not is_healthy:
            raise RuntimeError(f"Cloud service unavailable: {health_message}")

        logger.info(f"Cloud health check passed, executing {algorithm_id}")

        # Serialize input
        try:
            serialized_data = self._serialize_data(input_data)
        except Exception as e:
            raise RuntimeError(f"Failed to serialize input data for cloud transfer: {e}")

        # Extract metadata from input for preservation through cloud processing
        input_metadata = {
            "job_id": self.node_id,
        }

        # Try to extract axis metadata from input data
        if hasattr(input_data, "meta") and input_data.meta:
            meta = input_data.meta
            input_metadata.update({
                "x_title": meta.get("x_title"),
                "x_units": meta.get("x_units"),
                "y_title": meta.get("y_title"),
                "y_units": meta.get("y_units"),
            })
        elif hasattr(input_data, "units"):
            input_metadata["y_units"] = str(input_data.units)

        # Try to get x-axis info from coords
        x_coord = safe_get_coord(input_data, 'x')
        if x_coord is not None and hasattr(x_coord, "title"):
            input_metadata["x_title"] = x_coord.title
            if hasattr(x_coord, "units"):
                input_metadata["x_units"] = str(x_coord.units)

        payload = {
            "algorithm_id": algorithm_id,
            "data": serialized_data,
            "metadata": input_metadata
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        if app_config.cloud_api_key:
            headers["X-API-Key"] = app_config.cloud_api_key

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{app_config.cloud_compute_url.rstrip('/')}/api/v1/compute/execute",
                    json=payload,
                    headers=headers,
                    timeout=timeout
                )
                
                if response.status_code == 401:
                    raise RuntimeError("Cloud authentication failed. Check CLOUD_API_KEY setting.")
                
                response.raise_for_status()

                result_data = response.json()

                # Check for error in response
                if not result_data.get("success", True):
                    error_msg = result_data.get("error", "Unknown cloud computation error")
                    raise RuntimeError(f"Cloud computation failed: {error_msg}")

                # Log processing info if available
                if result_data.get("processing_info"):
                    logger.info(f"Cloud processing info: {result_data['processing_info']}")

                # Return the result in a format that downstream nodes can use
                # The ComputeResponse format preserves metadata for reconstruction
                return result_data

            except httpx.HTTPStatusError as e:
                raise RuntimeError(f"Cloud computation failed ({e.response.status_code}): {e.response.text}")
            except httpx.RequestError as e:
                raise RuntimeError(f"Could not connect to cloud service: {str(e)}")
            except Exception as e:
                raise RuntimeError(f"Unexpected error during cloud computation: {str(e)}")
