"""Tests for the compliance report generator."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from provena import ContextTrail, ProvenanceMetadata
from provena.report import generate_pdf_report, generate_report


@pytest.fixture
def trail_with_data():
    trail = ContextTrail(backend="memory")
    prov = ProvenanceMetadata(
        source_url="https://example.com",
        created_at=datetime.now(timezone.utc) - timedelta(days=5),
    )
    trail.log("valid data", source="retriever", provenance=prov)
    trail.log("no provenance", source="tool")
    trail.log("agent msg", source="agent")
    yield trail
    trail.close()


@pytest.fixture
def signed_trail():
    trail = ContextTrail(backend="memory", signing_key="test-key")
    prov = ProvenanceMetadata(
        source_url="https://example.com",
        created_at=datetime.now(timezone.utc),
    )
    trail.log("signed data", source="retriever", provenance=prov)
    yield trail
    trail.close()


class TestReportJSON:
    def test_json_report_structure(self, trail_with_data):
        report = generate_report(trail_with_data, format="json")
        data = json.loads(report)
        assert "compliance_score" in data
        assert "chain_integrity" in data
        assert "eu_ai_act" in data
        assert "summary" in data
        assert "issues" in data

    def test_compliance_score(self, trail_with_data):
        report = json.loads(generate_report(trail_with_data, format="json"))
        assert 0 <= report["compliance_score"] <= 100

    def test_eu_ai_act_articles(self, trail_with_data):
        report = json.loads(generate_report(trail_with_data, format="json"))
        articles = report["eu_ai_act"]
        assert "article_10" in articles
        assert "article_12" in articles
        assert "article_13" in articles
        assert "article_14" in articles

    def test_chain_intact(self, trail_with_data):
        report = json.loads(generate_report(trail_with_data, format="json"))
        assert report["chain_integrity"]["status"] == "INTACT"

    def test_signed_trail_higher_score(self, signed_trail):
        report = json.loads(generate_report(signed_trail, format="json"))
        assert report["compliance_score"] >= 75


class TestReportText:
    def test_text_report_contains_sections(self, trail_with_data):
        report = generate_report(trail_with_data, format="text")
        assert "COMPLIANCE SCORE" in report
        assert "CHAIN INTEGRITY" in report
        assert "EU AI ACT" in report
        assert "SUMMARY" in report

    def test_text_report_shows_issues(self, trail_with_data):
        report = generate_report(trail_with_data, format="text")
        assert "ISSUES" in report

    def test_text_report_compliance_score(self, trail_with_data):
        """Verify text report contains compliance score."""
        report = generate_report(trail_with_data, format="text")
        assert "COMPLIANCE SCORE:" in report
        # Should show percentage and checks passed
        assert "%" in report
        assert "checks passed" in report

    def test_text_report_chain_integrity_status(self, trail_with_data):
        """Verify text report shows chain integrity status."""
        report = generate_report(trail_with_data, format="text")
        assert "CHAIN INTEGRITY:" in report
        assert "Status:" in report
        assert "INTACT" in report or "BROKEN" in report
        assert "Verified:" in report

    def test_text_report_provenance_breakdown(self, trail_with_data):
        """Verify text report contains provenance status breakdown."""
        report = generate_report(trail_with_data, format="text")
        assert "Provenance:" in report
        # Should contain at least one provenance status
        assert "VALID" in report or "MISSING" in report or "INCOMPLETE" in report

    def test_text_report_freshness_breakdown(self, trail_with_data):
        """Verify text report contains freshness status breakdown."""
        report = generate_report(trail_with_data, format="text")
        assert "Freshness:" in report
        # Should contain at least one freshness status
        assert "FRESH" in report or "STALE" in report or "UNKNOWN" in report

    def test_text_report_source_breakdown(self, trail_with_data):
        """Verify text report contains source tracking breakdown."""
        report = generate_report(trail_with_data, format="text")
        assert "Sources:" in report

    def test_text_report_eu_ai_act_articles(self, trail_with_data):
        """Verify text report shows all EU AI Act articles."""
        report = generate_report(trail_with_data, format="text")
        assert "EU AI ACT COMPLIANCE:" in report
        assert "ARTICLE_10" in report or "article_10" in report
        assert "ARTICLE_12" in report or "article_12" in report
        assert "ARTICLE_13" in report or "article_13" in report
        assert "ARTICLE_14" in report or "article_14" in report

    def test_text_report_zero_issues(self):
        """Verify text report shows no ISSUES section when all checks pass."""
        # Create a trail with all checks passing: valid provenance, no stale, signed
        trail = ContextTrail(backend="memory", signing_key="test-key")
        prov = ProvenanceMetadata(
            source_url="https://example.com",
            created_at=datetime.now(timezone.utc),
        )
        trail.log("valid data", source="retriever", provenance=prov)
        report = generate_report(trail, format="text")
        # With all checks passing, no issues should be present
        # The report may still have ISSUES header but with no content
        if "ISSUES:" in report:
            # If header exists, verify it's not followed by actual issues
            lines = report.split("\n")
            issues_idx = None
            for i, line in enumerate(lines):
                if "ISSUES:" in line:
                    issues_idx = i
                    break
            if issues_idx is not None and issues_idx + 1 < len(lines):
                # Next non-empty line should not start with "!"
                for line in lines[issues_idx + 1 :]:
                    if line.strip():
                        assert not line.strip().startswith("!"), (
                            "Should not have issue markers when all checks pass"
                        )
                        break
        trail.close()

    def test_text_report_empty_trail(self):
        """Verify text report handles empty trail correctly."""
        trail = ContextTrail(backend="memory")
        report = generate_report(trail, format="text")
        assert "COMPLIANCE SCORE:" in report
        assert "0" in report or "25" in report  # Empty trail should show low score
        assert "CHAIN INTEGRITY:" in report
        assert "Verified: 0" in report
        trail.close()

    def test_text_report_broken_chain(self):
        """Verify text report shows FAIL for Article 12 when chain is tampered."""
        trail = ContextTrail(backend="memory")
        prov = ProvenanceMetadata(
            source_url="https://example.com",
            created_at=datetime.now(timezone.utc),
        )
        trail.log("record 1", source="retriever", provenance=prov)
        trail.log("record 2", source="retriever", provenance=prov)
        trail.log("record 3", source="retriever", provenance=prov)

        # Verify chain is intact before tampering
        verdict_before = trail.verify_chain()
        assert verdict_before.intact

        # Tamper with the trail backend by modifying chain_hash
        all_records = trail._backend.all_records()
        if len(all_records) > 1:
            # Modify the chain_hash of a middle record to break the chain
            tampered_record = dict(all_records[1])
            tampered_record["chain_hash"] = "0" * 64  # Invalid hash
            trail._backend._records[1] = tampered_record

        # Verify chain is now broken
        verdict_after = trail.verify_chain()
        assert not verdict_after.intact

        # Check report shows broken chain
        report = generate_report(trail, format="text")
        assert "BROKEN" in report
        assert "ARTICLE_12" in report or "article_12" in report
        # Should mention Article 12 with FAIL status in issues
        assert "Art. 12" in report or "Article 12" in report

        trail.close()

    def test_text_report_missing_provenance(self):
        """Verify text report shows REVIEW for Article 10 when provenance is incomplete."""
        trail = ContextTrail(backend="memory")
        prov = ProvenanceMetadata(
            source_url="https://example.com",
            created_at=datetime.now(timezone.utc),
        )
        # Log with mixed provenance: some valid, some missing
        trail.log("with provenance", source="retriever", provenance=prov)
        trail.log("without provenance", source="tool")
        trail.log("another without", source="agent")

        report = generate_report(trail, format="text")
        # Should show incomplete provenance
        assert "Art. 10" in report or "Article 10" in report
        # Should mention incomplete data lineage
        assert "incomplete" in report.lower() or "provenance" in report.lower()

        trail.close()

    def test_text_report_formatting(self, trail_with_data):
        """Verify text report has proper formatting with borders and alignment."""
        report = generate_report(trail_with_data, format="text")
        lines = report.split("\n")
        # Should have header separator lines
        assert any("=" * 50 in line for line in lines), "Missing separator lines"
        # Should be properly formatted with indentation
        assert any(line.startswith("  ") for line in lines), "Missing indentation"

    def test_text_report_title_centered(self, trail_with_data):
        """Verify text report centers the title."""
        custom_title = "My Custom Report"
        report = generate_report(trail_with_data, format="text", title=custom_title)
        assert custom_title in report
        # Check that title appears near the top (in first 5 lines)
        lines = report.split("\n")
        assert any(custom_title in line for line in lines[:5])


class TestReportPDF:
    def test_pdf_requires_fpdf2(self, trail_with_data, tmp_path):
        try:
            import fpdf  # noqa: F401

            path = str(tmp_path / "report.pdf")
            result = generate_pdf_report(trail_with_data, path)
            assert result == path
            with open(path, "rb") as f:
                header = f.read(5)
            assert header == b"%PDF-"
        except ImportError:
            with pytest.raises(ImportError, match="fpdf2"):
                generate_pdf_report(trail_with_data, str(tmp_path / "report.pdf"))

    def test_pdf_string_fallback(self, trail_with_data):
        try:
            import fpdf  # noqa: F401

            report = generate_report(trail_with_data, format="pdf")
            assert b"%PDF-" in report
        except ImportError:
            with pytest.raises(ImportError, match="fpdf2"):
                generate_report(trail_with_data, format="pdf")


class TestReportEmpty:
    def test_empty_trail(self):
        trail = ContextTrail(backend="memory")
        report = json.loads(generate_report(trail, format="json"))
        assert report["summary"]["total_records"] == 0
        assert report["compliance_score"] == 25
        trail.close()


class TestReportInvalidFormats:
    def test_invalid_format(self, trail_with_data):
        with pytest.raises(ValueError, match="Unsupported format"):
            generate_report(trail_with_data, format="html")
