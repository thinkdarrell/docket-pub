/**
 * admin.js — shared admin UI helpers.
 *
 * Loaded by the three coverage admin forms (new_note, new_citation, edit)
 * that include the subject picker.  Kept as a separate static file so the
 * function is defined exactly once rather than duplicated inline.
 */

/**
 * Add a subject chip to the #selected-subjects container.
 *
 * Called from the HTMX-rendered _search_results.html "Add" buttons:
 *   <button onclick="addSubjectChip(this)" data-subject-type="..." ...>
 *
 * @param {HTMLElement} btn  The button element that was clicked.
 */
function addSubjectChip(btn) {
  var ds = btn.dataset;
  var container = document.getElementById('selected-subjects');
  if (!container) return;

  var chip = document.createElement('span');
  chip.className = 'subject-chip';

  var label = document.createTextNode(ds.subjectType + ': ' + ds.subjectLabel + ' ');
  chip.appendChild(label);

  var hidden = document.createElement('input');
  hidden.type = 'hidden';
  hidden.name = 'subject[]';
  hidden.value = ds.subjectType + ':' + ds.subjectId;
  chip.appendChild(hidden);

  var rm = document.createElement('button');
  rm.type = 'button';
  rm.textContent = '✕';
  rm.addEventListener('click', function () { chip.remove(); });
  chip.appendChild(rm);

  container.appendChild(chip);
}
