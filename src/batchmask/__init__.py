"""Batch masking from presets: lens edge, people and sky for a whole scene in one call.

Built for the batch tool outside this app (``python -m src.cli run / probe / preset``); the app opens the
same thing from File > Batch Masking with Presets. Nothing here needs Qt.

- :mod:`.presets`: what a preset holds (the SAM3 prompts above all), where presets live, reading and saving.
- :mod:`.probe`: trying prompts on a few frames before a whole run — a table of what each prompt finds
  and contact sheets to look at, scored against masks already checked by hand when there are some.

A preset's prompts are right for the rig and scenes it was checked on, not in general ("black pole" is the
selfie stick of an OSMO 360 on 0022; another rig's stick may be silver, or not there). Each preset says
what it was checked on; on anything else, probe first.
"""
