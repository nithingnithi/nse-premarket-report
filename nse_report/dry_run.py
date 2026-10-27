"""Render saved, dated probe evidence. No network, credentials or live AI API.

Draft signal mappings apply to this labelled trial only. Missing/unreconciled
inputs remain unavailable; this module is not an unattended production adapter.
"""

import argparse
import json
from datetime import datetime
from decimal import Decimal
from html import escape
from pathlib import Path

from .calculations import FutureBar, CashRow, cash_trends, fii_positions, futures_build_up, score_summary


def analyze(data):
    if data["mode"] != "CAPTURED_DATA_DRY_RUN":
        raise ValueError("Only explicitly labelled captured-data trials supported")
    cutoff = datetime.fromisoformat(data["cutoff_IST"])
    if cutoff.utcoffset().total_seconds() != 19800 or cutoff.strftime("%H:%M:%S") != "07:45:00":
        raise ValueError("Expected 07:45 IST cutoff")
    if cutoff.date().isoformat() != data["report_date"]:
        raise ValueError("Report date/cutoff mismatch")
    sessions = data["provider_completed_sessions"]
    if any(s >= data["report_date"] for s in sessions["NSE"] + sessions["NFO"]):
        raise ValueError("Completed sessions must precede this pre-market report")
    futures = []
    for item in data["futures"]:
        observations = item["daily_observations"]
        if len(observations) != 2 or [r["date"] for r in observations] != sessions["NFO"]:
            raise ValueError("Unexpected futures observations")
        bars = [FutureBar(item["instrument_key"], item["expiry"], row["date"],
                          row["close"], row["oi_raw"], "raw provider OI counts", "Upstox")
                for row in observations]
        result = futures_build_up(*bars, latest_session=sessions["NFO"][0], previous_session=sessions["NFO"][1])
        futures.append({**item, **result})
    if len(futures) != 2 or [r["check"] for r in futures] != ["NIFTY futures", "BANKNIFTY futures"]:
        raise ValueError("Expected exact index futures identities")
    positions = data["fii_positions"]
    if [r["date"] for r in positions] != sessions["NFO"]:
        raise ValueError("Unexpected FII positions dates")
    pos = positions[0]
    fii = fii_positions(pos["long_contracts"], pos["short_contracts"], session=pos["date"],
                        expected_session=sessions["NFO"][0], unit="raw provider counts")
    cash = {}
    for item in data["cash"]:
        participant = item["check"].split()[0]
        if participant in cash:
            raise ValueError("Duplicate cash participant")
        rows = [CashRow(participant, r["date"], r["buy_raw"], r["sell_raw"],
                        "raw provider amounts", "Upstox") for r in item["observations"]]
        cash[participant] = cash_trends(rows, participant=participant,
                                        expected_sessions=sessions["NSE"],
                                        unit="raw provider amounts", provider="Upstox")
    if set(cash) != {"FII", "DII"}:
        raise ValueError("Expected both cash participants")
    # This draft mapping was disclosed for this trial, not enabled as a live model.
    build = futures[0]["classification"]
    point = 1 if build in ("LONG_BUILD_UP", "SHORT_COVERING") else -1 if build in (
        "SHORT_BUILD_UP", "LONG_UNWINDING") else 0
    score = score_summary({"futures_build_up": point,
                           "fii_futures": (fii["net"] > 0) - (fii["net"] < 0)})
    return {"futures": futures, "fii": fii, "cash": cash, "score": score}


def display(value, signed=False):
    if value is None:
        return "N/A"
    if isinstance(value, (Decimal, int, float)):
        return format(value, "+,.2f" if signed else ",.2f").replace(".00", "")
    return str(value)


def render(data, result, output):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

    navy, teal, orange = colors.HexColor("#142B40"), colors.HexColor("#006C71"), colors.HexColor("#A85A00")
    styles = {
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.3, leading=12.2, textColor=navy, spaceAfter=4),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8, leading=10, textColor=navy),
        "heading": ParagraphStyle("heading", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=teal, spaceBefore=8, spaceAfter=6),
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=23, leading=27, textColor=navy, spaceAfter=6),
        "bias": ParagraphStyle("bias", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=orange, spaceAfter=8),
    }
    def p(text, style="body"):
        # Every string, including externally sourced titles, is literal text.
        return Paragraph(escape(str(text)), styles[style])
    def linked(label, url):
        if not url.startswith("https://") or any(c in url for c in ('"', "'", "<", ">", "\n", "\r")):
            raise ValueError("Unsafe source URL")
        return Paragraph(f'<link href="{escape(url, quote=True)}" color="#006C71">{escape(label)}</link>', styles["small"])
    def table(headers, rows, widths):
        cells = [[p(c, "small") for c in headers]] + [[p(c, "small") for c in row] for row in rows]
        t = Table(cells, colWidths=widths, hAlign="LEFT", repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E4EEF2")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F8FA")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#BCCED6")),
        ]))
        return t
    story = []
    add = story.append
    score = result["score"]
    add(p("NSE morning report", "title"))
    add(p("DRY RUN - SAVED DATA - DRAFT POLICY", "heading"))
    add(p(f'Report: {data["report_date"]} | Cutoff: 07:45 IST | Target delivery: 08:00 IST'))
    add(p(f'Previous provider session: {data["provider_completed_sessions"]["NSE"][0]}; comparison: {data["provider_completed_sessions"]["NFO"][1]}. Independent NSE calendar check pending.', "small"))
    add(Spacer(1, 10))
    add(p(score["bias"], "bias"))
    low, high = score["score_range"]
    add(table(["RAW SCORE", "AVAILABLE", "POSSIBLE RANGE", "INDIA VIX FLAG"],
              [[str(score["score"]), f'{score["available"]}/6', f'[{low:+d}, {high:+d}]', "UNKNOWN / unverified"]], [110, 95, 120, 186]))
    add(p("VIX captured: 17.16 at 26 Oct 16:00 provider last-trade time. Freshness/semantics unresolved; proposed caution threshold 20 is separate from the score.", "small"))
    add(p("Top three alerts", "heading"))
    for line in (
        "1. Four signals are missing. A score of 0 is not a supported neutral conclusion; the possible range crosses bearish, neutral and bullish.",
        "2. Selected futures/options expire on 27 Oct. This trial includes expiry day; roll policy and baseline continuity need production validation.",
        "3. Global observations were captured on 26 Oct evening, not refreshed at this cutoff. Last-12-hour news is N/A for this report window.",
    ):
        add(p(line))
    add(p("Six signals - Nifty headline, Bank Nifty context", "heading"))
    add(table(["Signal", "Trial point", "Evidence / missing reason"], [
        ["Futures build-up", "+1", "Short covering: close +198.2; raw OI -101,140."],
        ["PCR direction", "N/A", "Raw chain rows and verified previous-session baseline unavailable."],
        ["Strike walls", "N/A", "Current/previous complete strike-OI snapshots unavailable."],
        ["FII index futures", "-1", "Aggregate net -277,105 raw counts; not Nifty-only exposure."],
        ["FII cash", "N/A", "Five-session raw sum available; monetary scale unresolved."],
        ["DII cash", "N/A", "Five-session raw sum available; monetary scale unresolved."],
    ], [112, 66, 333]))
    add(p("Codex review of saved evidence", "heading"))
    for line in data["review"]["notes"][:2]:
        add(p(line))
    add(p("Selected upcoming events - partial calendar", "heading"))
    wanted = ("All India Index of Industrial Production (IIP)", "FOMC scheduled announcement", "Gross Domestic Product", "Personal Income and Outlays")
    events = [e for e in data["calendar"]["events"] if e["title"] in wanted]
    add(table(["IST date / time", "Event", "Source"], [[e["date_IST"] + " " + e["time_display_IST"], e["title"], e["agency"]] for e in events], [116, 310, 85]))
    add(p("Planned dates may change. IIP time, forecasts, actuals and previous readings: N/A. Reviewed snapshots due for renewal 02 Nov; links on page 2.", "small"))
    add(PageBreak())
    add(p("Evidence dashboard", "title"))
    add(p("Captured observations only | All displayed times IST | Raw units retained", "small"))
    add(p("Global / forex / crude - freshness and benchmark units unverified", "heading"))
    global_rows = []
    for r in data["global"]:
        stamp = r.get("last_trade_IST", r.get("bar_start_IST", "N/A"))
        label = "trade" if "last_trade_IST" in r else "bar start"
        shown = stamp[5:10] + " " + stamp[11:16] if stamp != "N/A" else stamp
        global_rows.append([r["name"], display(r.get("last_price", r.get("last_closed_minute_price"))),
                            display(r.get("provider_net_change_raw"), signed=True), shown + " / " + label])
    add(table(["Provider name", "Raw value", "Provider change", "Provider timestamp (MM-DD)"], global_rows, [135, 90, 100, 186]))
    add(p("US values are evening observations, not verified final US closes. No opening-gap estimate or causal claim is inferred from these values.", "small"))
    add(p("Futures and options", "heading"))
    add(table(["Index / expiry", "Close / change", "Raw OI / change", "Build-up"], [[
        r["check"].replace(" futures", "") + " / " + r["expiry"],
        display(r["daily_observations"][0]["close"]) + " / " + display(r["price_change"], signed=True),
        display(r["daily_observations"][0]["oi_raw"]) + " / " + display(r["oi_change"], signed=True),
        r["classification"].replace("_", " ").lower(),
    ] for r in result["futures"]], [135, 120, 150, 106]))
    add(p("Nifty / Bank Nifty option expiry: 27 Oct. PCR, OI change, call/put walls, support/resistance and max pain: N/A. Earlier probes retained row counts, not the chain rows needed to calculate them.", "small"))
    add(p("Institutional flows - latest 26 Oct; cash window 26/23/22/21/19 Oct", "heading"))
    fii = result["fii"]
    add(table(["FII aggregate index futures", "Long", "Short", "Net", "Long/short"], [[
        "Raw provider counts", display(fii["long"]), display(fii["short"]), display(fii["net"], signed=True), f'{float(fii["long_short_ratio"]):.4f}'
    ]], [160, 83, 88, 90, 90]))
    add(table(["Cash participant", "Latest net", "3-session sum", "5-session sum", "Unit"], [[
        k, display(v["daily_net"][data["provider_completed_sessions"]["NSE"][0]], signed=True),
        display(v["net_3_sessions"], signed=True), display(v["net_5_sessions"], signed=True), "Raw / unresolved"
    ] for k, v in result["cash"].items()], [105, 98, 103, 103, 102]))
    add(p("No INR/crore or lot conversion. Cash excluded from scoring. DII purchases do not prove absorption of FII sales; no offset bonus. PCR/walls and futures/FII signals may overlap.", "small"))
    add(p("News / source trail", "heading"))
    add(p("News: N/A. Required window: (26 Oct 19:45, 27 Oct 07:45] IST. Previously collected articles use an older window and are excluded.", "small"))
    refs = [("Flows / futures: GitHub evidence run 40365801399", data["sources"][0]["url"]),
            ("Quotes / option access: GitHub evidence run 40361970131", data["sources"][1]["url"]),
            ("Global observations: GitHub evidence run 40368775767", data["sources"][2]["url"]),
            ("Calendar evidence: GitHub run 40379282618", data["sources"][3]["url"])]
    refs += [(e["agency"] + ": " + e["title"], e["source"]) for e in events]
    for label, url in refs:
        add(linked(label, url))
    add(Spacer(1, 4))
    add(p("Narrative: Codex review in this chat; no unattended AI API. This is a partial captured-data replay, not a live morning report. Pending work is recorded in docs/dry-run-todo.md.", "small"))

    def footer(canvas, doc):
        canvas.setStrokeColor(colors.HexColor("#BCCED6"))
        canvas.line(42, 33, A4[0] - 42, 33)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(navy)
        canvas.drawString(42, 21, "DRY RUN | Report 27 Oct 2026 | Personal informational use")
        canvas.drawRightString(A4[0] - 42, 21, f"{doc.page} / 2")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(output), pagesize=A4, rightMargin=42, leftMargin=42,
                      topMargin=30, bottomMargin=43, title="NSE morning report - captured-data dry run",
                      author="NSE Morning Report", pageCompression=1).build(story, onFirstPage=footer, onLaterPages=footer)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = json.loads(args.snapshot.read_text(), parse_float=Decimal)
    result = analyze(data)
    render(data, result, args.output)
    print(json.dumps({"mode": data["mode"], "score": result["score"], "output": str(args.output)}, default=str))


if __name__ == "__main__":
    main()
