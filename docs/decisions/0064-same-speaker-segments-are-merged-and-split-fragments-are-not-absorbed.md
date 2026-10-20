# 0064 — Back-to-back segments from one cluster are joined up to 30 seconds after the split, and a one-word fragment of a split greeting is not absorbed into its neighbour

## Decision

After `split_by_speaker()`, `merge_same_speaker()` in `transcriber/transcriber/engine.py` joins consecutive segments that share a non-`None` cluster when the gap between them is at most `MERGE_MAX_GAP_S` (1.0 s) and the joined span at most `MERGE_MAX_S` (30 s); the joined `avg_logprob` is the duration-weighted mean and `no_speech_prob` the larger of the two. The split itself still does no smoothing of short runs (decision `0047`): an unpunctuated one-word run such as `SPEAKER_08: Good` before `SPEAKER_07: morning. Council Member Williams...` stays its own segment. Output carrying the merge is `transcripts.version = 3`.

## Rationale

The operator's review of the first version-2 re-run (meeting 2543, 2026-10-17) found two readability defects: back-to-back rows from one speaker (24 pairs within 1 s and 30 s) and greetings cut one word in (`Good` | `morning.`). The merge fixes the first without changing who said anything: on the version-3 inputs of 2543 it takes 332 rows to 308 and the back-to-back pairs to 0, and the roll-call rows are unchanged.

A rule absorbing an unpunctuated one-word run into a following lowercase continuation was built and rejected on the same inputs. On 2543 the member says "Good" and the diarizer gives the member's "morning." to the clerk's cluster, so absorbing forward moved the two correct member labels onto the clerk, and the merge then joined the whole roll call into one 21-second clerk row. The fragment is a symptom of the diarizer giving most of the members' answers to the clerk (`D53`); hiding it makes the transcript read cleanly while attributing worse. The merge cap exists because without it a long speech collapses back into multi-minute rows; 30 seconds is the batched pipeline's chunk length. The weighted mean and the maximum are not honest per-row Whisper statistics (the reason `0047` gives children the chunk's numbers); nothing downstream reads the two columns (`src/` mentions them only in migration 035).

The trap is re-adding fragment absorption, or a minimum run length, because one-word rows look broken: on real roll calls the one-word row is often the only correctly labelled word.

## Date

2026-10-17, by hand on branch `feat/transcriber-v3-quick-wins` (plan `plans/completed/transcriber-v3-quick-wins.md`).

## Status

accepted
