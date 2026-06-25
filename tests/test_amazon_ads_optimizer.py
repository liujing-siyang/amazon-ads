import csv
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "amazon-ads-optimizer"
SCRIPTS = SKILL / "scripts"
UI = SKILL / "ui"


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_csv(path, rows, include_manual=False):
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
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


class AmazonAdsOptimizerTests(unittest.TestCase):
    def test_parse_filename_supports_short_and_full_end_dates(self):
        importer = load_module("import_ad_reports")

        short = importer.parse_report_filename("2026-05-01——06-25_B0GXZQXFM4_手动.csv")
        full = importer.parse_report_filename("2026-05-01——2026-06-25_B0GXZQXFM4_自动.csv")

        self.assertEqual(short, {
            "report_start": "2026-05-01",
            "report_end": "2026-06-25",
            "asin": "B0GXZQXFM4",
            "ad_mode": "manual",
        })
        self.assertEqual(full["report_end"], "2026-06-25")
        self.assertEqual(full["ad_mode"], "automatic")

    def test_parse_filename_rejects_malformed_names(self):
        importer = load_module("import_ad_reports")

        with self.assertRaisesRegex(ValueError, "Expected filename pattern"):
            importer.parse_report_filename("bad-file.csv")

    def test_import_ad_report_creates_schema_and_prevents_duplicates(self):
        importer = load_module("import_ad_reports")
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            db = tmp_path / "ads.sqlite"
            csv_path = tmp_path / "2026-05-01——06-25_B0GXZQXFM4_手动.csv"
            write_csv(csv_path, [{
                "已添加为": "关键词: 词组匹配",
                "顾客搜索词": "pillow speaker",
                "关键词": "pillow speaker",
                "目标竞价 (AUD)": "0.6",
                "展示量": "1783",
                "点击量": "39",
                "点击率": "0.0219",
                "总成本 (AUD)": "20.91",
                "CPC (AUD)": "0.54",
                "购买量": "13",
                "销售额 (AUD)": "413.87",
                "ACOS": "0.0505",
                "ROAS": "19.79",
                "购买率": "0.3333",
            }], include_manual=True)

            first = importer.import_report(db, csv_path)
            second = importer.import_report(db, csv_path)

            self.assertEqual(first["rows_imported"], 1)
            self.assertIs(second["duplicate"], True)
            with closing(sqlite3.connect(db)) as conn:
                count = conn.execute("select count(*) from search_term_performance").fetchone()[0]
                agg = conn.execute(
                    "select sum(spend), sum(sales), sum(orders) from search_term_performance"
                ).fetchone()
            self.assertEqual(count, 1)
            self.assertEqual(agg, (20.91, 413.87, 13))

    def test_validate_evidence_rejects_unsourced_external_values(self):
        validator = load_module("validate_evidence")
        importer = load_module("import_ad_reports")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "ads.sqlite"
            importer.ensure_schema(db)
            with closing(sqlite3.connect(db)) as conn:
                conn.execute("""
                    insert into external_keyword_evidence
                    (keyword, source_name, source_type, captured_date, cpc, confidence)
                    values ('pillow speaker', 'Tool', 'third_party_tool', '2026-06-25', 0.8, 'estimate')
                """)
                conn.commit()

            result = validator.validate_database(db)

            self.assertIs(result["ok"], False)
            self.assertEqual(result["missing_sources"], 1)

    def test_analyze_asin_generates_profit_and_listing_gap_recommendations(self):
        importer = load_module("import_ad_reports")
        analyzer = load_module("analyze_asin")
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            db = tmp_path / "ads.sqlite"
            csv_path = tmp_path / "2026-05-01——06-25_B0GXZQXFM4_自动.csv"
            write_csv(csv_path, [
                {
                    "顾客搜索词": "under pillow speaker bluetooth",
                    "关键词": "close-match",
                    "展示量": "10",
                    "点击量": "8",
                    "点击率": "0.8",
                    "总成本 (AUD)": "3.20",
                    "CPC (AUD)": "0.40",
                    "购买量": "2",
                    "销售额 (AUD)": "59.98",
                    "ACOS": "0.0534",
                    "ROAS": "18.74",
                    "购买率": "0.25",
                },
                {
                    "顾客搜索词": "irrelevant tablet speaker",
                    "关键词": "loose-match",
                    "展示量": "30",
                    "点击量": "21",
                    "点击率": "0.3333",
                    "总成本 (AUD)": "8.00",
                    "CPC (AUD)": "0.38",
                    "购买量": "0",
                    "销售额 (AUD)": "0",
                    "ACOS": "0",
                    "ROAS": "0",
                    "购买率": "0",
                },
            ])
            importer.import_report(db, csv_path)
            with closing(sqlite3.connect(db)) as conn:
                conn.execute("""
                    insert into listing_snapshots
                    (asin, marketplace, product_url, captured_at, title, bullets_json, extraction_status)
                    values (?, 'AU', ?, '2026-06-25T00:00:00', ?, ?, 'ok')
                """, (
                    "B0GXZQXFM4",
                    "https://www.amazon.com.au/dp/B0GXZQXFM4",
                    "Bluetooth Pillow Speaker",
                    json.dumps(["Thin sleep speaker"], ensure_ascii=False),
                ))
                conn.commit()

            result = analyzer.analyze(db, "B0GXZQXFM4", 0.2)
            actions = [r["action"] for r in result["recommendations"]]

            self.assertEqual(result["summary"]["spend"], 11.2)
            self.assertIn("promote_to_exact", actions)
            self.assertIn("add_negative_or_reduce_bid", actions)
            self.assertIn("listing_keyword_gap", actions)

    def test_rule_profile_defaults_and_custom_thresholds_affect_recommendations(self):
        importer = load_module("import_ad_reports")
        analyzer = load_module("analyze_asin")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "ads.sqlite"
            csv_path = Path(td) / "2026-05-01——06-25_B0GXZQXFM4_自动.csv"
            write_csv(csv_path, [{
                "顾客搜索词": "tablet speaker",
                "关键词": "loose-match",
                "展示量": "50",
                "点击量": "10",
                "点击率": "0.2",
                "总成本 (AUD)": "8.00",
                "CPC (AUD)": "0.80",
                "购买量": "0",
                "销售额 (AUD)": "0",
                "ACOS": "0",
                "ROAS": "0",
                "购买率": "0",
            }])
            importer.import_report(db, csv_path)

            default_result = analyzer.analyze(db, "B0GXZQXFM4", 0.2)
            permissive_result = analyzer.analyze(db, "B0GXZQXFM4", 0.2, rule_overrides={
                "wasted_click_threshold": 8,
                "wasted_spend_threshold": 5,
            })

            self.assertNotIn("add_negative_or_reduce_bid", [r["action"] for r in default_result["recommendations"]])
            self.assertIn("add_negative_or_reduce_bid", [r["action"] for r in permissive_result["recommendations"]])
            self.assertEqual(default_result["rule_profile"]["wasted_click_threshold"], 20)
            self.assertEqual(permissive_result["rule_profile"]["wasted_click_threshold"], 8)

    def test_ranking_support_tolerance_changes_recommendations(self):
        importer = load_module("import_ad_reports")
        analyzer = load_module("analyze_asin")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "ads.sqlite"
            csv_path = Path(td) / "2026-05-01——06-25_B0GXZQXFM4_手动.csv"
            write_csv(csv_path, [{
                "已添加为": "关键词: 精准匹配",
                "顾客搜索词": "premium pillow speaker",
                "关键词": "premium pillow speaker",
                "目标竞价 (AUD)": "1.0",
                "展示量": "100",
                "点击量": "20",
                "点击率": "0.2",
                "总成本 (AUD)": "12.00",
                "CPC (AUD)": "0.60",
                "购买量": "1",
                "销售额 (AUD)": "40.00",
                "ACOS": "0.3",
                "ROAS": "3.33",
                "购买率": "0.05",
            }], include_manual=True)
            importer.import_report(db, csv_path)

            default_result = analyzer.analyze(db, "B0GXZQXFM4", 0.2)
            tight_result = analyzer.analyze(db, "B0GXZQXFM4", 0.2, rule_overrides={"ranking_acos_tolerance": 1.2})

            default_actions = [r["action"] for r in default_result["recommendations"]]
            tight_actions = [r["action"] for r in tight_result["recommendations"]]
            self.assertIn("ranking_support_review", default_actions)
            self.assertIn("reduce_bid_for_high_acos", tight_actions)

    def test_import_sellersprite_xlsx_with_mapping(self):
        importer = load_module("import_ad_reports")
        seller = load_module("import_sellersprite")
        openpyxl = __import__("openpyxl")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "ads.sqlite"
            importer.ensure_schema(db)
            xlsx = Path(td) / "seller.xlsx"
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["Keyword", "Search Volume", "CPC", "Organic Rank", "Competition"])
            ws.append(["pillow speaker", 1200, 0.72, 8, "medium"])
            wb.save(xlsx)
            mapping = {
                "keyword": "Keyword",
                "search_volume": "Search Volume",
                "cpc": "CPC",
                "organic_rank": "Organic Rank",
                "competition": "Competition",
            }

            result = seller.import_sellersprite(db, xlsx, mapping, captured_date="2026-06-25")

            self.assertEqual(result["rows_imported"], 1)
            with closing(sqlite3.connect(db)) as conn:
                row = conn.execute("select keyword, source_type, source_file, search_volume, cpc from external_keyword_evidence").fetchone()
            self.assertEqual(row, ("pillow speaker", "sellersprite_excel", str(xlsx), 1200, 0.72))

    def test_html_report_generation_contains_interactive_decision_table(self):
        renderer = load_module("render_html_report")
        result = {
            "asin": "B0GXZQXFM4",
            "summary": {"spend": 10.0, "sales": 50.0, "orders": 2, "acos": 0.2, "target_acos": 0.25, "impressions": 100},
            "rule_profile": {"name": "default", "target_acos": 0.25, "wasted_click_threshold": 8},
            "evidence_validation": {"ok": True, "missing_sources": 0},
            "sources": [{"type": "amazon_ads_csv", "label": "sample.csv"}],
            "recommendations": [{
                "action": "promote_to_exact",
                "priority": "high",
                "search_term": "pillow speaker",
                "keyword": "close-match",
                "ad_mode": "automatic",
                "reason": "Converted below target ACOS.",
                "suggested_next_step": "Add as exact keyword.",
                "threshold_state": "below_target",
                "sellersprite_evidence": {"search_volume": 1200, "cpc": 0.72},
                "listing_gap_tokens": [],
                "metric_evidence": {"spend": 1.0, "clicks": 2, "orders": 1, "sales": 30.0, "acos": 0.033},
                "source_refs": [],
            }],
        }

        html = renderer.render_html(result)

        self.assertIn("Amazon Ads Optimization Report", html)
        self.assertIn("id=\"recommendations-table\"", html)
        self.assertIn("data-action=\"promote_to_exact\"", html)
        self.assertIn("SellerSprite", html)
        self.assertIn("filterAction", html)

    def test_config_json_shape_is_accepted_by_analyzer(self):
        importer = load_module("import_ad_reports")
        analyzer = load_module("analyze_asin")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "ads.sqlite"
            csv_path = Path(td) / "2026-05-01——06-25_B0GXZQXFM4_自动.csv"
            config_path = Path(td) / "analysis-config.json"
            write_csv(csv_path, [{
                "顾客搜索词": "pillow speaker",
                "关键词": "close-match",
                "展示量": "10",
                "点击量": "2",
                "点击率": "0.2",
                "总成本 (AUD)": "1.00",
                "CPC (AUD)": "0.50",
                "购买量": "1",
                "销售额 (AUD)": "30.00",
                "ACOS": "0.0333",
                "ROAS": "30",
                "购买率": "0.5",
            }])
            importer.import_report(db, csv_path)
            config_path.write_text(json.dumps({
                "asin": "B0GXZQXFM4",
                "target_acos": 0.25,
                "db": str(db),
                "rule_profile": {"wasted_click_threshold": 12},
            }), encoding="utf-8")

            result = analyzer.analyze_from_config(config_path)

            self.assertEqual(result["asin"], "B0GXZQXFM4")
            self.assertEqual(result["rule_profile"]["wasted_click_threshold"], 12)

    def test_static_config_builder_exists_and_exports_config(self):
        html_path = UI / "config-builder.html"
        text = html_path.read_text(encoding="utf-8")
        self.assertIn("analysis-config.json", text)
        self.assertIn("target_acos", text)
        self.assertIn("sellersprite_mapping", text)

    def test_local_server_status_endpoint(self):
        server = load_module("serve_ui")
        app = server.create_app(db_path="data/amazon_ads.sqlite")
        response = app.handle_for_test("GET", "/api/status", b"")
        self.assertEqual(response["status"], 200)
        data = json.loads(response["body"].decode("utf-8"))
        self.assertTrue(data["ok"])


    def test_dynamic_waste_threshold_uses_20_clicks_and_allowed_test_spend(self):
        importer = load_module("import_ad_reports")
        analyzer = load_module("analyze_asin")
        search = "\u987e\u5ba2\u641c\u7d22\u8bcd"
        keyword = "\u5173\u952e\u8bcd"
        impressions = "\u5c55\u793a\u91cf"
        clicks = "\u70b9\u51fb\u91cf"
        ctr = "\u70b9\u51fb\u7387"
        spend = "\u603b\u6210\u672c (AUD)"
        orders = "\u8d2d\u4e70\u91cf"
        sales = "\u9500\u552e\u989d (AUD)"
        cvr = "\u8d2d\u4e70\u7387"
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "ads.sqlite"
            csv_path = Path(td) / "auto.csv"
            write_csv(csv_path, [{
                search: "low intent speaker", keyword: "loose-match", impressions: "200", clicks: "19", ctr: "0.095",
                spend: "8.00", "CPC (AUD)": "0.42", orders: "0", sales: "0", "ACOS": "0", "ROAS": "0", cvr: "0",
            }, {
                search: "waste speaker", keyword: "loose-match", impressions: "300", clicks: "21", ctr: "0.07",
                spend: "8.20", "CPC (AUD)": "0.39", orders: "0", sales: "0", "ACOS": "0", "ROAS": "0", cvr: "0",
            }])
            metadata = {"report_start":"2026-05-01", "report_end":"2026-06-25", "asin":"B0GXZQXFM4", "ad_mode":"automatic"}
            importer.import_report(db, csv_path, metadata=metadata)
            result = analyzer.analyze(db, "B0GXZQXFM4", None, rule_overrides={"margin_model": {"selling_price": 40.0}, "target_acos": 0.2})
            waste_terms = [r["search_term"] for r in result["recommendations"] if r["action"] == "add_negative_or_reduce_bid"]

            self.assertEqual(result["rule_profile"]["wasted_click_threshold"], 20)
            self.assertEqual(result["rule_profile"]["allowed_test_spend"], 8.0)
            self.assertNotIn("low intent speaker", waste_terms)
            self.assertIn("waste speaker", waste_terms)

    def test_margin_model_derives_target_acos_and_profit_metrics(self):
        analyzer = load_module("analyze_asin")
        profile = analyzer.build_rule_profile(None, {"margin_model": {
            "selling_price": 40, "product_cost": 10, "fba_fee": 5, "referral_fee": 6,
            "shipping_packaging": 2, "return_allowance": 1, "other_cost": 1, "desired_profit_buffer": 0.10,
        }})

        self.assertAlmostEqual(profile["margin_model"]["break_even_acos"], 0.375)
        self.assertAlmostEqual(profile["target_acos"], 0.275)
        self.assertAlmostEqual(profile["allowed_test_spend"], 11.0)

    def test_keyword_intent_classification_and_ad_structure_are_generated(self):
        importer = load_module("import_ad_reports")
        analyzer = load_module("analyze_asin")
        added_as = "\u5df2\u6dfb\u52a0\u4e3a"
        search = "\u987e\u5ba2\u641c\u7d22\u8bcd"
        keyword = "\u5173\u952e\u8bcd"
        bid = "\u76ee\u6807\u7ade\u4ef7 (AUD)"
        impressions = "\u5c55\u793a\u91cf"
        clicks = "\u70b9\u51fb\u91cf"
        ctr = "\u70b9\u51fb\u7387"
        spend = "\u603b\u6210\u672c (AUD)"
        orders = "\u8d2d\u4e70\u91cf"
        sales = "\u9500\u552e\u989d (AUD)"
        cvr = "\u8d2d\u4e70\u7387"
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "ads.sqlite"
            csv_path = Path(td) / "manual.csv"
            write_csv(csv_path, [{
                added_as: "\u5173\u952e\u8bcd: \u7cbe\u51c6\u5339\u914d", search: "dreamwave pillow speaker", keyword: "pillow speaker", bid: "0.6",
                impressions: "100", clicks: "20", ctr: "0.2", spend: "8.00", "CPC (AUD)": "0.40", orders: "2", sales: "80.00", "ACOS": "0.1", "ROAS": "10", cvr: "0.1",
            }], include_manual=True)
            metadata = {"report_start":"2026-05-01", "report_end":"2026-06-25", "asin":"B0GXZQXFM4", "ad_mode":"manual"}
            importer.import_report(db, csv_path, metadata=metadata)
            result = analyzer.analyze(db, "B0GXZQXFM4", 0.2)

            rec = result["recommendations"][0]
            self.assertEqual(rec["intent"], "competitor")
            self.assertIn("\u7ade\u54c1", rec["intent_label_zh"])
            roles = [g["role"] for g in result["ad_structure_plan"]]
            self.assertIn("competitor_test", roles)

    def test_listing_score_and_english_listing_copy_with_chinese_rationale(self):
        importer = load_module("import_ad_reports")
        analyzer = load_module("analyze_asin")
        search = "\u987e\u5ba2\u641c\u7d22\u8bcd"
        keyword = "\u5173\u952e\u8bcd"
        impressions = "\u5c55\u793a\u91cf"
        clicks = "\u70b9\u51fb\u91cf"
        ctr = "\u70b9\u51fb\u7387"
        spend = "\u603b\u6210\u672c (AUD)"
        orders = "\u8d2d\u4e70\u91cf"
        sales = "\u9500\u552e\u989d (AUD)"
        cvr = "\u8d2d\u4e70\u7387"
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "ads.sqlite"
            csv_path = Path(td) / "auto.csv"
            write_csv(csv_path, [{
                search: "portable bluetooth speakers under pillow", keyword: "loose-match", impressions: "20", clicks: "5", ctr: "0.25",
                spend: "2.00", "CPC (AUD)": "0.40", orders: "1", sales: "35.99", "ACOS": "0.0556", "ROAS": "18", cvr: "0.2",
            }])
            metadata = {"report_start":"2026-05-01", "report_end":"2026-06-25", "asin":"B0GXZQXFM4", "ad_mode":"automatic"}
            importer.import_report(db, csv_path, metadata=metadata)
            with closing(sqlite3.connect(db)) as conn:
                conn.execute("""
                    insert into listing_snapshots
                    (asin, marketplace, product_url, captured_at, title, bullets_json, rating, review_count, extraction_status)
                    values (?, 'AU', ?, '2026-06-25T00:00:00', ?, ?, 4.7, 323, 'ok')
                """, ("B0GXZQXFM4", "https://www.amazon.com.au/dp/B0GXZQXFM4", "Bluetooth Pillow Speaker for Sleeping", json.dumps(["Ultra thin under pillow speaker"], ensure_ascii=False)))
                conn.commit()
            result = analyzer.analyze(db, "B0GXZQXFM4", 0.2)
            listing = result["listing_optimization"]

            self.assertGreaterEqual(listing["score"], 60)
            self.assertIn("portable", " ".join(listing["backend_search_terms"]).lower())
            self.assertIn("Bluetooth Pillow Speaker", listing["title"])
            self.assertIn("\u4e2d\u6587\u89e3\u8bfb", listing["rationale_zh"])

    def test_period_only_trend_message_and_chinese_html_sections(self):
        renderer = load_module("render_html_report")
        result = {
            "asin": "B0GXZQXFM4",
            "summary": {"spend": 10, "sales": 50, "orders": 2, "acos": 0.2, "target_acos": 0.25, "impressions": 100},
            "rule_profile": {"name": "default", "target_acos": 0.25, "wasted_click_threshold": 20, "allowed_test_spend": 10},
            "margin_model": {"break_even_acos": 0.35, "recommended_target_acos": 0.25},
            "trend_analysis": {"message_zh": "\u5f53\u524d\u5e7f\u544a\u6587\u4ef6\u53ea\u652f\u6301\u5468\u671f\u7ea7\u5bf9\u6bd4\uff0c\u4e0d\u80fd\u751f\u6210\u771f\u5b9e7/14/30\u5929\u8d8b\u52bf\u3002"},
            "ad_structure_plan": [{"role": "manual_exact_core", "terms": ["pillow speaker"]}],
            "listing_optimization": {"score": 80, "title": "Bluetooth Pillow Speaker", "bullets": ["Ultra Thin Under Pillow Speaker"], "description": "Sleep better.", "backend_search_terms": ["under pillow speaker"], "rationale_zh": "\u4e2d\u6587\u89e3\u8bfb\uff1a\u8986\u76d6\u6838\u5fc3\u8bcd\u3002"},
            "evidence_validation": {"ok": True},
            "sources": [],
            "recommendations": [{"action":"promote_to_exact","priority":"high","search_term":"pillow speaker","keyword":"close-match","ad_mode":"automatic","intent":"profit","intent_label_zh":"\u5229\u6da6\u8bcd","reason":"\u8868\u73b0\u597d","suggested_next_step":"\u52a0\u5165\u7cbe\u51c6","threshold_state":"below_target","metric_evidence":{"spend":1,"clicks":2,"orders":1,"sales":30,"acos":0.03},"source_refs":[]}],
        }
        html = renderer.render_html(result)

        self.assertIn("\u6bdb\u5229\u6a21\u578b\u4e0e\u76ee\u6807 ACOS", html)
        self.assertIn("\u52a8\u6001\u9608\u503c\u8bf4\u660e", html)
        self.assertIn("Listing \u627f\u63a5\u80fd\u529b\u8bc4\u5206", html)
        self.assertIn("\u5efa\u8bae\u6807\u9898", html)
        self.assertIn("pillow speaker", html)

    def test_external_keyword_import_supports_generic_tool_and_recommendation_tracking(self):
        importer = load_module("import_ad_reports")
        external = load_module("import_external_keywords")
        tracker = load_module("track_recommendations")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "ads.sqlite"
            importer.ensure_schema(db)
            csv_path = Path(td) / "keywords.csv"
            csv_path.write_text("Keyword,Search Volume,CPC\npillow speaker,1000,0.7\n", encoding="utf-8")
            mapping = {"keyword":"Keyword", "search_volume":"Search Volume", "estimated_cpc":"CPC"}
            imported = external.import_external_keywords(db, csv_path, "Helium 10", mapping, "2026-06-25")
            feedback = tracker.record_feedback(db, asin="B0GXZQXFM4", recommendation_id=None, status="executed", old_bid=0.6, new_bid=0.72, note="test")

            self.assertEqual(imported["rows_imported"], 1)
            self.assertEqual(feedback["status"], "executed")
            with closing(sqlite3.connect(db)) as conn:
                source = conn.execute("select source_name, source_type, cpc from external_keyword_evidence").fetchone()
                row = conn.execute("select old_bid, new_bid from recommendation_feedback").fetchone()
            self.assertEqual(source, ("Helium 10", "external_keyword_tool", 0.7))
            self.assertEqual(row, (0.6, 0.72))

    def test_sorftime_payloads_are_stored_with_source_metadata(self):
        importer = load_module("import_ad_reports")
        sorftime = load_module("fetch_sorftime_asin")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "ads.sqlite"
            importer.ensure_schema(db)
            payloads = {"product_detail": {"title": "Bluetooth Pillow Speaker"}, "product_trend_price": [{"date": "2026-06", "value": 35.99}]}
            result = sorftime.store_sorftime_payloads(db, "B0GXZQXFM4", "AU", payloads, query_date="2026-06-25")

            self.assertEqual(result["rows_stored"], 2)
            with closing(sqlite3.connect(db)) as conn:
                row = conn.execute("select source_type, metric_type, asin, marketplace from sorftime_snapshots order by metric_type limit 1").fetchone()
            self.assertEqual(row[0], "sorftime_mcp")
            self.assertEqual(row[2], "B0GXZQXFM4")
            self.assertEqual(row[3], "AU")


if __name__ == "__main__":
    unittest.main()
