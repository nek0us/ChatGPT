import unittest

from ChatGPTWeb.capabilities import discover_account_plan, infer_plan_from_model_categories


class AccountPlanDiscoveryTests(unittest.TestCase):
    def test_extracts_explicit_go_and_pro_plans(self):
        go = discover_account_plan({"subscription": {"plan": "ChatGPT Go"}}, "billing")
        pro = discover_account_plan({"entitlement_name": "pro"}, "billing")

        self.assertEqual(go.value, "go")
        self.assertEqual(go.source, "billing")
        self.assertEqual(pro.value, "pro")

    def test_conflicting_explicit_plans_remain_unknown(self):
        plan = discover_account_plan(
            {"subscription": {"plan": "plus"}, "entitlement": "pro"},
            "billing",
        )

        self.assertEqual(plan.value, "unknown")
        self.assertEqual(plan.source, "billing")

    def test_model_names_and_free_form_text_are_not_plan_evidence(self):
        plan = discover_account_plan(
            {"models": [{"title": "GPT Pro"}], "message": "Your Plus plan is active"},
            "billing",
        )

        self.assertEqual(plan.value, "unknown")
        self.assertEqual(plan.source, "unavailable")

    def test_model_category_inference_requires_one_unambiguous_tier(self):
        free = infer_plan_from_model_categories(["free", "free"], "models")
        mixed = infer_plan_from_model_categories(["free", "plus"], "models")

        self.assertEqual(free.value, "free")
        self.assertEqual(mixed.value, "unknown")


if __name__ == "__main__":
    unittest.main()
