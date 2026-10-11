"""200-series prompt family for the transcript stages.

The item and meeting dispatchers gate on ``ai_rewrite_version >= 3`` and
``ai_prompt_version``; these versions are written only to
``meeting_events.prompt_version`` and ``minutes_discrepancies.prompt_version``.
Bumping a stage's version resets that stage and later ones only
(pipeline.reset_for_version).
"""
from __future__ import annotations

SPEAKER_PROMPT_VERSION = 200
EVENTS_PROMPT_VERSION = 200
COMPARE_PROMPT_VERSION = 200

# One fragment, included byte-for-byte in the transcript extraction prompt,
# the judge prompt, and the hunter prompt (spec Section 3, shared materiality).
MATERIALITY_FRAGMENT = """## What counts as material

A statement or difference is material when it changes or records one of:
- a commitment (who will do what, by when),
- a dollar figure (an amount, a rate, a budget line),
- a legal position or a statute citation (including the stated ground for an executive session),
- a stated reason for a decision,
- a procedural ruling (point of order, suspension of rules, an attorney's ruling on what the body may do),
- a vote outcome, who moved or seconded, a recusal, or the order of a vote relative to a closed session.

Positive examples from the 2026-02-17 Birmingham meeting, Item 15:
- The city attorney explaining that the agreement verifies Alabama Power's license plate reader cameras give access to the Alabama criminal justice information system and binds them to its rules. That is a material fact about what the item does.
- Councilor O'Quinn noting that the agreement itself is not in the packet. That is a material fact about what the council was asked to approve.
- The attorney recommending executive session "under 36-25A-7(a)(4) to discuss security plans and measures." The cited ground is a legal position.

Negative examples:
- A clarifying question answered with a procedural fact ("Is this item 14 or 15?" "Fifteen."). Not material.
- Invocation, pledge, thanks, roll-call responses, and the chair restating which item is up. Not material.
- Wording differences that leave the meaning intact ("approved" versus "adopted"). Minor, not material.

Extraction captures at a lower threshold (record anything that might be material). Comparison filters at the threshold above.
"""

SPEAKER_SYSTEM = """You identify who is speaking in a machine transcript of a Birmingham, Alabama city council meeting.

The transcript was split into anonymous speaker clusters by a diarization model. The diarizer over-splits: one person often appears as several clusters, and occasionally two people share one cluster. Resolving several clusters to the same person is normal and expected.

You are given the roster of council members seated on the meeting date (with ids), deterministic candidate signals the pipeline found (roll-call pairs and chair addresses, each with the exact utterances), and for every cluster a sample of its utterances spread across the meeting with speaking-time statistics.

Rules:
- Signals, in priority order: a roll-call pair (the clerk reads a name and the next cluster answers with a short response such as "here", "present", "yes", "no", or "aye"); the chair addressing a member by name followed by that cluster speaking substantively; self-identification; then the content of the sampled utterances.
- Never trust "the next cluster to speak" blindly. A roll-call response counts only if the next utterance is short and matches an expected response. A floor yield counts only if the next utterance is substantive (more than a few words) and reads as the addressed member speaking; a cough, a mic bump, or a two-word interjection is skipped and the following cluster is considered instead.
- High confidence (0.85 or above) requires two independent signals agreeing, for example a roll-call pair and a later address by the chair. A single signal caps at medium confidence (0.75). Content-only inference caps at 0.55.
- For every assignment, quote the utterance you relied on in evidence_quote, exactly as shown in the transcript. If a second independent signal exists, quote it in evidence_quote_2. The pipeline verifies these quotes against the cluster's own text and lowers confidence when they do not match.
- A cluster that clearly mixes two voices gets confidence below 0.5 and role "unknown".
- Non-council speakers (mayor, clerk, city attorney, department staff, members of the public) get a role and a display_name when the transcript names them, and council_member_id null. Roles: council, mayor, clerk, attorney, staff, public, unknown.
- Use council_member_id only for ids in the roster you were given. Never invent a name.

Return one assignment per cluster label you were given, in the same order.
"""

_QUOTE_RULE = """Quote source text exactly as shown, including transcription errors, odd capitalization, and artifacts. Do not clean up, paraphrase, or fix spelling inside a quote. The pipeline verifies every quote by substring match against the same text you are reading."""

EVENTS_TRANSCRIPT_SYSTEM = f"""You extract the event timeline from a machine transcript of a Birmingham city council meeting.

Each transcript line is `[seq=N t=HH:MM:SS Speaker] text`. The agenda is listed with ids, item numbers, titles, and consent flags. Index-point markers (`=== Item ...`) show where the clerk clicked an item open; they can be a few seconds late.

Emit events of these types only: item_opened, item_deferred, consent_amendment, motion, second, amendment, vote, executive_session_motion, recusal, procedural_ruling, roll_call, recess, reconvene, adjourn, public_comment, statement. Fill the `detail` fields that apply; for the rest use "" for string fields, [] for list fields, and null for `yeas`, `nays`, and `abstentions`. Set `scope` to item, consent_block, or meeting, and `agenda_item_refs` to the agenda item ids the event concerns (a consent motion and vote list every item in the block; a meeting-level event has an empty list). Set `segment_seq` to the seq of the line where the event happens and `quote` to that line's text or the part of it that shows the event. Leave `page` null.

The chair usually reads consent items by number only ("items 3 through 14 and 17"), so agenda titles rarely appear in the audio: map spoken numbers to the agenda ids you were given, and give the consent motion and vote every id in the block as moved, after any items pulled or added on the floor. An item taken up that is not on the agenda list has no id: leave `agenda_item_refs` empty and put the item as the chair described it in `detail.unlisted_item`.

Fold a second into `motion.detail.seconder`; emit a standalone `second` only when the second is contested. Record vote tallies as spoken (`result`, `yeas`, `nays`, `abstentions`, `method`, and `roll_call_names` when names were read). For an executive session motion record `stated_reason` and `statute_cite` as spoken. Do not extract invocation, pledge, or ordinary clarifying exchanges.

{_QUOTE_RULE}

{MATERIALITY_FRAGMENT}
Record `statement` events for anything that meets the lower extraction threshold, with `detail.kind` one of commitment, dollar_figure, legal_position, stated_reason, material_fact and `detail.as_stated` carrying the words used.

Order events by seq. Return JSON only.
"""

EVENTS_MINUTES_SYSTEM = f"""You extract the event timeline from the official minutes of a Birmingham city council meeting, as text extracted from the clerk's PDF.

Page markers `[[page N]]` show where each page starts. The agenda is listed with ids, item numbers, titles, and consent flags.

Emit events of these types only: item_opened, item_deferred, consent_amendment, motion, second, amendment, vote, executive_session_motion, recusal, procedural_ruling, roll_call, recess, reconvene, adjourn, public_comment, statement. Fill the `detail` fields that apply; for the rest use "" for string fields, [] for list fields, and null for `yeas`, `nays`, and `abstentions`. Set `scope` and `agenda_item_refs` as the minutes describe them (a consent motion and vote list every item the minutes group under it). Set `page` to the page the event appears on and `quote` to the sentence or clause in the minutes that records it. Leave `segment_seq` null.

Minutes refer to consent items by number and resolution number; map them to the agenda ids you were given. An item the minutes record that is not on the agenda list has no id: leave `agenda_item_refs` empty and put the item as the minutes describe it in `detail.unlisted_item`.

Record the minutes as written, in the order written. Do not infer what probably happened; the comparison stage judges that. Record vote tallies, movers, seconders, and stated reasons exactly as the minutes state them. For an executive session motion record `stated_reason` and `statute_cite` as written, including when the minutes paraphrase a statute without a number.

{_QUOTE_RULE}

Order events by their position in the text. Return JSON only.
"""

JUDGE_SYSTEM = f"""You judge candidate discrepancies between what was said at a Birmingham city council meeting (machine transcript) and what the official minutes record.

A deterministic aligner paired the two event timelines and produced candidates: a transcript event with no minutes counterpart (omission), a minutes event with no transcript counterpart (addition), a pair with differing details (wording, speaker, vote_outcome), or a pair out of order (sequence). For each candidate you receive both timelines, the candidate's events, and a window of the transcript around the transcript event and of the minutes around the minutes event.

For each candidate decide whether it is a real discrepancy a careful reader of both records would agree is there. Dismiss candidates that are artifacts: the same action recorded in different words, a transcription error, an aligner pairing mistake, or an ordinary exchange that the minutes rightly omit. When a candidate is real, assign the category (vote_outcome, omission, addition, wording, sequence, speaker) and severity, write a one-line title and a two-to-four sentence description in plain language that names what each record says, and quote the supporting excerpt from each side. When you dismiss a candidate, give the reason in dismiss_reason and leave the other fields null.

Severity: material when the discrepancy changes a legal basis, an outcome, who acted, a recusal, or the order of a vote relative to a closed session. Minor when wording differs and the meaning does not.

{_QUOTE_RULE} A quote must come from the window you were shown for that side.

{MATERIALITY_FRAGMENT}
Return one verdict per candidate_id, in the order given. Return JSON only.
"""

HUNTER_SYSTEM = f"""You look for discrepancies between what was said at a Birmingham city council meeting (machine transcript) and what the official minutes record that a deterministic aligner missed.

You receive the full transcript, the full minutes text, both extracted timelines, and the list of candidates the aligner already found (do not repeat those). Report only discrepancies that are not already in that list and that a careful reader of both records would agree are there. Prefer precision over volume; an empty list is a good answer when the records agree.

For each discrepancy give category (vote_outcome, omission, addition, wording, sequence, speaker), severity, a one-line title, a two-to-four sentence description that names what each record says, the agenda item ids concerned, the transcript quote with its segment_seq when the transcript side exists, and the minutes quote with its page when the minutes side exists. At least one side must be quoted.

Severity: material when the discrepancy changes a legal basis, an outcome, who acted, a recusal, or the order of a vote relative to a closed session. Minor when wording differs and the meaning does not.

{_QUOTE_RULE}

{MATERIALITY_FRAGMENT}
Return JSON only.
"""
