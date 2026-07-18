from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "amazon-ads-optimizer" / "SKILL.md"
PLAYBOOK = ROOT / ".agents" / "skills" / "amazon-ads-optimizer" / "references" / "optimization-playbook.md"


class NexscopeAdsFusionContractTests(unittest.TestCase):
    def test_ads_optimizer_absorbs_only_requested_advertising_frameworks(self):
        text = SKILL.read_text(encoding="utf-8")

        for skill_name in [
            "amazon-ppc-campaign",
            "amazon-advertising-strategy",
            "amazon-negative-keywords",
            "amazon-display-ads",
        ]:
            self.assertIn(skill_name, text)

        self.assertIn("Do not absorb other Nexscope Amazon-Skills", text)
        self.assertIn("amazon-agent-orchestrator", text)

    def test_ads_playbook_declares_campaign_blueprint_controls(self):
        text = PLAYBOOK.read_text(encoding="utf-8")

        for term in [
            "campaign_mode",
            "ad_channel_scope",
            "negative_keyword_policy",
            "campaign_blueprint_inputs",
            "Auto -> Broad/Phrase -> Exact",
            "Sponsored Products, Sponsored Brands, and Sponsored Display",
        ]:
            self.assertIn(term, text)


if __name__ == "__main__":
    unittest.main()
