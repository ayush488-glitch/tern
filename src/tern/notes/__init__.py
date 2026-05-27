"""S12 / D4 — live HTML notes artifact.

Public surface:

  Note, append_note, read_notes, notes_path  — store
  render_html                                 — emit notes.html
"""

from tern.notes.render import render_html
from tern.notes.store import Note, append_note, notes_path, read_notes

__all__ = [
    "Note",
    "append_note",
    "notes_path",
    "read_notes",
    "render_html",
]
