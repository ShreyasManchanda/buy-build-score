"""people_named + owner_name: regexes on "Owner: Name", "Name, Founder", "founded by Name", "Dr. Name".

P0 per SPEC (spaCy PERSON entities are P1). Names are only ever what the page states: no inference.
"""

from __future__ import annotations

import re

from app.extractors import jsonld
from app.extractors.base import Evidence, Pages, snippet_at

_N = r"[A-Z][a-z]+(?:[-'’][A-Z]?[a-z]+)?"
# Tokens join on spaces only, never newlines: page text keeps one line per block element.
NAME = rf"{_N}(?:[ \t]+[A-Z]\.)?(?:[ \t]+(?:Mc|Mac|O')?{_N}){{1,2}}"
TITLES = r"owner|co-owner|founder|co-founder|president|principal|ceo|proprietor|managing partner"
TITLE_RANK = [
    "owner",
    "co-owner",
    "founder",
    "co-founder",
    "president",
    "principal",
    "ceo",
    "proprietor",
    "managing partner",
    "dr.",
]

# Names are case-sensitive (Capitalised Words); only the titles/verbs around them ignore case.
_T = rf"(?i:{TITLES})"
_PATTERNS = [
    re.compile(rf"\b(?P<title>{_T})\s*(?:[:,–—-]|&\s*\w+\s*[:,–—-])\s*(?P<name>{NAME})"),
    re.compile(rf"(?P<name>{NAME}),\s*(?:[A-Z]{{2,5}},\s*)?(?i:the\s+|our\s+)?(?P<title>{_T})\b"),
    re.compile(rf"(?P<name>{NAME})\s+(?i:is|has been|became)\s+(?i:the\s+|our\s+)?(?P<title>{_T})\b"),
    re.compile(
        rf"\b(?P<title>(?i:founded|started|established))\s+(?i:in\s+\d{{4}}\s+)?(?i:by)\s+(?P<name>{NAME})"
    ),
    re.compile(rf"\b(?:our\s+|the\s+)?(?P<title>owner|founder|president)\s+(?P<name>{NAME})\b"),
    re.compile(rf"\b(?P<title>Dr\.?)\s+(?P<name>{NAME})"),
]
OWNER_TITLES = set(TITLE_RANK) - {"dr."}

# Capitalised words that look like names in headings but aren't people.
_NOT_NAME = {
    "heating",
    "cooling",
    "air",
    "plumbing",
    "plumbers",
    "electric",
    "electrical",
    "services",
    "service",
    "company",
    "inc",
    "llc",
    "corp",
    "co",
    "group",
    "dental",
    "dentistry",
    "family",
    "auto",
    "repair",
    "automotive",
    "landscape",
    "landscaping",
    "lawn",
    "roofing",
    "cleaning",
    "columbus",
    "ohio",
    "the",
    "our",
    "team",
    "contact",
    "about",
    "us",
    "home",
    "since",
    "call",
    "today",
    "free",
    "estimate",
    "mechanical",
    "hvac",
    "center",
    "care",
    "street",
    "avenue",
    "road",
    "suite",
    "north",
    "south",
    "east",
    "west",
    "village",
    "city",
    "county",
    "smiles",
    "orthodontics",
    "associates",
    "and",
    "sons",
    "member",
    "members",
    "staff",
    "office",
    "manager",
    "license",
    "licensed",
    "insured",
    "certified",
    "read",
    "more",
    "learn",
    "meet",
    "welcome",
    "privacy",
    "policy",
    "terms",
    "copyright",
    "all",
    "rights",
    "reserved",
    "partners",
    "partner",
    "solutions",
    "systems",
    "comfort",
    "tree",
    "garden",
}


def _rank(title: str) -> int:
    return TITLE_RANK.index(title) if title in TITLE_RANK else len(TITLE_RANK)


def _title_norm(t: str) -> str:
    t = t.lower().rstrip(".")
    if t in ("founded", "started", "established"):
        return "founder"
    return "dr." if t == "dr" else t


def _ok_name(name: str) -> bool:
    words = [w.strip(".").lower() for w in name.split()]
    return len(words) >= 2 and not any(w in _NOT_NAME for w in words)


def people(pages: Pages) -> list[Evidence]:
    """Returns `people_named` (always, when pages exist) and `owner_name` (when a leader is named)."""
    if not pages.pages:
        return []
    found: dict[str, dict[str, str]] = {}

    def add(name: str, title: str, url: str, snip: str) -> None:
        name = " ".join(name.split())
        prev = found.get(name.lower())
        if prev is None or _rank(title) < _rank(prev["title"]):
            found[name.lower()] = {"name": name, "title": title, "url": url, "snippet": snip}

    for p in pages.pages:
        # schema.org people count only when the markup says who they are to the business:
        # an organisation's `founder`, or a Person whose jobTitle is an owner-type title.
        # A bare Person (review author, recruiter, staff member on a careers page) is not a leader.
        for obj in jsonld.objects(p):
            founders = obj.get("founder")
            for f in founders if isinstance(founders, list) else [founders]:
                fname = f.get("name") if isinstance(f, dict) else f
                if isinstance(fname, str) and _ok_name(fname):
                    add(fname, "founder", p.url, f"schema.org founder: {fname}")
            if (
                str(obj.get("@type", "")) == "Person"
                and isinstance(obj.get("name"), str)
                and _ok_name(obj["name"])
            ):
                job = str(obj.get("jobTitle") or "")
                title = _title_norm(job.split()[0]) if job else ""
                if title in TITLE_RANK and title != "dr.":
                    add(obj["name"], title, p.url, f"schema.org Person: {obj['name']}, {job}")
        text = p.text
        for pat in _PATTERNS:
            for m in pat.finditer(text):
                name = m.group("name")
                if not _ok_name(name):
                    continue
                add(name, _title_norm(m.group("title")), p.url, snippet_at(text, m.start(), m.end()))

    names = sorted(found.values(), key=lambda d: _rank(d["title"]))
    has_team_page = bool(pages.of_kind("team")) or bool(
        pages.home and pages.home.tree.css_first('a[href*="team"], a[href*="staff"], a[href*="leadership"]')
    )
    out = [
        Evidence(
            "people_named",
            [n["name"] for n in names],
            f"{len(names)} named" if names else "nobody named",
            names[0]["url"] if names else pages.home_url,
            snippet=names[0]["snippet"] if names else f"Checked {len(pages.pages)} page(s)",
            extra={"has_team_page": has_team_page, "people": names},
        )
    ]
    # Owner = someone with an owner-type title, or a lone "Dr." (a solo practice). Two doctors: unknown.
    lead = names[0] if names else None
    if lead and (lead["title"] in OWNER_TITLES or len(names) == 1):
        out.append(
            Evidence(
                "owner_name",
                lead["name"],
                lead["name"],
                lead["url"],
                snippet=lead["snippet"],
                extra={"title": lead["title"]},
            )
        )
    return out
