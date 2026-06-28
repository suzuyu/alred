import importlib.util
import pathlib
import sys
import types
import unittest


def _load_transform_module():
    package_root = pathlib.Path(__file__).resolve().parents[1] / "alred"

    if "alred" not in sys.modules:
        package = types.ModuleType("alred")
        package.__path__ = [str(package_root)]
        sys.modules["alred"] = package

    templates_module = types.ModuleType("alred.templates")
    templates_module.render_named_template_lines = lambda _name, _context: []
    sys.modules["alred.templates"] = templates_module

    transform_spec = importlib.util.spec_from_file_location("alred.transform", package_root / "transform.py")
    transform_module = importlib.util.module_from_spec(transform_spec)
    sys.modules["alred.transform"] = transform_module
    assert transform_spec.loader is not None
    transform_spec.loader.exec_module(transform_module)
    return transform_module


transform_run_config_text = _load_transform_module().transform_run_config_text


class TransformRunConfigTextTests(unittest.TestCase):
    def test_inserts_no_switchport_for_interface_with_ip_address(self) -> None:
        source = """interface Ethernet1/7
  description spsw0102 eth1/1
  mtu 9216
  port-type fabric
  ip address 10.0.4.0/31
  ip ospf network point-to-point
  ip router ospf UNDERLAY area 0.0.0.0
  ip ospf bfd
  no shutdown
"""

        transformed, _stats = transform_run_config_text(source, None)

        self.assertEqual(
            transformed,
            """interface Ethernet1/7
  description spsw0102 eth1/1
  no switchport
  mtu 9216
  port-type fabric
  ip address 10.0.4.0/31
  ip ospf network point-to-point
  ip router ospf UNDERLAY area 0.0.0.0
  ip ospf bfd
  no shutdown
""",
        )
        self.assertEqual(_stats["inserted_no_switchport"], 1)

if __name__ == "__main__":
    unittest.main()
