"""Captured fixture data for vote-matcher v2 regression tests.

Source: Birmingham Regular City Council Meeting, 2025-12-16 (meeting_id 26).
Vote 1342 — 7-0 approval of a quitclaim deed to Shield Property Solutions, LLC
for property at 609 4th Ave N for $11,155.25.

This is the canonical wrong-haystack failure case: raw_text contains the
substance, match_context contains only procedural language, and the v1
matcher does not link them.
"""

VOTE_1342_RAW_TEXT = """\
at Shield Property
Solutions, LLC has an interest in the Property, and accordingly, recommends that Shield
Property Solutions, LLC be allowed to purchase the Property for the amount of Eleven
Thousand One Hundred Fifty-Five and 25/100 Dollars ($11,155.25), which represents the total
amount of the original assessments plus costs, fees, and interest thereon at the rate of six
percent (6%) per annum.
NOW, THEREFORE, BE IT ORDAINED by the Council of the City of Birmingham
that the mayor be and hereby is authorized to execute, on behalf of the City of Birmingham, a
Quitclaim Deed conveying the Property to Shield Property Solutions, LLC upon payment of
the amount of $11,155.25 to the City within ninety (90) days of City Council approval.
NAME OF GRANTEE PROPERTY DESCRIPTION AMOUNT
Shield Property Solutions, LLC THE WEST 30 FEET OF LOT 7 AND $11,155.25
THE EAST 5 FEET OF LOTS 8 AND 10,
BLOCK 354, ACCORDING TO THE
PRESENT PLAN AND SURVEY OF THE
CITY OF BIRMINGHAMAS MADE BY
ELYTON LAND COMPANY, SITUATED
IN JEFFERSON COUNTY, ALABAMA.
PARCEL ID 22 00 35 3 032 004.000
City Account: 5332
PHYSICAL ADDRESS
609 4th Ave N
Birmingham, AL 35203
BE IT FURTHER ORDAINED that, in the judgment of said Council, the Property is not
needed for public or municipal purposes.
The resolution was read by the City Clerk, whereupon Councilmember Smitherman
made a motion that unanimous consent be granted to adopt said ordinance, which motion was
seconded by Councilmember Tate , and upon the roll being called, the vote was as follows:
Ayes: Gunn, Smith, Smitherman, Williams, Woods, Tate, Alexander
Nays: None
The vote was then announced by the City Clerk, whereupon the Presiding Officer
declared the motion to give unanimous consent for adoption of said ordinance adopted.
DEC 16 2025 6
Whereupon Councilmemb"""

VOTE_1342_MATCH_CONTEXT = (
    "ity Clerk, whereupon Councilmember Smitherman\n"
    "made a motion that unanimous consent be granted to adopt said ordinance, which motion was\n"
    "seconded by Councilmember Tate , and upon the roll being called,"
)

# Birmingham council surnames that appear in vote 1342's raw_text (used to
# verify the proper-noun denylist filters them out).
BIRMINGHAM_COUNCIL_SURNAMES_DEC_2025 = frozenset({
    "Gunn", "Smith", "Smitherman", "Williams", "Woods", "Tate", "Alexander",
})

# The agenda item this vote should match against.
AGENDA_ITEM_1256 = {
    "id": 1256,
    "item_number": "64",
    "title": (
        "P\t\tITEM 20. \n"
        "An Ordinance authorizing the Mayor, upon receipt of payment in the "
        "amount of $11,155.25, to execute a quitclaim deed to Shield Property "
        "Solutions, LLC, for the sale of property legally described as THE "
        "WEST 30 FEET OF LOT 7 AND THE EAST 5 FEE"
    ),
    "description": "",
}

# Distractor agenda items in the same meeting that should NOT match.
DISTRACTOR_AGENDA_ITEMS = [
    {
        "id": 1200,
        "item_number": "1",
        "title": "An Ordinance approving the City of Birmingham FY2026 budget",
        "description": "",
    },
    {
        "id": 1201,
        "item_number": "2",
        "title": "A Resolution honoring the Birmingham Public Library staff",
        "description": "",
    },
]
