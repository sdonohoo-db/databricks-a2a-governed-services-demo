import unittest

from databricks_config import (
    build_mcp_server_configs,
    public_app_url,
    qualified_tool_name,
)


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

    def test_url_is_required(self):
        with self.assertRaisesRegex(RuntimeError, "DATABRICKS_APP_URL is required"):
            public_app_url({})


if __name__ == "__main__":
    unittest.main()
