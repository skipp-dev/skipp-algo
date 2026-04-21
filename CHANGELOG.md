# Changelog

<!-- markdownlint-disable MD024 -->

All notable changes to this project are documented in this file.

## [Unreleased]

### Added (2026-06-13) — Plan 2.8 amber max + mov + newline

- New `scripts/plan_2_8_ledger_amber_index_max.py` reports the
  maximum index of an amber status (-1 if none).
- New `scripts/plan_2_8_digest_mov_file_count.py` counts
  top-level ``.mov`` files.
- New `scripts/plan_2_8_weekly_summary_newline_char_count.py`
  counts ``\n`` characters in the summary.
- Weekly workflow wires the three new steps after the ``}`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-12) — Plan 2.8 green max + mp4 + brace-close

- New `scripts/plan_2_8_ledger_green_index_max.py` reports the
  maximum index of a green status (-1 if none).
- New `scripts/plan_2_8_digest_mp4_file_count.py` counts
  top-level ``.mp4`` files.
- New `scripts/plan_2_8_weekly_summary_brace_close_char_count.py`
  counts ``}`` characters in the summary.
- Weekly workflow wires the three new steps after the ``{`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-11) — Plan 2.8 unknown min + flac + brace-open

- New `scripts/plan_2_8_ledger_unknown_index_min.py` reports the
  minimum index of an unknown status (-1 if none).
- New `scripts/plan_2_8_digest_flac_file_count.py` counts
  top-level ``.flac`` files.
- New `scripts/plan_2_8_weekly_summary_brace_open_char_count.py`
  counts ``{`` characters in the summary.
- Weekly workflow wires the three new steps after the ``]`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-10) — Plan 2.8 red min + ogg + bracket-close

- New `scripts/plan_2_8_ledger_red_index_min.py` reports the
  minimum index of a red status (-1 if none).
- New `scripts/plan_2_8_digest_ogg_file_count.py` counts
  top-level ``.ogg`` files.
- New `scripts/plan_2_8_weekly_summary_bracket_close_char_count.py`
  counts ``]`` characters in the summary.
- Weekly workflow wires the three new steps after the ``[`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-09) — Plan 2.8 amber min + wav + bracket-open

- New `scripts/plan_2_8_ledger_amber_index_min.py` reports the
  minimum index of an amber status (-1 if none).
- New `scripts/plan_2_8_digest_wav_file_count.py` counts
  top-level ``.wav`` files.
- New `scripts/plan_2_8_weekly_summary_bracket_open_char_count.py`
  counts ``[`` characters in the summary.
- Weekly workflow wires the three new steps after the ``)`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-08) — Plan 2.8 green min + mp3 + paren-close

- New `scripts/plan_2_8_ledger_green_index_min.py` reports the
  minimum index of a green status (-1 if none).
- New `scripts/plan_2_8_digest_mp3_file_count.py` counts top-level
  ``.mp3`` files.
- New `scripts/plan_2_8_weekly_summary_paren_close_char_count.py`
  counts ``)`` characters in the summary.
- Weekly workflow wires the three new steps after the ``(`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-07) — Plan 2.8 unknown variance + raw + paren-open

- New `scripts/plan_2_8_ledger_unknown_index_variance.py` reports
  the population variance of unknown indices.
- New `scripts/plan_2_8_digest_raw_file_count.py` counts
  top-level ``.raw`` files.
- New `scripts/plan_2_8_weekly_summary_paren_open_char_count.py`
  counts ``(`` characters in the summary.
- Weekly workflow wires the three new steps after the ``>`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-06) — Plan 2.8 red variance + psd + gt

- New `scripts/plan_2_8_ledger_red_index_variance.py` reports the
  population variance of red indices.
- New `scripts/plan_2_8_digest_psd_file_count.py` counts top-level
  ``.psd`` files.
- New `scripts/plan_2_8_weekly_summary_gt_char_count.py` counts
  ``>`` characters in the summary.
- Weekly workflow wires the three new steps after the ``<`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-05) — Plan 2.8 amber variance + avif + lt

- New `scripts/plan_2_8_ledger_amber_index_variance.py` reports
  the population variance of amber indices.
- New `scripts/plan_2_8_digest_avif_file_count.py` counts
  top-level ``.avif`` files.
- New `scripts/plan_2_8_weekly_summary_lt_char_count.py` counts
  ``<`` characters in the summary.
- Weekly workflow wires the three new steps after the percent
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-04) — Plan 2.8 green variance + heic + percent

- New `scripts/plan_2_8_ledger_green_index_variance.py` reports
  the population variance of green indices.
- New `scripts/plan_2_8_digest_heic_file_count.py` counts
  top-level ``.heic`` files.
- New `scripts/plan_2_8_weekly_summary_percent_char_count.py`
  counts ``%`` characters in the summary.
- Weekly workflow wires the three new steps after the ampersand
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-03) — Plan 2.8 unknown stddev + tif + ampersand

- New `scripts/plan_2_8_ledger_unknown_index_stddev.py` reports
  the population stddev of unknown indices.
- New `scripts/plan_2_8_digest_tif_file_count.py` counts top-level
  ``.tif``/``.tiff`` files.
- New `scripts/plan_2_8_weekly_summary_ampersand_char_count.py`
  counts ``&`` characters in the summary.
- Weekly workflow wires the three new steps after the ``@`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-02) — Plan 2.8 red stddev + bmp + at

- New `scripts/plan_2_8_ledger_red_index_stddev.py` reports the
  population stddev of red indices.
- New `scripts/plan_2_8_digest_bmp_file_count.py` counts top-level
  ``.bmp`` files.
- New `scripts/plan_2_8_weekly_summary_at_char_count.py` counts
  ``@`` characters in the summary.
- Weekly workflow wires the three new steps after the dollar
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-01) — Plan 2.8 amber stddev + ico + dollar

- New `scripts/plan_2_8_ledger_amber_index_stddev.py` reports the
  population stddev of amber indices.
- New `scripts/plan_2_8_digest_ico_file_count.py` counts top-level
  ``.ico`` files.
- New `scripts/plan_2_8_weekly_summary_dollar_char_count.py`
  counts ``$`` characters in the summary.
- Weekly workflow wires the three new steps after the grave
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-31) — Plan 2.8 green stddev + webp + grave

- New `scripts/plan_2_8_ledger_green_index_stddev.py` reports the
  population stddev of green indices.
- New `scripts/plan_2_8_digest_webp_file_count.py` counts
  top-level ``.webp`` files.
- New `scripts/plan_2_8_weekly_summary_grave_char_count.py` counts
  grave accent characters in the summary.
- Weekly workflow wires the three new steps after the tilde
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-30) — Plan 2.8 unknown median + jpg + tilde

- New `scripts/plan_2_8_ledger_unknown_index_median.py` reports
  the median index of unknown records.
- New `scripts/plan_2_8_digest_jpg_file_count.py` counts top-level
  ``.jpg``/``.jpeg`` files.
- New `scripts/plan_2_8_weekly_summary_tilde_char_count.py` counts
  ``~`` characters in the summary.
- Weekly workflow wires the three new steps after the caret
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-29) — Plan 2.8 red median + gif + caret

- New `scripts/plan_2_8_ledger_red_index_median.py` reports the
  median index of red records.
- New `scripts/plan_2_8_digest_gif_file_count.py` counts top-level
  ``.gif`` files.
- New `scripts/plan_2_8_weekly_summary_caret_char_count.py` counts
  ``^`` characters in the summary.
- Weekly workflow wires the three new steps after the backslash
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-28) — Plan 2.8 amber median + svg + backslash

- New `scripts/plan_2_8_ledger_amber_index_median.py` reports the
  median index of amber records.
- New `scripts/plan_2_8_digest_svg_file_count.py` counts top-level
  ``.svg`` files.
- New `scripts/plan_2_8_weekly_summary_backslash_char_count.py`
  counts ``\`` characters in the summary.
- Weekly workflow wires the three new steps after the slash
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-27) — Plan 2.8 green median + pdf + slash

- New `scripts/plan_2_8_ledger_green_index_median.py` reports the
  median index of green records.
- New `scripts/plan_2_8_digest_pdf_file_count.py` counts top-level
  ``.pdf`` files.
- New `scripts/plan_2_8_weekly_summary_slash_char_count.py` counts
  ``/`` characters in the summary.
- Weekly workflow wires the three new steps after the asterisk
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-26) — Plan 2.8 transition rate + xz + asterisk

- New `scripts/plan_2_8_ledger_status_transition_rate.py` reports
  the fraction of pairwise status transitions.
- New `scripts/plan_2_8_digest_xz_file_count.py` counts top-level
  ``.xz`` files.
- New `scripts/plan_2_8_weekly_summary_asterisk_char_count.py`
  counts ``*`` characters in the summary.
- Weekly workflow wires the three new steps after the equal-count
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-25) — Plan 2.8 last transition + bz2 + equal

- New `scripts/plan_2_8_ledger_last_transition_index.py` surfaces
  the last status change index.
- New `scripts/plan_2_8_digest_bz2_file_count.py` counts top-level
  ``.bz2`` files.
- New `scripts/plan_2_8_weekly_summary_equal_char_count.py` counts
  ``=`` characters in the summary.
- Weekly workflow wires the three new steps after the minus-count
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-24) — Plan 2.8 first transition + gz + minus

- New `scripts/plan_2_8_ledger_first_transition_index.py` surfaces
  the first status change index.
- New `scripts/plan_2_8_digest_gz_file_count.py` counts top-level
  ``.gz`` files.
- New `scripts/plan_2_8_weekly_summary_minus_char_count.py` counts
  ``-`` characters in the summary.
- Weekly workflow wires the three new steps after the plus-count
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-23) — Plan 2.8 status transitions + tar files + plus

- New `scripts/plan_2_8_ledger_status_transition_count.py` counts
  adjacent status transitions in the ledger.
- New `scripts/plan_2_8_digest_tar_file_count.py` counts top-level
  ``.tar``/``.tgz`` files.
- New `scripts/plan_2_8_weekly_summary_plus_char_count.py` counts
  ``+`` characters in the summary.
- Weekly workflow wires the three new steps after the
  underscore-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-22) — Plan 2.8 unknown index mean + zip files + underscore

- New `scripts/plan_2_8_ledger_unknown_index_mean.py` reports the
  arithmetic mean of unknown observation indices.
- New `scripts/plan_2_8_digest_zip_file_count.py` counts top-level
  ``.zip`` files.
- New `scripts/plan_2_8_weekly_summary_underscore_char_count.py`
  counts ``_`` characters in the summary.
- Weekly workflow wires the three new steps after the pipe-count
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-21) — Plan 2.8 red index mean + html files + pipe

- New `scripts/plan_2_8_ledger_red_index_mean.py` reports the
  arithmetic mean of red observation indices.
- New `scripts/plan_2_8_digest_html_file_count.py` counts top-level
  ``.html``/``.htm`` files.
- New `scripts/plan_2_8_weekly_summary_pipe_char_count.py` counts
  ``|`` characters in the summary.
- Weekly workflow wires the three new steps after the
  apostrophe-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-20) — Plan 2.8 amber index mean + xml files + apostrophe

- New `scripts/plan_2_8_ledger_amber_index_mean.py` reports the
  arithmetic mean of amber observation indices.
- New `scripts/plan_2_8_digest_xml_file_count.py` counts top-level
  ``.xml`` files.
- New `scripts/plan_2_8_weekly_summary_apostrophe_char_count.py`
  counts ASCII single-quote characters in the summary.
- Weekly workflow wires the three new steps after the quote-count
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-19) — Plan 2.8 green index mean + log files + quote

- New `scripts/plan_2_8_ledger_green_index_mean.py` reports the
  arithmetic mean of green observation indices.
- New `scripts/plan_2_8_digest_log_file_count.py` counts top-level
  ``.log`` files.
- New `scripts/plan_2_8_weekly_summary_quote_char_count.py` counts
  ASCII double-quote characters in the summary.
- Weekly workflow wires the three new steps after the colon-count
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-18) — Plan 2.8 last unknown + tsv files + colon

- New `scripts/plan_2_8_ledger_last_unknown_index.py` reports the
  zero-based index of the most recent unknown observation.
- New `scripts/plan_2_8_digest_tsv_file_count.py` counts top-level
  ``.tsv`` files.
- New `scripts/plan_2_8_weekly_summary_colon_char_count.py` counts
  ``:`` characters in the summary.
- Weekly workflow wires the three new steps after the
  semicolon-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-17) — Plan 2.8 last red + csv files + semicolon

- New `scripts/plan_2_8_ledger_last_red_index.py` reports the
  zero-based index of the most recent red observation.
- New `scripts/plan_2_8_digest_csv_file_count.py` counts top-level
  ``.csv`` files.
- New `scripts/plan_2_8_weekly_summary_semicolon_char_count.py`
  counts ``;`` characters in the summary.
- Weekly workflow wires the three new steps after the comma-count
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-16) — Plan 2.8 last amber + png files + comma

- New `scripts/plan_2_8_ledger_last_amber_index.py` reports the
  zero-based index of the most recent amber observation.
- New `scripts/plan_2_8_digest_png_file_count.py` counts top-level
  ``.png`` files.
- New `scripts/plan_2_8_weekly_summary_comma_char_count.py` counts
  ``,`` characters in the summary.
- Weekly workflow wires the three new steps after the
  exclamation-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-15) — Plan 2.8 last green + yml files + exclamation

- New `scripts/plan_2_8_ledger_last_green_index.py` reports the
  zero-based index of the most recent green observation.
- New `scripts/plan_2_8_digest_yml_file_count.py` counts top-level
  ``.yml``/``.yaml`` files.
- New `scripts/plan_2_8_weekly_summary_exclamation_char_count.py`
  counts ``!`` characters in the summary.
- Weekly workflow wires the three new steps after the
  question-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 first unknown + jsonl files + question

- New `scripts/plan_2_8_ledger_first_unknown_index.py` reports the
  zero-based index of the first unknown observation.
- New `scripts/plan_2_8_digest_jsonl_file_count.py` reports the
  count of top-level ``.jsonl`` files.
- New `scripts/plan_2_8_weekly_summary_question_char_count.py`
  counts ``?`` characters in the summary.
- Weekly workflow wires the three new steps after the
  sentence-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 first red + txt files + sentences

- New `scripts/plan_2_8_ledger_first_red_index.py` reports the
  zero-based index of the first red observation.
- New `scripts/plan_2_8_digest_txt_file_count.py` reports the
  count of top-level ``.txt`` files.
- New `scripts/plan_2_8_weekly_summary_sentence_count.py`
  counts sentence terminators in the summary.
- Weekly workflow wires the three new steps after the
  non-ascii-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 first amber + json files + non-ascii

- New `scripts/plan_2_8_ledger_first_amber_index.py` reports the
  zero-based index of the first amber observation.
- New `scripts/plan_2_8_digest_json_file_count.py` reports the
  count of top-level ``.json`` files.
- New `scripts/plan_2_8_weekly_summary_non_ascii_char_count.py`
  counts code points with ord > 127 in the summary.
- Weekly workflow wires the three new steps after the
  hash-char upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 first green + md files + hash chars

- New `scripts/plan_2_8_ledger_first_green_index.py` reports the
  zero-based index of the first green observation.
- New `scripts/plan_2_8_digest_md_file_count.py` reports the
  count of top-level ``.md`` files.
- New `scripts/plan_2_8_weekly_summary_hash_char_count.py`
  counts ``#`` characters in the summary.
- Weekly workflow wires the three new steps after the
  tab-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 unknown streak + nonempty files + tabs

- New `scripts/plan_2_8_ledger_unknown_streak_max.py` reports the
  longest consecutive unknown run.
- New `scripts/plan_2_8_digest_nonempty_file_count.py` reports the
  count of top-level files with size > 0.
- New `scripts/plan_2_8_weekly_summary_tab_char_count.py` counts
  ASCII tab characters in the summary.
- Weekly workflow wires the three new steps after the
  whitespace-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 green streak + smallest file + whitespace

- New `scripts/plan_2_8_ledger_green_streak_max.py` reports the
  longest consecutive green run.
- New `scripts/plan_2_8_digest_smallest_file_size.py` reports the
  byte size of the smallest top-level file.
- New `scripts/plan_2_8_weekly_summary_whitespace_char_count.py`
  counts ASCII whitespace characters in the summary.
- Weekly workflow wires the three new steps after the
  lowercase-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 red streak + largest file + lowercase

- New `scripts/plan_2_8_ledger_red_streak_max.py` reports the
  longest consecutive red run.
- New `scripts/plan_2_8_digest_largest_file_size.py` reports the
  byte size of the largest top-level file.
- New `scripts/plan_2_8_weekly_summary_lowercase_letter_count.py`
  counts ASCII lowercase letters in the summary.
- Weekly workflow wires the three new steps after the
  uppercase-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 amber streak + size variance + uppercase

- New `scripts/plan_2_8_ledger_amber_streak_max.py` reports the
  longest consecutive amber run.
- New `scripts/plan_2_8_digest_file_size_variance.py` reports
  the population variance of top-level file sizes.
- New `scripts/plan_2_8_weekly_summary_uppercase_letter_count.py`
  counts ASCII uppercase letters in the summary.
- Weekly workflow wires the three new steps after the
  vowel-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 record byte mean + total bytes + vowels

- New `scripts/plan_2_8_ledger_record_byte_size_mean.py` reports
  mean UTF-8 byte length of non-blank ledger lines.
- New `scripts/plan_2_8_digest_total_byte_size.py` reports the
  total byte size of top-level regular files.
- New `scripts/plan_2_8_weekly_summary_vowel_count.py` counts
  ASCII vowels in the summary file.
- Weekly workflow wires the three new steps after the
  checkbox-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 obs-per-day + size mean + checkboxes

- New `scripts/plan_2_8_ledger_observations_per_day_mean.py`
  reports mean observations per distinct day.
- New `scripts/plan_2_8_digest_file_size_mean.py` reports
  the arithmetic mean of top-level regular-file sizes.
- New `scripts/plan_2_8_weekly_summary_checkbox_count.py`
  counts GFM task-list checkbox lines.
- Weekly workflow wires the three new steps after the
  backtick-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-13) — Plan 2.8 unique days + total lines + backticks

- New `scripts/plan_2_8_ledger_unique_days.py` reports the
  count of distinct YYYY-MM-DD prefixes.
- New `scripts/plan_2_8_digest_total_line_count.py` sums
  lines across top-level text files.
- New `scripts/plan_2_8_weekly_summary_backtick_count.py`
  counts backtick characters in the summary.
- Weekly workflow wires the three new steps after the
  heading-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-12) — Plan 2.8 ledger blanks + writable frac + headings

- New `scripts/plan_2_8_ledger_blank_line_count.py` counts
  whitespace-only lines in the ledger.
- New `scripts/plan_2_8_digest_writable_fraction.py` reports
  writable file share among top-level regular files.
- New `scripts/plan_2_8_weekly_summary_heading_count.py`
  counts ATX headings in the summary file.
- Weekly workflow wires the three new steps after the
  avg-word-length upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-11) — Plan 2.8 malformed + readable frac + avg word

- New `scripts/plan_2_8_ledger_malformed_count.py` counts
  non-JSON ledger lines.
- New `scripts/plan_2_8_digest_readable_fraction.py` reports
  readable file fraction among top-level regular files.
- New `scripts/plan_2_8_weekly_summary_avg_word_length.py`
  reports mean whitespace token length.
- Weekly workflow wires the three new steps after the
  longest-word upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-10) — Plan 2.8 last obs + size median + longest word

- New `scripts/plan_2_8_ledger_last_observation.py` reports
  the last ``captured_at`` string across valid records.
- New `scripts/plan_2_8_digest_file_size_median.py` reports
  the median of top-level regular-file sizes.
- New `scripts/plan_2_8_weekly_summary_longest_word.py``
  reports the longest whitespace token.
- Weekly workflow wires the three new steps after the
  trailing-whitespace-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-09) — Plan 2.8 first obs + missing files + trailing ws

- New `scripts/plan_2_8_ledger_first_observation.py` reports
  the ``captured_at`` of the first valid ledger record.
- New `scripts/plan_2_8_digest_missing_files.py` flags which
  canonical digest files are missing from the output dir.
- New `scripts/plan_2_8_weekly_summary_trailing_whitespace_count.py`
  counts lines ending with space or tab.
- Weekly workflow wires the three new steps after the
  unique-word-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-08) — Plan 2.8 status entropy + size range + unique words

- New `scripts/plan_2_8_ledger_status_entropy.py` reports the
  Shannon entropy (base 2) of the status distribution.
- New `scripts/plan_2_8_digest_file_size_range.py` reports
  ``max - min`` of top-level regular-file sizes.
- New `scripts/plan_2_8_weekly_summary_unique_word_count.py``
  reports the count of distinct case-folded tokens.
- Weekly workflow wires the three new steps after the
  line-length-stddev upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-07) — Plan 2.8 green ratio + size stddev + line stddev

- New `scripts/plan_2_8_ledger_green_ratio.py` reports the
  share of valid observations recorded as ``green``.
- New `scripts/plan_2_8_digest_file_size_stddev.py` reports
  the population stddev of top-level regular-file sizes.
- New `scripts/plan_2_8_weekly_summary_line_length_stddev.py``
  reports the population stddev of line lengths.
- Weekly workflow wires the three new steps after the
  max-line-length upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-06) — Plan 2.8 coverage + min size + max line

- New `scripts/plan_2_8_ledger_status_coverage.py` reports
  fraction of canonical statuses observed.
- New `scripts/plan_2_8_digest_min_file_size.py` reports
  smallest top-level regular-file size.
- New `scripts/plan_2_8_weekly_summary_max_line_length.py`
  reports the longest line in the summary.
- Weekly workflow wires the three new steps after the
  median-line-length upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-05) — Plan 2.8 set size + max size + median line

- New `scripts/plan_2_8_ledger_status_set_size.py` reports
  the count of distinct canonical statuses observed.
- New `scripts/plan_2_8_digest_max_file_size.py` reports
  the largest top-level regular-file size.
- New `scripts/plan_2_8_weekly_summary_median_line_length.py`
  reports median line length across the summary.
- Weekly workflow wires the three new steps after the
  mean-line-length upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-04) — Plan 2.8 most common + executable + mean line

- New `scripts/plan_2_8_ledger_most_common_status.py` reports
  the most common canonical status.
- New `scripts/plan_2_8_digest_executable_file_count.py`
  counts executable top-level regular files.
- New `scripts/plan_2_8_weekly_summary_mean_line_length.py`
  reports mean line length across all lines.
- Weekly workflow wires the three new steps after the
  first-line-length upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-03) — Plan 2.8 rarest + writable + first-line

- New `scripts/plan_2_8_ledger_rarest_status.py` reports
  the rarest canonical status.
- New `scripts/plan_2_8_digest_writable_file_count.py`
  counts writable top-level regular files.
- New `scripts/plan_2_8_weekly_summary_first_line_length.py`
  reports length of first non-blank line.
- Weekly workflow wires the three new steps after the
  last-line-length upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-02) — Plan 2.8 per-status observations + readable + last-line

- New `scripts/plan_2_8_ledger_observations_by_status.py`
  reports observation counts split by canonical status.
- New `scripts/plan_2_8_digest_readable_file_count.py`
  counts readable top-level regular files.
- New `scripts/plan_2_8_weekly_summary_last_line_length.py`
  reports length of last non-blank line.
- Weekly workflow wires the three new steps after the
  starts-with-heading upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-01) — Plan 2.8 observations + binary + heading

- New `scripts/plan_2_8_ledger_observation_count.py` reports
  total valid status observations.
- New `scripts/plan_2_8_digest_binary_file_count.py` counts
  top-level files containing NUL bytes.
- New `scripts/plan_2_8_weekly_summary_starts_with_heading.py`
  probes whether the summary starts with an H1 line.
- Weekly workflow wires the three new steps after the
  trailing-newline upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-30) — Plan 2.8 variance + regular files + trailing NL

- New `scripts/plan_2_8_ledger_run_length_variance.py`
  reports population variance of run lengths.
- New `scripts/plan_2_8_digest_regular_file_count.py`
  counts top-level regular-file entries.
- New `scripts/plan_2_8_weekly_summary_trailing_newline.py`
  probes whether the summary ends with a newline.
- Weekly workflow wires the three new steps after the
  crlf-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-29) — Plan 2.8 iqr + directories + crlf

- New `scripts/plan_2_8_ledger_run_length_iqr.py` reports
  interquartile range of status run lengths.
- New `scripts/plan_2_8_digest_directory_count.py` counts
  top-level directory entries.
- New `scripts/plan_2_8_weekly_summary_crlf_count.py` counts
  CRLF sequences in the weekly summary body.
- Weekly workflow wires the three new steps after the
  cr-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 total per status + symlinks + CR

- New `scripts/plan_2_8_ledger_total_run_length_per_status.py`
  reports total observations per canonical status.
- New `scripts/plan_2_8_digest_symlink_count.py`
  counts top-level symlink entries.
- New `scripts/plan_2_8_weekly_summary_cr_count.py`
  counts CR (``\r``) characters in the weekly summary.
- Weekly workflow wires the three new steps after the
  newline-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 median per status + unique ext + newlines

- New `scripts/plan_2_8_ledger_median_run_length_per_status.py`
  reports median run length per canonical status.
- New `scripts/plan_2_8_digest_unique_extension_count.py`
  reports count of distinct top-level extensions.
- New `scripts/plan_2_8_weekly_summary_newline_count.py`
  counts LF characters in the weekly summary body.
- Weekly workflow wires the three new steps after the
  tab-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 min per status + alpha + tabs

- New `scripts/plan_2_8_ledger_min_run_length_per_status.py`
  reports the shortest run length per canonical status.
- New `scripts/plan_2_8_digest_alpha_basename_count.py`
  counts top-level files whose stem is letters only.
- New `scripts/plan_2_8_weekly_summary_tab_count.py`
  counts tab (U+0009) characters in the weekly summary.
- Weekly workflow wires the three new steps after the
  space-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 max per status + numeric + spaces

- New `scripts/plan_2_8_ledger_max_run_length_per_status.py`
  reports the longest run length per canonical status.
- New `scripts/plan_2_8_digest_numeric_basename_count.py`
  counts top-level files whose stem is digits only.
- New `scripts/plan_2_8_weekly_summary_space_count.py`
  counts ASCII U+0020 space characters.
- Weekly workflow wires the three new steps after the
  punctuation-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 mean per status + hidden + punctuation

- New `scripts/plan_2_8_ledger_mean_run_length_per_status.py`
  reports mean run length broken down by canonical status.
- New `scripts/plan_2_8_digest_hidden_file_count.py`
  counts top-level files whose basename starts with '.'.
- New `scripts/plan_2_8_weekly_summary_punctuation_count.py`
  counts ASCII punctuation characters in the weekly summary.
- Weekly workflow wires the three new steps after the
  letter-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 run-length range + lowercase + letters

- New `scripts/plan_2_8_ledger_run_length_range.py`
  reports the max-minus-min of status run lengths.
- New `scripts/plan_2_8_digest_lowercase_filename_count.py`
  counts top-level files with no uppercase ASCII letters.
- New `scripts/plan_2_8_weekly_summary_letter_count.py`
  counts ASCII letter characters in the weekly summary.
- Weekly workflow wires the three new steps after the
  digit-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 shortest run + uppercase + digits

- New `scripts/plan_2_8_ledger_shortest_run.py`
  reports the minimum status run length.
- New `scripts/plan_2_8_digest_uppercase_filename_count.py`
  counts top-level files with uppercase ASCII letters.
- New `scripts/plan_2_8_weekly_summary_digit_count.py`
  counts ASCII digit characters in the weekly summary.
- Weekly workflow wires the three new steps after the
  whitespace-ratio upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 stddev run + ext counts + whitespace

- New `scripts/plan_2_8_ledger_stddev_run_length.py`
  reports the population stddev of status run lengths.
- New `scripts/plan_2_8_digest_file_count_by_ext.py`
  reports file counts per top-level extension.
- New `scripts/plan_2_8_weekly_summary_whitespace_ratio.py`
  reports whitespace share of the weekly summary body.
- Weekly workflow wires the three new steps after the
  non-blank-line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 median run + empty file + non-blank

- New `scripts/plan_2_8_ledger_median_run_length.py`
  reports the median length of consecutive status runs.
- New `scripts/plan_2_8_digest_empty_file_count.py`
  reports the number of zero-byte artifact files.
- New `scripts/plan_2_8_weekly_summary_non_blank_line_count.py`
  counts lines containing any non-whitespace character.
- Weekly workflow wires the three new steps after the
  blank-line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 avg run length + non-empty + blank-line

- New `scripts/plan_2_8_ledger_avg_run_length.py` reports
  the mean length of consecutive status runs.
- New `scripts/plan_2_8_digest_non_empty_file_count.py`
  reports the number of top-level artifact files with
  size greater than zero.
- New `scripts/plan_2_8_weekly_summary_blank_line_count.py`
  counts whitespace-only lines in the weekly summary.
- Weekly workflow wires the three new steps after the
  diff-fence upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 run min + total size + diff-fence

- New `scripts/plan_2_8_ledger_status_run_min.py` reports
  the shortest consecutive status run.
- New `scripts/plan_2_8_digest_total_size.py` reports the
  total byte size across top-level artifact files.
- New `scripts/plan_2_8_weekly_summary_diff_fence_count.py`
  counts fenced code blocks whose info-string is
  ``diff``/``patch``.
- Weekly workflow wires the three new steps after the
  json-fence upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 run max + avg size + json-fence

- New `scripts/plan_2_8_ledger_status_run_max.py`
  reports the longest consecutive status run.
- New `scripts/plan_2_8_digest_avg_size.py` reports
  mean bytes per file across the artifact directory.
- New `scripts/plan_2_8_weekly_summary_json_fence_count.py`
  counts fenced code blocks whose info-string is
  ``json``/``json5``/``jsonc``.
- Weekly workflow wires the three new steps after the
  yaml-fence upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 run summary + shortest filename + yaml-fence

- New `scripts/plan_2_8_ledger_status_run_summary.py`
  enumerates every consecutive status run with start,
  end, and length.
- New `scripts/plan_2_8_digest_shortest_filename.py`
  reports the top-level file with the shortest basename.
- New `scripts/plan_2_8_weekly_summary_yaml_fence_count.py`
  counts fenced code blocks whose info-string is
  ``yaml``/``yml``.
- Weekly workflow wires the three new steps after the
  python-fence upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 run count + longest filename + python-fence

- New `scripts/plan_2_8_ledger_status_run_count.py`
  reports the total number of distinct consecutive
  status runs.
- New `scripts/plan_2_8_digest_longest_filename.py`
  reports the top-level file with the longest basename.
- New `scripts/plan_2_8_weekly_summary_python_fence_count.py`
  counts fenced code blocks whose info-string is
  ``python``/``py``/``python3``.
- Weekly workflow wires the three new steps after the
  shell-fence upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 status first/last + basename length + shell-fence

- New `scripts/plan_2_8_ledger_status_first_last.py`
  reports the first and last timestamp per observed
  ledger status.
- New `scripts/plan_2_8_digest_basename_length_stats.py`
  reports min/max/mean of file-basename lengths across
  the top-level artifact directory.
- New `scripts/plan_2_8_weekly_summary_shell_fence_count.py`
  counts fenced code blocks whose info-string is
  ``sh``/``bash``/``zsh``/``shell``.
- Weekly workflow wires the three new steps after the
  emoji-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 last unknown + line counts + emoji count

- New `scripts/plan_2_8_ledger_last_unknown.py` reports
  the timestamp of the most recent unknown ledger record.
- New `scripts/plan_2_8_digest_line_counts.py` reports
  per-file newline-based line counts plus a grand total.
- New `scripts/plan_2_8_weekly_summary_emoji_count.py`
  counts ``:emoji:`` shortcodes while excluding fenced
  blocks and inline code.
- Weekly workflow wires the three new steps after the
  autolink-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 last amber + word count + autolink count

- New `scripts/plan_2_8_ledger_last_amber.py` reports the
  timestamp of the most recent amber ledger record.
- New `scripts/plan_2_8_digest_word_count.py` reports the
  total word count across all artifact files plus a
  per-file breakdown sorted by name.
- New `scripts/plan_2_8_weekly_summary_autolink_count.py`
  counts ``<https:…>``/``<http:…>``/``<mailto:…>`` auto
  links while excluding fenced blocks and inline code.
- Weekly workflow wires the three new steps after the
  HTML-tag-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-27) — Plan 2.8 last red + per-ext bytes + HTML tag count

- New `scripts/plan_2_8_ledger_last_red.py` reports the
  timestamp of the most recent red ledger record.
- New `scripts/plan_2_8_digest_per_ext_bytes.py` reports
  total bytes per file extension (``(none)`` bucket for
  suffix-less files), sorted by bytes descending.
- New `scripts/plan_2_8_weekly_summary_html_tag_count.py`
  counts raw HTML tag occurrences while excluding fenced
  blocks, inline code, and HTML comments.
- Weekly workflow wires the three new steps after the
  reference-defs upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-26) — Plan 2.8 first unknown + mtime span + reference defs

- New `scripts/plan_2_8_ledger_first_unknown.py` reports the
  timestamp of the earliest unknown ledger record.
- New `scripts/plan_2_8_digest_mtime_span.py` reports the
  oldest→newest mtime span in hours across artifact files.
- New `scripts/plan_2_8_weekly_summary_reference_defs.py`
  counts Markdown link reference definitions (``[label]:
  url``), returning a sorted label list; fenced blocks are
  excluded.
- Weekly workflow wires the three new steps after the
  strikethrough-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-25) — Plan 2.8 first amber + median mtime + strikethrough count

- New `scripts/plan_2_8_ledger_first_amber.py` reports the
  timestamp of the earliest amber ledger record.
- New `scripts/plan_2_8_digest_median_mtime.py` reports the
  median mtime across top-level artifact files (lower
  middle for even counts).
- New `scripts/plan_2_8_weekly_summary_strikethrough_count.py`
  counts ``~~text~~`` spans while excluding fenced blocks
  and inline code.
- Weekly workflow wires the three new steps after the
  bold-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-24) — Plan 2.8 first red + newest file + bold count

- New `scripts/plan_2_8_ledger_first_red.py` reports the
  timestamp of the earliest red ledger record.
- New `scripts/plan_2_8_digest_newest_file.py` reports the
  single newest artifact-directory file by mtime.
- New `scripts/plan_2_8_weekly_summary_bold_count.py` counts
  ``**bold**`` and ``__bold__`` strong-emphasis spans while
  excluding fenced blocks and inline code.
- Weekly workflow wires the three new steps after the
  footnote-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-23) — Plan 2.8 green streak history + oldest file + footnote count

- New `scripts/plan_2_8_ledger_green_streak_history.py` lists
  all past green-streak segments in chronological order with
  length and duration-in-hours per segment.
- New `scripts/plan_2_8_digest_oldest_file.py` reports the
  single oldest artifact-directory file by mtime (subdirs
  ignored).
- New `scripts/plan_2_8_weekly_summary_footnote_count.py`
  counts Markdown footnote references and definitions while
  excluding fenced code blocks.
- Weekly workflow wires the three new steps after the
  longest-line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-22) — Plan 2.8 longest gap + duplicate sizes + longest line

- New `scripts/plan_2_8_ledger_longest_gap.py` reports the
  longest gap in hours between consecutive captures plus the
  boundary timestamps; ``--fail-above-hours`` for CI.
- New `scripts/plan_2_8_digest_duplicate_sizes.py` groups
  artifact files by identical byte size to surface suspect
  duplicates; ``--fail-on-duplicates`` for CI.
- New `scripts/plan_2_8_weekly_summary_longest_line.py`
  reports the longest line length and its 1-based line
  number; ``--fail-above-length`` for CI.
- Weekly workflow wires the three new steps after the
  sha256 upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-21) — Plan 2.8 captures per day + tiny files + summary sha256

- New `scripts/plan_2_8_ledger_captures_per_day.py` groups
  ledger records by UTC date and reports per-day capture
  counts; malformed timestamps and invalid statuses are
  skipped; days sorted ascending.
- New `scripts/plan_2_8_digest_tiny_files.py` lists artifact
  files below a configurable byte threshold (default 100B);
  boundary is exclusive; subdirs ignored;
  ``--fail-on-tiny`` for CI.
- New `scripts/plan_2_8_weekly_summary_sha256.py` computes a
  stable SHA256 fingerprint of the full weekly summary along
  with size and line counts.
- Weekly workflow wires the three new steps after the
  ordered-list-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 oldest captured_at + top ext + ordered list count

- New `scripts/plan_2_8_ledger_oldest_captured_at.py` reports
  the earliest ``captured_at`` in the ledger and its age in
  hours relative to ``--now`` (``--fail-below-hours``).
- New `scripts/plan_2_8_digest_ext_top.py` reports the most
  common file extension in the artifact dir (ties broken
  alphabetically, no-ext grouped); ``--fail-below-count``.
- New `scripts/plan_2_8_weekly_summary_ordered_list_count.py`
  counts ordered list items (``1.`` or ``1)``) in the weekly
  summary (fenced code excluded).
- Weekly workflow wires the three new steps after the list
  count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-21) — Plan 2.8 latest captured_at + smallest file + list count

- New `scripts/plan_2_8_ledger_latest_captured_at.py` reports
  the most recent ``captured_at`` timestamp (status-agnostic)
  and its age in hours relative to ``--now``
  (``--fail-above-hours`` for CI).
- New `scripts/plan_2_8_digest_smallest_file.py` reports the
  smallest non-empty file in the artifact dir (ties broken
  by name); ``--fail-below-bytes`` for CI.
- New `scripts/plan_2_8_weekly_summary_list_count.py` counts
  unordered list items (``-`` or ``*``) in the weekly
  summary (horizontal rules and fenced code excluded).
- Weekly workflow wires the three new steps after the link
  count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-21) — Plan 2.8 first green age + largest file + link count

- New `scripts/plan_2_8_ledger_first_green_age.py` reports
  hours since the first green ledger capture relative to
  ``--now`` (``--fail-below-hours`` for CI).
- New `scripts/plan_2_8_digest_largest_file.py` reports the
  largest artifact file by byte size (ties broken by name).
- New `scripts/plan_2_8_weekly_summary_link_count.py` counts
  Markdown inline links ``[text](url)`` and their distinct
  targets (images and fenced code excluded).
- Weekly workflow wires the three new steps after the table
  count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-21) — Plan 2.8 unique statuses + size sum + table count

- New `scripts/plan_2_8_ledger_unique_statuses.py` lists the
  distinct valid statuses seen in the ledger with per-status
  counts (``--fail-below-count`` for CI).
- New `scripts/plan_2_8_digest_size_sum.py` reports the total
  byte size of artifact-dir files (``--fail-above-bytes``).
- New `scripts/plan_2_8_weekly_summary_table_count.py` counts
  Markdown pipe-tables in the weekly summary (fenced code
  excluded).
- Weekly workflow wires the three new steps after the
  inline-code upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-21) — Plan 2.8 median gap + empty ratio + inline-code count

- New `scripts/plan_2_8_ledger_median_gap.py` reports the
  median gap in hours between consecutive ledger captures
  (``--fail-above-hours`` for CI).
- New `scripts/plan_2_8_digest_empty_ratio.py` reports the
  share of zero-byte files in the artifact directory
  (``--fail-above-ratio`` for CI).
- New `scripts/plan_2_8_weekly_summary_inline_code_count.py`
  counts single-backtick inline-code spans in the weekly
  summary (fenced code excluded).
- Weekly workflow wires the three new steps after the
  horizontal-rule upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-21) — Plan 2.8 unknown ratio + empty files + hr count

- New `scripts/plan_2_8_ledger_unknown_ratio.py` mirrors the
  red/amber/green ratio helpers for ``unknown`` records;
  ``--fail-above-ratio`` for CI.
- New `scripts/plan_2_8_digest_empty_files.py` lists
  zero-byte files (sorted by name) with ``--fail-on-empty``
  for CI.
- New `scripts/plan_2_8_weekly_summary_hr_count.py` counts
  Markdown horizontal-rule lines (``---``/``___``/``***``
  with three or more identical characters) outside fenced
  code blocks.
- Weekly workflow wires the three new steps after blockquote
  count.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 red ratio + file age stats + blockquote count

- New `scripts/plan_2_8_ledger_red_ratio.py` mirrors the
  amber-ratio helper for red records; includes
  ``--fail-above-ratio`` for CI.
- New `scripts/plan_2_8_digest_file_age_stats.py` reports
  min/mean/max file age (seconds since mtime) for the
  artifact dir; negative ages are clamped to zero; subdirs
  ignored; ``now_ts`` injection keeps tests deterministic.
- New `scripts/plan_2_8_weekly_summary_blockquote_count.py`
  counts blockquote lines and distinct blockquote blocks
  outside fenced code blocks.
- Weekly workflow wires the three new steps after heading
  hierarchy.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 amber ratio + name length stats + heading hierarchy

- New `scripts/plan_2_8_ledger_amber_ratio.py` mirrors the
  green-ratio helper for amber records; includes
  ``--fail-above-ratio`` for CI alerts.
- New `scripts/plan_2_8_digest_name_length_stats.py` reports
  min/mean/max filename lengths; subdirs ignored; empty dirs
  return zeros.
- New `scripts/plan_2_8_weekly_summary_heading_hierarchy.py`
  counts ATX headings per level (H1-H6) outside fenced code
  blocks and reports the deepest level seen.
- Weekly workflow wires the three new steps after paragraph
  stats.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 distinct days + extension coverage + paragraph stats

- New `scripts/plan_2_8_ledger_distinct_days.py` counts
  distinct UTC days present in the ledger; malformed
  timestamps and invalid statuses are skipped; days list is
  sorted.
- New `scripts/plan_2_8_digest_extension_coverage.py` reports
  how many artifact files carry a suffix and the coverage
  ratio; subdirectories ignored.
- New `scripts/plan_2_8_weekly_summary_paragraph_stats.py`
  counts paragraph runs (contiguous non-blank lines separated
  by blank lines) and reports the mean lines/paragraph;
  fenced-code markers are excluded to avoid inflating
  paragraph counts.
- Weekly workflow wires the three new steps after image
  count.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 status streaks + oldest/newest + image count

- New `scripts/plan_2_8_ledger_status_streaks.py` reports the
  current tail-end status streak (status, length, start_at,
  end_at); ``{"found": false}`` when no valid records.
- New `scripts/plan_2_8_digest_oldest_newest.py` reports the
  oldest and newest files in the artifact dir by mtime; ties
  broken on name ascending; subdirs ignored.
- New `scripts/plan_2_8_weekly_summary_image_count.py` counts
  ``![alt](src)`` image tags outside fenced code blocks and
  reports both total and distinct src counts.
- Weekly workflow wires the three new steps after emphasis
  count.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 recent green ratio + median size + emphasis count

- New `scripts/plan_2_8_ledger_recent_green_ratio.py` reports
  the green-share ratio over the trailing N ledger records
  (``None`` when the window is empty); ``--fail-below-ratio``
  for CI.
- New `scripts/plan_2_8_digest_median_size.py` reports the
  median file size across the artifact dir; subdirs ignored.
- New `scripts/plan_2_8_weekly_summary_emphasis_count.py`
  counts bold (``**...**``) and italic (``*...*`` or
  ``_..._``) spans outside fenced code blocks; bold markers
  stripped before italic scan to avoid double-counting.
- Weekly workflow wires the three new steps after tables
  count.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 last-N summary + mean size + tables count

- New `scripts/plan_2_8_ledger_last_n_summary.py` reports
  status counts within the trailing N ledger records;
  `--last-n 0` means all records.
- New `scripts/plan_2_8_digest_mean_size.py` reports the
  arithmetic mean (rounded 2dp) of artifact-dir file sizes
  alongside file_count and total_bytes; subdirectories
  ignored.
- New `scripts/plan_2_8_weekly_summary_tables_count.py`
  counts pipe-table blocks in the weekly summary (contiguous
  runs of two or more `|`-prefixed lines); content inside
  fenced code blocks excluded; single `|` lines are not
  counted as tables.
- Weekly workflow wires last-N, mean-size, and tables-count
  steps after list-stats.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 longest run + size histogram + list stats

- New `scripts/plan_2_8_ledger_longest_run.py` reports the
  longest consecutive run of each status in the ledger with
  start/end timestamps; statuses that never appear return
  length 0.
- New `scripts/plan_2_8_digest_size_histogram.py` buckets
  artifact files into five fixed size ranges (<1KB, 1-10KB,
  10-100KB, 100KB-1MB, >=1MB); boundary at 1024 bytes moves
  to the 1-10KB bucket.
- New `scripts/plan_2_8_weekly_summary_list_stats.py` counts
  bullet (`-`/`*`) vs numbered (`N.`) list items in the
  summary, skipping content inside fenced code blocks.
- Weekly workflow wires longest-run, size-histogram, and
  list-stats steps after link-check.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 run length + smallest files + link check

- New `scripts/plan_2_8_ledger_status_run_length.py`
  run-length-encodes the ledger status series into segments
  of `{status, length, start_at, end_at}`.
- New `scripts/plan_2_8_digest_smallest_files.py` mirrors
  largest_files but lists the bottom-N by size; subdirectories
  ignored.
- New `scripts/plan_2_8_weekly_summary_link_check.py` parses
  `[text](target)` links and flags fragment-only links without
  a matching heading anchor (GitHub-style slug); duplicate
  missing fragments deduplicated;
  `--fail-on-missing-fragments` gates CI.
- Weekly workflow wires run-length, smallest-files, and
  link-check steps after code-blocks.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 first flip + largest files + code blocks

- New `scripts/plan_2_8_ledger_first_flip.py` mirrors
  latest_flip but reports the earliest status transition in
  the ledger; returns `{"found": false}` when none exists.
- New `scripts/plan_2_8_digest_largest_files.py` lists the
  top-N largest files in the artifact directory (descending;
  ties broken by name); `--top-n 0` returns all;
  subdirectories ignored.
- New `scripts/plan_2_8_weekly_summary_code_blocks.py` counts
  fenced code blocks in the weekly summary; reports
  `unbalanced: true` when the final fence is unterminated;
  `--fail-on-unbalanced` gates CI.
- Weekly workflow wires first-flip, largest-files, and
  code-blocks steps after word-count.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 latest flip + filetype breakdown + word count

- New `scripts/plan_2_8_ledger_latest_flip.py` reports the
  most-recent status transition (from/to + captured_at) in the
  ledger; returns `{"found": false}` when no flip exists.
- New `scripts/plan_2_8_digest_filetype_breakdown.py` groups
  artifact files by lowercase extension (`""` bucket for files
  without an extension) and reports count + total bytes per
  group; subdirectories ignored.
- New `scripts/plan_2_8_weekly_summary_word_count.py` counts
  words, chars, non-whitespace chars, and lines in the weekly
  summary file; `--fail-below-words N` gates CI.
- Weekly workflow wires latest-flip, filetype-breakdown, and
  word-count steps after summary-preview.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 transition matrix + hash inventory + summary preview

- New `scripts/plan_2_8_ledger_transition_matrix.py` builds a
  4x4 NxN status-transition matrix (green/amber/red/unknown)
  from consecutive ledger records; only counts distinct
  from->to pairs and reports `total_transitions`.
- New `scripts/plan_2_8_digest_hash_inventory.py` computes a
  SHA256 for every regular file in the artifact directory
  (subdirectories ignored) for drift detection; deterministic
  across calls.
- New `scripts/plan_2_8_weekly_summary_preview.py` emits the
  first N lines of `weekly_summary.md` as a fenced block with
  `_empty_` placeholder when the summary is empty; negative
  `--max-lines` is clamped to zero.
- Weekly workflow wires transition-matrix, hash-inventory, and
  summary-preview steps after gap-detector.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 weekday histogram + summary index + gap detector

- New `scripts/plan_2_8_ledger_weekday_histogram.py` buckets
  records per UTC weekday (Mon=0..Sun=6) with name-friendly md
  rendering; reports empty_weekdays list; `--fail-on-empty-weekdays N`
  gates CI.
- New `scripts/plan_2_8_digest_summary_index.py` walks an
  artifact directory and builds a `.md` manifest with per-file
  size and first `# ` heading (falls back to filename); non-md
  files and subdirectories are ignored.
- New `scripts/plan_2_8_ledger_gap_detector.py` reports gaps
  between consecutive `captured_at` timestamps exceeding
  `--threshold-hours` (default 24); `--fail-on-gaps` gates CI;
  boundary (exactly threshold) is not flagged.
- Weekly workflow wires weekday-histogram, summary-index, and
  gap-detector steps after required-sections.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 hour histogram + stale report + required sections

- New `scripts/plan_2_8_ledger_hour_histogram.py` buckets
  records by UTC hour-of-day (0..23); reports empty_hours list;
  `--fail-on-empty-hours N` gates CI.
- New `scripts/plan_2_8_digest_stale_report.py` classifies
  artifacts as fresh / warn / stale with configurable
  `--warn-days` and `--stale-days` thresholds; subdirectories
  are ignored; `--fail-on-stale` gates CI.
- New `scripts/plan_2_8_weekly_summary_required_sections.py`
  asserts `DEFAULT_REQUIRED` level-2 headings are present in
  `weekly_summary.md`; `--fail-on-missing` gates CI.
- Weekly workflow wires hour-histogram, stale-report
  (warn=7/stale=14), and required-sections steps after TOC
  checksum; each uploads its output as a retained artifact.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 status share + missing + TOC checksum

- New `scripts/plan_2_8_ledger_status_share.py` computes
  share-of-time per valid status across the full ledger;
  percentages rounded to 2dp; `--fail-below-green` gates CI.
- New `scripts/plan_2_8_digest_missing_artifacts.py` compares
  filenames in the digest dir against a pinned `REQUIRED` tuple
  (31 entries) and reports missing + extra files;
  subdirectories are not counted; `--fail-on-missing` gates CI.
- New `scripts/plan_2_8_weekly_summary_toc_checksum.py`
  extracts the `## Contents` block from `weekly_summary.md`,
  normalises line endings, strips leading/trailing blanks, and
  emits a stable SHA256 so silent TOC drift is detectable.
- Weekly workflow wires status-share, missing-artifacts, and
  TOC-checksum steps after heading-order.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 best day + size trend + heading order

- New `scripts/plan_2_8_ledger_best_day.py` mirrors worst-day
  and flags the UTC date with the most green records; ties
  break by earliest date.
- New `scripts/plan_2_8_digest_size_trend.py` compares total
  bytes in two artifact directories (prior vs current) and
  reports delta_bytes and delta_pct (`None` when prior=0);
  `--fail-on-drop-pct` gates CI on sudden shrinkage;
  subdirectories are not counted.
- New `scripts/plan_2_8_weekly_summary_heading_order.py`
  validates that `##` headings in `weekly_summary.md` appear in
  `DEFAULT_ORDER` and reports missing, extra, and misorder;
  `--fail-on-misorder` gates CI.
- Weekly workflow wires best-day, size-trend (reuses the
  prior-catalog download dir), and heading-order steps after
  section-stats.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 worst day + catalog diff + section stats

- New `scripts/plan_2_8_ledger_worst_day.py` groups ledger
  records by UTC date and flags the date with the most
  non-green (amber+red) records; ties break by earliest date.
- New `scripts/plan_2_8_digest_catalog_diff.py` compares two
  artifact-catalog JSON outputs and reports added_known,
  added_unknown, dropped, known→unknown, and unknown→known;
  `--fail-on-unknown-growth` gates CI.
- New `scripts/plan_2_8_weekly_summary_section_stats.py`
  reports per-`##`-section line and word counts of
  `weekly_summary.md` with an empty-section list; H1 headings
  and pre-first-section content are ignored.
- Weekly workflow wires worst-day, catalog-diff (with prior
  catalog downloaded via download-artifact; falls back to the
  current catalog when no prior exists), and section-stats
  steps; each uploads its output as a retained artifact.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 streak now + artifact age + month summary

- New `scripts/plan_2_8_ledger_streak_now.py` computes the
  trailing (current) streak of the latest status and its
  `started_at` timestamp; emits markdown or JSON.
- New `scripts/plan_2_8_digest_artifact_age.py` scans the
  digest artifact directory and reports per-file size, mtime,
  and age-in-days relative to now; subdirectories are ignored;
  `--fail-on-older-than DAYS` gates CI on staleness.
- New `scripts/plan_2_8_ledger_month_summary.py` groups ledger
  records by calendar month (`YYYY-MM`) and reports per-status
  counts plus a total; invalid statuses/timestamps are tallied
  under `skipped`.
- Weekly workflow wires streak-now, artifact-age, and
  month-summary steps after the TOC step; each uploads its
  output as a retained artifact.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 status today + recent changes + TOC-only

- New `scripts/plan_2_8_ledger_status_today.py` returns the
  ledger record captured on a target UTC date (defaults to
  today); when multiple records match the day, the latest is
  returned. Invalid ISO dates and missing ledgers fail cleanly.
- New `scripts/plan_2_8_digest_recent_changes.py` walks the
  ledger and returns only *transitions* (status-change records);
  synthesises no initial entry. `--limit N` keeps the tail.
- New `scripts/plan_2_8_weekly_summary_toc_only.py` extracts
  just the `## Contents` block from `weekly_summary.md` and
  emits it as a standalone artifact; weekly wires this into
  `$GITHUB_STEP_SUMMARY` so the run page shows the TOC inline.
- Weekly digest wires all three steps; each uploads a 365-day
  retention artifact.

### Added (2026-04-21) — Plan 2.8 flap rate + trend threshold + artifact catalog

- New `scripts/plan_2_8_ledger_flap_rate.py` counts status
  transitions grouped by ISO week of the later record and
  reports total flips, weeks covered, and the average
  flips-per-week. `--fail-on-flips` turns any observed flip
  into rc=1.
- New `scripts/plan_2_8_trend_threshold_alert.py` reads
  `trend.json` and raises rc=1 (when `--fail-below` is set) if
  the most recent week's green % is strictly below the
  threshold; empty weeks list also fails.
- New `scripts/plan_2_8_digest_artifact_catalog.py` walks the
  digest artifact directory and emits a catalog classifying
  each file as `known` (with a short description) or `unknown`
  so stray outputs surface immediately. Subdirectories are
  ignored.
- Weekly digest wires flap rate, trend-threshold alert, and
  artifact catalog; also emits `trend.json` alongside `trend.md`
  so the threshold alert has a JSON input.

### Added (2026-04-21) — Plan 2.8 metadata diff + weekly trend + link check

- New `scripts/plan_2_8_metadata_diff.py` compares current
  `metadata.json` against a prior copy (downloaded via
  `dawidd6/action-download-artifact@v6`) and reports python
  version change, script-count delta, and per-script size
  deltas (added / removed / changed). Malformed or missing
  prior is treated as an empty baseline.
- New `scripts/plan_2_8_ledger_trend.py` buckets ledger records
  by ISO week and reports per-week totals, green counts, and
  green % (2dp) as JSON or a small markdown table.
- New `scripts/plan_2_8_weekly_summary_linkcheck.py` scans
  `weekly_summary.md` for internal anchor links and flags any
  that point at missing headings; `--fail-on-broken` turns
  broken links into rc=1.
- Weekly digest wires prior-metadata download, metadata diff,
  trend, and link check; artifacts uploaded with 365-day
  retention.

### Added (2026-04-21) — Plan 2.8 latest status + longest streak + digest metadata

- New `scripts/plan_2_8_ledger_latest_status.py` emits a tiny
  artifact with the most recent valid-status record (status +
  captured_at + run_url); empty or all-invalid ledgers yield
  `status = "unknown"`.
- New `scripts/plan_2_8_ledger_longest_streak.py` reports the
  longest consecutive run of each status (green / amber / red /
  unknown) with start/end captured_at and length. Records with
  invalid statuses are dropped before streak computation.
- New `scripts/plan_2_8_digest_metadata.py` captures
  generator-side metadata (python version, platform, UTC
  captured_at, size+mtime of each `plan_2_8_*.py`) so weekly
  outputs are self-describing.
- Weekly digest uploads the new `latest_status.json` and
  `metadata.json` artifacts.

### Added (2026-04-21) — Plan 2.8 ledger uptime % + file manifest + weekly summary index

- New `scripts/plan_2_8_ledger_uptime_pct.py` computes green
  uptime as a percentage over the last N weeks, using the most
  recent record before the cutoff as a window anchor so partial
  spans aren't dropped.
- New `scripts/plan_2_8_digest_file_manifest.py` walks
  `scripts/plan_2_8_*.py` and `tests/test_plan_2_8_*.py` and
  reports orphan scripts and orphan tests (self and
  `plan_2_8_status.py` are excluded from the scan).
- New `scripts/plan_2_8_weekly_summary_index.py` aggregates the
  weekly markdown reports (summary, flip-alert, downtime,
  size-budget, archive-index, index-diff) into a single
  `weekly_summary.md` with a table of contents; missing inputs
  become `_(missing)_` placeholders so the output always has the
  full section skeleton.
- Weekly digest uploads the new `uptime.md` and
  `weekly_summary.md` artifacts.

### Added (2026-04-21) — Plan 2.8 ledger downtime + weekly rollup + index diff

- New `scripts/plan_2_8_ledger_downtime.py` sums non-green
  durations (amber / red / unknown) between consecutive ledger
  entries. Trailing intervals are not counted.
- New `scripts/plan_2_8_ledger_weekly_rollup.py` produces a
  compact per-week rollup (status counts, flips, latest status).
- New `scripts/plan_2_8_digest_index_compare.py` diffs the
  current weekly `index.json` against the prior run's copy
  (downloaded via `dawidd6/action-download-artifact@v6`) and
  reports added / removed / size-changed files.
- Weekly digest wires downtime, prior-index download, and the
  index diff; three new uploads: `plan-2-8-ledger-downtime`,
  `plan-2-8-weekly-index-diff`.
- +42 tests plus two weekly-workflow pin-tests.

### Added (2026-04-21) — Plan 2.8 checksum verifier + status matrix + size budget

- New `scripts/plan_2_8_checksum_verify.py` verifies a
  `checksums.json` manifest against a directory, reporting
  missing/mismatched/extra files with opt-in failure on each.
- New `scripts/plan_2_8_ledger_status_matrix.py` builds a
  `from→to` status transition matrix over the ledger (invalid /
  non-string statuses break the chain so they never fabricate
  transitions).
- New `scripts/plan_2_8_digest_size_budget.py` enforces a per-file
  byte budget (default 1 MiB) on the weekly artifact directory;
  supports `--fail-on-breach` for CI.
- Weekly digest now emits and uploads the size-budget report.
- +41 tests covering verification/matrix/budget; one
  weekly-workflow pin-test.

### Added (2026-04-21) — Plan 2.8 ledger stats + artifact checksums + archive index

- New `scripts/plan_2_8_ledger_stats_json.py` buckets the status
  ledger per ISO year-week (default) or per calendar month and
  reports status counts per bucket, plus a skipped tally for
  malformed records.
- New `scripts/plan_2_8_artifact_checksum.py` computes SHA-256
  for every file in the weekly artifact directory and emits both
  `checksums.json` and `checksums.md`, with `--skip` support so
  the checksum files themselves are excluded from the next run.
- New `scripts/plan_2_8_digest_archive_index.py` indexes the
  digest-archive directory, reporting file count + total size
  per snapshot sub-directory.
- Weekly digest now publishes `plan-2-8-artifact-checksums` and
  `plan-2-8-digest-archive-index` (the latter is fail-soft when
  the archive dir is absent).
- +36 tests covering per-week/per-month bucketing, checksum
  computation, archive scanning; two weekly-workflow pin-tests.

### Added (2026-04-21) — Plan 2.8 status flip alert + ledger CSV export + ledger validator

- New `scripts/plan_2_8_status_flip_alert.py` detects status
  transitions in the last N weeks of the ledger (default 12) and
  emits a markdown alert (or JSON), with optional
  `--fail-on-flip`.
- New `scripts/plan_2_8_ledger_csv_export.py` converts the
  JSONL ledger to CSV (mirrors the `plan_2_8_history_export.py`
  shape), default fields `captured_at,status,run_url`.
- New `scripts/plan_2_8_ledger_validate.py` validates every
  ledger record (`captured_at` ISO-parseable, `status` in the
  allowed set), reports invalid lines with reason, supports
  `--fail-on-invalid`.
- Weekly digest now emits the flip alert and CSV alongside the
  ledger summary; two new uploads: `plan-2-8-status-flip-alert`,
  `plan-2-8-ledger-csv`.
- +42 tests covering flip detection, CSV rendering, and
  validator checks; two weekly-workflow pin-tests.

### Added (2026-04-21) — Plan 2.8 ledger prune + run stamp + weekly artifact index

- New `scripts/plan_2_8_status_ledger_prune.py` trims the status
  ledger to the last N records (default 104, ~2 years of weekly
  runs) via an atomic `tempfile` + `os.replace` rewrite. Blank and
  malformed lines are dropped.
- New `scripts/plan_2_8_run_stamp.py` writes a self-describing
  JSON stamp (`run_id`, `run_url`, `sha`, `ref`, `actor`,
  `captured_at`) with `GITHUB_*` env fallback.
- New `scripts/plan_2_8_weekly_index.py` scans the weekly artifact
  directory and emits `index.md` + `index.json` listing every
  produced artifact with its size.
- Weekly digest now prunes the ledger, emits the run stamp, and
  publishes the artifact index (also appended to the job summary).
  Three new uploads: `plan-2-8-run-stamp`, `plan-2-8-weekly-index`.
- +27 tests covering prune/index/stamp helpers plus three
  weekly-workflow pin-tests.

### Added (2026-04-21) — Plan 2.8 status ledger append + summariser

- New `scripts/plan_2_8_status_ledger.py` appends a single
  JSONL observation (`captured_at`, `status`, optional
  `run_url`) each week, carrying over the prior weekly
  artifact by downloading `plan-2-8-status-ledger` via
  `dawidd6/action-download-artifact@v6` with
  `name_is_regexp: true`. Handles both status-snapshot and
  bare health-rollup payloads. +14 tests with weekly-workflow
  pin-tests for download + append + upload steps.
- New `scripts/plan_2_8_status_ledger_summarize.py` summarises
  the ledger into `{counts, total, pct_green, current_status,
  current_streak, last_flip}`, tolerating blank and malformed
  lines. Supports md/json output. +14 tests including a
  weekly-workflow pin-test.
- Weekly digest chains download→append→upload→summary, attaches
  the summary to the job summary, and uploads both the ledger
  and its summary (365d).
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 alert trend gate + digest-vs-coverage projection + runbook section check

- New `scripts/plan_2_8_alert_trend_gate.py` turns the trend JSON
  into a soft gate with configurable thresholds
  (`--max-rising`, `--max-new`, `--max-falling`). Produces an md
  summary plus JSON, supports `--fail-on-breach`, and defends
  against bool-masquerading-as-int counts. +16 tests with a
  weekly-workflow pin-test (thresholds: rising≤5, new≤10).
- New `scripts/plan_2_8_digest_to_coverage.py` projects the
  weekly digest's alerts onto the coverage slice by
  `(tf, family)` and reports alerts-without-coverage,
  coverage-without-alerts, and their intersection. Accepts
  coverage either as an `{entries:[...]}` object or a bare list.
  `--fail-on-gap` for CI gating. +15 tests, one weekly-workflow
  pin-test.
- New `scripts/plan_2_8_runbook_sections.py` verifies the
  rollout runbook contains all canonical level-2 headings
  (default set pinned to existing "Phase timeline (addendum §6)",
  "Daily automation", "Status quick-check"). Skips fenced
  blocks. `--fail-on-missing` for CI gating. +16 tests
  including a real-runbook sweep and weekly pin-test.
- Weekly digest now runs all three steps after the alert trend
  step, appends each to the job summary, and uploads
  `plan-2-8-alert-trend-gate`, `plan-2-8-digest-vs-coverage`,
  and `plan-2-8-runbook-sections` (365d).
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 README badge markdown + alert trend aggregator

- New `scripts/plan_2_8_badge_markdown.py` emits a README-ready
  single-line markdown image linking to the Plan 2.8 shields.io
  endpoint badge, optionally wrapped in a click-through link.
  URL-encodes the endpoint URL and guards the label against
  stray `]`. +11 tests including a weekly-workflow pin-test.
- New `scripts/plan_2_8_alert_trend.py` ingests the latest two
  files from the Plan 2.8 digest archive and emits a per-
  `(tf, family)` trend record: latest/prev events and
  hit-rate, deltas, and a direction tag (`rising`, `falling`,
  `flat`, `new`, `gone`). Tolerant of malformed or missing
  archives. +17 tests including a weekly-workflow pin-test.
- Weekly digest now uploads `plan-2-8-badge-markdown` and
  `plan-2-8-alert-trend` (both retained 365 days) and appends the
  trend report to the job summary.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 digest schema validator + shields.io status badge

- New `scripts/plan_2_8_digest_schema.py` validates the weekly
  digest JSON against a lightweight, dependency-free schema
  (required top-level keys + per-alert field types; unknown keys
  tolerated). Supports md/json output and `--fail-on-invalid`.
  +18 tests including a bool-as-int rejection guard and a
  weekly-workflow pin-test.
- New `scripts/plan_2_8_runcard_badge.py` emits a shields.io
  endpoint-badge JSON (`schemaVersion: 1`) from either the
  status snapshot or a bare rollout-health JSON. Maps
  green/amber/red to brightgreen/yellow/red; any other value to
  lightgrey. +14 tests with a weekly-workflow pin-test.
- Weekly digest now runs both checks after the manifest diff,
  appends the schema report to the job summary, and uploads
  `plan-2-8-digest-schema-report` + `plan-2-8-status-badge`
  (both retained 365 days).
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 weekly snooze-expiry + script manifest + manifest diff wiring

- Weekly digest now surfaces a snooze-expiry report
  (`plan_2_8_snooze_expiry_report.py`) as both a job-summary
  section and `plan-2-8-snooze-expiry` artifact.
- Weekly digest runs `plan_2_8_manifest.py` (static scan of
  `scripts/plan_2_8_*.py` ↔ `tests/test_plan_2_8_*.py`) and
  uploads `plan-2-8-manifest`.
- New `scripts/plan_2_8_manifest_diff.py` diffs the prior weekly
  manifest against the current one, reporting
  `added_scripts`, `removed_scripts`, `newly_testless`,
  `newly_tested`, and per-script CLI flag deltas (as md/json).
  Wired into weekly digest, downloading the prior manifest via
  `dawidd6/action-download-artifact@v6` with
  `name_is_regexp: true`. Uploads `plan-2-8-manifest-diff`.
  Supports `--fail-on-regression` for CI gates. +17 tests,
  including two weekly-workflow pin-tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 weekly history CSV + runbook link-check wiring + snooze expiry + manifest

- Weekly digest workflow now (a) exports the last-365-day history
  as `plan-2-8-history-csv` via `plan_2_8_history_export.py`, and
  (b) runs `plan_2_8_runbook_link_check.py` against the rollout
  runbook, appending its markdown report to the job summary.
  Both steps are fail-soft and skip gracefully when inputs are
  missing.
- New `scripts/plan_2_8_snooze_expiry_report.py` categorises every
  entry in `configs/plan_2_8_snoozes.json` as expired, expiring,
  active, permanent, or malformed against a configurable horizon
  (`--within-days`). Supports md/json output and a
  `--fail-on-expired` guard for CI. +16 tests including two
  weekly-workflow pin-tests.
- New `scripts/plan_2_8_manifest.py` statically scans
  `scripts/plan_2_8_*.py` and `tests/test_plan_2_8_*.py`, pairing
  each script with its companion test and extracting CLI flags via
  a regex probe (no exec). Includes a `--fail-on-missing-test`
  guard so CI can assert that the Plan 2.8 test surface stays
  complete. +13 tests, one sweeping the real repo.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 compact status-runcard step + history CSV export + runbook link check

- Weekly digest workflow now runs the compact status runcard
  (`plan_2_8_runcard_from_status.py`) after the digest archive
  and uploads it as `plan-2-8-status-runcard` (365d).
- New `scripts/plan_2_8_history_export.py` converts
  `plan_2_8_history.jsonl` to CSV with a stable 7-column schema
  (`captured_at, scoring_root, tf, family, events, hit_rate_pct,
  delta_pp`). Supports `--lookback-days` and `--fields` override.
  Malformed/blank lines tolerated. +10 tests.
- New `scripts/plan_2_8_runbook_link_check.py` verifies intra-doc
  anchor links in `docs/plan_2_8_rollout_runbook.md` using the
  same slug algorithm as the TOC helper. Ignores external and
  cross-file links, skips fenced code. `--fail-on-broken` for CI.
  +13 tests including a real-runbook sweep and weekly workflow
  pin-test.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 weekly archive+compare + compact status runcard + history prune

- Weekly digest workflow now downloads the prior
  `plan-2-8-digest-archive` artifact, archives the fresh
  `digest.json` under its `captured_at` date, and when at least
  two dated archives exist compares them via
  `plan_2_8_digest_compare.py`; results are appended to the step
  summary and the rotating archive is re-uploaded (365d).
- New `scripts/plan_2_8_runcard_from_status.py` renders a slim
  one-page status runcard from machine-readable JSON
  (`status_snapshot.json`, `runcard_index.json`, `health.json`).
  Missing inputs render as `n/a` / unknown. +9 tests plus 2
  workflow pin-tests for archive+compare wiring.
- New `scripts/plan_2_8_history_prune.py` prunes
  `plan_2_8_history.jsonl` to the last N days (default 365),
  atomic rewrite, `--dry-run`, `--drop-undated`, `--output`.
  Malformed JSON lines are counted, blank lines ignored. +10
  tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 weekly snapshot + TOC steps + digest archive helper

- Weekly digest workflow now writes a `runbook_toc.md/json` via
  `plan_2_8_runbook_toc.py`, a one-line `status_snapshot.json`
  plus md via `plan_2_8_status_snapshot.py`, and uploads the
  status snapshot as `plan-2-8-status-snapshot` (365d retention).
- New `scripts/plan_2_8_digest_archive.py`: copies the current
  `digest.json` into a rotating archive keyed by `captured_at`
  (YYYY-MM-DD). Supports a `--fallback-date`, `--keep` count-based
  rotation, and `--emit-latest-two` for chaining into the digest
  comparator. Same-date writes overwrite in place. +12 tests,
  including two weekly workflow pin-tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 weekly heatmap step + runbook TOC + status snapshot

- Weekly digest workflow now runs the 90-day alert-history heatmap
  (`plan_2_8_alert_history_heatmap.py`) after the CHANGELOG slice
  step, appending its md to the GitHub step summary.
- New `scripts/plan_2_8_runbook_toc.py` emits a table-of-contents
  sidebar for `docs/plan_2_8_rollout_runbook.md`. Ignores fenced
  code blocks; disambiguates duplicate slugs. md/json output,
  tunable level range. +10 tests.
- New `scripts/plan_2_8_status_snapshot.py` collapses
  `health.json`, `runcard_index.json`, `coverage.json`, and
  `digest.json` into a one-line JSON suitable for dashboards. md
  render shows status/score/alerts/coverage/runcard presence.
  Tolerates missing or malformed inputs. +10 tests (including
  weekly heatmap pin-test).
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 runcard index + CHANGELOG slice step + digest compare + heatmap

- Weekly digest workflow now runs `plan_2_8_runcard_index.py`
  (md+json) after the runcard upload, and emits a 14-day
  `plan_2_8_changelog_digest.py` slice to the step summary.
- New `scripts/plan_2_8_digest_compare.py`: diff two digest.json
  snapshots on `(tf, family)` identity, report added/removed/
  persistent alerts with md/json output and `--fail-on-added`
  gate. +9 tests plus 2 workflow pin-tests.
- New `scripts/plan_2_8_alert_history_heatmap.py`: weekday x
  `tf/family` heatmap of the alert history, with optional
  `--lookback-days`, tolerant of bad timestamps and malformed
  JSONL lines. +11 tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 health step + CHANGELOG slice + runcard index

- Weekly digest workflow runs the rollout-health aggregator after
  coverage+stability and now also emits `coverage.json` and
  `stability.json` so the aggregator has structured inputs. Health
  md is appended to `GITHUB_STEP_SUMMARY`; no fail-on-red in CI.
- New `scripts/plan_2_8_changelog_digest.py` scrapes dated `Added/
  Changed/Fixed/Removed (YYYY-MM-DD) - title` entries from
  `CHANGELOG.md` and renders md/json for status sidebars. Supports
  `--lookback-days` and `--limit`. +10 tests.
- New `scripts/plan_2_8_runcard_index.py` scans the digest artifact
  dir, reports which runcard sections are present/missing/empty,
  renders md/json, and supports `--min-present` for CI gates. +12
  tests including section-map lockstep with
  `plan_2_8_weekly_runcard.SECTION_MAP`.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 weekly runcard step + monthly ADR queue + rollout health

- Weekly digest workflow now emits a consolidated operator runcard
  (digest + coverage + stability + lint + history summary) and
  uploads it as the `plan-2-8-weekly-runcard` artifact (180d).
- Monthly digest workflow appends a deferred-ADR queue section
  sourced from `docs/DECISIONS.md` via the new ADR queue helper.
- New `scripts/plan_2_8_health.py` aggregator collapses the per-axis
  JSON payloads (digest / coverage / stability) into a single
  0..1 score + `green|amber|red` status + findings list. Supports
  md/json output, `--fail-on-red`, and tolerates missing inputs.
  +15 tests including weekly/monthly workflow pin-tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 history backfill + ADR queue + weekly runcard

- `scripts/plan_2_8_history_backfill.py`: merge two history JSONLs
  de-duped on `(captured_at, scoring_root)`, atomic write via
  tempfile, `--dry-run` for safe preview. Chronological sort
  tolerates unparseable timestamps. +9 tests.
- `scripts/plan_2_8_adr_queue.py`: parse `docs/DECISIONS.md`,
  extract date/slug/status/decision-summary, filter by
  `accepted`/`deferred`/`superseded`, render md/json/text. +12 tests.
- `scripts/plan_2_8_weekly_runcard.py`: fold per-step digest
  artifacts (digest/issue/snooze_lint/diff/movers/coverage/
  stability/alert_history_summary) into a single operator runcard
  md. Missing or empty sections are silently skipped. +10 tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 snooze-lint + weekly alert-history summary step

- `scripts/plan_2_8_snooze_lint.py`: validate
  `configs/plan_2_8_snoozes.json` — flags missing `tf`, stale
  entries (expired `expires`), unparseable timestamps, duplicate
  `(tf, family)` pairs. Supports `--warn-only` for advisory CI use.
  +13 tests.
- Weekly digest workflow runs `snooze_lint` in warn-only mode
  *before* applying the snooze so operators see issues in the run
  summary without breaking the digest. +1 pin-test.
- Weekly digest workflow now also runs
  `plan_2_8_alert_history_summary.py` on the rolling
  `alert_history.jsonl` (90-day window) after the upload step and
  streams the ranked table into the run summary. +1 pin-test.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 alert-history wiring + monthly rollup + summary CLI

- Weekly digest workflow now appends fired alerts to a long-running
  `alert_history.jsonl` via `scripts/plan_2_8_alert_history.py` and
  publishes it as the `plan-2-8-alert-history` artifact (365-day
  retention). +2 pin-tests.
- Monthly digest workflow now streams the 8-week rolling HR trend
  from `scripts/plan_2_8_digest_rollup.py` into the run summary.
  +1 pin-test.
- `scripts/plan_2_8_alert_history_summary.py`: read the alert log
  and rank TF×family slices by frequency within a lookback window,
  with `last_delta_pp` + `max_abs_delta_pp` context. +9 tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 weekly stability step + alert history + rolling HR trend

- Weekly digest workflow now streams a fail-soft
  `Plan 2.8 slice stability (last 8 snapshots)` section into the run
  summary right after slice coverage. +1 pin-test.
- `scripts/plan_2_8_alert_history.py`: append fired drift alerts to
  a long-running JSONL log, de-duped on `(captured_at, tf, family)`
  for replay safety. Atomic rewrite-through-tempfile. Accepts both
  list-shaped and digest-shaped payloads. +8 tests.
- `scripts/plan_2_8_digest_rollup.py`: N-week rolling HR trend per
  slice with sparkline rendering. ISO-week bucketing (latest
  snapshot wins within a week). +10 tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 weekly coverage step + snooze admin + stability metric

- Weekly digest workflow now streams a fail-soft
  `Plan 2.8 slice coverage` section into the run summary,
  consuming `scripts/plan_2_8_coverage.py` against the latest
  rolling-bench history. +1 pin-test.
- `scripts/plan_2_8_snooze_admin.py`: operator CLI for the
  drift-alert snooze config — `add` / `list` / `expire` / `rm`.
  Atomic writes preserve the `_comment` scaffold; `list --active`
  filters on `expires`. +10 tests.
- `scripts/plan_2_8_history_stability.py`: per-slice HR stddev over
  the last N snapshots. Flags slices jittering beyond a configurable
  threshold with a `--fail-on-unstable` gate. +11 tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 snooze config + monthly digest + coverage helper

- `configs/plan_2_8_snoozes.json`: operator-managed drift-alert
  snooze list (empty by default). Weekly digest workflow now loads
  it, re-renders the digest via `plan_2_8_alert_snooze.py`, and
  resolves final `has_alerts` from the filtered result so suppressed
  slices never open/reopen GitHub issues.
- `.github/workflows/plan-2-8-weekly-digest.yml`: new `snoozed`
  pass-through pipeline — `digest` step emits a JSON digest, new
  `snooze` step applies config if present, new `resolve_alerts` step
  sets the final `has_alerts` output consumed by the open/close
  steps.
- `.github/workflows/plan-2-8-monthly-digest.yml`: schedule
  `0 13 1 * *` + dispatch. Runs the trend digest at 30d lookback and
  top-movers with `--top-n 10`. 365-day artifact retention.
- `scripts/plan_2_8_coverage.py`: report TF×family slices in the
  latest snapshot that are below `min_events`. Optional
  `--fail-on-under` for hard CI gating.
- `scripts/plan_2_8_status.py`: Phase 1 anchors include the snooze
  config, coverage helper, and monthly workflow + tests.
- Docs: runbook notes the weekly snooze behaviour and adds sections
  for monthly digest and slice coverage; pin-test inventory
  refreshed.
- Tests: +10 coverage, +7 monthly workflow, +3 weekly digest wiring
  (20 new).

### Added (2026-04-21) — Plan 2.8 alert snooze + top movers

- `scripts/plan_2_8_alert_snooze.py`: filter a trend-digest JSON
  against a snooze config. Supports tf-only / tf+family matching,
  optional ISO `expires`, invalid-timestamp safety (treated as
  inactive). Does not mutate input; records the suppressed alerts
  under a new `snoozed` key for triage.
- `scripts/plan_2_8_top_movers.py`: rank TF×family slices by
  `|delta_pp|` across a configurable lookback window. Honors
  `min_events` floor; renders both "gainers" and "losers" tables.
- `.github/workflows/plan-2-8-weekly-digest.yml`: new fail-soft
  "Plan 2.8 top movers (30-day window)" step streams the table into
  the run summary below the existing snapshot diff.
- `scripts/plan_2_8_status.py`: Phase 1 anchors include the two
  new helpers + their test files.
- Docs: runbook gains a top-movers / alert-snooze section; pin-test
  inventory refreshed.
- Tests: +10 alert-snooze, +11 top-movers, +1 weekly workflow step
  pin-test (22 new).

### Added (2026-04-21) — Plan 2.8 snapshot diff + drift-alert auto-close

- `scripts/plan_2_8_history_diff.py`: diff any two snapshots in the
  history JSONL (by captured_at or index). Emits per-TF and per-
  TF×family HR-delta tables. Markdown/JSON output. Defaults to the
  last two rows for quick "what changed since yesterday".
- `.github/workflows/plan-2-8-weekly-digest.yml`: new
  "Close drift-alert issues when alerts cleared" step — when the
  digest reports zero comparable slices over threshold, any still-
  open `plan-2.8,drift-alert` issues are auto-commented + closed.
  Additional fail-soft step runs the snapshot-diff helper on the
  last two rows and streams the table into the run summary.
- `scripts/plan_2_8_status.py`: Phase 1 anchors include the diff
  helper + its test file.
- Docs: runbook gains an auto-close paragraph and an ad-hoc
  snapshot-diff section; pin-test inventory refreshed.
- Tests: +9 history-diff, +2 weekly-digest auto-close wiring, +1
  history-diff workflow step (12 new).

### Added (2026-04-21) — Plan 2.8 history validate + drift-alert dedup + run-url

- `scripts/plan_2_8_history_validate.py`: non-destructive integrity
  check (well-formed JSON, parseable `captured_at`, no duplicate
  `(captured_at, scoring_root)` keys, `per_tf` shape). CLI exits
  non-zero on validation hits, can write a JSON report.
- `.github/workflows/smc-measurement-benchmark-rolling.yml`: new
  fail-soft "Plan 2.8 history validate" step after the rotate step.
  Uploads `plan_2_8_history_validate.json` and streams the report
  into the run summary.
- `scripts/plan_2_8_trend_digest.py`: `render_issue_body()` now
  accepts an optional `run_url` and the CLI gains `--run-url` so the
  weekly workflow can stamp the run link into the issue body.
- `.github/workflows/plan-2-8-weekly-digest.yml`: drift-alert step
  re-renders the issue body with the workflow-run URL footer, then
  de-dups via `gh issue list --label plan-2.8 --label drift-alert
  --state open` — comments on an existing open thread instead of
  spawning a new issue every week the alert persists.
- `scripts/plan_2_8_status.py`: Phase 1 anchors extended with the
  validator and its pin-tests.
- Docs: runbook gains a history-validate paragraph and an updated
  drift-alert auto-issue note describing the de-dup behaviour. Pin-
  test inventory refreshed.
- Tests: +11 history-validate, +5 rolling-bench validate wiring,
  +3 issue-body run_url, +2 weekly de-dup wiring (21 new).

### Added (2026-04-21) — Plan 2.8 drift-alert auto-issue + history rotation

- `scripts/plan_2_8_trend_digest.py`: new `render_issue_body()` +
  `has_alerts()` helpers plus `--format issue` / `--alerts-file` CLI
  flags so the weekly workflow can emit a compact GitHub-issue body
  alongside the existing markdown digest.
- `.github/workflows/plan-2-8-weekly-digest.yml`: after rendering
  the digest, also writes `issue_body.md` + `alerts.json`, surfaces
  `has_alerts` as a step output, and opens a `plan-2.8,drift-alert`
  labelled issue via `gh issue create` when the flag is `True`. New
  scoped `permissions: issues: write`.
- `scripts/plan_2_8_history_rotate.py`: size-bound the rolling
  history JSONL by `--max-rows` and/or `--max-age-days`. Atomic
  rewrite, keeps a `.bak`, fail-soft rollback on write errors,
  corrupt-line preservation (opt-in drop).
- `.github/workflows/smc-measurement-benchmark-rolling.yml`: new
  "Plan 2.8 history rotate" fail-soft step after the archive step,
  capped at 366 snapshots / 400 days by default.
- `scripts/plan_2_8_status.py`: Phase 1 anchors extended with the
  rotate helper + its pin-test + the digest-issue renderer + the
  weekly issue-wiring pin-test.
- Docs: runbook gains history-rotation and drift-alert auto-issue
  sections; pin-test inventory refreshed.
- Tests: +8 digest-issue body, +5 weekly issue wiring, +11 history
  rotate, +4 rolling-bench rotate wiring (28 new).

### Added (2026-04-21) — Plan 2.8 trend digest end-to-end

- `scripts/plan_2_8_trend_digest.py`: pure-stdlib weekly digest
  renderer over the JSONL history. Picks `(prev, latest)` endpoints
  using the newest snapshot still satisfying `lookback_days`, then
  reports per-TF and per-TF×family HR drift. A `comparable` flag is
  set only when both endpoints have ≥`min_events` events; alerts
  fire only on comparable slices whose absolute drift ≥
  `alert_threshold_pp`. Three named statuses: `empty`, `warmup`
  (history younger than the window), `ok`.
- `.github/workflows/smc-measurement-benchmark-rolling.yml`: new
  always() "Plan 2.8 history archive (snapshot append)" step
  slotted between the rollup step and the artifact upload. Calls
  `scripts/plan_2_8_history_archive.py` to fold the daily rollup
  into `${out_dir}/plan_2_8_history.jsonl` so the file is uploaded
  as part of the standard rolling-bench bundle. Fail-soft: missing
  rollup or write hiccup must not affect the benchmark outcome.
- `.github/workflows/plan-2-8-weekly-digest.yml`: Mondays at 12:00
  UTC. Downloads the most recent `smc-measurement-benchmark-rolling-*`
  artifact via `dawidd6/action-download-artifact@v6`, locates the
  history JSONL, runs the digest renderer with operator-tunable
  knobs (`lookback_days`, `min_events`, `alert_threshold_pp`),
  streams the markdown into `$GITHUB_STEP_SUMMARY`, and uploads it
  as the `plan-2-8-weekly-digest` artifact (90-day retention).
- `scripts/plan_2_8_status.py`: Phase-1 anchor list expanded with
  the new history-wiring pin-test, the digest script, and the
  weekly-digest workflow file.
- `docs/plan_2_8_rollout_runbook.md`: "Trend history" section
  updated to reflect that the daily rolling-bench now writes the
  history file automatically; new "Weekly trend digest" section
  documents the workflow + knobs + ad-hoc local invocation.
- Pin-tests:
  - `tests/test_plan_2_8_trend_digest.py` (12 tests — empty/warmup
    statuses, oldest-snapshot-satisfying-lookback selection,
    per-TF + per-family drift math, alert emission above threshold,
    no alert below threshold, `comparable=False` when min-events
    unmet (silences alerts), markdown for warmup skips tables, ok
    markdown has all sections, **end-to-end archive→digest** chain
    pinning the schema contract, CLI write, CLI error path).
  - `tests/test_plan_2_8_rolling_workflow_history_wiring.py` (5
    tests — step present + always(), order
    `rollup < archive < upload`, archiver invoked with rollup +
    history paths, history written inside `out_dir` for upload,
    fail-soft with `set +e` and existence guard).
  - `tests/test_plan_2_8_weekly_digest_workflow.py` (6 tests — file
    exists, Monday 12:00 UTC schedule + dispatch, default knob
    values match the digest defaults, digest step wires all flags
    and streams summary, artifact uploaded with `if: always()` and
    ≥90-day retention, download step targets the
    smc-measurement-benchmark-rolling workflow with
    `name_is_regexp: true`).

### Added (2026-04-21) — Plan 2.8 daily heartbeat + history + ADR-body renderer

- `.github/workflows/plan-2-8-status-daily.yml`: daily 06:15 UTC
  heartbeat that runs `scripts/plan_2_8_status.py`. Streams the
  markdown report into `$GITHUB_STEP_SUMMARY`, uploads it as the
  `plan-2-8-status-report` artifact (30-day retention), and fails
  the workflow only when a *required* anchor goes missing.
- `scripts/plan_2_8_history_archive.py`: idempotent JSONL archiver
  that projects each daily `plan_2_8_tf_family_rollup.json` into a
  compact per-TF×family snapshot (`captured_at`, `scoring_root`,
  `files_scanned`, `per_tf`) and appends it to a long-running
  history file. Dedup key = `(captured_at, scoring_root)`. Tolerates
  pre-existing corrupt lines without overwriting them.
- `scripts/plan_2_8_q4_gate_evaluator.py`: new
  `render_adr_body(verdict)` plus `--format adr` CLI choice. Emits a
  four-section ADR skeleton (`## Decision`, `## Alternatives
  considered`, `## Consequences`, `## Evidence`) with the actual gate
  numbers in-line, ready to pipe straight into
  `scripts/append_adr.py --alternatives-file …` for the W13
  decision record. Pass/fail branches each enumerate the
  corresponding rejected alternatives.
- `docs/plan_2_8_rollout_runbook.md`: new "Trend history" section
  with the archiver CLI snippet, expanded "Status quick-check"
  pointing at the new daily workflow, and the W13 ADR step rewritten
  to use `--format adr | append_adr.py --alternatives-file`.
- Pin-tests:
  - `tests/test_plan_2_8_status_daily_workflow.py` (5 tests — file
    exists, `schedule` + `workflow_dispatch` triggers, `15 6 * * *`
    cron, status step wires script + summary streaming, artifact
    uploaded with `if: always()`).
  - `tests/test_plan_2_8_history_archive.py` (7 tests — append
    writes JSONL with projection, idempotence on key, dedup key
    includes `scoring_root`, tolerates corrupt existing lines,
    creates parent directories, CLI write+dedup, CLI error path).
  - `tests/test_plan_2_8_q4_gate_evaluator_adr_body.py` (6 tests —
    all four ADR sections present, pass-path promotes 2H, fail-path
    rejects with failed gate name listed, evidence cites all three
    gates, Brier numbers formatted with sign, CLI `--format adr`
    emits the decision block).

### Added (2026-04-21) — Plan 2.8 Phase 2 bundle builder + status helper

- `scripts/plan_2_8_q4_gate_bundle_builder.py`: pure-stdlib builder
  that projects two `plan_2_8_tf_family_rollup.json` manifests (one
  per A/B arm) plus operator-supplied Brier scores into the bundle
  schema consumed by `plan_2_8_q4_gate_evaluator.py`. Bucket keys =
  `"<tf>/<family>"` from the intersection of TF×family slices in
  both rollups; deterministic ordering. Optional `--bucket
  tf/family` flag (repeatable) restricts the set. `n_events`
  reported per bucket is the candidate-arm count, matching addendum
  §3.2 G3 which gates on treatment-arm exposure. Refuses to
  fabricate Brier values.
- `scripts/plan_2_8_status.py`: read-only walker that scans the
  Phase 0–3 expected anchors (scripts, workflows, docs, pin-tests)
  and emits a markdown / JSON status report. Required-anchor
  failures exit `1`; optional-anchor absence is reported as
  `optional-missing` and does not fail.
- `docs/plan_2_8_rollout_runbook.md`: phase-2 row bumped from
  `in-flight` to `scaffolded` with link to the new builder; new
  "Phase 2 bundle assembly" section with concrete CLI snippet; new
  "Status quick-check" section.
- Pin-tests:
  - `tests/test_plan_2_8_q4_gate_bundle_builder.py` (9 tests —
    bucket intersection + sort order, Brier + sources passthrough,
    `--bucket` filter preserves order, malformed/missing bucket
    rejection, **end-to-end builder→evaluator pass-path**, **end-to-end
    builder→evaluator G3-fail-path** pinning the schema contract
    between the two scripts, CLI write, CLI error path).
  - `tests/test_plan_2_8_status.py` (8 tests — phases 0–3 covered,
    real-repo passes, empty-repo flags every required anchor as
    missing, optional anchors flagged softly, markdown structure,
    CLI happy path / failure path / `--output` writes).

### Added (2026-04-21) — Plan 2.8 Phase-2/3 operator surface

- `.github/workflows/plan-2-8-q4-gate-dryrun.yml`: new manual-only
  (`workflow_dispatch`) W13 dry-run workflow. Inputs: `bundle_path`
  plus all four threshold knobs (`uplift_min_pp`,
  `uplift_min_buckets`, `brier_max_regression`,
  `min_events_per_bucket`) defaulted to the addendum values
  (`0.03` / `2` / `0.02` / `30`). Streams the verdict markdown into
  `$GITHUB_STEP_SUMMARY` and uploads the JSON as the
  `plan-2-8-q4-gate-verdict` artifact (90-day retention).
- `scripts/append_adr.py`: ADR appender helper enforcing the
  canonical shape (Context / Decision / Alternatives considered /
  Consequences / Evidence / Status), with date validation,
  status whitelist (`accepted` / `deferred` / `superseded by ...`),
  `--dry-run`, and file-based `--context-file` /
  `--alternatives-file` inputs for longer sections. Enables the W13
  ADR workflow the rollout runbook describes.
- `docs/plan_2_8_rollout_runbook.md`: operator-facing rollout
  runbook: phase timeline (0/1 done, 2 in-flight, 3 scheduled), the
  daily rolling-bench automation pointer, the W13 Q4-gate
  review checklist with a concrete bundle example, the three-gate
  summary table, the shipped pin-test inventory, and the
  "Phase 2 not ready by W12" deferral escalation.
- Pin-tests:
  - `tests/test_plan_2_8_q4_gate_workflow.py` (6 tests — file exists,
    `workflow_dispatch`-only trigger, all five inputs present, default
    thresholds match the addendum, evaluator step wires all knobs and
    streams summary, artifact uploaded with `if: always()`).
  - `tests/test_append_adr.py` (11 tests — render required
    subsections, header shape, date/slug/decision validation, status
    whitelist, empty-alternatives placeholder, append ordering,
    `## Entries` section required, CLI dry-run, CLI write, CLI error
    exit code).
  - `tests/test_plan_2_8_rollout_runbook.py` (6 tests — title, three
    gates documented with thresholds, cross-references to shipped
    tooling, four-phase table, Phase 0/1 marked done, default
    constants cited verbatim).

### Added (2026-04-21) — docs/DECISIONS.md ADR scaffolding

- `docs/DECISIONS.md`: new append-only architectural decision log
  with canonical ADR format (Context / Decision / Alternatives
  considered / Consequences / Evidence / Status). First entry:
  **2026-04-21 — 3-layer HTF trend stack over Flux-style 7-TF
  bias**, closing the Plan 2.8 addendum §7 risk-mitigation ask for
  a canonical reject-reason location. The entry enumerates all
  three rejected alternatives (Flux 7-TF, 4th intraday layer /
  30m vs 2H, sub-minute LTF) and cross-references the pin-tests
  and the Q4-gate evaluator that would re-open the deferred 2H
  branch.
- `tests/test_docs_decisions_adr.py`: 6 structural pin-tests
  (file exists, required subsections, Plan 2.8 ADR present, ADR
  cross-references addendum + all four pin-tests + Q4 evaluator,
  all three rejected alternatives listed, `Status. accepted.`).

### Added (2026-04-21) — Plan 2.8 §3.2 Q4-Gate evaluator

- `scripts/plan_2_8_q4_gate_evaluator.py`: pure evaluator for the
  three cumulative Q4 gates the addendum §3.2 requires before any
  4th-trend-layer (2H) promotion:
    - **G1 uplift**: >= 3pp HR uplift in >= 2 of the tested context
      buckets (`uplift_min_pp`, `uplift_min_buckets` configurable);
    - **G2 Brier**: brier_candidate - brier_baseline <= 0.02
      (`brier_max_regression` configurable);
    - **G3 min-events**: every bucket carries >= 30 events after
      promotion (`min_events_per_bucket` configurable, Blasiok &
      Nakkiran 2023 smECE floor).
  Consumes a minimal JSON bundle (`buckets[]` + `brier_baseline` +
  `brier_candidate`) so it can plug into any A/B framework. Emits a
  schema_version=1 verdict with `overall: pass|fail`, per-gate
  reasons, per-bucket breakdown. CLI: `--bundle`, `--output`,
  `--format md|json`, `--quiet`, plus tuning knobs for each
  threshold. Mutates nothing — W13 operators can dry-run before
  acting. 13 tests.

### Changed (2026-04-21) — Plan 2.8 rollup wired into rolling benchmark workflow

- `.github/workflows/smc-measurement-benchmark-rolling.yml`: new
  `always()` step "Plan 2.8 Phase 1 per-TF family rollup" slotted
  between the FVG label audit and the artifact upload. Runs
  `scripts/plan_2_8_tf_family_rollup.py` against the day's
  scoring-artifact tree with the expanded `5m,15m,1H,4H` TF list,
  writes `plan_2_8_tf_family_rollup.json` into the benchmark output
  dir (automatically picked up by the existing directory-level
  upload), and streams the Markdown view to `$GITHUB_STEP_SUMMARY`
  so operators can eyeball the two Phase-E2 verdicts (FVG 5m vs
  15m+1H baseline, BOS 4H vs 15m+1H baseline) on every daily run.
  Fail-soft (`set +e` + trailing `true`) so a rollup hiccup cannot
  mask the benchmark outcome.
- `tests/test_plan_2_8_rolling_workflow_rollup_wiring.py`: 6
  structural pin-tests (step present, order
  `audit < rollup < upload`, all four TFs passed, markdown streams
  to step summary, fail-soft, manifest lands in upload path).

### Added (2026-04-21) — Plan 2.8 Phase 1 per-TF family rollup + E2 verdict

- `scripts/plan_2_8_tf_family_rollup.py`: aggregates
  `scoring_<symbol>_<tf>.json` artifacts under a measurement-benchmark
  root into per-TF event counts, per-TF hit rates, per-TF x per-family
  hit rates, and two Phase-E2 verdicts mandated by the addendum
  (W8 deliverable):
    - `fvg_ttf_5m_vs_baseline`: FVG hit-rate on 5m vs the merged
      15m+1H baseline (tests the TTF-artefact hypothesis D3).
    - `bos_stability_4h_vs_baseline`: BOS hit-rate on 4H vs the
      merged 15m+1H baseline (tests the 4H swing-stability claim).
  Both verdicts report `insufficient_data` when either side carries
  < 30 events, so downstream automation cannot act on noise. Schema
  version 1. CLI: `--scoring-root`, `--timeframes`, `--output`,
  `--format md|json`, `--quiet`. Tolerates unreadable files and
  flags unknown timeframes. 12 tests.

### Added (2026-04-21) — Plan 2.8 S3.1 per-TF partitioning pin-test

- `tests/test_plan_2_8_s3_1_per_tf_partitioning.py`: 4 structural
  tests pinning that `_path_token` is stable under the exact
  `RELEASE_REFERENCE_TIMEFRAMES` strings (`"5m"`, `"15m"`, `"1H"`,
  `"4H"`), that `_pair_output_dir` partitions all four TFs into
  distinct directories under the symbol root (no collisions), and
  that per-symbol separation is preserved. Addendum 2.8 Phase 1
  deliverable: without this guard a regression could silently merge
  5m + 15m events into the same scoring bucket and break per-chart_tf
  calibration right at the layer the addendum is designed to
  strengthen.

### Changed (2026-04-21) — Plan 2.8 S0 Pine MTF-stack tooltips

- `SMC_Core_Engine.pine`: the three `Trend TF N` inputs (group
  `7. Advanced - Higher Timeframe Trend`) now carry explicit
  tooltips that document the intentional ICT-standard 3-layer
  hierarchy (4H / 1D / 1W), the factor-~4 spacing, the adaptive
  IPDA dach-TF above layer 3, and the calibration caveat for
  non-default custom TFs. Also added a comment block referencing
  `docs/smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md`
  so future readers can trace the "3 layers, not 7" decision.
- `tests/test_plan_2_8_s0_pine_trend_tf_tooltips.py`: 4 structural
  pin-tests (3-layer mention on TF1, calibration caveat on TF2,
  IPDA + `select_ipda_htf` reference on TF3, all three have
  non-empty tooltips).

### Changed (2026-04-21) — Plan 2.8 S3.1 Chart-TF expansion (5m + 4H added)

- `scripts/run_smc_measurement_benchmark.py`: default `--timeframes`
  expanded from `RELEASE_REFERENCE_TIMEFRAMES[1:3]` (15m, 1H) to
  the full `RELEASE_REFERENCE_TIMEFRAMES` tuple (5m, 15m, 1H, 4H).
  No code change elsewhere — `RELEASE_REFERENCE_TIMEFRAMES` already
  carried all four TFs; only the rolling-benchmark default was
  clamped to the 2-TF slice.
- `.github/workflows/smc-measurement-benchmark-rolling.yml`:
  `workflow_dispatch` `timeframes` input default + run-step shell
  fallback both moved from `15m,1H` to `5m,15m,1H,4H`. The rolling
  benchmark is what feeds F2's daily dual-arm artifact dirs, so the
  expansion propagates automatically into Phase-E2 event collection
  (5m for FVG TTF hypothesis, 4H for BOS swing stability).
- `tests/test_plan_2_8_s3_1_chart_tf_expansion.py`: 4 pin-tests —
  `RELEASE_REFERENCE_TIMEFRAMES == ("5m","15m","1H","4H")`, CLI
  default covers all four, workflow-input default covers all four,
  shell fallback covers all four and no stray `"15m,1H"` literals
  remain.

Rationale: Plan 2.8 §3.1 GO — event density ~3x on 5m (statistical
belastbarkeit for per-context quality filter), 4H proof-point for
BOS family stability, marketing anchor "kalibriert auf 5m/15m/1H/4H"
vs. legacy "15m/1H". Cost: CI config only, benchmark runtime ~2x.

### Changed (2026-04-21) — daily workflow wires runbook + archive cleanup

- `.github/workflows/f2-promotion-gate-daily.yml`: two new
  `always()` steps slotted between the status snapshot and the
  upload — "Operator runbook (consolidated)" streams the
  `f2_runbook.py --format md` output to `$GITHUB_STEP_SUMMARY`
  (status + 7-day digest + ring tail) and "Prune stale archive
  entries (>90d)" runs `f2_cleanup_archives.py` with a 90-day
  retention policy and an audit journal. Both tolerate failure so
  the gate's `rc` stays the primary signal. Upload bundle now
  carries `runbook.json`, `cleanup_archives.json`, and
  `cleanup_archives_journal.jsonl`.
- `tests/test_f2_workflow_yaml_contract.py`: pin-tests extended to
  assert (a) step order
  `annotate < summary < status < runbook < cleanup < upload`,
  (b) both new steps run on `always()` with `set +e` + trailing
  `true`, (c) bundle includes the new files (10 tests, was 9).

### Added (2026-04-21) — consolidated F2 operator runbook

- `scripts/f2_runbook.py`: one-shot report combining
  `build_status()` + `build_digest()` + latest rollback-history ring
  tail into a pasteable Markdown document (Status / Weekly digest /
  Recent ring sections). Also exposes public `build_runbook()` and
  `render_markdown()` APIs. Supports `--format md|json`,
  `--window-days`, `--ring-tail`, `--output`, `--quiet`. Schema
  version 1. Long ring reasons truncated to keep the table
  pasteable. 10 tests.
- `tests/test_f2_helpers_convergence.py`: added `f2_runbook` to
  `F2_HELPERS` (28 tests, was 26).

### Added (2026-04-21) — F2 archive retention helper

- `scripts/f2_cleanup_archives.py`: prunes
  `contextual_calibration.archive/*.json` entries whose embedded
  `YYYY-MM-DDTHH-MM-SSZ` suffix is older than `--max-age-days`
  (default 90). Skips files without a parseable timestamp. Appends
  structured manifest (schema_version=1) to
  `artifacts/ci/f2/cleanup_archives_journal.jsonl` on real runs;
  `--dry-run` previews without unlinking or journalling. Tolerates
  missing archive dirs. CLI supports `--output`/`--quiet` for CI
  use. 12 tests.
- `tests/test_f2_helpers_convergence.py`: added
  `f2_cleanup_archives` to `F2_HELPERS` (26 tests, was 24).

### Added (2026-04-21) — local dry-run simulator for the F2 chain

- `scripts/f2_simulate_chain.py`: walks the full §2.4 G2 rollback
  chain locally against synthetic fixtures — seeds a spec +
  production artifact, writes N day reports, runs
  append → render-issue → revert → rotate → summarize → inspect →
  weekly-digest, and persists a `simulation_manifest.json`
  (schema_version=1) with the narrative + every intermediate record.
  Default fixture = 2 clean days + worse day + rollback day. Custom
  `days` list supported for no-rollback walks. No network, no CI.
  `--quiet` prints only the manifest path for scripting. 8 tests.
- `tests/test_f2_helpers_convergence.py`: added `f2_simulate_chain`
  to the parametrized `F2_HELPERS` list (24 tests, was 22).

### Added (2026-04-21) — f2-weekly-digest workflow (Monday 11 UTC)

- `.github/workflows/f2-weekly-digest.yml`: new scheduled workflow
  that runs `scripts/f2_weekly_digest.py` every Monday 11:00 UTC
  (after the 10:00 UTC daily gate), writes
  `artifacts/ci/f2/weekly_digest.json`, and appends the Markdown
  timeline table to `$GITHUB_STEP_SUMMARY`. Read-only permissions
  (no Issue-ping). Uploads as a 180-day artifact so the rolled-up
  view covers the §2.4 G3 30-day SPRT window plus historical
  context. Fail-soft: no reports dir yet → exits green with a
  `::notice` skip.
- `tests/test_f2_weekly_digest_workflow_contract.py`: structural
  pin-test for the new workflow (6 invariants: name, Monday 11 UTC
  cron, `workflow_dispatch.inputs.window_days`, `contents: read`
  permissions only, helper + reports-dir + md-format flag present,
  upload retention 180 days).

### Added (2026-04-21) — Q3/Q4 Plan §2.4 G3 weekly digest helper

- `scripts/f2_weekly_digest.py`: rolls up the last N days of
  `f2_promotion_gate_<DATE>.json` reports into a single JSON digest
  (schema_version=1) — per-day timeline with brier delta + SPRT n/k,
  decision counters, SPRT-decision counters, trailing
  `consecutive_worse` / `consecutive_better` runs. `--format md` emits
  a Markdown timeline table suitable for the 30-day SPRT window
  operator review. Default window 7 days; `--window-days` overrides.
  Tolerates unreadable report files and non-matching filenames. 16
  tests.
- `tests/test_f2_helpers_convergence.py`: added the new module to the
  parametrized `F2_HELPERS` list (22 tests, was 20).

### Added (2026-04-21) — Markdown render mode for status inspector

- `scripts/f2_inspect_status.py`: new `render_markdown(status)` helper
  + `--format md` CLI flag. Emits a compact operator-readable Markdown
  block (Artifact / Revert Journal / Promote Journal / Latest report
  sections) so the inspector is usable from the terminal without
  piping through `jq`. JSON output unchanged when `--format` is
  omitted; `--quiet` still wins over `--format` for stdout. 3 new
  tests (23 total).

### Added (2026-04-21) — F2 helpers convergence-pin tests

- `tests/test_f2_helpers_convergence.py`: cross-cutting invariants for
  the 8 F2 helpers — every script exposes a callable `main()`, every
  CLI accepts `--help` and exits 0 with `usage:` text, revert+promote
  share `ARCHIVE_SUBDIR_DEFAULT='contextual_calibration.archive'`,
  both journals live under `artifacts/ci/f2/` (and are distinct files
  so they cannot clobber each other), `SUMMARY_SCHEMA_VERSION` and
  `STATUS_SCHEMA_VERSION` are positive integers, and the
  `f2-rollback` Issue label stays pinned (also referenced verbatim in
  the workflow YAML). 20 tests, ~1.4 s.

### Added (2026-04-21) — `--quiet` one-line summary for status inspector

- `scripts/f2_inspect_status.py`: new `render_one_line(status)` helper
  + `--quiet` CLI flag. Compresses the digest to
  `f2[<experiment>] artifact=<status> revert=<n> promote=<n> latest=<date>:<decision>`
  for shell pipelines and CI annotations. `--output` still writes the
  full JSON; `--quiet` only changes stdout. 4 new tests (20 total).
- `.github/workflows/f2-promotion-gate-daily.yml`: status-snapshot step
  now also emits a `::notice title=f2-contextual-arm::<one-line>`
  annotation so the daily run state is visible in the workflow log
  header without scrolling into the fenced JSON block.

### Changed (2026-04-21) — wire status inspector into daily workflow

- `.github/workflows/f2-promotion-gate-daily.yml`: new `if: always()`
  "Contextual arm status snapshot" step runs `f2_inspect_status.py`
  after the history summary, writes `artifacts/ci/f2/status_snapshot.json`
  and appends a fenced JSON block to `$GITHUB_STEP_SUMMARY`. Failure
  tolerated with `|| true` so it cannot mask the gate's exit code.
  Upload bundle now also carries `promote_journal.jsonl` and
  `status_snapshot.json`.
- `tests/test_f2_workflow_yaml_contract.py`: pinned the new step in
  the ordering invariant (annotate < summary < status < upload),
  pinned `always()` on the new step, and pinned the two new upload
  paths.
- `tests/test_f2_pipeline_e2e.py`: end-to-end now also calls the
  inspector after the rotate step, asserting that artifact status,
  revert-history length, journal counters, and latest report all
  agree.

### Added (2026-04-21) — Q3/Q4 Plan §2.3 F2 + §2.4 G2 status inspector

- `scripts/f2_inspect_status.py`: read-only operator inspector that
  fuses the live treatment artifact, both journals (revert + promote),
  and the latest promotion-gate report into a single JSON digest. Pins
  schema_version=1. Includes per-action counts + bounded `tail`
  (default 5) for each journal, the artifact's current status with
  inline `revert_history`/`promote_history` lengths, and the latest
  report's date/decision/SPRT terminal block. Tolerates corrupt
  artifact JSON, corrupt journal lines, missing reports dir, and a
  spec without `arms.treatment.calibration_artifact`. 16 tests.

### Added (2026-04-21) — Q3/Q4 Plan §2.3 F2 ``on_promote`` operator helper

- `scripts/f2_promote_contextual_weights.py`: symmetric counterpart to
  the auto-revert helper. Operator-driven (the spec's `on_promote`
  action list is intentionally a manual follow-up after a clean SPRT
  `accept_h1` plus a clean rollback ring). Refuses unless the supplied
  promotion-gate report has `decision == 'promote'` (or `--force`).
  Archives the live shadow artifact to
  `contextual_calibration.archive/<stem>_<UTC-ISO>.json`, rewrites the
  live file with `status=production` and an appended `promote_history`
  entry, and journals every run to `artifacts/ci/f2/promote_journal.jsonl`.
  Atomic writes, idempotent (re-runs after promotion are no-ops). 16 tests.

### Added (2026-04-21) — Q3/Q4 Plan §2.4 G2 workflow contract test

- `tests/test_f2_workflow_yaml_contract.py`: structural pin-test for
  `.github/workflows/f2-promotion-gate-daily.yml`. Asserts step ordering
  (gate → append → issue → revert → annotate → summary → upload), the
  `if:` conditional gates (rc=='0' guards append, rc=='2' guards
  issue+revert, `always()` runs annotate/summary), `permissions:
  issues: write`, the 10:00 UTC daily cron, and that the upload bundle
  carries both `revert_journal.jsonl` and the
  `contextual_calibration.archive/**` tree.

### Added (2026-04-21) — Q3/Q4 Plan §2.3 F2 + §2.4 G2 end-to-end test

- `tests/test_f2_pipeline_e2e.py`: e2e regression test wiring all 5 operator-facing F2
  helpers together against synthetic fixtures (append → render-issue → revert → rotate →
  summarize). Covers the two-clean-days-then-rollback walkthrough plus revert idempotency
  on a re-run. Pure-Python, no benchmark I/O. Guards every helper in one place.

### Added (2026-04-21) — Q3/Q4 Plan §2.4 G2 automatic Revert

- **F2 contextual-weights auto-revert:** New
  `scripts/f2_revert_contextual_weights.py` closes the explicit
  "automatic Revert" half of the §2.4 G2 rule (the Issue-Ping half
  shipped in `2c284591`). Reads the F2 spec + the most recent
  promotion-gate report, validates `decision == 'rollback'` (refuses
  to demote any other decision unless `--force`), archives the live
  treatment calibration JSON to
  `artifacts/ci/f2/contextual_calibration.archive/<stem>_<UTC-ISO>.json`,
  rewrites the live file with `status=shadow`, and appends a
  `revert_history` entry that records the from-status, report path,
  decision, and archive location. Always appends a JSONL line to
  `artifacts/ci/f2/revert_journal.jsonl` (even on no-op paths) so
  the audit trail is complete. Atomic writes via tempfile +
  `os.replace`. Idempotent; no network. CLI exit codes: `0` on
  success / no-op, `1` on missing spec/report/artifact-field /
  malformed JSON / wrong decision without `--force`. 15 new tests;
  total green across the F2/SPRT/AB chain now 155.
- **Workflow auto-revert wiring:** Updated
  `.github/workflows/f2-promotion-gate-daily.yml` with a new
  "Auto-revert contextual calibration (§2.4 G2)" step that runs
  only on `steps.gate.outputs.rc == '2'`, after the Issue-Ping
  step. Failure is tolerated (`true` after `set +e`) so the
  workflow's own rc=2 stays the primary signal. The journal file
  and archive directory are added to the upload-artifact bundle.
- **Issue body runbook updated:** Step 2 of the rollback Issue
  body now reflects that the contextual JSON has *already* been
  demoted automatically; operators are pointed at the journal +
  archive instead of being asked to demote by hand.

### Added (2026-04-21) — Q3/Q4 Plan §2.3 F2 daily-history summarizer

- **F2 history summarizer:** New `scripts/f2_summarize_history.py`
  closes out the F2 operator toolset (append / rotate / render-issue /
  **summarize**). Reads
  `artifacts/ci/f2/rollback_history.json` (treatment − control
  `calibrated_brier` deltas) and optionally a directory of
  `f2_promotion_gate_*.json` reports, then emits a small
  `schema_version=1` digest with: history length / last delta /
  trailing-mean trend (default 30-day window) / consecutive worse
  vs better counts (matching the §2.4 G2 rollback rule), per-decision
  counts (`promote/hold/rollback/insufficient_data`), the latest
  report path + date + decision, and the verbatim latest SPRT
  terminal block. Pure-Python, deterministic, no network. Useful as
  input for a future Pine HUD row or weekly Slack digest. CLI exit
  codes: `0` on success, `1` on `--trend-window<1` or non-list
  history. 16 new tests; 140 total green across the F2/SPRT/AB chain.
- **Workflow wiring:** Updated
  `.github/workflows/f2-promotion-gate-daily.yml` to invoke the
  summarizer as an `if: always()` step (skip / rollback / config
  error all surface a digest). Writes
  `artifacts/ci/f2/history_summary.json` (now also in the uploaded
  artifact bundle) and appends a fenced JSON block to
  `$GITHUB_STEP_SUMMARY` so the Actions tab shows current pipeline
  state at a glance. Failure of this step is tolerated (`|| true`)
  so it can never mask the gate's exit code.

### Added (2026-04-21) — Q3/Q4 Plan §2.4 G2 GitHub-Issue-Ping

- **F2 rollback Issue renderer:** New
  `scripts/f2_render_rollback_issue.py` deterministically produces an
  Issue title (`[F2 rollback] <decision> on <date>`) and full
  Markdown body from a promotion-gate JSON report. Body includes the
  KPI-delta table, SPRT terminal block, rollback-window history, a
  link to the failing workflow run, the report path, and an operator
  runbook that explicitly points at
  `scripts/f2_rotate_rollback_history.py` for the post-review reset.
  Stable label: `f2-rollback`. CLI exit codes: `0` on success, `1`
  on missing/malformed report. 11 new tests; 124 total green across
  the F2/SPRT/AB chain.
- **Workflow ping wiring:** Updated
  `.github/workflows/f2-promotion-gate-daily.yml`:
  - Added `permissions: issues: write` (alongside existing
    `contents: read`) so the job can file rollback Issues.
  - New "Open rollback Issue" step runs only when
    `steps.gate.outputs.rc == '2'`. Uses `gh issue list` + label
    `f2-rollback` to dedupe: comments on the existing open Issue if
    one is already filed, otherwise opens a fresh one with
    `gh issue create --label f2-rollback`. The gate step's exit
    code 2 still surfaces as a workflow failure (CI red), as
    required by §2.4 G2.

### Added (2026-04-21) — Q3/Q4 Plan §2.4 G2 rollback-history rotate helper

- **F2 rollback-history rotate/reset helper:** New
  `scripts/f2_rotate_rollback_history.py`, an operator-callable
  companion to `f2_append_rollback_history.py`. After a rollback
  decision (gate exit code 2) and the manual review checklist, the
  daily ring at `artifacts/ci/f2/rollback_history.json` MUST be
  reset so the next day's gate does not immediately re-fire on
  stale history. The helper archives the live file to
  `artifacts/ci/f2/rollback_history.archive/<UTC-ISO>.json` (or a
  caller-supplied `--archive-dir`) and replaces it with `[]` (or a
  caller-supplied `--seed` JSON list). Atomic write via tempfile +
  `os.replace`. `--allow-empty` lets operators bootstrap a fresh
  ring when the live file does not yet exist. Refuses archive-name
  collisions to preserve the audit trail. CLI exit codes: `0` on
  success, `1` on configuration error. 13 new tests; 113 total
  green across the F2/SPRT/AB chain.

### Added (2026-04-21) — Q3/Q4 Plan §2.4 G2 rollback-history feedback loop

- **F2 rollback-history append helper:** New
  `scripts/f2_append_rollback_history.py` reads the daily promotion-
  gate JSON report and appends the `calibrated_brier` `delta`
  (treatment − control) to a bounded JSON ring at
  `artifacts/ci/f2/rollback_history.json` (default `--max-len 30`,
  configurable). Atomic write via tempfile + `os.replace`. CLI exit
  codes: `0` on success, `1` on missing report / malformed JSON /
  missing metric. 12 new tests; 100 total green across the
  F2/SPRT/AB chain.
- **F2 daily workflow wiring:** Updated
  `.github/workflows/f2-promotion-gate-daily.yml` to invoke the
  helper after a green gate run (`steps.gate.outputs.rc == '0'`)
  and include `artifacts/ci/f2/rollback_history.json` in the
  uploaded artifact bundle. Skipped when the gate already exited
  with `rc=2` (rollback) so the next manual review owns the reset.
  Closes the loop: the file the helper produces is exactly the
  `--rollback-history` input the next day's gate consumes.

### Added (2026-04-21) — Q3/Q4 Plan §2.3 F2 daily workflow

- **F2 promotion-gate daily workflow (plan §2.3 F2 + §2.4 G3):** New
  `.github/workflows/f2-promotion-gate-daily.yml` wraps
  `scripts/f2_run_promotion_gate.py` into a daily cron at 10:00 UTC
  (after the rolling-benchmark at 07:30 and feature-importance at
  09:00 so dual-arm artifact dirs are in place). Locates
  `artifacts/ci/f2/{static_global_weights,contextual_weights}/<DATE>`,
  runs the orchestrator with the shipping spec and optional rollback
  history, uploads `artifacts/reports/f2_promotion_gate_<DATE>.json`
  for 60 days. Fail-soft when arms are not yet produced
  (`status=skipped`, exit 0) so the 30-day window countdown keeps
  ticking. Exit-code policy: `0` on promote/hold/insufficient_data,
  `2` on rollback (CI red → GitHub-Issue-Ping per §2.4 G2), `1` on
  config error. Permissions: `contents: read` only — the workflow
  never mutates production calibration; promotion is a separate
  manual follow-up driven by the spec's `on_promote` action list.

### Added (2026-04-21) — Q3/Q4 Plan §2.3 F2 promotion-gate orchestrator

- **F2 promotion-gate CLI orchestrator (plan §2.3 F2 + §2.4 G3):** New
  `scripts/f2_run_promotion_gate.py` is a single CLI entry point that
  ties `run_ab_comparison.compare()` to
  `f2_experiment_spec.evaluate_promotion()`. Inputs: `--spec`,
  `--control-dir`, `--treatment-dir`, optional `--rollback-history`
  and `--output`. Output: schema-pinned (`schema_version=1`) JSON
  carrying the `{promote, hold, rollback, insufficient_data}`
  decision, the SPRT terminal report, the KPI deltas, the
  rollback-gate evaluation and the resolved action list. Exit codes:
  `0` on promote/hold/insufficient_data, `1` on configuration error,
  `2` on rollback (CI signal for the §2.4 G2 GitHub-Issue-Ping rule).
  Includes the unit-conversion fix in `_pair_dicts`:
  `PairReport.hit_rate` is a 0..1 fraction on disk but the SPRT
  wiring expects 0..100 percent, so the adapter multiplies by 100 to
  keep the convention consistent across the pipeline. 8 new tests
  (88 total green across the full F2/SPRT/AB chain).

### Added (2026-04-21) — Q3/Q4 Plan §2.3 F2 contextual promotion gate

- **F2 contextual promotion spec + gate evaluator (plan §2.3 F2 +
  §2.4 G3):** New `artifacts/experiments/f2_contextual_promotion.json`
  (schema_version=1) registers the experiment: control =
  `zone_priority_calibration.json` (static global weights), treatment
  = `zone_priority_contextual_calibration.json` (contextual + FVG
  quality score), SPRT config (p0=0.55, p1=0.60, α=0.05, β=0.20,
  max_n=600), rollback gate (2 consecutive worse runs on
  `calibrated_brier`), promotion gate (SPRT H1 + KPI deltas + rollback
  status) with `on_promote`/`on_reject` action lists, and data_window
  (≥30 days, ≥600 events per arm). New `scripts/f2_experiment_spec.py`
  exposes `load_f2_spec()`, `evaluate_rollback()` and
  `evaluate_promotion(digest, spec, daily_deltas)` returning one of
  `{promote, hold, rollback, insufficient_data}` directly from the
  `run_ab_comparison` digest. 16 new tests covering loader
  validation, all rollback-gate edge cases, and all five promotion
  decision branches. The F2 promotion gate is now operationally
  complete; only wall-clock blocker remains (30-day window once the
  contextual arm is wired into the rolling workflow).

### Added (2026-04-21) — Q3/Q4 Plan §2.4 G3 SPRT wired into A/B comparison

- **G3/F2 SPRT in `run_ab_comparison.py` (plan §2.4 G3):** New
  `terminal_decision(n, k, config)` helper in
  `scripts/smc_sprt_stop_rule.py` runs a closed-form aggregate Wald
  SPRT (LLR = `k·ln(p1/p0) + (n-k)·ln((1-p1)/(1-p0))`) against the
  lifetime baseline (p0=0.55, p1=0.60, α=0.05, β=0.20). Order-
  independent, the right call site for post-hoc analysis of fixed-
  window A/B benchmarks (plan: "SPRT *or* fixes N"). `compare()`
  output now carries a `sprt` block and `render_comparison()` emits
  a `## SPRT Stop-Rule (G3/F2)` markdown section with the terminal
  decision, totals, LLR vs Wald bounds and the resolved config.
  F2 promotion gate now consumes the SPRT terminal decision directly
  from `artifacts/reports/ab_comparison.json` on the next G3 30-day
  window completion. 12 new tests; 52 total green across SPRT module
  + comparison wiring.

### Added (2026-04-21) — Q3/Q4 Plan §2.4 G3 SPRT stop-rule

- **G3 / F2 SPRT stop-rule (plan §2.4 G3):** New
  `scripts/smc_sprt_stop_rule.py` implements one-sided two-hypothesis
  Wald SPRT on a single arm's binary outcomes (H0: p = p0 baseline,
  H1: p = p1 target). Pure Python (`math.log` only); no numpy/scipy
  dependency. `SPRTConfig` validates `p1 > p0`, error rates in
  (0, 0.5), `max_n >= 1`. `decide()` returns
  `{accept_h0, accept_h1, continue, max_n_reached}` so the gate
  cannot loop forever in CI. `evaluate_paired()` provides the
  McNemar-style discordant-pair filter for paired (control,
  treatment) tuples. CLI emits a schema-pinned `schema_version=1`
  report with `decision`, `n`, `k`, `hit_rate`, `llr`, Wald bounds
  and the resolved config. Unblocks F2 contextual-promotion gate
  (`docs/f2_contextual_promotion_decision_2026-04-21.md` step 3)
  and G3 30-day A/B once arms are wired into the rolling benchmark.
  17 new tests (incl. deterministic Monte-Carlo H1-truth check at
  ≥70 % acceptance rate).

### Added (2026-04-21) — Q3/Q4 Plan Amendment A1 (D4 + D2 + G1 closeout)

- **A1.A — Per-Event Ledger (plan §A1.A):** New `smc_core/event_ledger.py`
  reads/writes `events_<sym>_<tf>.jsonl` records carrying ScoredEvent
  fields plus the new `features` dict. Schema-pinned with round-trip
  tests; consumed by D4 recalibration and FI-drift downstream.
- **A1.B — D4 FVG-Quality Recalibration Script
  (plan §A1.B):** New `scripts/fvg_quality_recalibration.py` produces
  `artifacts/reports/fvg_quality_calibration_shadow.json`. Pure-Python
  L2 logistic regression (no numpy/scipy/sklearn dep), weights capped
  to [0.05, 0.40] then re-normalised to sum 1.0. Acceptance gate
  codified: top-quartile HR ≥ 0.70, bottom-quartile HR ≤ 0.55,
  Spearman ≥ 0.20. Fail-soft semantics distinguish
  `insufficient_features` vs `insufficient_events`. Shadow-only;
  production `fvg_quality_calibration.json` is not mutated.
- **A1.C — D2 Tri-Axis FVG Pine Codegen (plan §A1.C):** New
  `smc_core/fvg_pine_emit.py` consumes `stratified_fvg_report()` JSON
  and emits a deterministic Pine v5 const block of
  `FVG_HEALTH_<SESSION>_<VOL>` + `_STATUS` (OK / WARN / WEAK / INSUF
  on HR thresholds 0.70 / 0.55). Insufficient buckets render as
  `"insufficient (n=N)"`. Wiring into `SMC_Core_Engine.pine` is the
  remaining manual step (compile-only preflight).
- **A1.D — G1 Baseline Seed Workflow (plan §A1.D):** New
  `.github/workflows/smc-baseline-seed-rolling.yml` runs the daily
  baseline-seed reproducibility check against the 20-symbol universe
  and writes to `artifacts/ci/baseline_seed_rolling/YYYY-MM-DD/`.
  Acceptance memo unblocks after 5 consecutive weekday green runs.
- **D4 enricher (chains A1.B):** `ScoredEvent` gained
  `features: dict[str, Any]` (frozen-safe via `field(default_factory=
  dict)`). `smc_integration/measurement_evidence._score_zone_event`
  now populates the five A1.B feature keys (`gap_size_atr`,
  `htf_aligned`, `distance_to_price_atr`, `is_full_body`, `hurst_50`)
  for the FVG family via new `_atr_at` (Wilder ATR) and
  `_fvg_hurst_50` (delegating to `smc_core.fvg_quality.rolling_hurst`)
  helpers. Missing ATR / Hurst → key omitted (no zero-fill, so
  `insufficient_features` detection stays accurate). End-to-end chain
  `_score_zone_event → ScoredEvent.features → event_ledger →
  recalibration shadow JSON` now closes on the next CI rolling run.

### Added (2026-04-21) — Q3/Q4 Plan Phase E + F1 + E4

- **E1 — Symbol-Expansion (plan §2.2):** Recurring measurement-benchmark
  workflow universe extended from 12 → 20 symbols (adds GOOGL, META,
  NVDA, TSLA, V, UNH, HD, CVX, COP, OXY, BAC, GS, MS). All three preset
  cohorts (Tech-Megacap, Financials, Energy) now covered.
- **E2 — Timeframe-Expansion (plan §2.2):** 5m and 4H added alongside
  existing 15m/1H. Workflow now produces 80 (sym × tf) artifact dirs.
- **E3 — Rolling Benchmark (plan §2.2):** New
  `.github/workflows/smc-measurement-benchmark-rolling.yml` runs the
  20-sym universe daily at 07:30 UTC, writes to dated sub-dirs
  (`artifacts/ci/measurement_benchmark_rolling/YYYY-MM-DD/`), and
  retains 30 days. Includes per-day zone-priority calibration (with
  smECE) + FVG label audit. Purely observational; does not mutate
  checked-in lifetime corpus or production calibration.
- **E4 — FI Ranking-Drift Alert (plan §2.2):**
  `open_prep/feature_importance_report.py` now reads the previous
  `latest.json` before overwriting and attaches a `ranking_drift` block
  to the new record (status ∈ {ok, warn, unknown}, max_position_delta,
  drifted_features). Drifted = top-10 position shift > 3. Features
  dropping out of top-10 count as position N+1 so silent churn cannot
  hide drift. Advisory signal; CLI prints the drifted feature rows.
- **F1 — Testable Calibration alongside ECE (plan §2.3):**
  `scripts/smc_zone_priority_calibration.py` reconstructs corpus-level
  (pred, outcome) arrays from `calibration.bins` in every
  `scoring_*.json` and emits `testable_calibration` with binned ECE
  (n=10), smECE (Błasiok & Nakkiran 2023, kernel) and dCE upper bound
  (Rossellini et al. 2025). smECE is the primary F1 promotion-gate
  input; ECE kept for back-compat. Project-root `sys.path` fallback so
  the `smc_core` import works from CLI invocation.

### Evidence (Databento live, 10 025 events / 78 pairs)

- FVG hit-rate **56.1 %** vs BOS **86.8 %** — confirms WP21 FVG
  weakness at 55× sample size; not a small-sample artifact.
- `session:ASIA` boosts every family's HR (OB +0.3005, FVG +0.1175,
  SWEEP +0.1338) — coherent regime signal.
- `session:NY_AM` FVG underperformance -0.0812 at n=2 662 — single
  largest actionable lever.
- Aggregate smECE 0.1349, ECE 0.1332, dCE 0.1260 — all three agree;
  grid-artifact risk is low.
- Production `artifacts/reports/zone_priority_calibration.json`
  intentionally NOT bumped: global OB drift -0.3534 exceeds the 0.15
  drift-gate. F2 contextual promotion gated on G3 30-day A/B with
  SPRT/fixed-N stop rule per plan.

### Added (2026-04-20)


- **Phase H — Pine Consumer Maturity:**
  - **Calibration Confidence Indicator** — new `[ Calibration Confidence ]` section in Dashboard Audit View (rows 23–25) showing top-family calibration weight with tier label (high/good/ok/low) and composite confidence across all 4 families. Zone Priority + Calibration exports (`ZONE_CAL_OB/FVG/BOS/SWEEP` + Phase F contextual variants) added to the live generated library.
  - **Per-Family Win Rates** — new `[ Per-Family Performance ]` section in Dashboard Audit View (rows 26–30) showing OB, FVG, BOS, SWEEP individually with calibrated historical performance weight as percentage and color-coded confidence tier.
  - **FVG Health Warning** — composite health score (0–100) derived from `FVG_FRESH`, `FVG_INVALIDATED`, `FVG_FILL_PCT`, `FVG_MATURITY_LEVEL`, `FVG_NET_IMBALANCE`. New `[ FVG Health ]` section in Audit View (rows 31–33) with status + conditional warning. New `✅/⚠ FVG Health` checklist item in Explain mode. Warnings for invalidated FVGs, heavily filled zones (≥75%), and weak health.

- **Owner Review v2 (OV3–OV7):**
  - **OV3: Performance Report Script** (`scripts/generate_performance_report.py`) — consolidated Markdown + JSON performance report from measurement benchmark artifacts. Computes weighted-mean KPIs (Brier, ECE, hit rate), letter grades (A–F), pass/fail gates vs `MeasurementShadowThresholds`. CLI: `--input-dir` / `--output-dir`. 14 unit tests.
  - **OV4: Colorblind Palette** — Tableau-10 safe palette (bull=#1f77b4, bear=#ff7f0e, warn=#17becf, caution=#bcbd22) wired through Core Engine (3 lifecycle colors + 3 resolver functions), Dashboard (7 palette constants + all view modes), Mobile Dashboard (5 palette constants). Activated via existing `color_theme` input → "Colorblind Safe".
  - **OV6: Library Field Audit** — reverse-direction test (`test_every_generated_field_has_pine_consumer`) ensures every generated field has at least one Pine consumer or is declared `_INFRA_ONLY`. 18 enrichment-reserve fields catalogued. Staleness guard for `_INFRA_ONLY`.
  - **OV7: Enrichment A/B Framework** (`scripts/smc_ab_experiment.py`) — deterministic symbol-level experiment assignment (SHA-256 bucketing), flag resolution per arm, JSON experiment spec loading, provenance tagging. Comparison script (`scripts/run_ab_comparison.py`) diffs benchmark KPIs between arms with Markdown + JSON output. 16 unit tests.

- **Hygiene & Feature Round:**
  - **Provider Health Tab** in `streamlit_terminal.py` — neues "🩺 Provider Health" Tab zeigt Gesamtstatus (Coverage/Warnings/Failures), Provider-Domain-Matrix mit Failure-Semantik, Domain-Alerts und Failure-Semantics-Referenz. Basiert auf `provider_health.py` API.
  - **Zone Priority → Pine Consumer** — `SMC_Dashboard.pine` zeigt Zone Priority in Decision Brief (Rank + Score + Catalyst, farbkodiert A/B/C/D) und Audit View (vollständige Details mit Top-Family und Reason). `SkippALGO_Confluence.pine` zeigt Zone Prio als neue Zeile 7 (Rank + Score/100 + Catalyst).
  - **Provider Health Tab Tests** (`tests/test_provider_health_tab.py`) — 5 Integrationstests für die Provider Health Imports.

### Changed (2026-04-20)

- **Sunset Warning Cleanup** — entfernt den 20-Zeilen-Sunset-Warning-Block aus `generate_smc_micro_profiles.py`. `DEPRECATED_COMPATIBILITY_GROUPS` ist seit 2026-04-14 leer; die Warnung war nur noch Noise. `DEPRECATED_FIELD_POLICY` bleibt im Manifest für Contract Verification.
- **Stale asof_date Fixture Warnings** — `pyproject.toml` unterdrückt jetzt die 12 `UserWarning: Microstructure base asof_date is ... days old` Meldungen im Test-Output via `filterwarnings`.
- **Dashboard Row Shift** — Audit View und Decision Brief Row-Nummern in 3 Test-Dateien und e2e-Smoke-Referenz aktualisiert (87→88 Audit Rows).

### Added (2026-04-19)

- **Phase A+B+C — UX optimization (Strategie Q2 2026):**
  - **A1: 6 neue Alert-Conditions** in `SMC_Core_Engine.pine` — Bullish/Bearish BOS, Bullish/Bearish CHoCH, Zone Armed, Zone Invalidated. Nutzer können jetzt über TradingView-Alerts direkt auf Struktur- und Lifecycle-Events reagieren (insgesamt 16 Alert-Conditions).
  - **A2: Focus-Ansicht** im `SMC_Dashboard.pine` — neuer "Focus" View-Modus mit 3-Zeilen Traffic-Light (Ampel + Level + Market). Keine Konfiguration, keine Ablenkung — sofortige Orientierung.
  - **A3: Performance-Tabelle** in `SMC_Long_Strategy.pine` — 8-Zeilen-Table zeigt Trades, Win Rate, Profit Factor, Net Profit, Max Drawdown, Avg Trade und aktuellen Modus. Farbkodiert nach Ergebnis-Qualität.
  - **B4: SkippALGO Confluence Hub** (`SkippALGO_Confluence.pine`) — aggregiert SMC Zone-Lifecycle (BUS) + Trend (EMA) + Momentum (RSI/MACD) + Mean-Reversion (BB) zu einem 0–100 Confluence-Score mit Traffic-Light (🟢 TRADE / 🟡 WATCH / 🔴 STAY AWAY). 2 Alert-Conditions.
  - **B5: SMC Setup Check** (`SMC_Setup_Check.pine`) — validiert BUS-Verbindungen zum Core Engine mit ✅/❌ Checklist. Zeigt Anleitung für nächste Schritte direkt im Chart. Kein leeres Dashboard mehr.
  - **C8: SMC Mobile Dashboard** (`SMC_Mobile_Dashboard.pine`) — Mobile-first 4-Zeilen Dashboard: Traffic-Light + Levels + Market + Quality. Keine Overlays, nur Table. Optimiert für kleine Screens.
  - **C9: AI Zone-Priorisierung** (`scripts/smc_zone_priority.py`) — Composite-Score (0–100) aus 3 Dimensionen: historische Performance (Ensemble, 0–30), aktueller Kontext (Regime/Vol/Session/Projektion/HTF, 0–35+15), News-Catalyst (0–10) minus Event-Risk-Penalty (0–50). Output: Rank (A/B/C/D), Top-Family, Catalyst, Reason. 5 neue `ZONE_PRIORITY_*` Exports in der Generated Library. 26 Unit-Tests.
  - **B7: Signal Replay** Tab in `streamlit_terminal.py` — historische Signal-Timeline mit Aggregate-Metriken (Signals, Resolved, Hit Rate, Avg/Total P&L), Hit-Rate-Matrix nach Gap×RVOL Bucket, tägliche Signal-Timeline mit Expander pro Tag. 11 Unit-Tests.
  - **B6: Gehostetes Terminal** — `Dockerfile`, `docker-compose.yml`, `.dockerignore` für Self-Hosted-Deployment. Token-basierter Auth-Guard `terminal_auth.py` (`STREAMLIT_AUTH_TOKEN` env var), timing-safe Vergleich, Zero-Friction lokal. 10 Unit-Tests.
  - **C10: Explain-Modus** im `SMC_Dashboard.pine` — neuer "Explain" View-Modus mit ✅/❌ Checklist (9 Kriterien: Struktur, Zone, Qualität, Freshness, Session, Market, Event, HTF, Pressure). Zeigt Next Step und erklärt WARUM der aktuelle Zone-State gilt.
  - **Outcome Backfill Pipeline** (`open_prep/outcome_backfill.py`) — Post-Open-Job zum Auffüllen der bisher leeren `profitable_30m`/`pnl_30m_pct` Felder in Outcome-Dateien. Holt 1-min OHLCV-Bars von Databento für das [09:30–10:00 ET]-Fenster, berechnet 30-min P&L, aktualisiert Dateien atomar. CLI: `python -m open_prep.outcome_backfill [--date YYYY-MM-DD] [--lookback N] [--dry-run] [--feature-importance]`. Feature-Importance-Backfill schließt den Kalibrations-Feedback-Loop. 25 Unit-Tests.
  - **Strategiedokument** `docs/SYSTEM_REVIEW_AND_STRATEGY_2026_Q2.md` — vollständiges Systemreview mit Vergleichsmatrix, Designprinzipien und 10-Punkte-Umsetzungsplan (A1–C10).

### Changed (2026-04-09)

- **SMC / Databento / NewsAPI.ai stabilization wave:**
  - Added a Databento reference alias-cache and identifier-change risk layer across the SMC generator, Open Prep, terminal Databento helpers, and the v5 event-risk builder so recent corporate-action ticker changes are no longer invisible to enrichment and ranking.
  - Added NewsAPI.ai Event Registry feed-cursor persistence, provider-status export, and probe tooling so live/news fallback paths can resume incrementally and expose clearer diagnostics when the feed is reachable but has no new symbol-matching items.
  - Added deterministic live-news regression coverage plus verified review/runbook documentation for the recent SMC hardening work; see `docs/smc-databento-change-note-2026-04-09.md` for the compact technical summary of the published mainline range.

### Fixed (2026-04-08)

- **SMC deeper integration and micro-library hardening:**
  - Centralized lazy Open Prep runtime construction in `open_prep_boundary.py` and rewired the Databento, terminal, and bridge FMP consumers to use the shared boundary instead of importing `open_prep.macro.FMPClient` directly.
  - Extracted realtime A0/A1 promotion into `open_prep/rt_promotion.py` so the shared promotion logic no longer depends on Streamlit imports, and added regression coverage that locks the workflow and runtime-boundary rules in place.
  - Hardened Databento bundle base generation with a compatibility fallback from legacy `close` and `volume` columns when `day_close` or `day_volume` are absent in symbol-day features.
  - Fixed SMC news scoring so only actually mentioned universe tickers are exported, and hardened Pine CSV sharding so multi-part exports preserve comma boundaries instead of silently corrupting long strings.
  - Hardened TradingView exact-open verification so Pine declaration lines that carry a matching shorttitle no longer invalidate an otherwise correct `SMC Core` editor identity.
  - Reduced TradingView open-script trace noise by collapsing repeated missing-candidate diagnostics into per-step summaries, while keeping the existing alias-based script recovery intact.
  - Decoupled micro-library publish status from the downstream repo-core preflight gate so exact/idempotent library publishes are reported as `published` while the overall command still stays failed when repo-core validation is red.
  - This removes the oversized neutral-news export path that surfaced during live micro-library validation and restores a compile-clean TradingView library generation path without changing the checked-in seed artifacts.
  - The latest fully green SMC mainline evidence is `automation/tradingview/reports/preflight-2026-04-08T12-37-12-028Z.json`.

### Changed (2026-04-08)

- **SMC mainline settings hierarchy refresh:**
  - Reordered `SMC_Dashboard.pine` so the visible `Product Surface` controls open before the hidden BUS bindings, and relabeled the remaining binding and debug sections as explicit operator-only groups.
  - Reordered `SMC_Long_Strategy.pine` so `Execution Setup` and `Trade Plan` appear before the two `Expert Mapping` sections.
  - Reprioritized `SMC_Core_Engine.pine` settings into `Core Setup`, `Output`, `Trade Plan`, `Session Gate`, and `Runtime Budget`, with the remaining technical groups marked as `Advanced`.
  - Refreshed the operator guide, strategy guide, validation runbooks, and checklist so the active docs match the shipped TradingView settings surface.

- **SMC core first-run hero and overlay cut:**
  - Tightened the `SMC_Core_Engine.pine` Focus View hero copy so `Why now` and `Main risk` stay short and confidence remains tier-based instead of pseudo-precise.
  - Made `Core Trigger` and `Core Invalidation` explicitly depend on the actionable `Ready` / entry states rather than a broader visual-state threshold.
  - Suppressed standalone volume and strict-LTF warning labels plus default strong/weak swing overlays in Focus View so the hero stays the only primary first-run message.
  - Updated the focused TradingView UI and contract tests plus the manual validation docs to lock the compact-surface behavior in place.

- **SMC execution wrapper language cleanup:**
  - Reworded the visible `SMC_Long_Strategy.pine` setup and expert-mapping tooltips so the surface talks about linked core outputs and execution plans instead of raw BUS-contract internals.
  - Refreshed the execution guide and operator guide summary so the wrapper stays clearly operator-only without leaking unnecessary transport jargon into the visible setup path.

- **SMC execution surface copy cut:**
  - Renamed the four visible strategy controls to `Execution Stage`, `Minimum Quality Score`, `Take Profit (R)`, and `Use Take Profit` so the wrapper reads like execution setup instead of mixed setup/transport language.
  - Renamed the visible strategy chart outputs to `Execution Trigger`, `Execution Invalidation`, and `Execution Take Profit`, and aligned the strategy guide, validation docs, screen spec, and evidence manifest to the new execution-surface terminology.

- **SMC product-surface validation evidence contract:**
  - Added a canonical `validationEvidence` block to `scripts/smc_bus_manifest.py` and the checked-in TradingView product-cut artifact so the four required rendered chart captures are defined in one machine-readable contract.
  - Aligned the German and English manual validation runbooks plus report templates to the manifest-backed evidence pack and locked the editor-screenshot exclusion into docs/tests.

### Changed (2026-04-07)

- **SMC mainline surface implementation wave:**
  - Renamed the visible Core/Dashboard/Strategy controls to the new Lite, Companion, and Execution-surface language in `SMC_Core_Engine.pine`, `SMC_Dashboard.pine`, and `SMC_Long_Strategy.pine`.
  - Added actionable trigger and invalidation lines directly to the Core so `READY LONG` and `ENTER LONG` remain legible without switching to a second script.
  - Reordered the dashboard summary first fold around action, blocker reason, and risk plan, and replaced terse blocker copy with clearer trader-facing text.
  - Aligned the strategy guide, migration guide, and manual validation runbooks with the new `Lite Surface`, `Companion Summary`, and `Execution Stage` terminology.

- **SMC post-cut documentation cleanup:**
  - Clarified the post-cut cleanup guardrails in `docs/smc-lite-pro-product-cut.md` so the remaining follow-up items read as later architecture rules rather than open release blockers.
  - Added a UX-review-derived surface concept, concrete copy deltas, and a prioritized implementation backlog for the SMC Core, Dashboard, and Long Strategy mainline surfaces in `docs/smc-lite-pro-product-cut.md`.
  - Replaced the stale SkippALGO strategy guide with an SMC mainline wrapper guide in `docs/TRADINGVIEW_STRATEGY_GUIDE.md`.
  - Refreshed the German and English TradingView manual validation runbooks to reflect that the canonical `tv:preflight:smc-mainline` gate is reproducible from this workspace again.
  - Updated `docs/README.md` and the root `README.md` to point at the canonical SMC mainline gate and product-cut references.

### Changed (2026-04-06)

- **TradingView decision-first first-release closure:**
  - Finished the SMC decision-first surface work for `SMC_Core_Engine.pine` and `SMC_Dashboard.pine`, and aligned the released docs to the Core/Dashboard/Long Strategy scope.
  - Kept the shipped SkippALGO HUD work documented as a separate TradingView surface change, not as part of the SMC architecture scope.
  - Added a decision-first TradingView preflight config for `SMC_Core_Engine.pine`, `SMC_Dashboard.pine`, `SMC_Long_Strategy.pine`, and companion TradingView automation, plus npm wiring for repeatable release validation.
  - Marked the first-release ticketset and R1.1 migration guide as released and updated the README to reflect the corrected SMC scope.

### Changed (2026-04-06)

- **TradingView decision-first R1.1 hardening:**
  - Regrouped the `SMC_Dashboard.pine` Pro diagnostics surface into clearer operator-facing sections without changing the underlying BUS binding order or diagnostic row contracts.
  - Added explicit migration/operator guidance for the decision-first rollout, including safe-default expectations for `compact_mode`, `surface_mode`, and `surfaceMode` plus the operator-only BUS binding workflow for the dashboard companion script.
  - Kept the decision-first visual modes as presentation changes only; no additional engine gating is introduced by the new Lite/Pro defaults.

### Added — Pine Library Modularization (Task 3)

- **Five new Pine Script v6 libraries** (`pine/` folder) extracting shared logic
  from the SkippALGO family:
  - `skipp_math` — constants, clamping, probability/logit, percentile,
    statistics, array safety, scoring helpers (24 exports).
  - `skipp_scoring` — trend/regime detection, ensemble scoring, binning,
    quantile helpers, decision quality (20 exports).
  - `skipp_indicators` — zero-lag EMA variants, log regression oscillator
    (5 exports).
  - `skipp_calibration` — rolling accumulators, 3-way probability,
    calibration engine, eval stats (16 exports).
  - `skipp_labels` — label text truncation, capped label buffer (2 exports).

- **Consumer slimming** — 6 Pine scripts now delegate shared functions to the
  libraries via thin wrappers (`f_xxx(…) => lib.xxx(…)`):
  - `SkippALGO.pine`: ~50 functions delegated (4 545 → 4 178 lines, −367).
  - `QuickALGO.pine`: 50 functions delegated (4 908 → 4 709 lines, −199).
  - `SkippALGO_Strategy.pine`: 48 functions (4 839 → 4 642, −197).
  - `SkippALGO_Mid.pine`: 18 functions (2 930 → 2 847, −83).
  - `SkippALGO_Mid_Strategy.pine`: 18 functions (2 954 → 2 871, −83).
  - `SkippALGO_Mid_Indicator.pine`: 18 functions (2 948 → 2 865, −83).
  - **Total: ~1 012 duplicated lines removed** across consumers.

- **Bulk slimming script** `scripts/pine_slim.py` — automates import injection
  and function body→delegate replacement for future Pine library extraction.

- Functions with heavy global/UDT dependencies (TfState, input-bound
  parameters) intentionally kept inline to preserve semantic safety.

### Fixed (2026-03-25)

- **Historical Benzinga symbol-day export hardening:**
  - Fixed historical Benzinga news fetches in `newsstack_fmp/ingest_benzinga.py` to retry provider-rejected request shapes with date-only filters and an alternate symbol parameter fallback instead of failing immediately on HTTP 400.
  - Updated `scripts/databento_production_export.py` to use Benzinga-friendly day filters for historical company-news export requests while still enforcing the exact ET/UTC event windows locally after fetch.
  - Added focused regression coverage in `tests/test_benzinga_news_endpoints.py` and updated `tests/test_databento_production_export_news.py` to lock the new historical request shape.

- **SMC base session-minute coverage guard:**
  - Fixed `scripts/smc_microstructure_base_runtime.py` so Databento symbols explicitly reported as unresolved at runtime are excluded from the hard session-minute completeness check instead of causing false `incomplete symbol coverage` failures.
  - Added regression coverage in `tests/test_smc_microstructure_base_runtime.py` for runtime-unsupported symbols.

- **SMC base workbook Excel row-limit hardening:**
  - Fixed `scripts/smc_microstructure_base_runtime.py` workbook export to split oversized `base_snapshot` outputs across numbered sheets when row count exceeds Excel's per-sheet limit, preventing `This sheet is too large` failures during base scan exports.

- **Databento open-window second-detail duplicate handling:**
  - Fixed `databento_volatility_screener.py` duplicate symbol-second logging to distinguish expected multi-publisher `ohlcv-1s` shards from anomalous duplicate rows.
  - Expected venue-level shards are now consolidated into composite OHLCV with info-level logging, while same-publisher anomalies remain warning-level.
  - Added regression coverage in `tests/test_databento_volatility_screener.py` for both multi-publisher composite rows and true duplicate anomalies.

### Fixed (2026-03-24)

- **TradingView validation-layer storage-state hardening:**
  - Fixed portable `TV_STORAGE_STATE` reuse by exporting Playwright storage state with IndexedDB included, instead of relying on cookies and localStorage alone.
  - Fixed false chart-presence detection so generic script-name text and non-actionable editor containers no longer count as proof that a script is already on the chart.
  - Fixed settings-surface targeting to prefer actionable legend wrappers, preventing Dashboard and Strategy checks from landing on unrelated chart or volume settings.
  - Fixed Pine editor reuse under portable auth by auto-restoring TradingView's read-only historical-version state before attempting to write code.
  - Fixed staged target aggregation so any populated runtime/editor error forces `overall_preflight_ok = false` for that target.
  - The latest fully green portable-auth evidence is `automation/tradingview/reports/preflight-2026-03-24T09-10-25-787Z.json`.

### Fixed (2026-03-21)

- **SMC++ intrabar invalidation and watchlist-level consistency:**
  - Kept `Long Setup` and `Long Visual` sticky on `Invalidated` / `Fail` for the rest of the realtime bar after an intrabar invalidation, so the dashboard no longer drops back to a neutral-looking state after the alert already fired.
  - Aligned the long-dip watchlist alert level with the existing active-zone preference logic, so overlapping OB/FVG cases now point at the same preferred active zone used by the setup engine instead of always preferring OB.

### Changed (2026-03-21)

- **SMC++ documentation refresh:**
  - Updated the German dashboard guide to document sticky intrabar invalidation behavior in the dashboard and the watchlist alert-level alignment with active-zone preference.

### Fixed (2026-03-20)

- **SMC++ long-dip state, alert, and profile consistency:**
  - Fixed overlapping OB/FVG long-dip sequencing so strict reclaim history, arming, and invalidation now track the actual source object instead of the merged long-zone view.
  - Fixed armed-source invalidation to compare against the active zone for the armed source kind, preventing overlap cases from silently surviving on the wrong zone.
  - Fixed long-dip watchlist alerts to be generic again: the watchlist event now triggers only when the generic watchlist becomes active, not when OB/FVG source rotation happens inside an already active watchlist.
  - Fixed priority-mode dynamic lifecycle alerts so `Long Invalidated` can still fire on the same realtime bar after a weaker lifecycle alert was already sent earlier in that bar.
  - Fixed TradingView `alertcondition(...)` lifecycle presets and OB/FVG event presets to use per-bar latched event state, reducing missed intrabar transitions for close-safe users.
  - Fixed volume-quality signaling to distinguish current-bar volume loss from rolling feed degradation, and aligned dashboard messaging with that split.
  - Fixed lower-timeframe confirmation fallback handling by separating price availability from volume availability and by tightening when strict-entry fallback is allowed historically.
  - Fixed OB profile value-area construction to expand from the POC outward and hardened profile alignment against empty or zero-volume profiles.
  - Fixed active long-zone selection to prefer the better overlap candidate instead of relying on a first-match merge.
  - Fixed pivot HH/HL/LH/LL labels, FVG hide cleanup, and symbol-token matching for microstructure/profile overrides.

### Changed (2026-03-20)

- **SMC++ dashboard and workflow documentation:**
  - Documented that the Watchlist tier is a generic context stage, while strict sequencing, backing-zone tracking, and invalidation are source-specific to the active OB or FVG.
  - Documented the new microstructure display behavior where the dashboard shows both the primary profile and active modifiers that can tighten or relax long-dip filters.
  - Documented the degraded-data model for relative volume and lower-timeframe checks so users can see when the engine is operating with price-only or fallback-safe context.

### Fixed (2026-03-19)

- **SMC++ long-dip and object lifecycle hardening:**
  - Fixed swing OB break handling so older blocks are no longer skipped just because the newest tracked block was not broken yet.
  - Fixed bullish and bearish FVG maintenance loops so older filled gaps are still updated and migrated even when newer gaps remain open.
  - Fixed `update(FVG this)` so the close-vs-live fill mode is recalculated per gap instead of leaking through a static `var`, which could silently mis-handle later FVG fills.
  - Fixed OB/FVG reclaim detection so a reclaim can complete on a later bar after the initial zone touch, as long as it stays within the configured long signal window.
  - Fixed a follow-up reclaim regression so OB/FVG reclaims fire only once on the actual crossover bar instead of staying latched true across later bars above the reclaimed zone.
  - Replaced fixed-millisecond OB/FVG projection with exact event timestamps for time-based overlays and index-based drawing for chart-timeframe OB/FVG objects, removing weekend/holiday/DST drift.
  - Wired the existing OB/FVG garbage-collection cycle through the main indicator so insignificant objects can actually be cleaned up on schedule.
  - Fixed HTF FVG retention to respect `Keep filled` history settings instead of using a hardcoded history depth of `2`.
  - Stopped HTF FVG `request.security()` calls from running while the HTF overlay is hidden.
  - Tightened long setup expiry semantics so setups now expire exactly when they reach the configured bar limit.
  - Aligned long-dip preset alerts with the multi-bar setup model by using recent-zone context instead of requiring the current bar to still overlap the pullback zone.
  - De-spammed dynamic long-dip state alerts so watchlist, armed, early, clean, and entry presets now emit only on state transitions.
  - Restored the pre-break OB cutoff semantics for index-based rendering so broken order blocks no longer extend one bar too far to the right.
  - Removed leftover dead code from earlier alert/dashboard iterations, including unused compact trend text, unused HTF state locals, unused intrabar event counting, and unused legacy FVG plotting wrappers.
  - Removed redundant per-bar OB/FVG registry rebuilds from the dashboard count path and switched those counts to direct array sizes.
  - Hardened the premium/discount warning helper to reuse a single warning label instead of creating a new one every bar.
  - Added lower-timeframe guardrails that automatically disable `request.security_lower_tf()` sampling when the chart-to-LTF ratio or estimated intrabar array size exceeds configured safety thresholds.
  - Hardened volume-data quality checks so relative volume, OB profiles, and volume-driven confirmations degrade gracefully on symbols with missing or effectively empty volume.
  - Added optional intraday VWAP/session alignment as an extra long filter for users who want session-aware intraday confirmation.
  - Added a practical risk/exit overlay that exposes trigger, invalidation, ATR-buffered stop, and 1R/2R targets directly on the chart and dashboard.
  - Switched strict HTF trend confirmation to a confirmed-only `request.security()` pattern so live HTF bars can no longer repaint strict long-entry gating.
  - Fixed same-bar OB/FVG dip-and-reclaim detection so valid wick-through reclaim candles no longer get missed when the previous close was already back above the zone.
  - Restored newest-last ordering for broken OB and filled FVG event buffers, and aligned downstream alert level lookups with that ordering.
  - Fixed visible-range filtering to respect the effective rendered right edge of extended OB/FVG objects, including the OB break bar.
  - Aligned TradingView `alertcondition(...)` long-dip presets with the existing one-shot dynamic alerts by exposing the preset states as edge events.
  - Wired the volume-quality guard through the OB profile capture/alignment engine path, not only the profile rendering path.

- **SMC++ live alert and timeframe hardening:**
  - Fixed intrabar OB/FVG live alerts in `SMC++.pine` to prefer exact engine event buffers (`ob_broken_new_*`, `filled_fvgs_new_*`) before scanning active objects, preventing silent misses on the event bar.
  - Fixed FVG fill alert levels to report the correct newest filled gap level by using the engine's event ordering instead of `.last()`.
  - Hardened lower-timeframe and HTF-FVG timeframe validation for non-time-based charts by normalizing timeframe seconds and rejecting unsupported chart/HTF combinations explicitly.
  - Tightened HTF FVG validation so the selected HTF must again be strictly higher than the chart timeframe.
  - Upgraded realtime marker dedupe guards to `varip` so reclaim and long-state markers stay stable on open realtime bars.
  - Made OB/FVG engine execution explicit via hidden `Use OB engine` and `Use FVG engine` inputs, preserving the intended visual-only meaning of `Show` toggles while removing silent ambiguity.

### Added (2026-03-19)

- **SMC++ long-dip alert presets:**
  - Added seven reusable alert preset booleans in `SMC++.pine` for `Watchlist`, `Armed+`, `Early`, `Clean`, `Entry Best`, `Entry Strict`, and `Failed` long-dip states.
  - Added matching `alertcondition(...)` definitions so the presets are available directly in TradingView alerts.
  - Added matching `fire_dynamic_alert(...)` calls so dynamic alerts can emit the same long-dip lifecycle states with level context.
  - Added dedicated German and English documentation for the SMC++ dashboard and long-dip workflow under `docs/`.

### Changed (2026-03-19)

- **SMC++ dashboard layout tightened:**
  - Reworked the `SMC++.pine` dashboard to be narrower and taller by splitting wide aggregate rows into shorter stacked rows.
  - HTF trend, object counts, swing/internal levels, zone levels, and trigger levels now render as compact single-purpose rows instead of wide combined summaries.
  - Shortened dashboard labels and legend text so the panel uses vertical space more efficiently without removing state information.

### Added (2026-03-17)

- **Databento bullish-quality score presets:**
  - Added selectable Bullish-Quality weighting presets in `scripts/bullish_quality_config.py`:
    - `conservative`
    - `balanced` (default)
    - `aggressive`
  - The presets change how strongly market-structure signals influence `window_quality_score` without changing the export contract.
  - Added test coverage for preset resolution in `tests/test_generate_bullish_quality_scanner.py`.
  - Added Streamlit sidebar selection for the Bullish-Quality score profile in `databento_volatility_screener.py`.
  - Added production-export CLI support via `--bullish-score-profile` in `scripts/databento_production_export.py`.

### Changed (2026-03-17)

- **Databento structure-aware scanner ranking and documentation:**
  - Bullish-Quality remains structure-forward by default via the new `balanced` preset.
  - Added dedicated structure-feature documentation in `docs/DATABENTO_STRUCTURE_FEATURES.md`.
  - Extended `docs/RFC_BULLISH_QUALITY_PREMARKET_SCANNER.md` with structure-field and score-profile details.
  - Long-Dip and Bullish-Quality ranking now expose the new structure columns more clearly in the Streamlit UI.

### Added (2026-03-05)

- **USI-CHOCH early-entry upgrade (`USI-CHOCH.pine`):**
  - Added **Same-Bar Verify** for bullish CHoCH (`same-bar OR next-bar`), enabling earlier CHoCH confirmation.
  - Added **Early Signal Inputs** for anticipation and momentum pre-signals:
    - anticipation proximity (%),
    - momentum RSI/divergence window,
    - volume spike multiplier,
    - marker visibility toggles.
  - Added **Anticipation markers** (`A↑`/`A↓`) when price approaches swing levels under matching structure context.
  - Added **Momentum Pre-CHoCH markers** (`M↑`/`M↓`) using RSI divergence + volume spike conditions.
  - Added early-signal alertconditions:
    - `Anticipation Bullish/Bearish`,
    - `Momentum Pre-CHoCH Bullish/Bearish`.

### Changed (2026-03-05)

- **CHoCH fast-signal parity across scripts:**
  - The three “earlier BUY/CHoCH” improvements now exist in both `CHoCH.pine` and `USI-CHOCH.pine`:
    1. Same-Bar Verify,
    2. Anticipation,
    3. Momentum Pre-CHoCH.

### Changed (2026-03-04)

- **� RT Engine auto-start across all entry points:**
  - Added `ensure_rt_engine_running()` helper in `realtime_signals.py` — PID file management + pgrep fallback + `subprocess.Popen` background launch.
  - **streamlit_terminal.py**: Auto-starts RT engine on session init (skipped on Streamlit Cloud). Imports `RealtimeEngine` and `ensure_rt_engine_running`.
  - **streamlit_monitor.py**: Auto-starts RT engine on session init (skipped on Streamlit Cloud).
  - **vd_signals_live.sh**: Engine now auto-starts by default (previously required `--start-engine`). Added `--no-engine` flag to opt out.
  - **vd_watch.sh**: Auto-starts RT engine before rendering dashboard.
  - **vd_open_prep.sh**: Auto-starts RT engine before pipeline extraction.

- **🏆 Rankings tab enhanced with realtime signals (streamlit_terminal.py):**
  - Rankings composite score updated: **50% price move + 20% news + 15% RT technical + 15% RT signal tier**. Was 70/30 price/news.
  - New columns: **Signal** (A0/A1/A2), **Tech** (weighted indicator score), **RSI** (RSI-14 with color coding), **MACD** (signal direction).
  - Sort order now prioritizes RT signal tier (A0 > A1) within bullish/bearish tiers.
  - Loads full RT signal data from both VisiData JSONL and structured JSON, enriching each ranked symbol with technical scores, RSI, MACD, direction, and volume ratio from the RT engine.

- **�🔭 Realtime Signals — full universe monitoring (900+ symbols):**
  - Removed the fixed `top_n=15` watchlist limit. The engine now monitors **all scored symbols** from the pipeline run (typically 900+), not just the top-ranked candidates.
  - `_load_watchlist()` merges `ranked_v2` (top scored) + `filtered_out_v2` overflow entries (scored but below display cutoff) + `enriched_quotes` (remaining universe symbols) to build the full monitoring universe.
  - `DEFAULT_TOP_N` changed from `15` → `0` (meaning all). The `--top-n` CLI flag still works for backward compatibility (`--top-n 20` limits to 20).
  - `_enrich_watchlist_live()` now uses FMP bulk profile endpoint (`/stable/profile-bulk`) for avgVolume enrichment across 900+ symbols in a single call. Falls back to per-symbol profile calls (capped at 50) when bulk is unavailable.
  - `_fetch_realtime_quotes()` now chunks FMP batch-quote requests into groups of 500 symbols to avoid URL-length limits.
  - CLI help updated to reflect `0 = all` default.

- **🔧 Realtime Signals — TechnicalScorer integration (6 bug fixes):**
  - Added `TechnicalScorer` class integrating TradingView + FMP technical indicators (RSI, MACD, ADX, MA alignment) into signal detection.
  - Fixed CRITICAL bug: VisiData rows used undefined `existing` variable → `sym_signals` (NameError crash).
  - Fixed `_MIN_CALL_SPACING` 3.0 → 13.0s (must exceed TradingView's 12s rate limit).
  - Fixed RSI/tech A1→A0 upgrade bypassing dynamic cooldown anti-spam protection.
  - Fixed cache eviction to fall back to oldest-entries removal when TTL eviction alone doesn't shrink below max.
  - Fixed `_restore_signals_from_disk()` to include `technical_score`, `technical_signal`, `rsi`, `macd_signal` fields.
  - Fixed ADX scoring to be direction-neutral (amplifies existing bias instead of adding unconditional bullish tilt).

### Added (2026-03-02 – 2026-03-02)

- **📊 Actionable / Rankings / Segments tab enrichment:**

- **🧠 AI Insights consolidation & tab reorder:**
  - Removed the old "AI Insights" tab (was using basic TradingView-only context)
  - Renamed "FMP AI" → "AI Insights" (the multi-layer enriched version is now the default)
  - Deleted `terminal_tabs/tab_ai.py` (no longer needed)
  - Reordered tabs: AI Insights → Actionable → Segments → Rankings → Outlook → Live Feed → Bitcoin → Alerts → Data Table

- **📊 Actionable / Rankings / Segments tab enrichment:**
  - **Actionable tab** — now shows 6 new inline columns: `Price`, `Chg%`, `Social` (Finnhub), `Analyst` (FMP consensus + upside%), `NLP` (NewsAPI.ai), `P/E`, `Vol`. Includes column guide popover explaining each data source.
  - **Rankings tab** — added 4 new inline columns: `Tech` (TradingView signal), `Social`, `Analyst`, `P/E`. FMP batch quotes enrich price data when spike data is missing. Social sentiment and analyst forecasts use cached data or fetch fresh.
  - **Segments tab** — added GICS sector performance overlay (expandable metric cards at top). "Top Symbols per Segment" drill-down now shows `Price`, `Chg%`, `Tech`, `Social`, `Analyst`, `P/E` columns per ticker.
  - All three tabs gracefully fall back to cached data or empty columns when APIs are unavailable.

- **🧠 FMP AI multi-layer enrichment (8 new data sources):**
  - FMP AI context now includes **11 data layers** (up from 3) for dramatically richer LLM analysis:
    1. **FMP quotes** (price, change%, volume, P/E, EPS) — *existing*
    2. **FMP profiles** (sector, industry, beta) — *existing*
    3. **TradingView technicals** (RSI, MACD, Stoch, MAs) — *existing*
    4. **Economic calendar** — today's US macro events (GDP, CPI, FOMC, NFP) with estimates vs actuals from FMP
    5. **Sector performance** — 11 GICS sector % changes for rotation analysis from FMP
    6. **Social sentiment** — Reddit + Twitter mention counts and bullish/bearish scores from Finnhub
    7. **Analyst forecasts** — price targets, consensus ratings, EPS estimates, recent upgrades/downgrades from FMP
    8. **Benzinga analyst ratings** — institutional upgrades, downgrades, price target changes (last 7 days)
    9. **Benzinga earnings calendar** — upcoming/recent EPS and revenue estimates vs actuals (±7 days)
    10. **Insider trades** — recent executive buys/sells with transaction values from FMP
    11. **Congressional trades** — Senate + House member stock trades from FMP
  - Each data source has independent caching and graceful fallback if the API is unavailable.
  - UI metadata line now shows `🔗 N data layers` count alongside existing article/ticker/FMP metrics.
  - System prompt upgraded to instruct the LLM to cross-reference ALL available layers and identify disconnects (e.g. bullish news + bearish technicals, insider selling + analyst upgrades).
  - Context expander description updated to list all data sources.
  - `assemble_context()` expanded with 8 new optional keyword parameters — fully backward-compatible.

- **🏦 FMP AI tab (new):**
  - Mirrors the AI Insights tab UI — same 6 preset questions, custom question input, Generate/Regenerate/Clear buttons.
  - Fetches real-time FMP quotes (price, change%, volume, market cap, P/E, EPS) and company profiles (sector, industry, beta) for the top 12 tickers in the feed.
  - Sends FMP-enriched context to OpenAI GPT-4o with a finance-data-aware system prompt that cross-references news sentiment with actual price action.
  - Separate session state keys (`fmp_ai_*`), separate cache, separate save file (`fmp_ai_trade_ideas.txt`).
  - Auto-refresh pauses when FMP AI result is being reviewed (`fmp_ai_pause_auto_refresh`).
  - Requires both `FMP_API_KEY` and `OPENAI_API_KEY`.
  - New files: `terminal_fmp_insights.py` (backend), `terminal_tabs/tab_fmp_ai.py` (UI).
  - Tab count increased 9 → 10.

- **FMP technicals fallback provider:**
  - New `terminal_fmp_technicals.py` module — fetches RSI(14), MACD(12,26), Stochastic(14,3,3), Williams %R(14), ADX(14), SMA & EMA (10, 20, 50, 100, 200) from FMP REST API.
  - Computes Buy/Sell/Neutral signals using standard thresholds (RSI >70/< 30, MACD crossover, Stoch >80/<20, etc.).
  - Returns data in the same `TechnicalResult` format as TradingView — transparent to all callers.
  - 3-minute in-memory cache with thread-safe locking and auto-eviction.
  - FMP has 3,000 calls/min rate limit — no 429 risk.

### Fixed (2026-03-02 – 2026-03-02)

- **TradingView 429 spam — proper cooldown escalation (`51a84e6`):**
  - `_tv_register_success()` was resetting the consecutive 429 counter while a cooldown was still active, preventing escalation (120s → 240s → 480s). Now only resets when cooldown has fully expired.
  - Cooldown early-return in `fetch_technicals()` now caches its result so repeated calls during cooldown skip immediately.
  - Cooldown `RuntimeError`s from `_tv_throttle()` are now distinguished from actual TradingView 429 responses — they no longer re-register as new 429s, which was artificially escalating cooldown timers.
  - Cooldown-block log messages downgraded from WARNING to DEBUG to reduce noise.

- **AI Insights infinite spinner — 30s time budget (`d98aa25`):**
  - The AI tab was hanging at "Fetching technicals for 8 tickers…" because each TradingView call has a 12s minimum spacing (anti-429 throttle). 8 tickers × up to 3 exchanges × 12s = up to 288 seconds of blocking.
  - Added a 30-second time budget to the technicals fetch loop — breaks out early and uses whatever was collected.
  - Falls back to previously cached technicals from session state if the time budget expires before any fresh data is fetched.
  - Spinner now shows "≤30 s" hint so users know it won't hang indefinitely.

- **AI tabs blocked during TradingView cooldown (`bb61050`, `caf082d`):**
  - AI Insights and FMP AI tabs now check `_tv_is_cooling_down()` before the technicals fetch loop and skip entirely when TradingView is rate-limited.
  - Shows a visible caption with remaining cooldown time (e.g., "⏳ TradingView rate-limited — cooldown 120s remaining. Using cached technicals.").
  - Both tabs proceed straight to the LLM query with whatever data is available.
  - Technical Data expander widgets in `streamlit_terminal.py` and `_shared.py` also had redundant cooldown guards that were removed after fallback integration.

- **FMP as automatic TradingView fallback (`cbee41f`):**
  - `fetch_technicals()` cooldown path now calls `_fmp_fallback()` which imports `fetch_fmp_technicals` and converts its dict result to a `TechnicalResult`.
  - When TradingView is in 429 cooldown (120–900s), all callers transparently receive FMP-sourced technicals instead of error results.
  - FMP results are cached in the TradingView cache so subsequent calls return instantly.
  - Redundant widget-level cooldown guards removed from `streamlit_terminal.py` and `terminal_tabs/_shared.py` since `fetch_technicals()` now handles fallback internally.

- **Deprecated `use_container_width` warnings (`836e223`, `72385f0`):**
  - Replaced all 7 occurrences of `use_container_width=True` with `width='stretch'` across `streamlit_terminal.py` (3), `terminal_tabs/tab_ai.py` (3), and `terminal_tabs/tab_heatmap.py` (1).

- **Rankings tab empty during off-hours (`f592850`):**
  - Rankings tab was empty because it only sourced from `SpikeDetector.events` (empty outside market hours).
  - Added feed items as a fallback data source so Rankings populates whenever there is feed data.

- **Sector performance chart styling (`b32de5f`):**
  - Restored original vertical bar chart with red-yellow-green gradient (`#FF1744`, `#FFC107`, `#00C853`), dark background, and angled labels — matching the pre-refactor appearance.

### Changed (2026-03-02 – 2026-03-02)

- **API budget optimization (`fc477c6`):**
  - Removed 10 low-value tabs (~1,500 lines of UI code) to reduce API call volume and rendering overhead.
  - Poll interval changed from 5s → 10s during market hours.
  - Added 30-second periodic dedup reset to prevent feed staleness from accumulating duplicate filters.
  - Slowed Bitcoin-related TTLs to reduce FMP bandwidth consumption.
  - Refactored Rankings tab to use only feed + RT spike data (removed extra API calls).
  - Removed 7 orphaned cached functions that were no longer called after tab removal.
  - Added Sector Performance chart above the tab bar.
  - Created `docs/API_BUDGET_CALCULATIONS.md` with detailed FMP budget analysis (150 GB/30d bandwidth, 3,000 calls/min rate limit).

- **Feed staleness bypass fix (`6d9732e`):**
  - `notify_ingest()` now only fires when the feed actually grows, preventing false staleness resets.

### Added (2026-03-03)

- **Live technicals wired into AI Insights:**
  - `tab_ai.py` now fetches real TradingView technical analysis (RSI, MACD, ADX, oscillators, MAs) for the top 8 tickers by |news_score| on each AI query, using the 15m interval.
  - Previously `_cached_technicals` was referenced but never populated — LLM context only included news headlines. The LLM now receives technicals summaries alongside news, dramatically improving Trade Ideas and Market Pulse quality.
  - Results cached in `st.session_state["_cached_technicals"]` for reuse across tabs.

- **Tech badge column in dashboard tabs:**
  - Top Movers, Actionable, and Defense & Aerospace tabs now display a **Tech** column showing TradingView summary signals (🟢 Buy, 🔴 Sell, ⚪ Neutral, etc.) for each symbol.
  - Added `_get_tech_summary()` helper in `streamlit_terminal.py` reads cached technicals from session state.

- **🎯 Actionable tab (new — tab #4):**
  - Curated view of high-conviction trade setups ranked by composite news + technical score.
  - Includes Tech badge column and news score overlay.
  - Tab count increased 18 → 19.

- **Today Outlook in Outlook tab:**
  - Outlook tab now shows both **Today** and **Next-Trading-Day** outlooks side by side.
  - `compute_today_outlook()` function added to `terminal_poller.py` — uses shared `_compute_outlook_for_date()` core with the current trading day (returns "MARKET CLOSED" on non-trading days).
  - Tomorrow outlook refactored into shared core (`_compute_outlook_for_date()`) with backward-compatible aliases.

- **CHOCH-Indicator.pine alertcondition() calls:**
  - Added 4 `alertcondition()` calls — **Buy**, **Short**, **Exit** (close long), **Cover** (close short) — enabling TradingView "Create Alert" directly from the CHOCH indicator.

- **Leveraged ETF skip-list in terminal_forecast.py:**
  - Added `_NO_FUNDAMENTALS_SYMBOLS` set (~45 tickers: SOXL, TQQQ, UVXY, TSLL, etc.) to skip yfinance fundamental lookups that always 404.
  - Added 30-min negative-TTL cache (`_CACHE_NO_DATA_TTL_S`) to avoid re-fetching symbols with no data.
  - Silenced yfinance internal logger (set to CRITICAL) to stop noisy 404 ERRORs flooding the console.

### Fixed (2026-03-03)

- **Race condition in BackgroundPoller:** `wake_event.set()` now properly interrupts `stop_event.wait()` — replaced `stop_event.wait()` with `wake_event.wait()` inside the poll loop and checking `stop_event.is_set()` explicitly.
- **BackgroundPoller stop_and_join():** Added `stop_and_join()` method for clean thread shutdown in tests and session teardown; previous code called `stop_event.set()` but never joined the thread.
- **Feed stuck on exception:** Empty-poll counter now increments on exception paths too, preventing infinite exception loops that kept the poller alive without producing data.
- **Auto-prune oscillation:** Changed auto-prune `keep=250` → `keep=0` to fully clear the dedup gate and unblock fresh fetches instead of partially pruning.
- **SQLite corruption resilience:** `store_sqlite.py` now runs `PRAGMA quick_check` on init; if the database is corrupt, it auto-renames the file and creates a fresh database instead of crashing.
- **Movers KeyError guards:** Added `.get()` guards for Benzinga movers response fields (`symbol`, `change`, `price`) that could be missing, preventing uncaught KeyError crashes.
- **Feed staleness churn loop:** Feed lifecycle recovery now tracks `last_ingest_ts` (time of most recent successful ingest) with a configurable grace period, preventing the recovery loop from firing repeatedly when published timestamps are old but the feed is actually active.
- **AI Insights "Clear AI result" button:** Added `st.rerun()` after clearing session state so the UI immediately reflects the cleared state.
- **AI Insights preset button switching:** Added `st.rerun()` after preset button clicks (e.g., switching from "Market Pulse" to "Trade Ideas") to ensure the new question is processed immediately instead of requiring a second click.

### Changed (2026-03-03)

- **Technicals cache TTL reduced:** `terminal_technicals.py` `_CACHE_TTL_S` changed from 900s (15 min) → 180s (3 min) for fresher intraday data.
- **"News Score" column rename:** "Score" column in Movers tab renamed to "News Score" for clarity, avoiding confusion with technical/composite scores.
- **CHOCH-Base_Indikator.pine defaults aligned:** `ms_logic` default changed "Standard" → "SMC+Sweep", `ms_mode` default changed "Verify" → "Ping" to match strategy defaults.
- **SkippALGO_Strategy.pine cooldown sync:** Added `presetAutoCooldown` input and synchronized `cooldownTriggersEff`/`ModeEff`/`MinutesEff`/`BarsEff` to respect preset-driven cooldown overrides.
- **VWAP_Reclaim_Indicator.pine alert rename:** Alert titles renamed from "Long Entry / Exit Long / Short Entry / Exit Short" to "Buy / Exit / Short / Cover" for consistency with CHOCH and SkippALGO conventions.
- **Outlook tab refactored:** Renamed from "Tomorrow Outlook" to "Today & Next-Trading-Day Outlook", with `_compute_outlook_for_date()` shared core eliminating code duplication.
- **Outlook return keys normalized:** Generic keys (`target_date`, `earnings_count`, `high_impact_events`) with backward-compatible aliases for existing consumers.

### Fixed (2026-03-02)

- **Streamlit Cloud inotify crash:** Added `fileWatcherType = "none"` to `.streamlit/config.toml` to prevent `OSError: [Errno 24] inotify instance limit reached` on shared Linux hosts. Streamlit's default `watchdog`-based file watcher exhausted the low inotify limit, cascading to EMFILE errors on all network connections (Benzinga, FMP).
- **EMFILE resilience in `load_jsonl_feed`:** Catch `OSError` during JSONL file read so the app degrades gracefully (returns partial data) instead of crashing if file descriptors are exhausted.
- **Sidebar API key detection:** Re-reads `os.environ` directly instead of stale cached `TerminalConfig`, so keys added to `.env` after session start are detected.
- **Streamlit Cloud secrets bridge:** Added `_load_streamlit_secrets()` to both `streamlit_terminal.py` and `open_prep/streamlit_monitor.py` — copies `st.secrets` into `os.environ` for Cloud deployments where `.env` is gitignored.
- **RT Engine path resolution:** VD signals JSONL path now resolved as absolute (`PROJECT_ROOT`-relative) so CWD doesn't matter.

### Changed (2026-03-02)

- **Rebranding: "Real-Time News Intelligence Dashboard — AI supported":**
  - Replaced all "Bloomberg-style" / "News Terminal" branding references across README, docstrings, LLM system prompt, changelog, requirements.txt, and docs/BLOOMBERG_TERMINAL_PLAN.md.
  - Page title and main heading in `streamlit_terminal.py` updated.
  - Added AI Insights anchor link directly below the main heading.
  - Kept factual references to Bloomberg as a news source (source tier classification in playbook.py, FMP endpoint docs) — only product branding was neutralized.
- **Documentation refresh (README):**
  - Updated tab count from 17 → 18 (AI Insights tab added).
  - Updated module count from 14 → 16 (added `terminal_ai_insights.py` and `terminal_tabs/`).
  - Rewrote Tabs Overview table with current tab order (AI Insights #2, Bitcoin #5, Outlook replaces Tomorrow Outlook).
  - Updated architecture diagram with `terminal_ai_insights` and `terminal_tabs/` directory.
  - Updated test count 1 674 → 1 681.
  - Updated Streamlit config section with `fileWatcherType = "none"` and local override instructions.
  - Updated project structure tree with `terminal_ai_insights.py` and `terminal_tabs/` directory.

### Changed (2026-03-01)

- **Documentation refresh (README):**
  - Added a dedicated **Live Feed Score Badge Semantics** section describing sentiment-aware color mapping, thresholds (`0.80` / `0.50`), directional prefixes (`+`, `−`, `n`), and WIIM (`🔍`) marker meaning.
  - Expanded **Open-Prep Streamlit Monitor** docs with operational behavior details: minimum auto-refresh floor, rate-limit cooldown handling, cache-vs-live fetch strategy, stale-cache auto-recovery, stage-progress status panel, UTC/Berlin timestamp display, and extended-hours Benzinga quote overlay behavior.
  - Added **Open-Prep Realtime Engine operations quickstart** (start/verify/restart) and clarified that RT engine is a separate long-running process from Streamlit.
  - Added explicit product positioning language (**Research & Monitoring Terminal**, **News Intelligence + Alerting**, **Workflow/Decision Support**) and clear compliance disclaimers (no personalized recommendations, no order execution).
- **Ops runbook refresh (`docs/OPEN_PREP_OPS_QUICK_REFERENCE.md`):**
  - Updated document date to `01.03.2026`.
  - Added copy/paste sections for RT engine **Start / Verify / Restart** including process and artifact freshness checks.
  - Added the same positioning/compliance framing to align operations documentation with README messaging.

### Changed (2026-02-28)

- **README.md rewritten:** Comprehensive GitHub-ready documentation covering Real-Time News Intelligence Dashboard (17-tab architecture, module map, data sources, configuration, background poller, notifications, export), Open-Prep Pipeline (Streamlit monitor, macro explainability), Pine Script (Outlook/Forecast, signal modes, key features), and Developer Guide (tests, linting, project structure, documentation index).

### Removed (2026-02-28)

- **Dead code removal (~680 lines across 6 files):**
  - `terminal_poller.py`: Removed 21 unused fetch functions — `fetch_treasury_rates`, `fetch_house_trading`, `fetch_congress_trading`, 15× `fetch_finnhub_*` (insider sentiment, peers, market status, FDA calendar, lobbying, USA spending, patents, social sentiment, pattern recognition, support/resistance, aggregate indicators, supply chain, earnings quality, news sentiment, ESG), 3× `fetch_alpaca_*` (news, most active, top movers). File reduced from ~1 865 to ~1 329 lines.
  - `terminal_newsapi.py`: Removed `concept_type_icon` (unused icon mapper) and `fetch_market_articles` (unreferenced ad-hoc article query wrapper).
  - `newsstack_fmp/scoring.py`: Removed `headline_jaccard`, `_headline_tokens`, `_TOKEN_RX`, `_STOP_WORDS` (unused Jaccard-similarity helpers).
  - `open_prep/realtime_signals.py`: Removed `get_a0_signals` and `get_a1_signals` (unused filter methods).
  - `open_prep/streamlit_monitor.py`: Removed `_cached_ind_perf_op`, `_cached_bz_profile_op`, `_cached_bz_detail_op` (uncalled cached wrappers) and their dead imports (`_fetch_ind_perf`, `_fetch_bz_profile`, `_fetch_bz_detail`).
  - `newsstack_fmp/ingest_benzinga_financial.py`: Removed `_extract_dict` (unused extraction method).

### Fixed (2026-02-28)

- **Race condition** in `terminal_notifications.py`: `_last_notified` dict now protected by `threading.Lock()` to prevent concurrent access from background poller and main Streamlit thread.
- **API key leak** in `terminal_bitcoin.py` and `terminal_newsapi.py`: `httpx` exception strings containing full URLs with `apikey=` parameters are now sanitized via `_APIKEY_RE` regex before logging.
- **Silent exception swallowers** in `streamlit_terminal.py`: Added `logger.warning()` to 3 bare `except` handlers (alert rules JSON load, extended-hours quotes, BG extended-hours quotes).
- **SSRF vulnerability** in `streamlit_terminal.py`: Webhook URL input now validated with `_is_safe_webhook_url()` — blocks private IP ranges (127.x, 10.x, 172.16-31.x, 192.168.x, 169.254.x, localhost, 0.0.0.0) and requires http/https scheme.
- **State desync** in `streamlit_terminal.py`: Feed lifecycle cursor reset now propagates to background poller session state, preventing cursor drift after auto-recovery.
- **Unbounded memory** in `terminal_spike_detector.py`: Stale symbols in `_price_buf` and `_last_spike_ts` are now pruned every 100 polls when newest snapshot exceeds `max_event_age_s`.
- **Narrow exception** in `newsstack_fmp/ingest_benzinga.py`: WebSocket JSON parse now catches `(json.JSONDecodeError, ValueError)` instead of bare `Exception`.
- **Pre-existing test failure** in `tests/test_production_gatekeeper.py`: `test_valid_quote_produces_signal` now patches `_is_within_market_hours` and `_expected_cumulative_volume_fraction` to pass regardless of time-of-day.

### Added (2026-02-28)

- **Finnhub + Alpaca Multi-Provider Integration (Phase 1–3):**
  - **`FinnhubClient`** in `open_prep/macro.py` — 15 methods across 3 tiers:
    - Phase 1 FREE (8 endpoints): `get_insider_sentiment` (MSPR score), `get_peers`, `get_market_status`, `get_market_holiday`, `get_fda_calendar`, `get_lobbying`, `get_usa_spending`, `get_patents`
    - Phase 2 PREMIUM (8 endpoints): `get_social_sentiment` (Reddit+Twitter), `get_pattern_recognition`, `get_support_resistance`, `get_aggregate_indicators`, `get_supply_chain`, `get_earnings_quality`, `get_news_sentiment`, `get_esg`
    - Auth via `FINNHUB_API_KEY` env var, 30 req/s free tier
  - **`AlpacaClient`** in `open_prep/macro.py` — 4 methods:
    - `get_news` (real-time news with sentiment), `get_most_active` (screener), `get_top_movers` (gainers/losers), `get_option_chain`
    - Auth via `APCA_API_KEY_ID` + `APCA_API_SECRET_KEY` headers

- **Pipeline expansion (`open_prep/run_open_prep.py`):**
  - `TOTAL_STAGES` 15 → 17 (2 new Finnhub stages)
  - Stage 12: Finnhub Insider Sentiment + Company Peers + FDA Calendar
  - Stage 13: Finnhub Social Sentiment + Pattern Recognition (PREMIUM)
  - 4 new pipeline helpers: `_fetch_finnhub_insider_sentiment`, `_fetch_finnhub_peers`, `_fetch_finnhub_social_sentiment`, `_fetch_finnhub_patterns`
  - Enriched quotes with: `fh_mspr_avg`, `fh_insider_sentiment_emoji`, `fh_peers`, `fh_social_score`, `fh_social_mentions`, `fh_pattern_label`, `fh_tech_signal`, `fh_support_levels`, `fh_resistance_levels`

- **Streamlit dashboard (`streamlit_terminal.py`) — 5 new tabs (16 → 21 total):**
  - 🧠 Insider Sentiment — Finnhub MSPR scores with color-coded emojis + company peers
  - 📡 Social Sentiment — Reddit/Twitter mention counts and sentiment scores
  - 📐 Patterns & S/R — Chart pattern recognition + support/resistance levels + composite tech signals
  - 💊 FDA Calendar — Upcoming FDA advisory committee meetings
  - 🗞️ Alpaca News — Real-time news feed + Most Active screener + Top Movers (sub-tabs)
  - 14 new `@st.cache_data` cached functions (11 Finnhub + 3 Alpaca)

- **Fetch functions (`terminal_poller.py`) — 18 new functions:**
  - 7 Finnhub FREE: `fetch_finnhub_insider_sentiment`, `fetch_finnhub_peers`, `fetch_finnhub_market_status`, `fetch_finnhub_fda_calendar`, `fetch_finnhub_lobbying`, `fetch_finnhub_usa_spending`, `fetch_finnhub_patents`
  - 8 Finnhub PREMIUM: `fetch_finnhub_social_sentiment`, `fetch_finnhub_pattern_recognition`, `fetch_finnhub_support_resistance`, `fetch_finnhub_aggregate_indicators`, `fetch_finnhub_supply_chain`, `fetch_finnhub_earnings_quality`, `fetch_finnhub_news_sentiment`, `fetch_finnhub_esg`
  - 3 Alpaca: `fetch_alpaca_news`, `fetch_alpaca_most_active`, `fetch_alpaca_top_movers`

- **VisiData export (`terminal_export.py`) — 6 new columns:**
  - `insider_mspr` (MSPR avg score), `insider_sent` (emoji), `social_score` (composite), `social_emoji`, `pattern` (detected chart pattern), `tech_signal` (composite buy/sell/neutral)

- **Provider comparison report (`docs/ANBIETER_VERGLEICH_Finnhub_TwelveData_Alpaca.md`):**
  - Comprehensive German-language analysis of Finnhub, Twelve Data, and Alpaca APIs
  - Gap analysis against existing FMP + Benzinga coverage
  - Integration roadmap with effort estimates

### Fixed (2026-02-28)

- **Markdown lint (MD060)** in `docs/FMP_ENDPOINT_GAP_ANALYSE.md`: Fixed all table separator spacing
- **Markdown lint (MD060 + MD051)** in `docs/ANBIETER_VERGLEICH_Finnhub_TwelveData_Alpaca.md`: Fixed table separators and link fragment anchors

### Added (2026-02-27)

- **Auto-recovery mechanism (data freshness self-healing):**
  - **Terminal (`streamlit_terminal.py` + `terminal_feed_lifecycle.py`):** When news feed is >30 min stale during market hours (04:00–20:00 ET), automatically resets API cursor + prunes SQLite dedup to force a fresh poll. 5 min cooldown between attempts. Manual "Reset Cursor" sidebar button as escape hatch. Sidebar shows feed age, cursor age, empty poll count.
  - **Open Prep Streamlit (`open_prep/streamlit_monitor.py`):** When cached pipeline data is >5 min old during market hours, automatically invalidates cache and forces a fresh pipeline run (~68s). 5 min cooldown between attempts. Sidebar shows recovery counter. `_STALE_CACHE_MAX_AGE_MIN = 5`.
  - **VisiData signals (`scripts/vd_signals_live.sh`):** When signal file is >5 min old and engine process is not running, auto-starts `open_prep.realtime_signals` in the background.
  - **VisiData open-prep watch mode (`scripts/vd_open_prep.sh`):** Tracks consecutive pipeline failures; after 3 failures, re-sources `.env` (catches rotated keys) and waits 60s before retrying.
  - **Background poller (`terminal_background_poller.py`):** Same hardened prune + cursor reset pattern as terminal — each prune call independent, cursor reset always executes even if prune fails.

- **Staleness thresholds (all surfaces):**

  | Surface | What is checked | Threshold | Action |
  | --- | --- | --- | --- |
  | Terminal feed | Newest article age | 5 min | Cursor reset + dedup prune |
  | Open Prep cache | Pipeline cache age | 5 min | Cache invalidate + fresh pipeline |
  | RT signals (Streamlit) | Signal file mtime | 5 min | Orange warning banner |
  | VD signals launcher | Signal file mtime | 5 min | Auto-start engine |
  | VD open-prep launcher | JSON file mtime | 5 min | Console warning |
  | Sector performance cache | `@st.cache_data` TTL | 60s (was 300s) | Auto-evict |

- **Hardened failure handling (auto-recovery never crashes):**
  - Each `prune_seen` / `prune_clusters` call has its own try/except — one failing doesn't block the other.
  - Cursor reset moved outside try blocks — the primary recovery action always executes even when SQLite prune fails.
  - `manage()` call site wrapped in try/except — lifecycle errors can never crash the Streamlit page.
  - Individual prune error logging (`prune(seen)` vs `prune(clusters)`) for debugging.

- **Benzinga delayed-quote overlay (extended-hours freshness):**
  - Integrated `fetch_benzinga_delayed_quotes()` into terminal spike scanner, VisiData snapshot, open_prep Streamlit monitor, and all stale FMP price displays.
  - During pre-market/after-hours, `bz_price`/`bz_chg_pct` columns overlay fresher Benzinga quotes on top of stale FMP close data.
  - Market-session aware: `market_session()` in `terminal_spike_scanner.py` detects pre-market, regular, after-hours, and closed states.
  - `SESSION_ICONS` extracted as canonical dict in `terminal_spike_scanner.py`, imported by both Streamlit apps.
  - Rankings tab in `streamlit_terminal.py` accepts `bz_quotes` param with RT > BZ > None price source priority.

- **Benzinga calendar, movers & quotes adapters:**
  - `BenzingaCalendarAdapter` in `newsstack_fmp/ingest_benzinga_calendar.py` with typed fetchers (ratings, earnings, economics, conference calls).
  - `fetch_benzinga_movers()` and `fetch_benzinga_delayed_quotes()` via REST endpoints.
  - WIIM article boost in `_classify_item()` for "Why Is It Moving" actionability.
  - 79 tests in `tests/test_benzinga_calendar.py`.

- **Benzinga full API coverage (news + calendar + financial endpoints):**
  - **News endpoints (3 new):** `fetch_benzinga_top_news()` (curated top stories), `fetch_benzinga_channels()` (available channel list), `fetch_benzinga_quantified_news()` (sentiment-scored articles with entity scores) — all added to `newsstack_fmp/ingest_benzinga.py`.
  - **Calendar endpoints (5 new):** `fetch_dividends()`, `fetch_splits()`, `fetch_ipos()`, `fetch_guidance()`, `fetch_retail()` — all added to `BenzingaCalendarAdapter` in `newsstack_fmp/ingest_benzinga_calendar.py`.
  - **Financial Data adapter (20+ methods, new file):** `BenzingaFinancialAdapter` in `newsstack_fmp/ingest_benzinga_financial.py` covering fundamentals, financials, valuation ratios, company profiles, price history, charts, auto-complete, security/instruments lookup, logos, ticker detail, options activity. Eight standalone wrapper functions exported.
  - **Channels & topics filtering:** `channels` and `topics` query parameters wired into REST adapter, WebSocket adapter, `Config`, and `terminal_poller.py`. New env var `TERMINAL_TOPICS`.
  - 103 new tests across 4 files: `test_benzinga_news_endpoints.py` (18), `test_benzinga_financial.py` (44), `test_benzinga_calendar_extended.py` (17), `test_vd_bz_enrichment.py` (24).

- **Benzinga Intelligence — Streamlit Terminal (expanded):**
  - Expanded Benzinga Intel tab from 3 to 11 sub-tabs: Ratings, Earnings, Economics, **Dividends**, **Splits**, **IPOs**, **Guidance**, **Retail**, **Top News**, **Quantified News**, **Options Flow**.
  - All new sub-tabs use `@st.cache_data(ttl=120)` wrappers and graceful error handling.

- **Benzinga Intelligence — Open Prep Streamlit:**
  - New "📊 Benzinga Intelligence" section in `open_prep/streamlit_monitor.py` with 8 tabs: Dividends, Splits, IPOs, Guidance, Retail Sentiment, Top News, Quantified News, Options Flow.
  - 10 cached wrapper functions with `@st.cache_data(ttl=120)` TTLs.
  - All imports guarded by `try/except ImportError` for Streamlit Cloud compatibility.

- **VisiData Benzinga enrichment:**
  - `build_vd_snapshot()` and `save_vd_snapshot()` accept `bz_dividends`, `bz_guidance`, `bz_options` parameters.
  - Per-ticker enrichment columns: `div_exdate`, `div_yield` (from dividends), `guid_eps` (from guidance), `options_flow` (from options activity).
  - New `build_vd_bz_calendar()` and `save_vd_bz_calendar()` functions produce a standalone Benzinga Calendar JSONL file with dividends, splits, IPOs, and guidance events.
  - Default export path: `artifacts/vd_bz_calendar.jsonl`.

- **Terminal UI improvements:**
  - Data table headlines are now clickable links to source articles (`LinkColumn`).
  - Ring-buffer eviction replaces queue drop-on-full (maxsize 100 → 500).
  - Optional import guard for `ingest_benzinga_calendar` on Streamlit Cloud.

### Fixed (2026-02-27)

- **Production readiness hardening (3 review cycles, 12 bugs fixed):**
  - **Review #1:** P0 falsy `or` in dict lookup, P1 `bq.get("last", 0)` default, P1 unconditional API calls in non-extended sessions, P2 inner import, P2 source concatenation, P2 duplicate dicts.
  - **Review #2:** P1 cache key thrashing from non-deterministic set iteration → `sorted()`, P2 6× `market_session()` per render → consolidated to single `_current_session`, P1 `_get_bz_quotes_for_symbols` in open_prep had no caching → added `@st.cache_data(ttl=60)` wrapper, P2 unused `timezone` import.
  - **Review #3:** P2 spike symbols not sorted before `join()` for cache key, P2 BZ overlay ran after `_reorder_ranked_columns` so bz columns appeared at tail.
  - **Refactoring:** DRY `SESSION_ICONS` extraction, symbol extraction `g.get("symbol") or g.get("ticker", "")` pattern, loop var rename `l` → `loser`.

- **Pylance/Pyright lint cleanup (0 workspace errors):**
  - Wrapped `json.load`, `getattr`, `round/max/min`, `st.session_state` returns with explicit casts (`float()`, `str()`, `list()`, `# type: ignore[no-any-return]`).
  - Added `# type: ignore[assignment]` for optional import `None` sentinel assignments.
  - Renamed loop var `q` → `quote` in `terminal_spike_scanner.py` to avoid type-narrowing shadow.
  - Imported `ClassifiedItem` at module level + `dict[str, Any]` annotation on defaults in tests.
  - Fixed `Generator` return type for yield fixtures in `tests/test_benzinga_calendar.py`.
  - Used `callable()` check instead of truthiness for `_market_session` function.

### Verification (2026-02-28)

- Full regression suite: **1 674 passed, 34 subtests passed, 0 failures**.
- Pylance/Pyright: **0 workspace errors**.
- Dead code removed: **~680 lines across 6 files** (31 functions).

### Verification (2026-02-27)

- Full regression suite: **1599 passed, 34 subtests passed**.
- Pylance/Pyright: **0 workspace errors** (only external `~/.visidatarc` stub, suppressed).
- Lint (`ruff`): clean.

### Added (2026-02-26)

- **Python quality/documentation baseline (repo-level):**
  - Added centralized `pyproject.toml` configuration for `pytest`, `ruff`, `mypy`, and coverage reporting.
  - Added focused coverage expansion in `tests/test_coverage_gaps.py` for Python runtime modules (`terminal_poller`, `terminal_export`, `newsstack_fmp` adapters/pipeline/store).
  - Improved top-level README developer guidance for reproducible quality checks.

- **VWAP Reclaim expansion (Long/Short/Both):**
  - Added new bidirectional scripts:
    - `VWAP_Reclaim_Indicator.pine`
    - `VWAP_Reclaim_Strategy.pine`
  - Added `Trade Direction` toggle (`Long` / `Short` / `Both`) with mirrored short state machine (`Reclaim → Retest → Go`) and dedicated short entry/exit labeling.
  - Added short-side trend gating parity (`matchedTrendsFilter_short`) and USI bear-stack gate parity in bidirectional variants.

- **Signal filter controls (all VWAP reclaim variants):**
  - Added grouped `🔒 Signal Filters` controls:
    - `Bar Close Only`
    - `Volume Filter`
    - `Min Volume Ratio`
    - `Volume SMA Length`
  - Integrated `barCloseGate` + `volGate` into signal generation and visualization flow.

- **News Intelligence Dashboard integration (workspace):**
  - Added terminal pipeline/runtime modules:
    - `terminal_poller.py`
    - `terminal_export.py`
    - `streamlit_terminal.py`
  - Added coverage in `tests/test_terminal.py` and planning doc `docs/BLOOMBERG_TERMINAL_PLAN.md`.

### Fixed (2026-02-26)

- **VWAP reclaim reliability hardening (indicator/strategy parity):**
  - ATR bootstrap safety: `atr = nz(ta.atr(14), syminfo.mintick * 10)` to avoid early-bar `na` tolerance propagation.
  - Anchor reset hardening: reclaim/position state now resets fully on `isNewPeriod` (including reclaim bar markers), preventing stale sequence carry-over.
  - Strategy reset parity: bidirectional strategy closes all active exposure with unified `strategy.position_size != 0` guard on period reset.
  - Bidirectional strategy concurrency: `pyramiding=2` to allow intended simultaneous long+short behavior in `Both` mode.
  - Long-stop safety: `nz(retestLow, vwapValue)` guard prevents `na` stop propagation in long-only strategy.
  - Debug marker stability: reclaim/retest debug markers now respect `barCloseGate`.
  - UX semantics: long-only USI status now uses `FLAT` (gray) instead of `BEAR` when no bull stack is present.

### Verification (2026-02-26)

- Full regression suite (local): **1028 passed, 34 subtests passed**.

### Verification (2026-02-26, later run)

- Full regression suite (local): **1116 passed, 34 subtests passed**.
- Linting (`ruff`): **All checks passed**.
- Type-checking (`mypy`): **Success, no issues found**.
- Core Python coverage (`newsstack_fmp`, `terminal_poller`, `terminal_export`): **83%**.

### Added (2026-02-25)

- **Open-Prep Streamlit v2: auto-promotion for realtime A0/A1 signals:**
  - Added deterministic promotion logic in `open_prep/streamlit_monitor.py` to lift symbols from
    `filtered_out_v2` into `ranked_v2` when all of the following are true:
    - active realtime level is `A0` or `A1`,
    - symbol is **not** already ranked,
    - pipeline reason is exactly `below_top_n_cutoff`.
  - Promoted rows are flagged with `rt_promoted=true` and include realtime context
    (`rt_level`, `rt_direction`, `rt_pattern`, `rt_change_pct`, `rt_volume_ratio`).
  - Streamlit UI now renders a dedicated **🔥 RT-PROMOTED** block above the normal v2 tiers.
  - Promoted symbols are removed from `filtered_out_v2` display to avoid duplicate listing.
  - Cross-reference panel now reuses preloaded realtime A0/A1 data and excludes already-promoted symbols,
    so “missing from v2” only reflects hard-filtered or non-universe cases.

- **New unit test coverage for promotion behavior:**
  - Added `tests/test_rt_promotion.py` with coverage for:
    - below-cutoff promotion (A0/A1),
    - hard-filter exclusion,
    - no-duplication for already-ranked symbols,
    - case-insensitive symbol matching,
    - fallback semantics for promoted price fields,
    - multi-symbol and no-op edge cases.

### Verification (2026-02-25)

- Targeted suite: **13 passed** (`tests/test_rt_promotion.py`).
- Full regression suite: **985 passed, 34 subtests passed**.

### Added (2026-02-21)

- **Indicator/Strategy parity hardening finalized:**
  - Synced `EXIT` timing state in Strategy with Indicator (`enTime := time`).
  - Kept same-bar reversal/entry gate mapping aligned (`COVER→BUY`, `EXIT→SHORT`) with strict anti-same-direction guard.
  - Added/updated regression coverage to lock parity behavior in:
    - `tests/test_skippalgo_pine.py`
    - `tests/test_skippalgo_strategy_pine.py`
    - `tests/test_behavioral.py`
    - `tests/pine_sim.py`

- **REV JSON alert-action parity in Strategy:**
  - Consolidated runtime `alert()` path in `SkippALGO_Strategy.pine` now maps first signal label like Indicator:
    - `BUY`/`REV-BUY` → `buy`
    - `SHORT`/`REV-SHORT` → `sell`
    - `EXIT`/`COVER` → `exit`
  - Prevents action misclassification when reversal labels are emitted.

- **Open-prep robustness and data-output refresh:**
  - Strengthened macro/news processing paths and updated report artifacts in `reports/`.

### Verification (2026-02-21)

- Pine-focused parity suites: **193 passed, 8 subtests passed**.
- Full regression suite: **551 passed, 32 subtests passed**.

### Added (2026-02-20)

- **VWT integration (Volume Weighted Trend) in Indicator + Strategy:**
  - Added configurable VWT filter inputs in both scripts:
    - `useVwtTrendFilter`
    - `vwtPreset` (`Auto`, `Default`, `Fast Response`, `Smooth Trend`, `Custom`)
    - `vwtLengthInput`, `vwtAtrMultInput`
    - `vwtReversalOnly`, `vwtReversalWindowBars`
    - `showVwtTrendBackground`, `vwtBgTransparency`
  - Added effective Auto mapping (`vwtPresetEff`, `vwtReversalWindowEff`) based on `entryPreset`.
  - Added VWT runtime state and entry guards:
    - `vwtTrendDirection`, `vwtTurnedBull/Bear`, `vwtBullRecent/BearRecent`
    - `vwtLongEntryOk` / `vwtShortEntryOk`
  - Wired VWT gates into all entry paths:
    - engine gates (`gateLongNow`, `gateShortNow`),
    - reversal globals (`revBuyGlobal`, `revShortGlobal`),
    - score entries (`scoreBuy`, `scoreShort`).

- **Optional VWT trend background overlay (Indicator + Strategy):**
  - Added regime-based background coloring for bullish/bearish VWT trend state.

- **New regression tests for VWT feature:**
  - `tests/test_skippalgo_pine.py`
    - `test_vwt_inputs_exist`
    - `test_vwt_gating_wired_into_all_entry_paths`
  - `tests/test_skippalgo_strategy_pine.py`
    - `test_vwt_inputs_exist`
    - `test_vwt_gating_wired_into_all_entry_paths`

### Verification (2026-02-20)

- Full test run completed locally:
  - **478 passed, 16 subtests passed, 0 failed**.

### Added

- **ChoCH fast-mode parity in Strategy (v6.3.13 line):**
  - Added Strategy-side ChoCH runtime controls to match Indicator behavior:
    - `ChoCH signal mode` (`Ping (Fast)`, `Verify (Safer)`, `Ping+Verify`),
    - `Show ChoCH Ping markers`.
  - Added Strategy ChoCH presets:
    - `ChoCH Scalp Fast preset` (forces `Wick` + `Ping (Fast)` + effective `swingR=max(swingR,1)`),
    - `ChoCH Fast+Safer preset` (forces `Wick` + `Ping+Verify` + effective `swingR=max(swingR,1)`).
  - Strategy eval HUD now appends active ChoCH runtime configuration (`preset/mode/source/R`) for on-chart verification.

- **Runtime Success-Rate HUD + Eval mode guidance (indicator + strategy):**
  - Added a lightweight last-bar chart label showing live evaluation success rate and sample count:
    - `Success rate (History+Live): xx% (N=yy)` or
    - `Success rate (LiveOnly): xx% (N=yy)`
  - Added explicit `Evaluation mode` tooltip guidance with practical examples:
    - `History+Live` shows immediate populated values from confirmed history,
    - `LiveOnly` starts at `0% (N=0)` on historical bars and grows only in realtime.

- **Configurable BUY re-entry timing after COVER (indicator + strategy):**
  - Added `allowSameBarBuyAfterCover` (default `false`) to both scripts.
  - `false` keeps legacy one-bar delay after a `COVER` before the next `BUY`.
  - `true` allows immediate same-bar `COVER → BUY` re-entry.

- **Configurable SHORT re-entry timing after EXIT (strategy):**
  - Added `allowSameBarShortAfterExit` (default `false`) to strategy.
  - `false` keeps legacy one-bar delay after an `EXIT` before the next `SHORT`.
  - `true` allows immediate same-bar `EXIT → SHORT` re-entry.

- **Same-bar reversal mapping correction (indicator + strategy):**
  - Corrected cross-directional pairing to match runtime exit semantics:
    - `BUY` same-bar control is now `COVER → BUY` (`allowSameBarBuyAfterCover`),
    - `SHORT` same-bar control is now `EXIT → SHORT` (`allowSameBarShortAfterExit`).
  - Rewired phase-2 guards accordingly (`didCover` for BUY, `didExit` for SHORT).
  - Added regression tests to lock this mapping and prevent future inversion.

- **USI Length 5 lower-bound update (indicator + strategy):**
  - `Length 5 (fastest / Red)` now supports `minval=1` (previously `2`) in both scripts.
  - This allows a more aggressive fast-line configuration for USI Quantum Pulse tuning.

- **USI Aggressive Entry Mode guidance (indicator + strategy):**
  - Compact fast-scalping preset recommendation:
    - `USI Aggressive: same-bar verify = ON`
    - `USI Aggressive: verify 1-of-3 = ON`
    - `USI Aggressive: tight-spread votes = ON` (optional)
    - `Hardened Hold (L5 > L4) = OFF`

- **Scalp Early entry behavior profile (indicator + strategy):**
  - Added `Scalp Early (v6.3.12-fast)` to `Entry behavior profile`.
  - Keeps v6.3.12 structure but biases for earlier entries via:
    - slightly lower score thresholds,
    - slightly lower directional/score probability thresholds,
    - lower ChoCH probability threshold,
    - disabled score confidence hard-gate.

- **Cooldown trigger mode `EntriesOnly` (indicator + strategy):**
  - Added new `cooldownTriggers` option `EntriesOnly` in both scripts.
  - `EntriesOnly` updates cooldown timestamps only on entry signals (`BUY`/`SHORT`).
  - In `EntriesOnly` with `cooldownBars >= 1`, exits are hold-gated by entry bar index to enforce one full bar after entry before `EXIT`/`COVER` can fire.
  - Exception update: `EXIT SL` and `COVER` bypass this hold and may fire immediately after entry.
  - Existing modes remain unchanged:
    - `ExitsOnly` updates on `EXIT`/`COVER`.
    - `AllSignals` updates on all signals.

- **Global directional probability floors (indicator + strategy):**
  - Added `Enforce score min pU/pD on all entries` (default `true`).
  - When enabled, `Score min pU (Long)` / `Score min pD (Short)` are enforced as hard floors across BUY/SHORT entry paths.
  - `REV-BUY` is exempt and keeps its dedicated reversal probability gates (`revMinProb` + reversal/open-window logic).
  - Added `Global floor: bypass in open window` (default `true`) to optionally preserve open-window entry behavior.

- **Dedicated REV alert conditions (indicator + strategy):**
  - Added standalone `REV-BUY` and `REV-SHORT` alert conditions.
  - Consolidated runtime alert text now prioritizes `REV-BUY`/`REV-SHORT` labels over generic `BUY`/`SHORT` when reversal entries fire.

- **Dedicated consolidation alert condition (indicator + strategy):**
  - Added standalone `CONSOLIDATION` alert condition.
  - Trigger is phase-entry based (`sidewaysVisual and not sidewaysVisual[1]`) to avoid repeated alerts on every consolidation bar.

- **Sideways visual hysteresis parity (strategy):**
  - Strategy now uses the same visual consolidation hysteresis model as indicator (`sideEnter`/`sideExit` + latched `sidewaysVisual`).
  - This aligns consolidation alert timing semantics across both scripts without changing engine-side entry gating.

- **Consolidation dot color refinement (indicator):**
  - Consolidation dots are now **reddish** when USI is short (`usiStackDir == -1`).
  - All other consolidation states remain **orange**.

- **Directional consolidation entry veto (indicator + strategy):**
  - `BUY` is blocked during bearish/reddish consolidation.
  - `SHORT` is blocked during bullish/orange consolidation.
  - Veto applies to entries only; exits keep normal behavior.

- **Directional consolidation entry veto removed (indicator + strategy):**
  - Consolidation dot color/state is now informational only.
  - `BUY`/`SHORT` are no longer directly blocked by bearish/bullish consolidation dot state.

- **Intrabar alerts/labels default enabled (indicator + strategy):**
  - `Alerts: bar close only` now defaults to `false`.
  - Runtime alert/label flow is intrabar-first by default for BUY/SHORT/EXIT/COVER and PRE-BUY/PRE-SHORT.
  - Close-confirmed-only behavior remains available by setting `Alerts: bar close only = true`.

- **v6.3.13 parity hardening (indicator + strategy):**
  - restored strict entry gating parity in Strategy (`reliabilityOk`, `evidenceOk`, `evalOk`, `abstainGate/decisionFinal`) while preserving session filtering,
  - added full Strategy-side dynamic TP/SL runtime profile support:
    - Dynamic TP expansion (`useDynamicTpExpansion`, `dynamicTpKickInR`, `dynamicTpAddATRPerR`, `dynamicTpMaxAddATR`, trend/conf gates),
    - Dynamic SL profile (`useDynamicSlProfile`, widen/tighten phases, trend/conf gates),
    - preset-driven effective dynamic TP mapping (`Manual/Conservative/Balanced/Runner/Super Runner`) aligned with indicator.
- **Structure tag wiring completed:**
  - Strategy now renders BOS/ChoCH structure tags (not only entry/exit labels),
  - Indicator now renders BOS tags alongside existing ChoCH tags.
- **ChoCH volume requirement wired:**
  - `chochReqVol` now actively gates ChoCH-triggered entries in both scripts.

### Verification

- Targeted strict-related suites (local, 2026-02-16): **152 passed, 8 subtests passed**.
- Full regression suite (local, 2026-02-16): **390 passed, 16 subtests passed**.

- **Entry behavior profile toggle (legacy timing fallback):** added `entryBehaviorProfile` in indicator + strategy under **Score Engine (Option C)**:
  - `Current (v6.3.12)` keeps stricter score gating/chop veto behavior.
  - `Legacy (v6.3.9-like)` relaxes entry strictness for earlier signal timing by:
    - disabling score probability and confidence hard-gates,
    - disabling score directional-context hard requirement,
    - disabling hard chop veto in final score merge,
    - disabling Regime Classifier 2 auto-tightening,
    - slightly loosening ChoCH probability threshold.

  ### Changed

  - **Fallback activated by default:** `entryBehaviorProfile` now defaults to `Legacy (v6.3.9-like)` in both indicator and strategy for immediate v6.3.9-like signal timing behavior out of the box.

## [v6.3.13] - 2026-02-16

### Added

- Strategy parity completion for dynamic runtime risk modules:
  - Dynamic TP expansion,
  - Dynamic SL profile (widen/tighten),
  - preset-aware effective dynamic TP mapping.
- Structure visualization parity updates:
  - BOS tags now rendered in indicator,
  - BOS/ChoCH structure tags now rendered in strategy.

### Changed

- Restored strict Strategy entry gating parity with indicator:
  - reliability/evidence/eval/abstain decision checks active again in `allowEntry`.
- Wired `chochReqVol` into ChoCH-triggered entry filtering in both scripts.
- Version sync: bumped visible script versions/titles to `v6.3.13`.

### Verification

- Full regression suite: **386 passed**.

## [v6.3.12] - 2026-02-15

### Added

- **RFC v6.4 Phase-3 quality tuning (regime hysteresis):** added state-stability controls for Regime Classifier 2.0 in both scripts:
  - `regimeMinHoldBars` (minimum hold duration before non-shock regime switches)
  - `regimeShockReleaseDelta` (VOL_SHOCK release threshold hysteresis)
  - latched regime logic via `rawRegime2State`, `regime2State`, `regime2HoldBars`
  - shock persistence rule keeps `VOL_SHOCK` active until ATR percentile cools below release threshold

### Changed

- **Version sync:** bumped visible script versions to `v6.3.12` in indicator and strategy headers/titles.
- **Tests:** added Phase-3 parity lock in `tests/test_score_engine_parity.py` (`test_phase3_regime_hysteresis_parity`).
- **Tests (behavioral):** added simulator snapshot coverage for Phase-3 hysteresis edge cases in `tests/test_functional_features.py` (`TestPhase3RegimeHysteresisBehavior`):
  - regime flapping damping via `regimeMinHoldBars`
  - VOL_SHOCK sticky release via `regimeShockReleaseDelta`

### Verification

- Full regression suite passes after integration: **384 passed**.

## [v6.3.11] - 2026-02-15

### Added

- **RFC v6.4 Phase-2 opt-in wiring (default-safe):** integrated the Phase-1 scaffold into active signal controls when explicitly enabled (`useRegimeClassifier2` + `regimeAutoPreset` + detected regime):
  - new effective tuning variables `cooldownBarsEff`, `chochMinProbEff`, `abstainOverrideConfEff`
  - regime-aware mapping for TREND/RANGE/CHOP/VOL_SHOCK under `regime2TuneOn`
  - trend core activation in signal layer via `trendReg = f_trend_regime(trendCoreFast, trendCoreSlow, atrNormHere)` and `trendStrength = f_trend_strength(trendCoreFast, trendCoreSlow)`
  - ChoCH gating updated to effective threshold (`chochMinProbEff`) in all relevant entry paths
  - abstain override uses effective threshold (`abstainOverrideConfEff`)

### Changed

- **Version sync:** bumped visible script versions to `v6.3.11` in indicator and strategy headers/titles.
- **Tests:**
  - added Phase-2 wiring parity coverage in `tests/test_score_engine_parity.py` (`test_phase2_optin_wiring_parity`)
  - aligned trend-regime presence checks to trend-core wiring in:
    - `tests/test_skippalgo_pine.py`
    - `tests/test_skippalgo_strategy.py`

### Verification

- Full regression suite passes after integration: **378 passed**.

## [v6.3.10] - 2026-02-15

### Added

- **RFC v6.4 Phase-1 scaffold (default-off):** added non-invasive foundation in both `SkippALGO.pine` and `SkippALGO_Strategy.pine`:
  - Zero-Lag Trend Core inputs (`useZeroLagTrendCore`, `trendCoreMode`, `zlTrendLenFast/Slow`, `zlTrendAggressiveness`, `zlTrendNoiseGuard`)
  - Regime Classifier 2.0 inputs (`useRegimeClassifier2`, `regimeLookback`, `regimeAtrShockPct`, `regimeAdxTrendMin`, `regimeHurstRangeMax`, `regimeChopBandMax`, `regimeAutoPreset`)
  - debug visibility toggle `showPhase1Debug` with hidden Data Window plots
  - helper functions `f_zl_trend_core` and `f_hurst_proxy`
  - derived diagnostic state variables (`trendCoreFast/Slow`, `trendCoreDiffNorm`, `regime2State`, `regime2Name`)

### Changed

- **Version sync:** bumped visible script versions to `v6.3.10` in indicator and strategy headers/titles.
- **Tests:** expanded parity/functional coverage for Phase-1 scaffold invariants:
  - `tests/test_score_engine_parity.py`
  - `tests/test_functional_features.py`
  - `tests/pine_sim.py` (Phase-1 config surface)

### Verification

- Full regression suite passes after integration: **377 passed**.

## [v6.3.9] - 2026-02-15

### Added

- **Functional behavior test matrix (new):** added simulator-driven feature coverage in `tests/test_functional_features.py` for:
  - gate functionality (`reliabilityOk`, `evidenceOk`, `evalOk`, `decisionFinal`),
  - open-window + strict-mode behavior,
  - engine scenarios (Hybrid/Breakout/Trend+Pullback/Loose),
  - risk/exit behavior,
  - reversal logic,
  - feature-flag matrix,
  - randomized invariants,
  - golden-master snapshots.
- **Label/display regression suite (new):** added `tests/test_label_display_regression.py` to lock label payload/style/color contracts and event→label family mapping (BUY/REV-BUY/SHORT/REV-SHORT/EXIT/COVER).
- **Functional test documentation:** added `docs/FUNCTIONAL_TEST_MATRIX.md` and linked it from `README.md`.

### Changed

- **CI guard hardened:** `.github/workflows/ci.yml` now includes explicit read permissions, concurrency cancel-in-progress, manual dispatch (`workflow_dispatch`), timeout guard, and strict pytest execution (`-q --maxfail=1`).
- **Version sync:** updated script headers/titles and docs references to `v6.3.9` for consistency.

### Verification

- Full regression suite passes after integration: **375 passed**.

### Changed

- **Entry presets (new):** added score presets in indicator + strategy via:
  - `entryPreset = Manual | Intraday | Swing`
  - `presetAutoCooldown` (default `false`)
  Presets now drive effective score variables (`*_Eff`) for thresholds, weights, and score probability floors.
- **Optional preset-driven cooldown:** when `presetAutoCooldown = true` and preset is not `Manual`, cooldown uses effective preset values:
  - mode: `Bars`
  - triggers: `ExitsOnly`
  - minutes: `15` (Intraday) / `45` (Swing)
  With `presetAutoCooldown = false` (default), cooldown remains fully user-input controlled.
- **Score integration mode adjusted (Option C):** restored hybrid signal merge so score can inject entries again while still respecting engine logic context.
- **Score directional context gate (new, default ON):** added `scoreRequireDirectionalContext` so score injection requires directional context:
  - BUY score injection needs bullish context (`trendUp`/USI bull state),
  - SHORT score injection needs bearish context (`trendDn`/USI bear state).
- **Dynamic TP expansion:** outward-only TP mode is active by default (default ON) in indicator + strategy:
  - `useDynamicTpExpansion`
  - `dynamicTpKickInR`, `dynamicTpAddATRPerR`, `dynamicTpMaxAddATR`
  - optional gates: `dynamicTpRequireTrend`, `dynamicTpRequireConf`, `dynamicTpMinConf`
  TP expands as unrealized $R$ grows and never tightens due to this module.
- **Dynamic SL profile (new, default ON):** added adaptive stop profiling in indicator + strategy:
  - optional early widening window (`dynamicSlWidenUntilR`, `dynamicSlMaxWidenATR`) to reduce noise stopouts,
  - progressive tightening phase (`dynamicSlTightenStartR`, `dynamicSlTightenATRPerR`, `dynamicSlMaxTightenATR`) as $R$ grows,
  - optional gates: `dynamicSlRequireTrend`, `dynamicSlRequireConf`, `dynamicSlMinConf`.
  Widening is disabled once BE was hit or trailing is active.
- **Score hard confidence gate (new):** added optional hard confidence floor for score entries in indicator + strategy:
  - `scoreUseConfGate`
  - `scoreMinConfLong`, `scoreMinConfShort`
  - integrated in final score entry decisions via effective vars (`*_Eff`) for preset parity.
  - **Current defaults:** `scoreUseConfGate = true`, `scoreMinConfLong = 0.50`, `scoreMinConfShort = 0.50`.

### Fixed

- **Chop penalty enforcement:** added explicit chop veto in final score merge path:
  - `chopVeto = isChop and (wChopPenalty < 0)`
  - final merge now blocks BUY/SHORT when chop veto is active.
- **Unified exit trigger (LONG + SHORT):** exit/cover now use one OR-union trigger in both scripts:
  - `riskExitHit (TP/SL/Trailing) OR usiExitHit OR engExitHit`
  - whichever condition fires first closes the position.
- **Cooldown semantics restored:** when `cooldownTriggers` is `ExitsOnly` or `AllSignals`, cooldown timestamps are updated on both EXIT and COVER events again (indicator + strategy parity).
- **Debug transparency:** score debug panel now prints chop veto status (`veto:0/1`) next to `chop` for faster root-cause diagnosis.
- **Debug blocker clarity:** score debug now shows explicit block reason (for example `BLOCK:IN_POSITION`) and prints last-signal age safely (`LS:...@n/a` instead of `NaN` when unavailable).
- **Debug context visibility:** score debug now prints directional context gate flags:
  - `ctxL:0/1` for long score-context pass/fail,
  - `ctxS:0/1` for short score-context pass/fail.
- **Token-budget hardening (Strategy):** reduced compile-token pressure by compacting debug payloads and removing Strategy table rendering (visual-only) while keeping signal/risk/entry-exit logic intact.
- **Parity:** same logic mirrored in both `SkippALGO.pine` and `SkippALGO_Strategy.pine`.

## [v6.3.8] - 2026-02-15

### Changed

- **USI Exit/Flip Touch Logic (Tier A Red vs Blue):** refined cross detection to treat visual touch/near-touch transitions as valid flip events, improving practical EXIT timing when Red approaches Blue from above.
- **USI Red De-lag Option (Option 2):** added optional Red-line source de-lag controls:
  - `useUsiZeroLagRed`
  - `usiZlAggressiveness`
  This is applied pre-RSI on Line5 for earlier flips with controllable aggressiveness.

### Fixed

- **Contra-state entries blocked (hard rule):** BUY is now vetoed when USI is bearish, and SHORT is vetoed when USI is bullish (when USI is enabled).
- **Parity hardening:** synchronized logic in both `SkippALGO.pine` and `SkippALGO_Strategy.pine`, including gate-timeframe (`f_usi_30m_calc_raw`) handling for the new Red-line de-lag path.

### Tests

- Extended parity checks in `tests/test_score_engine_parity.py` to verify:
  - presence of new USI Red de-lag inputs,
  - Red-line implementation parity,
  - hard USI state blocking in score decisions.

## [v6.3.7] - 2026-02-14

### Added

- **Exit control flexibility:** `useStrictEmaExit` added to allow relaxed trend exits (wait for full EMA trend flip when disabled), reducing deep-pullback shakeouts.

## [v6.3.4] - 2026-02-14

### Fixed

- **SkippALGO Strategy**: Synchronized fix for `plotchar()` scope (global scope with conditional logic) to resolve "Cannot use plotchar in local scope".
- **Maintenance**: Unified versioning across Indicator (v6.3.3 based) and Strategy.

## [v6.3.3] - 2026-02-14

### Fixed

- **SkippALGO Indicator**: Moved `plotchar()` debug calls from local scope (if-block) to global scope with conditional `debugUsiPulse and ...` logic to fix "Cannot use plotchar in local scope" errors.

## [v6.3.2] - 2026-02-14

### Fixed

- **SkippALGO Indicator**: Replaced `color.cyan` with `color.aqua` to resolve an undeclared identifier error (Pine v6 standard).

## [v6.3.1] - 2026-02-14

### Fixed

- **SkippALGO Indicator**: Removed duplicate/erroneous code block related to `qVerifyBuy` logic that caused a "Mismatched input bool" syntax error.
- **Maintenance**: Parity version bump for Strategy script (no functional changes in Strategy).

## [v6.3.0] - 2026-02-14

### Added (System Hardening)

- **Time-Based Cooldown**: `cooldownMode` input ("Bars" vs "Minutes") allows proper HTF trade management without multi-hour lockouts.
- **Explicit Triggers**: `cooldownTriggers` input ("ExitsOnly" vs "AllSignals") strictly defines what resets the timer. "ExitsOnly" (default) ensures fast add-on entries are possible.

### Changed (Optimization)

- **QuickALGO Logic**: Switched from restrictive "Hard-AND" momentum check to "Score+Verify" weighted approach.
- **QuickALGO MTF Fix**: Added `lookahead=barmerge.lookahead_off` to prevent repainting.
- **Cleanup**: Removed legacy "Deep Upgrade" branding from script headers.

## [2026-02-12]

### Added (Signals & Volatility)

- New input: `REV: Min dir prob` (`revMinProb`, default `0.50`) for the normal REV entry probability path.

### Changed (Parity)

- Stabilized script titles to preserve TradingView input settings across updates:
  - `indicator("SkippALGO", ...)`
  - `strategy("SkippALGO Strategy", ...)`
- Consolidated runtime alert dispatch to one `alert()` call per bar per symbol, reducing watchlist alert-rate pressure and TradingView throttling risk.
- EXIT/COVER label text layout split into shorter multi-line rows for better chart readability.
- Open-window directional probability (`pU`/`pD`) bypass behavior applies during configured market-open windows as implemented in current logic.

### Clarified

- `Rescue Mode: Min Probability` (`rescueMinProb`) controls only the rescue fallback path (requires volume + impulse), while `revMinProb` controls the normal REV path.

### Fixed

- Corrected Strategy-side forecast gate indentation/structure parity so open-window bypass behavior is consistently applied.

### Added

- Optional **3-candle engulfing filter** (default OFF) in both `SkippALGO.pine` and `SkippALGO_Strategy.pine`:
  - Long entries require bullish engulfing after 3 bearish candles.
  - Short entries require bearish engulfing after 3 bullish candles.
  - Optional body-dominance condition (`body > previous body`).
  - Optional engulfing bar coloring (bullish yellow / bearish white).
- Optional **ATR volatility context layer** (default OFF) in both scripts:
  - Regime overlay and label: `COMPRESSION`, `EXPANSION`, `HIGH VOL`, `EXHAUSTION`.
  - ATR ratio to configurable baseline (`SMA`/`EMA`).
  - Optional ATR percentile context (`0..100`) with configurable lookback.

### Changed

- Maintained strict **Indicator ⇄ Strategy parity** for new signal/context features to avoid behavior drift between visual and strategy paths.

---

## Notes

- This changelog tracks user-facing behavior and operational reliability updates.
- Historical items before this file was introduced may still be referenced in commit history and docs.
