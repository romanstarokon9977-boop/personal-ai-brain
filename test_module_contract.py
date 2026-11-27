import unittest

from module_contract import ModuleManifestError, validate_catalog, validate_manifest


def manifest(module_id="sample", version="1.0.0", **overrides):
    value = {
        "schema_version": 1,
        "module_id": module_id,
        "name": "Sample module",
        "version": version,
        "api_version": 1,
        "entrypoint": "sample_module.entry",
        "description": "A safe sample module contract.",
        "capabilities": ["filesystem.read"],
        "dependencies": [],
        "permissions": ["filesystem.read"],
        "risk": "low",
        "auto_enable": False,
    }
    value.update(overrides)
    return value


class ModuleContractTests(unittest.TestCase):
    def test_boolean_schema_versions_are_rejected(self):
        with self.assertRaisesRegex(ModuleManifestError, "UNSUPPORTED_SCHEMA_VERSION"):
            validate_manifest(manifest(schema_version=True))
        with self.assertRaisesRegex(ModuleManifestError, "UNSUPPORTED_MODULE_API"):
            validate_manifest(manifest(api_version=True))

    def test_valid_manifest_is_normalized_without_execution(self):
        result = validate_manifest(manifest())
        self.assertEqual(result["module_id"], "sample")
        self.assertEqual(result["risk"], "low")
        self.assertFalse(result["auto_enable"])

    def test_entrypoint_path_traversal_and_unknown_fields_are_rejected(self):
        for invalid in (
            manifest(entrypoint="../outside.run"),
            manifest(entrypoint="/tmp/module.py"),
            manifest(extra="not allowed"),
            manifest(auto_enable=True),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ModuleManifestError):
                    validate_manifest(invalid)

    def test_capabilities_require_matching_permissions_and_risk(self):
        with self.assertRaisesRegex(ModuleManifestError, "CAPABILITY_WITHOUT_PERMISSION"):
            validate_manifest(manifest(permissions=[]))
        with self.assertRaisesRegex(ModuleManifestError, "RISK_UNDERCLASSIFIED"):
            validate_manifest(manifest(
                capabilities=["process.execute"],
                permissions=["process.execute"],
                risk="low",
            ))

    def test_catalog_orders_dependencies_before_dependants(self):
        base = manifest("base", "1.2.0")
        addon = manifest(
            "addon",
            dependencies=[{"module_id": "base", "minimum_version": "1.1.0"}],
        )
        result = validate_catalog([addon, base])
        self.assertEqual(result["dependency_order"], ["base", "addon"])
        self.assertFalse(result["enabled"])
        self.assertFalse(result["executed"])

    def test_missing_or_incompatible_dependency_is_rejected(self):
        with self.assertRaisesRegex(ModuleManifestError, "DEPENDENCY_MISSING"):
            validate_catalog([manifest(
                "addon", dependencies=[{"module_id": "base", "minimum_version": "1.0.0"}]
            )])
        with self.assertRaisesRegex(ModuleManifestError, "DEPENDENCY_VERSION_UNSATISFIED"):
            validate_catalog([
                manifest("base", "1.0.0"),
                manifest("addon", dependencies=[{"module_id": "base", "minimum_version": "2.0.0"}]),
            ])

    def test_duplicate_ids_and_dependency_cycles_are_rejected(self):
        with self.assertRaisesRegex(ModuleManifestError, "DUPLICATE_MODULE_ID"):
            validate_catalog([manifest("same"), manifest("same", "2.0.0")])
        with self.assertRaisesRegex(ModuleManifestError, "DEPENDENCY_CYCLE"):
            validate_catalog([
                manifest("alpha", dependencies=[{"module_id": "beta", "minimum_version": "1.0.0"}]),
                manifest("beta", dependencies=[{"module_id": "alpha", "minimum_version": "1.0.0"}]),
            ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
