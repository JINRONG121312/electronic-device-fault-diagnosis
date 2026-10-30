import unittest

from fru_diagnosis.model_registry import discover_registry_paths, find_known_model


class ModelRegistryTests(unittest.TestCase):
    def test_match_asus_tianxuan5_fx607jv(self):
        match = find_known_model(
            device_type="laptop",
            manufacturer="ASUSTeK COMPUTER INC.",
            model="ASUS TUF Gaming F16 FX607JV_FX607JV",
            display_name="华硕天选5pro",
        )

        self.assertIsNotNone(match)
        assert match is not None
        self.assertGreaterEqual(match.score, 60)
        self.assertIn("fx607", match.profile.model_family.casefold())
        self.assertIn("pro", match.profile.display_name.casefold())
        self.assertIn("configs", str(match.profile.config_path.parent))

    def test_discover_asus_laptop_registry_by_vendor_folder(self):
        paths = discover_registry_paths(
            device_type="laptop",
            manufacturer="ASUSTeK COMPUTER INC.",
        )

        self.assertEqual(len(paths), 1)
        self.assertIn("laptops", str(paths[0]))
        self.assertIn("asus", str(paths[0]))

    def test_match_lenovo_ideapad_81yl(self):
        match = find_known_model(
            device_type="laptop",
            manufacturer="LENOVO",
            model="81YL",
            display_name="LENOVO 81YL",
        )

        self.assertIsNotNone(match)
        assert match is not None
        self.assertGreaterEqual(match.score, 60)
        self.assertIn("81yl", match.profile.model_family.casefold())
        self.assertIn("ideapad", match.profile.display_name.casefold())
        self.assertEqual(
            match.profile.config_path.name,
            "lenovo_ideapad_5_15iil05_81yl.json",
        )

    def test_discover_lenovo_laptop_registry_by_vendor_folder(self):
        paths = discover_registry_paths(
            device_type="laptop",
            manufacturer="LENOVO",
        )

        self.assertEqual(len(paths), 1)
        self.assertIn("laptops", str(paths[0]))
        self.assertIn("lenovo", str(paths[0]))

    def test_server_registry_is_reserved_and_empty(self):
        match = find_known_model(
            device_type="server",
            manufacturer="ASUSTeK COMPUTER INC.",
            model="ASUS TUF Gaming F16 FX607JV_FX607JV",
        )

        self.assertIsNone(match)


if __name__ == "__main__":
    unittest.main()
