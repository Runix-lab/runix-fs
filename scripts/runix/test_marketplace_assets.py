import struct
import unittest
import xml.etree.ElementTree as xml
from pathlib import Path


DIRECTORY = Path(__file__).resolve().parents[2] / "images" / "marketplace"


class MarketplaceAssetTests(unittest.TestCase):
    def test_png_dimensions_and_opaque_gallery(self):
        for name, dimensions in (
            ("runix-logo-320.png", (320, 320)),
            ("runix-fs-overview-780x439.png", (780, 439)),
        ):
            with self.subTest(name=name):
                data = (DIRECTORY / name).read_bytes()
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(data[12:16], b"IHDR")
                self.assertEqual(struct.unpack(">II", data[16:24]), dimensions)
                if "overview" in name:
                    self.assertEqual(data[25], 2)
                    self.assertNotIn(b"tRNS", data)

    def test_preview_discloses_status_and_attribution(self):
        document = xml.parse(DIRECTORY / "runix-fs-overview.svg")
        text = " ".join(document.getroot().itertext())
        for required in (
            "PRODUCT PREVIEW", "Commercial onboarding in preparation",
            "Apache-2.0", "Curvine", "runixcloud.io/fs",
        ):
            self.assertIn(required, text)
        for forbidden in ("99.99%", "10 PiB", "1000 clients", "JuiceFS", "6.6 TiB"):
            self.assertNotIn(forbidden, text)

    def test_vectors_have_no_executable_or_external_dependencies(self):
        for source in DIRECTORY.glob("*.svg"):
            document = xml.parse(source)
            for element in document.iter():
                self.assertNotIn(element.tag.split("}")[-1], {"script", "foreignObject"})
                for attribute, value in element.attrib.items():
                    self.assertFalse(attribute.lower().startswith("on"))
                    if attribute.endswith("href"):
                        self.assertTrue(value.startswith("#"))


if __name__ == "__main__":
    unittest.main()
