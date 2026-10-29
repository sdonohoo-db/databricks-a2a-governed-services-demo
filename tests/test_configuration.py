import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src" / "a2a-provider"))
sys.path.insert(0, str(Path(__file__).parents[1] / "setup"))

from databricks_config import (
    build_mcp_server_configs,
    public_app_url,
    qualified_tool_name,
)
from render_demo_function import quote_function_name, render_sql


class MCPConfigurationTests(unittest.TestCase):
    def test_multiple_backends(self):
        configs = build_mcp_server_configs(
            {
                "MCP_BACKENDS": "genie,functions",
                "GENIE_SPACE_ID": "space-123",
                "UC_FUNCTION_NAME": "catalog.schema.demo_function",
            },
            workspace_host="https://example.cloud.databricks.com/",
        )

        self.assertEqual([config.key for config in configs], ["genie", "functions"])
        self.assertEqual(
            configs[0].url,
            "https://example.cloud.databricks.com/api/2.0/mcp/genie/space-123",
        )
        self.assertEqual(
            configs[1].url,
            "https://example.cloud.databricks.com/api/2.0/mcp/functions/catalog/schema",
        )

    def test_legacy_single_backend(self):
        configs = build_mcp_server_configs(
            {
                "MCP_BACKEND": "functions",
                "UC_FUNCTIONS_CATALOG": "catalog",
                "UC_FUNCTIONS_SCHEMA": "schema",
            },
            workspace_host="https://example.cloud.databricks.com",
        )
        self.assertEqual([config.key for config in configs], ["functions"])

    def test_invalid_function_name(self):
        with self.assertRaisesRegex(RuntimeError, "three-part name"):
            build_mcp_server_configs(
                {"MCP_BACKEND": "functions", "UC_FUNCTION_NAME": "two.parts"},
                workspace_host="https://example.cloud.databricks.com",
            )

    def test_tool_names_are_namespaced_and_bounded(self):
        short = qualified_tool_name("genie", "query")
        long = qualified_tool_name("functions", "tool." + "x" * 100)

        self.assertEqual(short, "genie__query")
        self.assertLessEqual(len(long), 64)
        self.assertNotIn(".", long)


class PublicUrlTests(unittest.TestCase):
    def test_explicit_url_wins(self):
        self.assertEqual(
            public_app_url({"DATABRICKS_APP_URL": "https://custom.example/"}),
            "https://custom.example",
        )

    def test_url_is_derived_from_forwarded_headers(self):
        self.assertEqual(
            public_app_url(
                {},
                {
                    "x-forwarded-proto": "https",
                    "x-forwarded-host": "my-app.example.com",
                },
            ),
            "https://my-app.example.com",
        )

    def test_url_requires_configuration_or_request_host(self):
        with self.assertRaisesRegex(RuntimeError, "Unable to determine"):
            public_app_url({})


class DemoFunctionTemplateTests(unittest.TestCase):
    def test_renders_caller_supplied_function_name(self):
        sql = render_sql("my_catalog.agent_services.shipping_quote")
        self.assertIn("`my_catalog`.`agent_services`.`shipping_quote`", sql)
        self.assertNotIn("{{FUNCTION_NAME}}", sql)

    def test_function_name_must_have_three_parts(self):
        with self.assertRaisesRegex(ValueError, "three non-empty parts"):
            quote_function_name("catalog.schema")


if __name__ == "__main__":
    unittest.main()
