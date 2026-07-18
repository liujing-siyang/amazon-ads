import csv
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents" / "skills" / "amazon-ads-optimizer" / "scripts"
BOOK_NOOK_SKILL = ROOT / ".agents" / "skills" / "book-nook-ads-optimizer"


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_ad_csv(path, rows, include_manual=False):
    headers = [
        "顾客搜索词",
        "关键词",
        "展示量",
        "点击量",
        "点击率",
        "总成本 (AUD)",
        "CPC (AUD)",
        "购买量",
        "销售额 (AUD)",
        "ACOS",
        "ROAS",
        "购买率",
    ]
    if include_manual:
        headers = ["已添加为"] + headers[:2] + ["目标竞价 (AUD)"] + headers[2:]
    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


class BookNookAdsOptimizerTests(unittest.TestCase):
    def test_theme_profile_defaults_and_merges_book_nook_knowledge(self):
        optimizer = load_module("book_nook_optimizer")
        knowledge = {
            "core_keywords": {
                "book nook": {"monthly_search_volume": 5291},
                "book nook kit": {"monthly_search_volume": 2442},
            },
            "competitor_brands": ["CUTEBEE"],
            "long_term_pre_negatives": ["kindle", "reading light"],
        }
        context = {
            "scope_id": "B0TESTBOOK1",
            "asins": ["B0TESTBOOK1"],
            "theme_label": "BookNook_Tavern",
            "theme_longtail_terms": ["corner tavern book nook", "pub book nook"],
            "generic_observation_terms": ["miniature house kit"],
        }

        profile = optimizer.build_theme_profile(context, knowledge)

        self.assertEqual(profile["theme_label"], "BookNook_Tavern")
        self.assertIn("book nook", profile["core_terms"])
        self.assertIn("book nook kit", profile["core_terms"])
        self.assertIn("booknook", profile["core_terms"])
        self.assertIn("corner tavern book nook", profile["theme_longtail_terms"])
        self.assertIn("miniature house kit", profile["generic_observation_terms"])
        negative_terms = [item["term"] for item in profile["pre_negative_terms"]]
        self.assertIn("kindle", negative_terms)
        self.assertIn("reading light", negative_terms)
        self.assertIn("CUTEBEE", profile["competitor_brands"])
        combined = json.dumps(profile, ensure_ascii=False)
        self.assertNotIn("japanese book nook", combined)
        self.assertNotIn("book nook library", combined)

    def test_book_nook_workflow_generates_three_pack_and_middle_files(self):
        importer = load_module("import_ad_reports")
        optimizer = load_module("book_nook_optimizer")
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            db = td / "ads.sqlite"
            auto = td / "auto.csv"
            manual = td / "manual.csv"
            write_ad_csv(auto, [{
                "顾客搜索词": "book nook", "关键词": "close-match", "展示量": "200", "点击量": "20",
                "点击率": "0.1", "总成本 (AUD)": "6.00", "CPC (AUD)": "0.30", "购买量": "2",
                "销售额 (AUD)": "120.00", "ACOS": "0.05", "ROAS": "20", "购买率": "0.1",
            }])
            write_ad_csv(manual, [{
                "已添加为": "关键词: 词组匹配", "顾客搜索词": "corner tavern book nook",
                "关键词": "corner tavern book nook", "目标竞价 (AUD)": "0.4", "展示量": "50",
                "点击量": "5", "点击率": "0.1", "总成本 (AUD)": "1.50", "CPC (AUD)": "0.30",
                "购买量": "1", "销售额 (AUD)": "65.99", "ACOS": "0.0227", "ROAS": "44",
                "购买率": "0.2",
            }], include_manual=True)
            importer.import_report(db, auto, metadata={
                "report_start": "2026-05-12",
                "report_end": "2026-07-15",
                "asin": "B0TESTBOOK1",
                "ad_mode": "automatic",
            })
            importer.import_report(db, manual, metadata={
                "report_start": "2026-05-12",
                "report_end": "2026-07-15",
                "asin": "B0TESTBOOK1",
                "ad_mode": "manual",
            })
            context_path = td / "context.json"
            context_path.write_text(json.dumps({
                "scope_id": "B0TESTBOOK1",
                "asins": ["B0TESTBOOK1"],
                "shared_id": None,
                "theme_label": "BookNook_Tavern",
                "parent_label": "BookNook_Tavern",
                "theme_longtail_terms": ["corner tavern book nook", "pub book nook"],
                "keyword_details": {"book nook": {"月搜索量": 5291}},
                "keyword_search_results": {"book nook": [{"ASIN": "B0COMPET01", "品牌": "CUTEBEE", "标题": "Book Nook Kit"}]},
            }, ensure_ascii=False), encoding="utf-8")

            result = optimizer.run_book_nook_optimization(
                db_path=db,
                context_json=context_path,
                output_root=td,
                report_prefix=td / "reports" / "B0TESTBOOK1_sorftime_launch_plan_2026-07-15",
                knowledge_json=td / "configs" / "book_nook_category_knowledge.json",
                knowledge_md=td / "reports" / "book_nook_category_knowledge.md",
                generated_at="2026-07-15",
            )

            files = result["files"]
            self.assertTrue(Path(files["html_report"]).exists())
            self.assertTrue(Path(files["campaign_build_csv"]).exists())
            self.assertTrue(Path(files["pre_negatives_csv"]).exists())
            self.assertTrue(Path(files["json_config"]).exists())
            for path in result["middle_files"].values():
                self.assertTrue(Path(path).exists())
            campaign = Path(files["campaign_build_csv"]).read_text(encoding="utf-8-sig")
            config = json.loads(Path(files["json_config"]).read_text(encoding="utf-8"))
            self.assertIn("SP_AUTO_Research_BookNook_Tavern", campaign)
            self.assertIn("SP_EXACT_Core_BookNook_Tavern", campaign)
            self.assertIn("SP_PHRASE_Longtail_BookNook_Tavern", campaign)
            self.assertIn("SP_PRODUCT_ASIN_Test_BookNook", campaign)
            self.assertIn("SP_RANKING_Push_Selected", campaign)
            self.assertIsNone(config["shared_id"])
            forbidden = campaign + json.dumps(config, ensure_ascii=False)
            self.assertNotIn("Pillow Speaker", forbidden)
            self.assertNotIn("SP_PHRASE_Longtail_Japanese", forbidden)
            self.assertNotIn("B0G4D6CQRQ-B0FQNHGLPZ", forbidden)
            with closing(sqlite3.connect(db)) as conn:
                artifacts = conn.execute("select count(*) from analysis_artifacts where scope_id='B0TESTBOOK1'").fetchone()[0]
            self.assertGreaterEqual(artifacts, 6)

    def test_forest_florist_new_launch_without_ads_data_does_not_leak_old_themes(self):
        optimizer = load_module("book_nook_optimizer")
        importer = load_module("import_ad_reports")
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            db = td / "ads.sqlite"
            importer.ensure_schema(db)
            knowledge_json = td / "configs" / "book_nook_category_knowledge.json"
            knowledge_md = td / "reports" / "book_nook_category_knowledge.md"
            knowledge_json.parent.mkdir(parents=True, exist_ok=True)
            knowledge_json.write_text(json.dumps({
                "category": "Book Nook",
                "themes": [
                    {"parent_asin": "B0LIBRARY", "theme_label": "BookNook_Library", "asins": ["B0LIB"]},
                    {"parent_asin": "B0TAVERN", "theme_label": "BookNook_Tavern", "asins": ["B0TAV"]},
                ],
                "core_keywords": {
                    "book nook": {"monthly_search_volume": 5291},
                    "book nook library": {"monthly_search_volume": 0},
                    "corner tavern book nook": {"monthly_search_volume": 0},
                },
                "competitor_brands": ["CUTEBEE", "Rolife"],
                "long_term_pre_negatives": ["kindle", "reading light"],
            }, ensure_ascii=False), encoding="utf-8")
            context_path = td / "forest_context.json"
            context_path.write_text(json.dumps({
                "scope_id": "B0GYPTLQ7B",
                "asins": ["B0GYPTLQ7B"],
                "shared_id": None,
                "marketplace": "AU",
                "parent_asin": "B0GZG9X46R",
                "theme_label": "BookNook_Forest_Florist",
                "parent_label": "BookNook_Forest_Florist",
                "core_terms": ["book nook", "book nook kit", "booknook", "book nook kits australia"],
                "theme_longtail_terms": [
                    "flower house book nook",
                    "florist book nook",
                    "garden book nook",
                    "greenhouse book nook",
                    "forest book nook",
                    "enchanted forest book nook",
                    "wisteria book nook",
                    "plant shop book nook",
                ],
                "generic_observation_terms": [
                    "miniature house kit",
                    "diy miniature house kit",
                    "3d wooden puzzle",
                    "3d puzzles for adults",
                    "bookshelf decor",
                    "adult craft",
                    "dollhouse",
                ],
                "ranking_terms": ["book nook", "book nook kit"],
                "product_details": {"B0GYPTLQ7B": {"title": "French Florist Book Nook Kit", "monthly_sales": 5, "review_count": 0}},
                "keyword_details": {
                    "book nook": {"月搜索量": 5291, "词搜索量旺季": "11月, 12月"},
                    "book nook kit": {"月搜索量": 2442, "词搜索量旺季": "11月, 12月"},
                    "miniature house kit": {"月搜索量": 1382, "词搜索量旺季": "11月, 12月, 1月"},
                },
                "keyword_search_results": {
                    "book nook": [{"ASIN": "B0D8HLDR4R", "品牌": "CUTEBEE", "标题": "Book Nook Kit"}],
                    "book nook kit": [{"ASIN": "B0FXMC8D7V", "品牌": "CUTEBEE", "标题": "Flower House Florist Book Nook Kit"}],
                },
            }, ensure_ascii=False), encoding="utf-8")

            result = optimizer.run_book_nook_optimization(
                db_path=db,
                context_json=context_path,
                output_root=td,
                report_prefix=td / "reports" / "B0GYPTLQ7B_sorftime_launch_plan_2026-07-15",
                knowledge_json=knowledge_json,
                knowledge_md=knowledge_md,
                generated_at="2026-07-15",
            )

            campaign = Path(result["files"]["campaign_build_csv"]).read_text(encoding="utf-8-sig")
            negatives = Path(result["files"]["pre_negatives_csv"]).read_text(encoding="utf-8-sig")
            config_text = Path(result["files"]["json_config"]).read_text(encoding="utf-8")
            html = Path(result["files"]["html_report"]).read_text(encoding="utf-8")
            knowledge = json.loads(knowledge_json.read_text(encoding="utf-8"))
            combined = "\n".join([campaign, negatives, config_text, html])

            self.assertIn("SP_AUTO_Research_BookNook_Forest_Florist", campaign)
            self.assertIn("SP_EXACT_Core_BookNook_Forest_Florist", campaign)
            self.assertIn("SP_PHRASE_Longtail_BookNook_Forest_Florist", campaign)
            self.assertIn("flower house book nook", campaign)
            self.assertIn("greenhouse book nook", campaign)
            self.assertIn("B0FXMC8D7V", campaign)
            self.assertIn("kindle", negatives)
            self.assertIn("CUTEBEE", negatives)
            self.assertNotIn("corner tavern book nook", campaign)
            self.assertNotIn("book nook library", campaign)
            self.assertNotIn("SP_PHRASE_Longtail_Japanese", combined)
            self.assertNotIn("Pillow Speaker", combined)
            self.assertNotIn("锛", combined)
            self.assertNotIn("骞垮憡", combined)
            self.assertIn("BookNook_Library", [t["theme_label"] for t in knowledge["themes"]])
            self.assertIn("BookNook_Tavern", [t["theme_label"] for t in knowledge["themes"]])
            self.assertIn("BookNook_Forest_Florist", [t["theme_label"] for t in knowledge["themes"]])

    def test_forest_group_variant_launch_uses_firecrawl_listing_evidence_and_routes_terms(self):
        optimizer = load_module("book_nook_optimizer")
        importer = load_module("import_ad_reports")
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            db = td / "ads.sqlite"
            importer.ensure_schema(db)
            knowledge_json = td / "configs" / "book_nook_category_knowledge.json"
            knowledge_md = td / "reports" / "book_nook_category_knowledge.md"
            knowledge_json.parent.mkdir(parents=True, exist_ok=True)
            knowledge_json.write_text(json.dumps({
                "category": "Book Nook",
                "themes": [
                    {"parent_asin": "B0LIBRARY", "theme_label": "BookNook_Library", "asins": ["B0LIB"]},
                    {"parent_asin": "B0TAVERN", "theme_label": "BookNook_Tavern", "asins": ["B0TAV"]},
                ],
                "core_keywords": {},
                "competitor_brands": ["CUTEBEE", "Rolife"],
                "long_term_pre_negatives": ["kindle", "reading light"],
            }, ensure_ascii=False), encoding="utf-8")
            context_path = td / "forest_group_context.json"
            context_path.write_text(json.dumps({
                "scope_id": "B0GZG9X46R_Forest_Group",
                "asins": ["B0GYPTLQ7B", "B0GZ37K89Z"],
                "shared_id": None,
                "marketplace": "AU",
                "parent_asin": "B0GZG9X46R",
                "theme_label": "BookNook_Forest_Group",
                "parent_label": "BookNook_Forest_Group",
                "core_terms": ["book nook", "book nook kit", "booknook", "book nook kits australia"],
                "theme_longtail_terms": [
                    "flower house book nook",
                    "wisteria book nook",
                    "forest tea book club",
                    "enchanted forest book nook",
                    "tea club book nook",
                ],
                "generic_observation_terms": ["miniature house kit", "3d wooden puzzle", "bookshelf decor", "dollhouse"],
                "ranking_terms": ["book nook", "book nook kit"],
                "variant_routing_rules": {
                    "B0GYPTLQ7B": {"keywords": ["flower house", "florist", "wisteria", "plant shop", "french florist"]},
                    "B0GZ37K89Z": {"keywords": ["forest tea", "tea club", "enchanted forest", "bibliophile", "creative hobby", "forest book nook"]},
                },
                "product_details": {
                    "B0GYPTLQ7B": {"title": "French Florist Book Nook Kit", "brand": "Luvryon", "review_count": 0},
                    "B0GZ37K89Z": {
                        "title": "DIY Book Nook Kit Miniature House Kit 3D Wooden Puzzle for Adults & Teen Book Shelf Decor Bookshelf Insert with LED Light Craft Kit for Beginners Creative Hobby Gift(Forest Tea Book Club)",
                        "brand": "Luvryon",
                        "price": 65.99,
                        "rating": 4.8,
                        "review_count": 130,
                        "availability": "In stock",
                        "main_image": "https://m.media-amazon.com/images/I/51VGAkJF6iL._AC_SX569_.jpg",
                        "evidence_source": "firecrawl_amazon_au",
                        "bullets": ["Enchanted Forest Tea Club Theme", "Warm LED Lighting & Interactive Touch Switch"],
                    },
                },
                "keyword_details": {"book nook": {"monthly_search_volume": 5291}, "book nook kit": {"monthly_search_volume": 2442}},
                "keyword_search_results": {
                    "book nook": [{"ASIN": "B0D8HLDR4R", "brand": "CUTEBEE", "title": "Book Nook Kit"}],
                    "book nook kit": [{"ASIN": "B0G8Z1FZ3G", "brand": "CUTEBEE", "title": "Magic Forest Miniature Theater"}],
                },
            }, ensure_ascii=False), encoding="utf-8")

            result = optimizer.run_book_nook_optimization(
                db_path=db,
                context_json=context_path,
                output_root=td,
                report_prefix=td / "reports" / "B0GYPTLQ7B_B0GZ37K89Z_sorftime_launch_plan_2026-07-15",
                knowledge_json=knowledge_json,
                knowledge_md=knowledge_md,
                generated_at="2026-07-15",
            )

            campaign = Path(result["files"]["campaign_build_csv"]).read_text(encoding="utf-8-sig")
            config = json.loads(Path(result["files"]["json_config"]).read_text(encoding="utf-8"))
            html = Path(result["files"]["html_report"]).read_text(encoding="utf-8")
            knowledge = json.loads(knowledge_json.read_text(encoding="utf-8"))
            combined = "\n".join([campaign, json.dumps(config, ensure_ascii=False), html])

            self.assertIn("SP_AUTO_Research_BookNook_Forest_Group", campaign)
            self.assertIn("SP_EXACT_Core_BookNook_Forest_Group", campaign)
            self.assertIn("SP_PHRASE_Longtail_BookNook_Forest_Group", campaign)
            self.assertIn("forest tea book club", campaign)
            self.assertIn("B0GZ37K89Z", campaign)
            self.assertIn("B0GYPTLQ7B", campaign)
            self.assertEqual(config["asins"], ["B0GYPTLQ7B", "B0GZ37K89Z"])
            self.assertIsNone(config["shared_id"])
            self.assertEqual(config["sorftime_context"]["product_details"]["B0GZ37K89Z"]["evidence_source"], "firecrawl_amazon_au")
            self.assertIn("Forest Tea Book Club", json.dumps(config, ensure_ascii=False))
            self.assertIn("B0GZG9X46R", [t["parent_asin"] for t in knowledge["themes"]])
            self.assertNotIn("corner tavern book nook", campaign)
            self.assertNotIn("book nook library", campaign)
            self.assertNotIn("Pillow Speaker", combined)
            self.assertNotIn("SP_PHRASE_Longtail_Japanese", combined)

    def test_book_nook_skill_files_describe_default_workflow(self):
        skill = BOOK_NOOK_SKILL / "SKILL.md"
        agent = BOOK_NOOK_SKILL / "agents" / "openai.yaml"

        self.assertTrue(skill.exists())
        self.assertTrue(agent.exists())
        text = skill.read_text(encoding="utf-8")
        self.assertIn("Sorftime", text)
        self.assertIn("Amazon Ads CSV", text)
        self.assertIn("HTML", text)
        self.assertIn("Campaign Build CSV", text)
        self.assertIn("Pre-Negatives CSV", text)
        self.assertIn("shared manual", text)
        self.assertIn("scripts/book_nook_optimizer.py", text)


if __name__ == "__main__":
    unittest.main()
