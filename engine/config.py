"""Everything the pipeline treats as a rule lives here, so it can be read in one place.

Titles, tiers, the company gate limits and the per-market phone rules. Nothing in here is
client data. Change a number here and every step picks it up.
"""
import re

# ------------------------------------------------------------------ markets
# One entry per market. `dial` is the country calling code, `location` is the string
# Prospeo expects in its location filters.
MARKETS = {
    "CA": {"name": "Canada", "dial": "1", "location": "Canada #CA"},
    "DE": {"name": "Germany", "dial": "49", "location": "Germany #DE"},
    "UK": {"name": "United Kingdom", "dial": "44", "location": "United Kingdom #GB"},
    "IE": {"name": "Ireland", "dial": "353", "location": "Ireland #IE"},
    "FR": {"name": "France", "dial": "33", "location": "France #FR"},
    "NL": {"name": "Netherlands", "dial": "31", "location": "Netherlands #NL"},
    "BE": {"name": "Belgium", "dial": "32", "location": "Belgium #BE"},
    "AT": {"name": "Austria", "dial": "43", "location": "Austria #AT"},
    "PT": {"name": "Portugal", "dial": "351", "location": "Portugal #PT"},
}

# ------------------------------------------------------------------ company gate
HEADCOUNT_MIN = 50        # hard cut below this (range -> midpoint)
HEADCOUNT_MAX = 1500      # over this it is an enterprise deal: slow, committee-bought
SWEET_SPOT = (80, 400)    # agents; used only as a note on the scorecard

# Verticals, best fit first. Points feed the 20-pt "sub-vertical fit" line of the matrix.
VERTICAL_POINTS = [
    (re.compile(r"collect|inkasso|recouvrement|receivable|\barm\b|debt", re.I), 20),
    (re.compile(r"bpo|outsourc|contact cent|call cent|answering|callcenter", re.I), 20),
    (re.compile(r"insur|claims|assistance|versicher|schaden|\btpa\b", re.I), 15),
    (re.compile(r"market research|cati|telefonstudio|survey", re.I), 15),
    (re.compile(r"bank|lend|credit|financ", re.I), 10),
]
VERTICAL_DEFAULT = 8

# Verticals the client ruled out. A company that lands here is cut, not scored.
BANNED_VERTICAL = re.compile(
    r"utilit|hydro|power|energy|property|condo|reit|apartment|real estate|metering"
    r"|telemedicine|health.?tech|marketplace|saas|software", re.I)

# Call-QA tools. Already having one means not greenfield: REVIEW, not an automatic cut.
QA_TOOLS = re.compile(r"verint|nice|callminer|observe\.?ai|calabrio|playvox", re.I)

# ------------------------------------------------------------------ titles
# What we ask the people database for. English plus the German forms that show up on
# LinkedIn, because the search matches on substrings.
JOB_TITLES = [
    "CEO", "Chief Executive Officer", "Managing Director", "Owner", "Founder", "President",
    "COO", "Chief Operating Officer", "CTO", "Chief Technology Officer", "CIO",
    "Chief Customer Officer", "Chief Experience Officer", "Chief Revenue Officer",
    "Executive Vice President", "Senior Vice President",
    "VP Operations", "VP Customer Experience", "VP Customer Service", "VP Collections",
    "VP Contact Centre", "VP Claims",
    "Director of Operations", "Operations Director", "Director of Customer Service",
    "Director of Customer Experience", "Director of Contact Centre", "Call Centre Director",
    "Director of Collections", "Director of Claims", "Director of Compliance",
    "Head of Operations", "Head of Contact Centre", "Head of Contact Center",
    "Head of Customer Service", "Head of Customer Experience", "Head of Customer Care",
    "Head of Collections", "Head of Compliance", "Head of Quality", "Head of Quality Assurance",
    "Head of Claims", "Head of Support",
    "Geschaeftsfuehrer", "Geschäftsführer", "Vorstand", "Inhaber",
    "Leiter Kundenservice", "Leiter Operations", "Leiter Qualitätsmanagement",
    "Leiter Callcenter", "Leiter Servicecenter", "Bereichsleiter", "Abteilungsleiter",
    # Tier C, only used to fill a company that has nobody senior
    "Contact Centre Manager", "Call Centre Manager", "Operations Manager", "QA Manager",
]

TIER_A = re.compile(
    r"\b(ceo|chief \w+ officer|chief executive|managing director|founder|owner|president"
    r"|coo|cto|cio|cso|cmo|gesch.ftsf.hrer|vorstand|inhaber|gr.nder)\b", re.I)
TIER_B = re.compile(
    r"\b(head of|vp|svp|evp|vice president|director|direktor|leiter|leitung"
    r"|bereichsleiter|abteilungsleiter)\b", re.I)
TIER_C = re.compile(r"\b(manager|lead|supervisor|teamleiter)\b", re.I)

# People who own call quality day to day.
PAIN_FEELER = re.compile(
    r"quality|\bqa\b|\bqc\b|qualit.t|operations|betrieb|compliance|customer service"
    r"|kundenservice|customer experience|customer care|support|contact cent|call ?cent"
    r"|servicecenter|collection|claims", re.I)

# Functions that are never the buyer or the floor owner, however senior the title reads.
OFF_ICP = re.compile(
    r"art director|creative|account director|account manager|brand|design|public affairs"
    r"|people ?(&|and) ?culture|talent|recruit|\bhr\b|human resources|personal(wesen)?"
    r"|legal|recht|\btax\b|steuer|audit|revision|controlling|treasury|investor"
    r"|product owner|scrum|software|engineer|developer|architekt|data scien"
    r"|real estate|immobilien|facility|einkauf|procurement|bezirksdirektor|vertriebsdirektor",
    re.I)

# Ranking inside one company. Higher wins.
DECISION_MAKER_RANK = [
    (re.compile(r"gesch.ftsf.hrer|managing director|\bceo\b|chief executive", re.I), 100),
    (re.compile(r"\bcoo\b|chief operating", re.I), 90),
    (re.compile(r"\binhaber|\bowner\b|gr.nder|founder|\bpresident\b", re.I), 85),
    (re.compile(r"\bvorstand\b|chief \w+ officer", re.I), 80),
    (re.compile(r"\b(evp|svp)\b|(executive|senior) vice president", re.I), 70),
    (re.compile(r"\bcio\b|\bcto\b|chief (information|technology)", re.I), 60),
    (re.compile(r"(head of|leiter|leitung|vp|director).{0,30}(operations|betrieb)", re.I), 55),
]
PAIN_FEELER_RANK = [
    (re.compile(r"(head of|leiter|leitung|director|direktor|vp).{0,30}"
                r"(quality|qualit|\bqa\b|\bqc\b)", re.I), 100),
    (re.compile(r"(head of|leiter|leitung|director|direktor|vp).{0,30}"
                r"(contact ?cent|call ?cent|servicecenter|service ?cent)", re.I), 95),
    (re.compile(r"(head of|leiter|leitung|director|direktor|vp).{0,30}"
                r"(customer service|kundenservice|customer care)", re.I), 90),
    (re.compile(r"(head of|leiter|leitung|director|direktor|vp).{0,30}"
                r"(operations|betrieb|inkasso|collection|claims|schaden)", re.I), 85),
    (re.compile(r"(head of|leiter|leitung|director|direktor|vp).{0,30}"
                r"(compliance|customer experience|support)", re.I), 75),
    (re.compile(r"\bcoo\b|chief operating", re.I), 70),
    (re.compile(r"manager.{0,20}(quality|qa|contact|call|operations)", re.I), 30),
]

PEOPLE_PER_COMPANY = 2    # one decision-maker plus one pain-feeler
