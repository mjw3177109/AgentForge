"""Three immutable synthetic Django repair scenarios for V1.1 acceptance.

Fixtures are generated locally. No customer source, model response or secrets
are embedded. Cases exercise distinct logic and require independent tests.
"""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .v05_fixture import make_fixture


@dataclass(frozen=True)
class Scenario:
    identifier: str
    category: str
    source: str
    target_path: str
    tests: str
    requirement: str
    minimum_tests: int

    def manifest(self):
        return {
            "id": self.identifier,
            "category": self.category,
            "target_path": self.target_path,
            "requirement": self.requirement,
            "source_sha256": hashlib.sha256(self.source.encode()).hexdigest(),
            "tests_sha256": hashlib.sha256(self.tests.encode()).hexdigest(),
            "minimum_tests": self.minimum_tests,
        }


SCENARIOS = (
    Scenario(
        identifier="arith-001",
        category="arithmetic",
        target_path="app/views.py",
        source="def add(a, b):\n    return a - b\n",
        tests=(
            "from django.test import SimpleTestCase\n"
            "from .views import add\n"
            "class AdditionTests(SimpleTestCase):\n"
            "    def test_positive(self): self.assertEqual(add(3, 2), 5)\n"
            "    def test_negative(self): self.assertEqual(add(-4, 2), -2)\n"
            "    def test_zero(self): self.assertEqual(add(0, 7), 7)\n"
        ),
        requirement=(
            "Fix only app/views.py. The existing add(a, b) helper must calculate "
            "mathematically correct addition for positive, negative and zero "
            "inputs. Preserve the function name/signature and existing tests."
        ),
        minimum_tests=3,
    ),
    Scenario(
        identifier="pricing-002",
        category="integer_discount",
        target_path="app/pricing.py",
        source=(
            "def final_price(cents, percent):\n"
            "    return cents + cents * percent // 100\n"
        ),
        tests=(
            "from django.test import SimpleTestCase\n"
            "from .pricing import final_price\n"
            "class PricingTests(SimpleTestCase):\n"
            "    def test_discount(self): self.assertEqual(final_price(200, 25), 150)\n"
            "    def test_no_discount(self): self.assertEqual(final_price(150, 0), 150)\n"
            "    def test_full_discount(self): self.assertEqual(final_price(150, 100), 0)\n"
            "    def test_integer_round_down(self): self.assertEqual(final_price(101, 10), 90)\n"
        ),
        requirement=(
            "Fix only app/pricing.py. final_price(cents, percent) accepts "
            "nonnegative integer cents and integer discounts 0-100 inclusive. "
            "Return the discounted cents as an integer using floor division. "
            "Correct zero/full discounts and rounding. Never change tests."
        ),
        minimum_tests=4,
    ),
    Scenario(
        identifier="access-003",
        category="object_authorization",
        target_path="app/access.py",
        source=(
            "def may_read(actor_id, owner_id, is_staff=False):\n"
            "    return True\n"
        ),
        tests=(
            "from django.test import SimpleTestCase\n"
            "from .access import may_read\n"
            "class AccessTests(SimpleTestCase):\n"
            "    def test_owner(self): self.assertTrue(may_read(7, 7))\n"
            "    def test_staff(self): self.assertTrue(may_read(8, 7, is_staff=True))\n"
            "    def test_foreign_user(self): self.assertFalse(may_read(8, 7))\n"
            "    def test_anonymous(self): self.assertFalse(may_read(None, 7))\n"
            "    def test_anonymous_staff_flag(self): self.assertFalse(may_read(None, 7, True))\n"
        ),
        requirement=(
            "Fix only app/access.py. may_read(actor_id, owner_id, is_staff=False) "
            "must deny anonymous actor_id=None even if is_staff is true. "
            "Allow authenticated owner or authenticated staff; deny other users. "
            "Keep the public signature and existing Django tests unchanged."
        ),
        minimum_tests=5,
    ),
)


def suite_fingerprint():
    payload = [x.manifest() for x in SCENARIOS]
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def make_scenario(root: Path, scenario: Scenario):
    if scenario not in SCENARIOS:
        raise ValueError("Scenario is not from approved V1.1 test suite")
    make_fixture(root)
    target = root / scenario.target_path
    if target != root / "app/views.py":
        target.write_text(scenario.source, "utf-8")
        (root / "app/views.py").write_text("# deliberate unrelated source\n", "utf-8")
    else:
        target.write_text(scenario.source, "utf-8")
    (root / "app/tests.py").write_text(scenario.tests, "utf-8")
    return root
