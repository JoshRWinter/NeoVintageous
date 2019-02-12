# Copyright (C) 2018 The NeoVintageous Team (NeoVintageous).
#
# This file is part of NeoVintageous.
#
# NeoVintageous is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# NeoVintageous is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with NeoVintageous.  If not, see <https://www.gnu.org/licenses/>.

from itertools import chain

from sublime import CLASS_EMPTY_LINE
from sublime import ENCODED_POSITION
from sublime import LITERAL
from sublime import Region
from sublime import version
from sublime_plugin import WindowCommand

from NeoVintageous.nv.cmds import _nv_cmdline_feed_key
from NeoVintageous.nv.history import history_update
from NeoVintageous.nv.jumplist import jumplist_update
from NeoVintageous.nv.state import State
from NeoVintageous.nv.ui import ui_blink
from NeoVintageous.nv.ui import ui_cmdline_prompt
from NeoVintageous.nv.ui import ui_region_flags
from NeoVintageous.nv.vi import cmd_defs
from NeoVintageous.nv.vi import units
from NeoVintageous.nv.vi import utils
from NeoVintageous.nv.vi.cmd_defs import ViSearchBackwardImpl
from NeoVintageous.nv.vi.cmd_defs import ViSearchForwardImpl
from NeoVintageous.nv.vi.core import ViMotionCommand
from NeoVintageous.nv.vi.search import BufferSearchBase
from NeoVintageous.nv.vi.search import ExactWordBufferSearchBase
from NeoVintageous.nv.vi.search import find_in_range
from NeoVintageous.nv.vi.search import find_wrapping
from NeoVintageous.nv.vi.search import reverse_find_wrapping
from NeoVintageous.nv.vi.search import reverse_search_by_pt
from NeoVintageous.nv.vi.text_objects import find_containing_tag
from NeoVintageous.nv.vi.text_objects import find_next_lone_bracket
from NeoVintageous.nv.vi.text_objects import find_prev_lone_bracket
from NeoVintageous.nv.vi.text_objects import find_sentences_backward
from NeoVintageous.nv.vi.text_objects import find_sentences_forward
from NeoVintageous.nv.vi.text_objects import get_closest_tag
from NeoVintageous.nv.vi.text_objects import get_text_object_region
from NeoVintageous.nv.vi.text_objects import word_end_reverse
from NeoVintageous.nv.vi.text_objects import word_reverse
from NeoVintageous.nv.vi.utils import get_bol
from NeoVintageous.nv.vi.utils import next_non_blank
from NeoVintageous.nv.vi.utils import next_non_white_space_char
from NeoVintageous.nv.vi.utils import regions_transformer
from NeoVintageous.nv.vi.utils import resize_visual_region
from NeoVintageous.nv.vi.utils import resolve_insertion_point_at_a
from NeoVintageous.nv.vi.utils import resolve_insertion_point_at_b
from NeoVintageous.nv.vi.utils import row_at
from NeoVintageous.nv.vi.utils import row_to_pt
from NeoVintageous.nv.vi.utils import show_if_not_visible
from NeoVintageous.nv.vim import console_message
from NeoVintageous.nv.vim import DIRECTION_DOWN
from NeoVintageous.nv.vim import DIRECTION_UP
from NeoVintageous.nv.vim import enter_normal_mode
from NeoVintageous.nv.vim import INTERNAL_NORMAL
from NeoVintageous.nv.vim import NORMAL
from NeoVintageous.nv.vim import SELECT
from NeoVintageous.nv.vim import VISUAL
from NeoVintageous.nv.vim import VISUAL_BLOCK
from NeoVintageous.nv.vim import VISUAL_LINE


__all__ = [
    '_vi_b',
    '_vi_big_b',
    '_vi_big_e',
    '_vi_big_g',
    '_vi_big_h',
    '_vi_big_l',
    '_vi_big_m',
    '_vi_big_n',
    '_vi_big_w',
    '_vi_ctrl_b',
    '_vi_ctrl_d',
    '_vi_ctrl_f',
    '_vi_ctrl_u',
    '_vi_dollar',
    '_vi_e',
    '_vi_enter',
    '_vi_find_in_line',
    '_vi_g__',
    '_vi_g_big_e',
    '_vi_ge',
    '_vi_gg',
    '_vi_gj',
    '_vi_gk',
    '_vi_gm',
    '_vi_go_to_line',
    '_vi_go_to_symbol',
    '_vi_h',
    '_vi_hat',
    '_vi_j',
    '_vi_k',
    '_vi_l',
    '_vi_left_brace',
    '_vi_left_paren',
    '_vi_left_square_bracket_c',
    '_vi_left_square_bracket_target',
    '_vi_minus',
    '_vi_n',
    '_vi_octothorp',
    '_vi_percent',
    '_vi_pipe',
    '_vi_question_mark',
    '_vi_question_mark_impl',
    '_vi_question_mark_on_parser_done',
    '_vi_repeat_buffer_search',
    '_vi_reverse_find_in_line',
    '_vi_right_brace',
    '_vi_right_paren',
    '_vi_right_square_bracket_c',
    '_vi_right_square_bracket_target',
    '_vi_select_text_object',
    '_vi_shift_enter',
    '_vi_slash',
    '_vi_slash_impl',
    '_vi_slash_on_parser_done',
    '_vi_star',
    '_vi_underscore',
    '_vi_w',
    '_vi_zero'
]


class _vi_find_in_line(ViMotionCommand):
    def run(self, char=None, mode=None, count=1, inclusive=True, skipping=False):
        # Contrary to *f*, *t* does not look past the caret's position, so if
        # @character is under the caret, nothing happens.

        def f(view, s):
            if mode == VISUAL_LINE:
                raise ValueError(
                    'this operator is not valid in mode {}'.format(mode))

            b = s.b
            # If we are in any visual mode, get the actual insertion point.
            if s.size() > 0:
                b = resolve_insertion_point_at_b(s)

            # Vim skips a character while performing the search
            # if the command is ';' or ',' after a 't' or 'T'
            if skipping:
                b = b + 1

            eol = view.line(b).end()

            match = Region(b + 1)
            for i in range(count):
                # Define search range as 'rest of the line to the right'.
                search_range = Region(match.end(), eol)
                match = find_in_range(view, char, search_range.a, search_range.b, LITERAL)

                # Count too high or simply no match; break.
                if match is None:
                    return s

            target_pos = match.a
            if not inclusive:
                target_pos = target_pos - 1

            if mode == NORMAL:
                return Region(target_pos)
            elif mode == INTERNAL_NORMAL:
                return Region(s.a, target_pos + 1)
            else:  # For visual modes...
                new_a = resolve_insertion_point_at_a(s)
                return utils.new_inclusive_region(new_a, target_pos)

        if not all([char, mode]):
            raise ValueError('bad parameters')

        char = utils.translate_char(char)

        regions_transformer(self.view, f)


class _vi_reverse_find_in_line(ViMotionCommand):
    """
    Reverse search.

    Contrary to *F*, *T* does not look past the caret's position, so if
    ``character`` is right before the caret, nothing happens.
    """

    def run(self, char=None, mode=None, count=1, inclusive=True, skipping=False):
        def f(view, s):
            if mode == VISUAL_LINE:
                raise ValueError(
                    'this operator is not valid in mode {}'.format(mode))

            b = s.b
            if s.size() > 0:
                b = resolve_insertion_point_at_b(s)

            # Vim skips a character while performing the search
            # if the command is ';' or ',' after a 't' or 'T'
            if skipping:
                b = b - 1

            line_start = view.line(b).a

            try:
                match = b
                for i in range(count):
                    # line_text does not include character at match
                    line_text = view.substr(Region(line_start, match))
                    found_at = line_text.rindex(char)
                    match = line_start + found_at
            except ValueError:
                return s

            target_pos = match
            if not inclusive:
                target_pos = target_pos + 1

            if mode == NORMAL:
                return Region(target_pos)
            elif mode == INTERNAL_NORMAL:
                return Region(b, target_pos)
            else:  # For visual modes...
                new_a = resolve_insertion_point_at_a(s)
                return utils.new_inclusive_region(new_a, target_pos)

        if not all([char, mode]):
            raise ValueError('bad parameters')

        char = utils.translate_char(char)

        regions_transformer(self.view, f)


class _vi_slash(ViMotionCommand, BufferSearchBase):

    def run(self):
        self.state.reset_during_init = False

        # TODO Add incsearch option e.g. on_change = self.on_change if 'incsearch' else None

        ui_cmdline_prompt(
            self.view.window(),
            initial_text='/',
            on_done=self.on_done,
            on_change=self.on_change,
            on_cancel=self.on_cancel)

    def on_done(self, s):
        if len(s) <= 1:
            return

        if s[0] != '/':
            return

        history_update(s)
        _nv_cmdline_feed_key.reset_last_history_index()
        s = s[1:]

        state = self.state
        state.sequence += s + '<CR>'
        self.view.erase_regions('vi_inc_search')
        state.last_buffer_search_command = 'vi_slash'
        state.motion = cmd_defs.ViSearchForwardImpl(term=s)

        # If s is empty, we must repeat the last search.
        state.last_buffer_search = s or state.last_buffer_search
        state.eval()

    def on_change(self, s):
        if s == '':
            return self._force_cancel()

        if len(s) <= 1:
            return

        if s[0] != '/':
            return self._force_cancel()

        s = s[1:]

        state = self.state
        flags = self.calculate_flags(s)
        self.view.erase_regions('vi_inc_search')
        next_hit = find_wrapping(self.view,
                                 term=s,
                                 start=self.view.sel()[0].b + 1,
                                 end=self.view.size(),
                                 flags=flags,
                                 times=state.count)
        if next_hit:
            if state.mode == VISUAL:
                next_hit = Region(self.view.sel()[0].a, next_hit.a + 1)

            # The scopes are prefixed with common color scopes so that color
            # schemes have sane default colors. Color schemes can progressively
            # enhance support by using the nv_* scopes.
            self.view.add_regions(
                'vi_inc_search',
                [next_hit],
                scope='support.function neovintageous_search_inc',
                flags=ui_region_flags(self.view.settings().get('neovintageous_search_inc_style'))
            )

            if not self.view.visible_region().contains(next_hit.b):
                self.view.show(next_hit.b)

    def _force_cancel(self):
        self.on_cancel()
        self.view.window().run_command('hide_panel', {'cancel': True})

    def on_cancel(self):
        state = self.state
        self.view.erase_regions('vi_inc_search')
        state.reset_command_data()
        _nv_cmdline_feed_key.reset_last_history_index()

        if not self.view.visible_region().contains(self.view.sel()[0]):
            self.view.show(self.view.sel()[0])


class _vi_slash_impl(ViMotionCommand, BufferSearchBase):
    def run(self, search_string='', mode=None, count=1):
        def f(view, s):
            if mode == VISUAL:
                return Region(s.a, match.a + 1)

            elif mode == INTERNAL_NORMAL:
                return Region(s.a, match.a)

            elif mode == NORMAL:
                return Region(match.a, match.a)

            elif mode == VISUAL_LINE:
                return Region(s.a, view.full_line(match.b - 1).b)

            return s

        # This happens when we attempt to repeat the search and there's no search term stored yet.
        if not search_string:
            return

        # We want to start searching right after the current selection.
        current_sel = self.view.sel()[0]
        start = current_sel.b if not current_sel.empty() else current_sel.b + 1
        wrapped_end = self.view.size()

        flags = self.calculate_flags(search_string)
        match = find_wrapping(self.view, search_string, start, wrapped_end, flags=flags, times=count)
        if not match:
            return

        regions_transformer(self.view, f)
        self.hilite(search_string)


class _vi_slash_on_parser_done(WindowCommand):

    def run(self, key=None):
        state = State(self.window.active_view())
        state.motion = ViSearchForwardImpl()
        state.last_buffer_search = (state.motion.inp or state.last_buffer_search)


class _vi_l(ViMotionCommand):
    def run(self, mode=None, count=1):
        def f(view, s):
            if mode == NORMAL:
                if view.line(s.b).empty():
                    return s

                x_limit = min(view.line(s.b).b - 1, s.b + count, view.size())
                return Region(x_limit, x_limit)

            if mode == INTERNAL_NORMAL:
                x_limit = min(view.line(s.b).b, s.b + count)
                x_limit = max(0, x_limit)
                return Region(s.a, x_limit)

            if mode in (VISUAL, VISUAL_BLOCK):
                if s.a < s.b:
                    x_limit = min(view.full_line(s.b - 1).b, s.b + count)
                    return Region(s.a, x_limit)

                if s.a > s.b:
                    x_limit = min(view.full_line(s.b).b - 1, s.b + count)
                    if view.substr(s.b) == '\n':
                        return s

                    if view.line(s.a) == view.line(s.b) and count >= s.size():
                        x_limit = min(view.full_line(s.b).b, s.b + count + 1)
                        return Region(s.a - 1, x_limit)

                    return Region(s.a, x_limit)

            return s

        regions_transformer(self.view, f)


class _vi_h(ViMotionCommand):
    def run(self, count=1, mode=None):
        def f(view, s):
            if mode == INTERNAL_NORMAL:
                x_limit = max(view.line(s.b).a, s.b - count)
                return Region(s.a, x_limit)

            # TODO: Split handling of the two modes for clarity.
            elif mode in (VISUAL, VISUAL_BLOCK):

                if s.a < s.b:
                    if mode == VISUAL_BLOCK and self.view.rowcol(s.b - 1)[1] == baseline:
                        return s

                    x_limit = max(view.line(s.b - 1).a + 1, s.b - count)
                    if view.line(s.a) == view.line(s.b - 1) and count >= s.size():
                        x_limit = max(view.line(s.b - 1).a, s.b - count - 1)
                        return Region(s.a + 1, x_limit)
                    return Region(s.a, x_limit)

                if s.a > s.b:
                    x_limit = max(view.line(s.b).a, s.b - count)
                    return Region(s.a, x_limit)

            elif mode == NORMAL:
                x_limit = max(view.line(s.b).a, s.b - count)
                return Region(x_limit, x_limit)

            # XXX: We should never reach this.
            return s

        # For jagged selections (on the rhs), only those sticking out need to move leftwards.
        # Example ([] denotes the selection):
        #
        #   10 foo bar foo [bar]
        #   11 foo bar foo [bar foo bar]
        #   12 foo bar foo [bar foo]
        #
        #  Only lines 11 and 12 should move when we press h.
        baseline = 0
        if mode == VISUAL_BLOCK:
            sel = self.view.sel()[0]
            if sel.a < sel.b:
                min_ = min(self.view.rowcol(r.b - 1)[1] for r in self.view.sel())
                if any(self.view.rowcol(r.b - 1)[1] != min_ for r in self.view.sel()):
                    baseline = min_

        regions_transformer(self.view, f)


class _vi_j(ViMotionCommand):
    def folded_rows(self, pt):
        folds = self.view.folded_regions()
        try:
            fold = [f for f in folds if f.contains(pt)][0]
            fold_row_a = self.view.rowcol(fold.a)[0]
            fold_row_b = self.view.rowcol(fold.b - 1)[0]
            # Return no. of hidden lines.
            return (fold_row_b - fold_row_a)
        except IndexError:
            return 0

    def next_non_folded_pt(self, pt):
        # FIXME: If we have two contiguous folds, this method will fail.
        # Handle folded regions.
        folds = self.view.folded_regions()
        try:
            fold = [f for f in folds if f.contains(pt)][0]
            non_folded_row = self.view.rowcol(self.view.full_line(fold.b).b)[0]
            pt = self.view.text_point(non_folded_row, 0)
        except IndexError:
            pass
        return pt

    def calculate_xpos(self, start, xpos):
        size = self.view.settings().get('tab_size')
        if self.view.line(start).empty():
            return start, 0
        else:
            eol = self.view.line(start).b - 1
        pt = 0
        chars = 0
        while (pt < xpos):
            if self.view.substr(start + chars) == '\t':
                pt += size
            else:
                pt += 1
            chars += 1
        pt = min(eol, start + chars)
        return pt, chars

    def run(self, count=1, mode=None, xpos=0, no_translation=False):
        def f(view, s):
            nonlocal xpos
            if mode == NORMAL:
                current_row = view.rowcol(s.b)[0]
                target_row = min(current_row + count, view.rowcol(view.size())[0])
                invisible_rows = self.folded_rows(view.line(s.b).b + 1)
                target_pt = view.text_point(target_row + invisible_rows, 0)
                target_pt = self.next_non_folded_pt(target_pt)

                if view.line(target_pt).empty():
                    return Region(target_pt, target_pt)

                pt = self.calculate_xpos(target_pt, xpos)[0]

                return Region(pt)

            if mode == INTERNAL_NORMAL:
                current_row = view.rowcol(s.b)[0]
                target_row = min(current_row + count, view.rowcol(view.size())[0])
                target_pt = view.text_point(target_row, 0)
                return Region(view.line(s.a).a, view.full_line(target_pt).b)

            if mode == VISUAL:
                exact_position = s.b - 1 if (s.a < s.b) else s.b
                current_row = view.rowcol(exact_position)[0]
                target_row = min(current_row + count, view.rowcol(view.size())[0])
                target_pt = view.text_point(target_row, 0)
                _, xpos = self.calculate_xpos(target_pt, xpos)

                end = min(self.view.line(target_pt).b, target_pt + xpos)
                if s.a < s.b:
                    return Region(s.a, end + 1)

                if (target_pt + xpos) >= s.a:
                    return Region(s.a - 1, end + 1)

                return Region(s.a, target_pt + xpos)

            if mode == VISUAL_LINE:
                if s.a < s.b:
                    current_row = view.rowcol(s.b - 1)[0]
                    target_row = min(current_row + count, view.rowcol(view.size())[0])
                    target_pt = view.text_point(target_row, 0)

                    return Region(s.a, view.full_line(target_pt).b)

                elif s.a > s.b:
                    current_row = view.rowcol(s.b)[0]
                    target_row = min(current_row + count, view.rowcol(view.size())[0])
                    target_pt = view.text_point(target_row, 0)

                    if target_row > view.rowcol(s.a - 1)[0]:
                        return Region(view.line(s.a - 1).a, view.full_line(target_pt).b)

                    return Region(s.a, view.full_line(target_pt).a)

            return s

        state = State(self.view)

        if mode == VISUAL_BLOCK:
            if len(self.view.sel()) == 1:
                state.visual_block_direction = DIRECTION_DOWN

            # Don't do anything if we have reversed selections.
            if any((r.b < r.a) for r in self.view.sel()):
                return

            if state.visual_block_direction == DIRECTION_DOWN:
                for i in range(count):
                    # FIXME: When there are multiple rectangular selections, S3 considers sel 0 to be the
                    # active one in all cases, so we can't know the 'direction' of such a selection and,
                    # therefore, we can't shrink it when we press k or j. We can only easily expand it.
                    # We could, however, have some more global state to keep track of the direction of
                    # visual block selections.
                    row, rect_b = self.view.rowcol(self.view.sel()[-1].b - 1)

                    # Don't do anything if the next row is empty or too short. Vim does a crazy thing: it
                    # doesn't select it and it doesn't include it in actions, but you have to still navigate
                    # your way through them.
                    # TODO: Match Vim's behavior.
                    next_line = self.view.line(self.view.text_point(row + 1, 0))
                    if next_line.empty() or self.view.rowcol(next_line.b)[1] < rect_b:
                        # TODO Fix Visual block select stops at empty lines.
                        # See https://github.com/NeoVintageous/NeoVintageous/issues/227.
                        # self.view.sel().add(next_line.begin())
                        # TODO Fix Visual Block does not work across multiple indentation levels.
                        # See https://github.com/NeoVintageous/NeoVintageous/issues/195.
                        return

                    max_size = max(r.size() for r in self.view.sel())
                    row, col = self.view.rowcol(self.view.sel()[-1].a)
                    start = self.view.text_point(row + 1, col)
                    new_region = Region(start, start + max_size)
                    self.view.sel().add(new_region)
                    # FIXME: Perhaps we should scroll into view in a more general way...

                self.view.show(new_region, False)
                return

            else:
                # Must delete last sel.
                self.view.sel().subtract(self.view.sel()[0])
                return

        regions_transformer(self.view, f)


class _vi_k(ViMotionCommand):
    def previous_non_folded_pt(self, pt):
        # FIXME: If we have two contiguous folds, this method will fail.
        # Handle folded regions.
        folds = self.view.folded_regions()
        try:
            fold = [f for f in folds if f.contains(pt)][0]
            non_folded_row = self.view.rowcol(fold.a - 1)[0]
            pt = self.view.text_point(non_folded_row, 0)
        except IndexError:
            pass
        return pt

    def calculate_xpos(self, start, xpos):
        if self.view.line(start).empty():
            return start, 0
        size = self.view.settings().get('tab_size')
        eol = self.view.line(start).b - 1
        pt = 0
        chars = 0
        while (pt < xpos):
            if self.view.substr(start + chars) == '\t':
                pt += size
            else:
                pt += 1
            chars += 1
        pt = min(eol, start + chars)
        return (pt, chars)

    def run(self, count=1, mode=None, xpos=0, no_translation=False):
        def f(view, s):
            nonlocal xpos
            if mode == NORMAL:
                current_row = view.rowcol(s.b)[0]
                target_row = min(current_row - count, view.rowcol(view.size())[0])
                target_pt = view.text_point(target_row, 0)
                target_pt = self.previous_non_folded_pt(target_pt)

                if view.line(target_pt).empty():
                    return Region(target_pt, target_pt)

                pt, _ = self.calculate_xpos(target_pt, xpos)

                return Region(pt)

            if mode == INTERNAL_NORMAL:
                current_row = view.rowcol(s.b)[0]
                target_row = min(current_row - count, view.rowcol(view.size())[0])
                target_pt = view.text_point(target_row, 0)

                return Region(view.full_line(s.a).b, view.line(target_pt).a)

            if mode == VISUAL:
                exact_position = s.b - 1 if (s.a < s.b) else s.b
                current_row = view.rowcol(exact_position)[0]
                target_row = max(current_row - count, 0)
                target_pt = view.text_point(target_row, 0)
                _, xpos = self.calculate_xpos(target_pt, xpos)

                end = min(self.view.line(target_pt).b, target_pt + xpos)
                if s.b >= s.a:
                    if (self.view.line(s.a).contains(s.b - 1) and not self.view.line(s.a).contains(target_pt)):
                        return Region(s.a + 1, end)
                    else:
                        if (target_pt + xpos) < s.a:
                            return Region(s.a + 1, end)
                        else:
                            return Region(s.a, end + 1)

                return Region(s.a, end)

            if mode == VISUAL_LINE:
                if s.a < s.b:
                    current_row = view.rowcol(s.b - 1)[0]
                    target_row = min(current_row - count, view.rowcol(view.size())[0])
                    target_pt = view.text_point(target_row, 0)

                    if target_row < view.rowcol(s.begin())[0]:
                        return Region(view.full_line(s.a).b, view.full_line(target_pt).a)

                    return Region(s.a, view.full_line(target_pt).b)

                elif s.a > s.b:
                    current_row = view.rowcol(s.b)[0]
                    target_row = max(current_row - count, 0)
                    target_pt = view.text_point(target_row, 0)

                    return Region(s.a, view.full_line(target_pt).a)

        state = State(self.view)

        if mode == VISUAL_BLOCK:
            if len(self.view.sel()) == 1:
                state.visual_block_direction = DIRECTION_UP

            # Don't do anything if we have reversed selections.
            if any((r.b < r.a) for r in self.view.sel()):
                return

            if state.visual_block_direction == DIRECTION_UP:

                for i in range(count):
                    rect_b = max(self.view.rowcol(r.b - 1)[1] for r in self.view.sel())
                    row, rect_a = self.view.rowcol(self.view.sel()[0].a)
                    previous_line = self.view.line(self.view.text_point(row - 1, 0))
                    # Don't do anything if previous row is empty. Vim does crazy stuff in that case.
                    # Don't do anything either if the previous line can't accomodate a rectangular selection
                    # of the required size.
                    if (previous_line.empty() or self.view.rowcol(previous_line.b)[1] < rect_b):
                        return
                    rect_size = max(r.size() for r in self.view.sel())
                    rect_a_pt = self.view.text_point(row - 1, rect_a)
                    new_region = Region(rect_a_pt, rect_a_pt + rect_size)
                    self.view.sel().add(new_region)
                    # FIXME: We should probably scroll into view in a more general way.
                    #        Or maybe every motion should handle this on their own.

                self.view.show(new_region, False)
                return

            elif SELECT:
                # Must remove last selection.
                self.view.sel().subtract(self.view.sel()[-1])
                return
            else:
                return

        regions_transformer(self.view, f)


class _vi_gg(ViMotionCommand):
    def run(self, mode=None, count=1):
        def f(view, s):
            if mode == NORMAL:
                return Region(next_non_blank(self.view, 0))
            elif mode == VISUAL:
                if s.a < s.b:
                    return Region(s.a + 1, next_non_blank(self.view, 0))
                else:
                    return Region(s.a, next_non_blank(self.view, 0))
            elif mode == INTERNAL_NORMAL:
                return Region(view.full_line(s.b).b, 0)
            elif mode == VISUAL_LINE:
                if s.a < s.b:
                    return Region(s.b, 0)
                else:
                    return Region(s.a, 0)
            return s

        jumplist_update(self.view)
        regions_transformer(self.view, f)
        jumplist_update(self.view)


class _vi_go_to_line(ViMotionCommand):
    def run(self, line=None, mode=None):
        line = line if line > 0 else 1
        dest = self.view.text_point(line - 1, 0)

        def f(view, s):
            if mode == NORMAL:
                non_ws = utils.next_non_white_space_char(view, dest)
                return Region(non_ws, non_ws)
            elif mode == INTERNAL_NORMAL:
                start_line = view.full_line(s.a)
                dest_line = view.full_line(dest)
                if start_line.a == dest_line.a:
                    return dest_line
                elif start_line.a < dest_line.a:
                    return Region(start_line.a, dest_line.b)
                else:
                    return Region(start_line.b, dest_line.a)
            elif mode == VISUAL:
                if dest < s.a and s.a < s.b:
                    return Region(s.a + 1, dest)
                elif dest < s.a:
                    return Region(s.a, dest)
                elif dest > s.b and s.a > s.b:
                    return Region(s.a - 1, dest + 1)
                return Region(s.a, dest + 1)
            elif mode == VISUAL_LINE:
                if dest < s.a and s.a < s.b:
                    return Region(view.full_line(s.a).b, dest)
                elif dest < s.a:
                    return Region(s.a, dest)
                elif dest > s.a and s.a > s.b:
                    return Region(view.full_line(s.a - 1).a, view.full_line(dest).b)
                return Region(s.a, view.full_line(dest).b)
            return s

        jumplist_update(self.view)
        regions_transformer(self.view, f)
        jumplist_update(self.view)

        # FIXME: Bringing the selections into view will be undesirable in many cases. Maybe we
        # should have an optional .scroll_selections_into_view() step during command execution.
        self.view.show(self.view.sel()[0])


class _vi_big_g(ViMotionCommand):
    def run(self, mode=None, count=None):
        def f(view, s):
            if mode == NORMAL:
                eof_line = view.line(eof)
                if not eof_line.empty():
                    return Region(next_non_blank(self.view, eof_line.a))

                return Region(eof_line.a)
            elif mode == VISUAL:
                eof_line = view.line(eof)
                if not eof_line.empty():
                    return Region(s.a, next_non_blank(self.view, eof_line.a) + 1)

                return Region(s.a, eof_line.a)
            elif mode == INTERNAL_NORMAL:
                return Region(max(0, view.line(s.b).a), eof)
            elif mode == VISUAL_LINE:
                return Region(s.a, eof)

            return s

        jumplist_update(self.view)
        eof = self.view.size()
        regions_transformer(self.view, f)
        jumplist_update(self.view)


class _vi_dollar(ViMotionCommand):
    def run(self, mode=None, count=1):
        def f(view, s):
            target = resolve_insertion_point_at_b(s)
            if count > 1:
                target = row_to_pt(view, row_at(view, target) + (count - 1))

            eol = view.line(target).b

            if mode == NORMAL:
                return Region(eol if view.line(eol).empty() else (eol - 1))

            elif mode == VISUAL:
                # TODO is this really a special case? can we not include this
                # case in .resize_visual_region()?
                # Perhaps we should always ensure that a minimal visual sel
                # was always such that .a < .b?
                if (s.a == eol) and not view.line(eol).empty():
                    return Region(s.a - 1, eol + 1)

                return resize_visual_region(s, eol)

            elif mode == INTERNAL_NORMAL:
                # TODO perhaps create a .is_linewise_motion() helper?
                if get_bol(view, s.a) == s.a:
                    return Region(s.a, eol + 1)

                return Region(s.a, eol)

            elif mode == VISUAL_LINE:
                # TODO: Implement this. Not too useful, though.
                return s

            return s

        regions_transformer(self.view, f)


class _vi_w(ViMotionCommand):
    def run(self, mode=None, count=1):
        def f(view, s):
            if mode == NORMAL:
                pt = units.word_starts(view, start=s.b, count=count)
                if ((pt == view.size()) and (not view.line(pt).empty())):
                    pt = utils.previous_non_white_space_char(view, pt - 1, white_space='\n')

                return Region(pt, pt)

            elif mode in (VISUAL, VISUAL_BLOCK):
                start = (s.b - 1) if (s.a < s.b) else s.b
                pt = units.word_starts(view, start=start, count=count)

                if (s.a > s.b) and (pt >= s.a):
                    return Region(s.a - 1, pt + 1)
                elif s.a > s.b:
                    return Region(s.a, pt)
                elif view.size() == pt:
                    pt -= 1

                return Region(s.a, pt + 1)

            elif mode == INTERNAL_NORMAL:
                a = s.a
                pt = units.word_starts(view, start=s.b, count=count, internal=True)
                if (not view.substr(view.line(s.a)).strip() and view.line(s.b) != view.line(pt)):
                    a = view.line(s.a).a

                return Region(a, pt)

            return s

        regions_transformer(self.view, f)


class _vi_big_w(ViMotionCommand):
    def run(self, mode=None, count=1):
        def f(view, s):
            if mode == NORMAL:
                pt = units.big_word_starts(view, start=s.b, count=count)
                if ((pt == view.size()) and (not view.line(pt).empty())):
                    pt = utils.previous_non_white_space_char(view, pt - 1, white_space='\n')

                return Region(pt, pt)

            elif mode == VISUAL:
                pt = units.big_word_starts(view, start=s.b - 1, count=count)
                if s.a > s.b and pt >= s.a:
                    return Region(s.a - 1, pt + 1)
                elif s.a > s.b:
                    return Region(s.a, pt)
                elif (view.size() == pt):
                    pt -= 1

                return Region(s.a, pt + 1)

            elif mode == INTERNAL_NORMAL:
                a = s.a
                pt = units.big_word_starts(view, start=s.b, count=count, internal=True)
                if (not view.substr(view.line(s.a)).strip() and view.line(s.b) != view.line(pt)):
                    a = view.line(s.a).a

                return Region(a, pt)

            return s

        regions_transformer(self.view, f)


class _vi_e(ViMotionCommand):
    def run(self, mode=None, count=1):
        def f(view, s):
            if mode == NORMAL:
                pt = units.word_ends(view, start=s.b, count=count)
                return Region(pt - 1)

            elif mode == VISUAL:
                pt = units.word_ends(view, start=s.b - 1, count=count)
                if (s.a > s.b) and (pt >= s.a):
                    return Region(s.a - 1, pt)
                elif (s.a > s.b):
                    return Region(s.a, pt)

                return Region(s.a, pt)

            elif mode == INTERNAL_NORMAL:
                a = s.a
                pt = units.word_ends(view, start=s.b, count=count)
                if (not view.substr(view.line(s.a)).strip() and view.line(s.b) != view.line(pt)):
                    a = view.line(s.a).a

                return Region(a, pt)

            return s

        regions_transformer(self.view, f)


class _vi_zero(ViMotionCommand):
    def run(self, mode=None, count=1):
        def f(view, s):
            if mode == NORMAL:
                return Region(view.line(s.b).a)
            elif mode == INTERNAL_NORMAL:
                return Region(s.a, view.line(s.b).a)
            elif mode == VISUAL:
                if s.a < s.b:
                    line = view.line(s.b)
                    if s.a > line.a:
                        return Region(s.a + 1, line.a)
                    else:
                        return Region(s.a, line.a + 1)
                else:
                    return Region(s.a, view.line(s.b).a)

            return s

        regions_transformer(self.view, f)


class _vi_right_brace(ViMotionCommand):
    def run(self, mode=None, count=1):
        def f(view, s):
            if mode == NORMAL:
                par_begin = units.next_paragraph_start(view, s.b, count)
                # find the next non-empty row if needed
                return Region(par_begin)

            elif mode == VISUAL:
                next_start = units.next_paragraph_start(view, s.b, count, skip_empty=count > 1)

                return resize_visual_region(s, next_start)

            # TODO Delete previous ws in remaining start line.
            elif mode == INTERNAL_NORMAL:
                par_begin = units.next_paragraph_start(view, s.b, count, skip_empty=count > 1)
                if par_begin == (self.view.size() - 1):
                    return Region(s.a, self.view.size())
                if view.substr(s.a - 1) == '\n' or s.a == 0:
                    return Region(s.a, par_begin)

                return Region(s.a, par_begin - 1)

            elif mode == VISUAL_LINE:
                par_begin = units.next_paragraph_start(view, s.b, count, skip_empty=count > 1)
                if s.a <= s.b:
                    return Region(s.a, par_begin + 1)
                else:
                    if par_begin > s.a:
                        return Region(view.line(s.a - 1).a, par_begin + 1)

                    return Region(s.a, par_begin)

            return s

        regions_transformer(self.view, f)


class _vi_left_brace(ViMotionCommand):
    def run(self, mode=None, count=1):
        def f(view, s):
            # TODO: must skip empty paragraphs.
            start = utils.previous_non_white_space_char(view, s.b - 1, white_space='\n \t')
            par_as_region = view.expand_by_class(start, CLASS_EMPTY_LINE)

            if mode == NORMAL:
                next_start = units.prev_paragraph_start(view, s.b, count)
                return Region(next_start)

            elif mode == VISUAL:
                next_start = units.prev_paragraph_start(view, s.b, count)
                return resize_visual_region(s, next_start)

            elif mode == INTERNAL_NORMAL:
                next_start = units.prev_paragraph_start(view, s.b, count)
                return Region(s.a, next_start)

            elif mode == VISUAL_LINE:
                if s.a <= s.b:
                    if par_as_region.a < s.a:
                        return Region(view.full_line(s.a).b, par_as_region.a)
                    return Region(s.a, par_as_region.a + 1)
                else:
                    return Region(s.a, par_as_region.a)

            return s

        regions_transformer(self.view, f)


class _vi_percent(ViMotionCommand):

    pairs = (
        ('(', ')'),
        ('[', ']'),
        ('{', '}'),
        ('<', '>'),
    )

    def find_tag(self, pt):
        # Args:
        #   pt (int)
        #
        # Returns:
        #   Region|None
        if (self.view.score_selector(0, 'text.html') == 0 and self.view.score_selector(0, 'text.xml') == 0):
            return None

        if any([self.view.substr(pt) in p for p in self.pairs]):
            return None

        _, closest_tag = get_closest_tag(self.view, pt)
        if not closest_tag:
            return None

        if closest_tag.contains(pt):
            begin_tag, end_tag, _ = find_containing_tag(self.view, pt)
            if begin_tag:
                return begin_tag if end_tag.contains(pt) else end_tag

        return None

    def run(self, percent=None, mode=None):
        # Args:
        #   percent (int): Percentage down in file.
        #   mode: (str)
        if percent is None:
            def move_to_bracket(view, s):
                def find_bracket_location(region):
                    # Args:
                    #   region (Region)
                    #
                    # Returns:
                    #   int|None
                    pt = region.b
                    if (region.size() > 0) and (region.b > region.a):
                        pt = region.b - 1

                    tag = self.find_tag(pt)
                    if tag:
                        return tag.a

                    bracket, brackets, bracket_pt = self.find_a_bracket(pt)
                    if not bracket:
                        return

                    if bracket == brackets[0]:
                        return self.find_balanced_closing_bracket(bracket_pt + 1, brackets)
                    else:
                        return self.find_balanced_opening_bracket(bracket_pt, brackets)

                if mode == VISUAL:
                    found = find_bracket_location(s)
                    if found is not None:
                        # Offset by 1 if s.a was upperbound but begin is not
                        begin = (s.a - 1) if (s.b < s.a and (s.a - 1) < found) else s.a
                        # Offset by 1 if begin is now upperbound but s.a was not
                        begin = (s.a + 1) if (found < s.a and s.a < s.b) else begin

                        # Testing against adjusted begin
                        end = (found + 1) if (begin <= found) else found

                        return Region(begin, end)

                if mode == VISUAL_LINE:

                    sel = s
                    if sel.a > sel.b:
                        # If selection is in reverse: b <-- a
                        # Find bracket starting at end of line of point b
                        target_pt = find_bracket_location(Region(sel.b, self.view.line(sel.b).end()))
                    else:
                        # If selection is forward: a --> b
                        # Find bracket starting at point b - 1:
                        #   Because point b for an a --> b VISUAL LINE selection
                        #   is the eol (newline) character.
                        target_pt = find_bracket_location(Region(sel.a, sel.b - 1))

                    if target_pt is not None:
                        target_full_line = self.view.full_line(target_pt)

                        if sel.a > sel.b:
                            # If REVERSE selection: b <-- a

                            if target_full_line.a > sel.a:
                                # If target is after start of selection: b <-- a --> t
                                # Keep line a, extend to end of target, and reverse: a --> t
                                a, b = self.view.line(sel.a - 1).a, target_full_line.b
                            else:
                                # If target is before or after end of selection:
                                #   Before: b     t <-- a (subtract t --> b)
                                #   After:  t <-- b <-- a (extend b --> t)
                                a, b = sel.a, target_full_line.a

                        else:
                            # If FORWARD selection: a --> b

                            if target_full_line.a < sel.a:
                                # If target is before start of selection: t <-- a --> b
                                # Keep line a, extend to start of target, and reverse: t <-- a
                                a, b = self.view.full_line(sel.a).b, target_full_line.a
                            else:
                                # If target is before or after end of selection:
                                #   Before: a --> t     b (subtract t --> b)
                                #   After:  a --> b --> t (extend b --> t)
                                a, b = s.a, target_full_line.b

                        return Region(a, b)

                elif mode == NORMAL:
                    a = find_bracket_location(s)
                    if a is not None:
                        return Region(a, a)

                # TODO: According to Vim we must swallow brackets in this case.
                elif mode == INTERNAL_NORMAL:
                    found = find_bracket_location(s)
                    if found is not None:
                        if found < s.a:
                            return Region(s.a + 1, found)
                        else:
                            return Region(s.a, found + 1)

                return s

            regions_transformer(self.view, move_to_bracket)

        else:

            row = self.view.rowcol(self.view.size())[0] * (percent / 100)

            def f(view, s):
                return Region(view.text_point(row, 0))

            regions_transformer(self.view, f)

            # FIXME Bringing the selections into view will be undesirable in many cases. Maybe we should have an optional .scroll_selections_into_view() step during command execution.  # noqa: E501
            self.view.show(self.view.sel()[0])

    def find_a_bracket(self, caret_pt):
        """
        Locate the next bracket after the caret in the current line.

        If None is found, execution must be aborted.

        Return (bracket, brackets, bracket_pt).

        Example ('(', ('(', ')'), 1337)).
        """
        caret_row, caret_col = self.view.rowcol(caret_pt)
        line_text = self.view.substr(Region(caret_pt, self.view.line(caret_pt).b))
        try:
            found_brackets = min([(line_text.index(bracket), bracket)
                                 for bracket in chain(*self.pairs)
                                 if bracket in line_text])
        except ValueError:
            return None, None, None

        bracket_a, bracket_b = [(a, b) for (a, b) in self.pairs if found_brackets[1] in (a, b)][0]
        return (found_brackets[1], (bracket_a, bracket_b),
                self.view.text_point(caret_row, caret_col + found_brackets[0]))

    def find_balanced_closing_bracket(self, start, brackets, unbalanced=0):
        # Returns:
        #   Region|None
        new_start = start
        for i in range(unbalanced or 1):
            next_closing_bracket = find_in_range(
                self.view,
                brackets[1],
                start=new_start,
                end=self.view.size(),
                flags=LITERAL
            )

            if next_closing_bracket is None:  # Unbalanced brackets; nothing we can do.
                return

            new_start = next_closing_bracket.end()

        nested = 0
        while True:
            next_opening_bracket = find_in_range(
                self.view,
                brackets[0],
                start=start,
                end=next_closing_bracket.end(),
                flags=LITERAL
            )

            if not next_opening_bracket:
                break

            nested += 1
            start = next_opening_bracket.end()

        if nested > 0:
            return self.find_balanced_closing_bracket(
                next_closing_bracket.end(),
                brackets,
                nested
            )
        else:
            return next_closing_bracket.begin()

    def find_balanced_opening_bracket(self, start, brackets, unbalanced=0):
        new_start = start
        for i in range(unbalanced or 1):
            prev_opening_bracket = reverse_search_by_pt(self.view, brackets[0],
                                                        start=0,
                                                        end=new_start,
                                                        flags=LITERAL)
            if prev_opening_bracket is None:
                # Unbalanced brackets; nothing we can do.
                return
            new_start = prev_opening_bracket.begin()

        nested = 0
        while True:
            next_closing_bracket = reverse_search_by_pt(self.view, brackets[1],
                                                        start=prev_opening_bracket.a,
                                                        end=start,
                                                        flags=LITERAL)
            if not next_closing_bracket:
                break
            nested += 1
            start = next_closing_bracket.begin()

        if nested > 0:
            return self.find_balanced_opening_bracket(prev_opening_bracket.begin(),
                                                      brackets,
                                                      nested)
        else:
            return prev_opening_bracket.begin()


def highlow_visible_rows(view):
    visible_region = view.visible_region()
    highest_visible_row = view.rowcol(visible_region.a)[0]
    lowest_visible_row = view.rowcol(visible_region.b - 1)[0]

    # To avoid scrolling when we move to the highest visible row, we need to
    # check if the row is fully visible or only partially visible. If the row is
    # only partially visible we will move to next one.

    line_height = view.line_height()
    view_position = view.viewport_position()
    viewport_extent = view.viewport_extent()

    # The extent y position needs an additional "1.0" to its height. It's not
    # clear why Sublime needs to add it, but it always adds it.

    highest_position = (highest_visible_row * line_height) + 1.0
    if highest_position < view_position[1]:
        highest_visible_row += 1

    lowest_position = ((lowest_visible_row + 1) * line_height) + 1.0
    if lowest_position > (view_position[1] + viewport_extent[1]):
        lowest_visible_row -= 1

    return (highest_visible_row, lowest_visible_row)


def highest_visible_pt(view):
    return view.text_point(highlow_visible_rows(view)[0], 0)


def lowest_visible_pt(view):
    return view.text_point(highlow_visible_rows(view)[1], 0)


class _vi_big_h(ViMotionCommand):
    def run(self, count=None, mode=None):
        def f(view, s):
            if mode == NORMAL:
                return Region(target_pt)
            elif mode == INTERNAL_NORMAL:
                return Region(s.a, target_pt)
            elif mode == VISUAL:
                if s.a < s.b and target_pt < s.a:
                    return Region(s.a + 1, target_pt)
                return Region(s.a, target_pt)
            elif mode == VISUAL_LINE:
                if s.b > s.a and target_pt <= s.a:
                    a = self.view.full_line(s.a).b
                    b = self.view.line(target_pt).a
                elif s.b > s.a:
                    a = s.a
                    b = self.view.full_line(target_pt).b
                else:
                    a = s.a
                    b = self.view.line(target_pt).a

                return Region(a, b)

            return s

        target_pt = next_non_blank(self.view, highest_visible_pt(self.view))
        regions_transformer(self.view, f)


class _vi_big_l(ViMotionCommand):
    def run(self, count=None, mode=None):
        def f(view, s):
            if mode == NORMAL:
                return Region(target_pt)
            elif mode == INTERNAL_NORMAL:
                if s.b >= target_pt:
                    return Region(s.a + 1, target_pt)

                return Region(s.a, target_pt)
            elif mode == VISUAL:
                if s.a > s.b and target_pt > s.a:
                    return Region(s.a - 1, target_pt + 1)

                return Region(s.a, target_pt + 1)
            elif mode == VISUAL_LINE:
                if s.a > s.b and target_pt >= s.a:
                    a = self.view.line(s.a - 1).a
                    b = self.view.full_line(target_pt).b
                elif s.a > s.b:
                    a = self.view.line(target_pt).a
                    b = s.a
                else:
                    a = s.a
                    b = self.view.full_line(target_pt).b

                return Region(a, b)
            else:
                return s

        target_pt = next_non_blank(self.view, lowest_visible_pt(self.view))
        regions_transformer(self.view, f)


class _vi_big_m(ViMotionCommand):
    def run(self, count=None, extend=False, mode=None):
        def f(view, s):
            if mode == NORMAL:
                return Region(target_pt)
            elif mode == INTERNAL_NORMAL:
                return Region(s.a, target_pt)
            elif mode == VISUAL_LINE:
                if s.b > s.a:
                    if target_pt < s.a:
                        a = self.view.full_line(s.a).b
                        b = self.view.line(target_pt).a
                    else:
                        a = s.a
                        b = self.view.full_line(target_pt).b
                else:
                    if target_pt >= s.a:
                        a = self.view.line(s.a - 1).a
                        b = self.view.full_line(target_pt).b
                    else:
                        a = s.a
                        b = self.view.full_line(target_pt).a

                return Region(a, b)
            elif mode == VISUAL:
                a = s.a
                b = target_pt

                if s.b > s.a and target_pt < s.a:
                    a += 1
                elif s.a > s.b and target_pt > s.a:
                    a -= 1
                    b += 1
                elif s.b > s.a:
                    b += 1

                return Region(a, b)
            else:
                return s

        highest_row, lowest_row = highlow_visible_rows(self.view)
        half_visible_lines = (lowest_row - highest_row) // 2
        middle_row = highest_row + half_visible_lines
        target_pt = next_non_blank(self.view, self.view.text_point(middle_row, 0))
        regions_transformer(self.view, f)


class _vi_star(ViMotionCommand, ExactWordBufferSearchBase):
    def run(self, count=1, mode=None, search_string=None):
        def f(view, s):
            pattern = self.build_pattern(query)
            flags = self.calculate_flags(query)

            if mode == INTERNAL_NORMAL:
                match = find_wrapping(view,
                                      term=pattern,
                                      start=view.word(s.end()).end(),
                                      end=view.size(),
                                      flags=flags,
                                      times=1)
            else:
                match = find_wrapping(view,
                                      term=pattern,
                                      start=view.word(s.end()).end(),
                                      end=view.size(),
                                      flags=flags,
                                      times=1)

            if match:
                if mode == INTERNAL_NORMAL:
                    return Region(s.a, match.begin())
                elif mode == VISUAL:
                    return Region(s.a, match.begin())
                elif mode == NORMAL:
                    return Region(match.begin(), match.begin())

            elif mode == NORMAL:
                pt = view.word(s.end()).begin()
                return Region(pt)

            return s

        state = self.state
        query = search_string or self.get_query()

        jumplist_update(self.view)
        regions_transformer(self.view, f)
        jumplist_update(self.view)

        if query:
            self.hilite(query)
            # Ensure n and N can repeat this search later.
            state.last_buffer_search = query

        if not search_string:
            state.last_buffer_search_command = 'vi_star'

        show_if_not_visible(self.view)


class _vi_octothorp(ViMotionCommand, ExactWordBufferSearchBase):
    def run(self, count=1, mode=None, search_string=None):
        def f(view, s):
            pattern = self.build_pattern(query)
            flags = self.calculate_flags(query)

            if mode == INTERNAL_NORMAL:
                match = reverse_find_wrapping(view,
                                              term=pattern,
                                              start=0,
                                              end=start_sel.a,
                                              flags=flags,
                                              times=1)
            else:
                match = reverse_find_wrapping(view,
                                              term=pattern,
                                              start=0,
                                              end=start_sel.a,
                                              flags=flags,
                                              times=1)

            if match:
                if mode == INTERNAL_NORMAL:
                    return Region(s.b, match.begin())
                elif mode == VISUAL:
                    return Region(s.b, match.begin())
                elif mode == NORMAL:
                    return Region(match.begin(), match.begin())

            elif mode == NORMAL:
                pt = utils.previous_white_space_char(view, s.b)
                return Region(pt + 1)

            return s

        state = self.state

        query = search_string or self.get_query()

        jumplist_update(self.view)
        start_sel = self.view.sel()[0]
        regions_transformer(self.view, f)
        jumplist_update(self.view)

        if query:
            self.hilite(query)
            # Ensure n and N can repeat this search later.
            state.last_buffer_search = query

        if not search_string:
            state.last_buffer_search_command = 'vi_octothorp'

        show_if_not_visible(self.view)


class _vi_b(ViMotionCommand):
    def run(self, mode=None, count=1):
        def do_motion(view, s):
            if mode == NORMAL:
                pt = word_reverse(self.view, s.b, count)
                return Region(pt)

            elif mode == INTERNAL_NORMAL:
                pt = word_reverse(self.view, s.b, count)
                return Region(s.a, pt)

            elif mode in (VISUAL, VISUAL_BLOCK):
                if s.a < s.b:
                    pt = word_reverse(self.view, s.b - 1, count)
                    if pt < s.a:
                        return Region(s.a + 1, pt)
                    return Region(s.a, pt + 1)
                elif s.b < s.a:
                    pt = word_reverse(self.view, s.b, count)
                    return Region(s.a, pt)

            return s

        regions_transformer(self.view, do_motion)


class _vi_big_b(ViMotionCommand):
    # TODO: Reimplement this.
    def run(self, count=1, mode=None):
        def do_motion(view, s):
            if mode == NORMAL:
                pt = word_reverse(self.view, s.b, count, big=True)
                return Region(pt)

            elif mode == INTERNAL_NORMAL:
                pt = word_reverse(self.view, s.b, count, big=True)
                return Region(s.a, pt)

            elif mode in (VISUAL, VISUAL_BLOCK):
                if s.a < s.b:
                    pt = word_reverse(self.view, s.b - 1, count, big=True)
                    if pt < s.a:
                        return Region(s.a + 1, pt)
                    return Region(s.a, pt + 1)
                elif s.b < s.a:
                    pt = word_reverse(self.view, s.b, count, big=True)
                    return Region(s.a, pt)

            return s

        regions_transformer(self.view, do_motion)


class _vi_underscore(ViMotionCommand):
    def run(self, count=None, mode=None):
        def f(view, s):
            a = s.a
            b = s.b
            if s.size() > 0:
                a = resolve_insertion_point_at_a(s)
                b = resolve_insertion_point_at_b(s)

            current_row = self.view.rowcol(b)[0]
            target_row = current_row + (count - 1)
            last_row = self.view.rowcol(self.view.size() - 1)[0]

            if target_row > last_row:
                target_row = last_row

            bol = self.view.text_point(target_row, 0)

            if mode == NORMAL:
                bol = next_non_white_space_char(self.view, bol)
                return Region(bol)

            elif mode == INTERNAL_NORMAL:
                # TODO: differentiate between 'd' and 'c'
                begin = self.view.line(b).a
                target_row_bol = self.view.text_point(target_row, 0)
                end = self.view.line(target_row_bol).b

                # XXX: There may be better ways to communicate between actions
                # and motions than by inspecting state.
                if isinstance(self.state.action, cmd_defs.ViChangeByChars):
                    return Region(begin, end)
                else:
                    return Region(begin, end + 1)

            elif mode == VISUAL:
                bol = next_non_white_space_char(self.view, bol)
                return utils.new_inclusive_region(a, bol)
            else:
                return s

        regions_transformer(self.view, f)


class _vi_hat(ViMotionCommand):
    def run(self, count=None, mode=None):
        def f(view, s):
            a = s.a
            b = s.b
            if s.size() > 0:
                a = resolve_insertion_point_at_a(s)
                b = resolve_insertion_point_at_b(s)

            bol = self.view.line(b).a
            bol = next_non_white_space_char(self.view, bol)

            if mode == NORMAL:
                return Region(bol)
            elif mode == INTERNAL_NORMAL:
                # The character at the "end" of the region is skipped in both
                # forward and reverse cases, so unlike other regions, no need to add 1 to it
                return Region(a, bol)
            elif mode == VISUAL:
                return utils.new_inclusive_region(a, bol)
            else:
                return s

        regions_transformer(self.view, f)


class _vi_gj(ViMotionCommand):
    def run(self, mode=None, count=1):
        if mode == NORMAL:
            for i in range(count):
                self.view.run_command('move', {'by': 'lines', 'forward': True, 'extend': False})
        elif mode == VISUAL:
            for i in range(count):
                self.view.run_command('move', {'by': 'lines', 'forward': True, 'extend': True})
        elif mode == VISUAL_LINE:
            self.view.run_command('_vi_j', {'mode': mode, 'count': count})
        elif mode == INTERNAL_NORMAL:
            for i in range(count):
                self.view.run_command('move', {'by': 'lines', 'forward': True, 'extend': False})


class _vi_gk(ViMotionCommand):
    def run(self, mode=None, count=1):
        if mode == NORMAL:
            for i in range(count):
                self.view.run_command('move', {'by': 'lines', 'forward': False, 'extend': False})
        elif mode == VISUAL:
            for i in range(count):
                self.view.run_command('move', {'by': 'lines', 'forward': False, 'extend': True})
        elif mode == VISUAL_LINE:
            self.view.run_command('_vi_k', {'mode': mode, 'count': count})
        elif mode == INTERNAL_NORMAL:
            for i in range(count):
                self.view.run_command('move', {'by': 'lines', 'forward': False, 'extend': False})


class _vi_g__(ViMotionCommand):
    def run(self, count=1, mode=None):
        def f(view, s):
            if mode == NORMAL:
                eol = view.line(s.b).b
                return Region(eol - 1, eol - 1)
            elif mode == VISUAL:
                eol = None
                if s.a < s.b:
                    eol = view.line(s.b - 1).b
                    return Region(s.a, eol)
                else:
                    eol = view.line(s.b).b
                    if eol > s.a:
                        return Region(s.a - 1, eol)
                    return Region(s.a, eol)

            elif mode == INTERNAL_NORMAL:
                eol = view.line(s.b).b
                return Region(s.a, eol)

            return s

        regions_transformer(self.view, f)


def _get_option_scroll(view):
    line_height = view.line_height()
    viewport_extent = view.viewport_extent()
    line_count = viewport_extent[1] / line_height
    number_of_scroll_lines = line_count / 2

    return int(number_of_scroll_lines)


def _scroll_viewport_position(view, number_of_scroll_lines, forward=True):
    x, y = view.viewport_position()

    y_addend = ((number_of_scroll_lines) * view.line_height())

    if forward:
        viewport_position = (x, y + y_addend)
    else:
        viewport_position = (x, y - y_addend)

    view.set_viewport_position(viewport_position, animate=False)


def _get_scroll_target(view, number_of_scroll_lines, forward=True):
    s = view.sel()[0]

    if forward:
        if s.b > s.a and view.substr(s.b - 1) == '\n':
            sel_row, sel_col = view.rowcol(s.b - 1)
        else:
            sel_row, sel_col = view.rowcol(s.b)

        target_row = sel_row + number_of_scroll_lines

        # Ignore the last line if it's a blank line. In Sublime the last
        # character is a NULL character point ('\x00'). We don't need to check
        # that it's NULL, just backup one point and retrieve that row and col.
        last_line_row, last_line_col = view.rowcol(view.size() - 1)

        # Ensure the target does not overflow the bottom of the buffer.
        if target_row >= last_line_row:
            target_row = last_line_row
    else:
        if s.b > s.a and view.substr(s.b - 1) == '\n':
            sel_row, sel_col = view.rowcol(s.b - 1)
        else:
            sel_row, sel_col = view.rowcol(s.b)

        target_row = sel_row - number_of_scroll_lines

        # Ensure the target does not overflow the top of the buffer.
        if target_row <= 0:
            target_row = 0

    # Return nothing to indicate there no need to scroll.
    if sel_row == target_row:
        return

    target_pt = next_non_blank(view, view.text_point(target_row, 0))

    return target_pt


def _get_scroll_up_target_pt(view, number_of_scroll_lines):
    return _get_scroll_target(view, number_of_scroll_lines, forward=False)


def _get_scroll_down_target_pt(view, number_of_scroll_lines):
    return _get_scroll_target(view, number_of_scroll_lines, forward=True)


class _vi_ctrl_u(ViMotionCommand):

    def run(self, count=0, mode=None):
        def f(view, s):
            if mode == NORMAL:
                return Region(scroll_target_pt)
            elif mode == VISUAL:
                a = s.a
                b = scroll_target_pt

                if s.b > s.a:
                    if scroll_target_pt < s.a:
                        a += 1
                    else:
                        b += 1

                return Region(a, b)

                if s.a < s.b and scroll_target_pt < s.a:
                    return Region(min(s.a + 1, self.view.size()), scroll_target_pt)
                return Region(s.a, scroll_target_pt)

            elif mode == INTERNAL_NORMAL:
                return Region(s.a, scroll_target_pt)
            elif mode == VISUAL_LINE:
                if s.b > s.a:
                    if scroll_target_pt < s.a:
                        a = self.view.full_line(s.a).b
                        b = self.view.line(scroll_target_pt).a
                    else:
                        a = self.view.line(s.a).a
                        b = self.view.full_line(scroll_target_pt).b
                else:
                    a = s.a
                    b = self.view.line(scroll_target_pt).a

                return Region(a, b)
            return s

        number_of_scroll_lines = count if count >= 1 else _get_option_scroll(self.view)
        scroll_target_pt = _get_scroll_up_target_pt(self.view, number_of_scroll_lines)
        if scroll_target_pt is None:
            return ui_blink()

        regions_transformer(self.view, f)
        if not self.view.visible_region().contains(0):
            _scroll_viewport_position(self.view, number_of_scroll_lines, forward=False)


class _vi_ctrl_d(ViMotionCommand):

    def run(self, count=0, mode=None):
        def f(view, s):
            if mode == NORMAL:
                return Region(scroll_target_pt)
            elif mode == VISUAL:
                a = s.a
                b = scroll_target_pt

                if s.b > s.a:
                    b += 1
                elif scroll_target_pt >= s.a:
                    a -= 1
                    b += 1

                return Region(a, b)
            elif mode == INTERNAL_NORMAL:
                return Region(s.a, scroll_target_pt)
            elif mode == VISUAL_LINE:
                if s.a > s.b:
                    if scroll_target_pt >= s.a:
                        a = self.view.line(s.a - 1).a
                        b = self.view.full_line(scroll_target_pt).b
                    else:
                        a = s.a
                        b = self.view.line(scroll_target_pt).a
                else:
                    a = s.a
                    b = self.view.full_line(scroll_target_pt).b

                return Region(a, b)

            return s

        number_of_scroll_lines = count if count >= 1 else _get_option_scroll(self.view)
        scroll_target_pt = _get_scroll_down_target_pt(self.view, number_of_scroll_lines)
        if scroll_target_pt is None:
            return ui_blink()

        regions_transformer(self.view, f)
        if not self.view.visible_region().contains(self.view.size()):
            _scroll_viewport_position(self.view, number_of_scroll_lines)


class _vi_pipe(ViMotionCommand):

    def _col_to_pt(self, pt, current_col):
        if self.view.line(pt).size() < current_col:
            return self.view.line(pt).b - 1

        row = self.view.rowcol(pt)[0]

        return self.view.text_point(row, current_col) - 1

    def run(self, mode=None, count=1):
        def f(view, s):
            if mode == NORMAL:
                return Region(self._col_to_pt(s.b, count))
            elif mode == VISUAL:
                pt = self._col_to_pt(s.b - 1, count)
                if s.a < s.b:
                    if pt < s.a:
                        return Region(s.a + 1, pt)
                    else:
                        return Region(s.a, pt + 1)
                else:
                    if pt > s.a:
                        return Region(s.a - 1, pt + 1)
                    else:
                        return Region(s.a, pt)

            elif mode == INTERNAL_NORMAL:
                pt = self._col_to_pt(s.b, count)

                if s.a < s.b:
                    return Region(s.a, pt)
                else:
                    return Region(s.a + 1, pt)

            return s

        regions_transformer(self.view, f)


class _vi_ge(ViMotionCommand):
    def run(self, mode=None, count=1):
        def to_word_end(view, s):
            if mode == NORMAL:
                pt = word_end_reverse(view, s.b, count)
                return Region(pt)
            elif mode in (VISUAL, VISUAL_BLOCK):
                if s.a < s.b:
                    pt = word_end_reverse(view, s.b - 1, count)
                    if pt > s.a:
                        return Region(s.a, pt + 1)
                    return Region(s.a + 1, pt)
                pt = word_end_reverse(view, s.b, count)
                return Region(s.a, pt)
            return s

        regions_transformer(self.view, to_word_end)


class _vi_g_big_e(ViMotionCommand):
    def run(self, mode=None, count=1):
        def to_word_end(view, s):
            if mode == NORMAL:
                pt = word_end_reverse(view, s.b, count, big=True)
                return Region(pt)
            elif mode in (VISUAL, VISUAL_BLOCK):
                if s.a < s.b:
                    pt = word_end_reverse(view, s.b - 1, count, big=True)
                    if pt > s.a:
                        return Region(s.a, pt + 1)
                    return Region(s.a + 1, pt)
                pt = word_end_reverse(view, s.b, count, big=True)
                return Region(s.a, pt)
            return s

        regions_transformer(self.view, to_word_end)


class _vi_left_paren(ViMotionCommand):

    def run(self, mode=None, count=1):
        def f(view, s):
            previous_sentence = find_sentences_backward(self.view, s, count)
            if previous_sentence is None:
                return s

            if mode == NORMAL:
                return Region(previous_sentence.a)
            elif mode == VISUAL:
                return Region(s.a + 1, previous_sentence.a + 1)
            elif mode == INTERNAL_NORMAL:
                return Region(s.a, previous_sentence.a + 1)

            return s

        regions_transformer(self.view, f)


class _vi_right_paren(ViMotionCommand):

    def run(self, mode=None, count=1):
        def f(view, s):
            next_sentence = find_sentences_forward(self.view, s, count)
            if next_sentence is None:
                return s

            if mode == NORMAL:
                return Region(min(next_sentence.b, view.size() - 1))
            elif mode == VISUAL:
                return Region(s.a, min(next_sentence.b + 1, view.size() - 1))
            elif mode == INTERNAL_NORMAL:
                return Region(s.a, next_sentence.b)

            return s

        regions_transformer(self.view, f)


class _vi_question_mark_impl(ViMotionCommand, BufferSearchBase):
    def run(self, search_string, mode=None, count=1, extend=False):
        def f(view, s):
            if mode == VISUAL:
                return Region(s.end(), found.a)
            elif mode == INTERNAL_NORMAL:
                return Region(s.end(), found.a)
            elif mode == NORMAL:
                return Region(found.a, found.a)
            elif mode == VISUAL_LINE:
                return Region(s.end(), view.full_line(found.a).a)

            return s

        # This happens when we attempt to repeat the search and there's no
        # search term stored yet.
        if search_string is None:
            return

        flags = self.calculate_flags(search_string)
        # FIXME: What should we do here? Case-sensitive or case-insensitive search? Configurable?
        found = reverse_find_wrapping(self.view,
                                      term=search_string,
                                      start=0,
                                      end=self.view.sel()[0].b,
                                      flags=flags,
                                      times=count)

        if not found:
            return console_message('Pattern not found')

        regions_transformer(self.view, f)
        self.hilite(search_string)


class _vi_question_mark(ViMotionCommand, BufferSearchBase):

    def run(self):
        self.state.reset_during_init = False

        # TODO Add incsearch option e.g. on_change = self.on_change if 'incsearch' else None

        ui_cmdline_prompt(
            self.view.window(),
            initial_text='?',
            on_done=self.on_done,
            on_change=self.on_change,
            on_cancel=self.on_cancel)

    def on_done(self, s):
        if len(s) <= 1:
            return

        if s[0] != '?':
            return

        history_update(s)
        _nv_cmdline_feed_key.reset_last_history_index()
        s = s[1:]

        state = self.state
        state.sequence += s + '<CR>'
        self.view.erase_regions('vi_inc_search')
        state.last_buffer_search_command = 'vi_question_mark'
        state.motion = cmd_defs.ViSearchBackwardImpl(term=s)

        # If s is empty, we must repeat the last search.
        state.last_buffer_search = s or state.last_buffer_search
        state.eval()

    def on_change(self, s):
        if s == '':
            return self._force_cancel()

        if len(s) <= 1:
            return

        if s[0] != '?':
            return self._force_cancel()

        s = s[1:]

        flags = self.calculate_flags(s)
        self.view.erase_regions('vi_inc_search')
        state = self.state
        occurrence = reverse_find_wrapping(self.view,
                                           term=s,
                                           start=0,
                                           end=self.view.sel()[0].b,
                                           flags=flags,
                                           times=state.count)
        if occurrence:
            if state.mode == VISUAL:
                occurrence = Region(self.view.sel()[0].a, occurrence.a)

            # The scopes are prefixed with common color scopes so that color
            # schemes have sane default colors. Color schemes can progressively
            # enhance support by using the nv_* scopes.
            self.view.add_regions(
                'vi_inc_search',
                [occurrence],
                scope='support.function neovintageous_search_inc',
                flags=ui_region_flags(self.view.settings().get('neovintageous_search_inc_style'))
            )

            if not self.view.visible_region().contains(occurrence):
                self.view.show(occurrence)

    def _force_cancel(self):
        self.on_cancel()
        self.view.window().run_command('hide_panel', {'cancel': True})

    def on_cancel(self):
        self.view.erase_regions('vi_inc_search')
        state = self.state
        state.reset_command_data()
        _nv_cmdline_feed_key.reset_last_history_index()

        if not self.view.visible_region().contains(self.view.sel()[0]):
            self.view.show(self.view.sel()[0])


class _vi_question_mark_on_parser_done(WindowCommand):

    def run(self, key=None):
        state = State(self.window.active_view())
        state.motion = ViSearchBackwardImpl()
        state.last_buffer_search = (state.motion.inp or state.last_buffer_search)


class _vi_repeat_buffer_search(ViMotionCommand):
    # TODO: This is a jump.
    commands = {
        'vi_slash': ['_vi_slash_impl', '_vi_question_mark_impl'],
        'vi_question_mark': ['_vi_question_mark_impl', '_vi_slash_impl'],
        'vi_star': ['_vi_star', '_vi_octothorp'],
        'vi_octothorp': ['_vi_octothorp', '_vi_star'],
    }

    def run(self, mode=None, count=1, reverse=False):
        state = self.state
        search_string = state.last_buffer_search
        search_command = state.last_buffer_search_command
        command = self.commands[search_command][int(reverse)]

        self.view.run_command(command, {
            'mode': mode,
            'count': count,
            'search_string': search_string
        })

        self.view.show(self.view.sel(), show_surrounds=True)


class _vi_n(ViMotionCommand):
    # TODO: This is a jump.
    def run(self, mode=None, count=1, search_string=''):
        self.view.run_command('_vi_slash_impl', {'mode': mode, 'count': count, 'search_string': search_string})


class _vi_big_n(ViMotionCommand):
    # TODO: This is a jump.
    def run(self, count=1, mode=None, search_string=''):
        self.view.run_command('_vi_question_mark_impl', {'mode': mode, 'count': count, 'search_string': search_string})


class _vi_big_e(ViMotionCommand):
    def run(self, mode=None, count=1):
        def do_move(view, s):
            b = s.b
            if s.a < s.b:
                b = s.b - 1

            pt = units.word_ends(view, b, count=count, big=True)

            if mode == NORMAL:
                return Region(pt - 1)

            elif mode == INTERNAL_NORMAL:
                return Region(s.a, pt)

            elif mode == VISUAL:
                start = s.a
                if s.b < s.a:
                    start = s.a - 1
                end = pt - 1
                if start <= end:
                    return Region(start, end + 1)
                else:
                    return Region(start + 1, end)

            # Untested
            elif mode == VISUAL_BLOCK:
                if s.a > s.b:
                    if pt > s.a:
                        return Region(s.a - 1, pt)
                    return Region(s.a, pt - 1)
                return Region(s.a, pt)

            return s

        regions_transformer(self.view, do_move)


class _vi_ctrl_f(ViMotionCommand):
    def run(self, mode=None, count=1):
        if mode == NORMAL:
            self.view.run_command('move', {'by': 'pages', 'forward': True})
        elif mode == VISUAL:
            self.view.run_command('move', {'by': 'pages', 'forward': True, 'extend': True})
        elif mode == VISUAL_LINE:
            self.view.run_command('move', {'by': 'pages', 'forward': True, 'extend': True})

            new_sels = []
            for sel in self.view.sel():
                line = self.view.full_line(sel.b)
                if sel.b > sel.a:
                    new_sels.append(Region(sel.a, line.end()))
                else:
                    new_sels.append(Region(sel.a, line.begin()))

            if new_sels:
                self.view.sel().clear()
                self.view.sel().add_all(new_sels)


class _vi_ctrl_b(ViMotionCommand):
    def run(self, mode=None, count=1):
        if mode == NORMAL:
            self.view.run_command('move', {'by': 'pages', 'forward': False})
        elif mode == VISUAL:
            self.view.run_command('move', {'by': 'pages', 'forward': False, 'extend': True})
        elif mode == VISUAL_LINE:
            self.view.run_command('move', {'by': 'pages', 'forward': False, 'extend': True})

            new_sels = []
            for sel in self.view.sel():
                line = self.view.full_line(sel.b)
                if sel.b > sel.a:
                    new_sels.append(Region(sel.a, line.end()))
                else:
                    new_sels.append(Region(sel.a, line.begin()))

            if new_sels:
                self.view.sel().clear()
                self.view.sel().add_all(new_sels)


class _vi_enter(ViMotionCommand):
    def run(self, mode=None, count=1):
        self.view.run_command('_vi_j', {'mode': mode, 'count': count})

        def advance(view, s):
            if mode == NORMAL:
                return Region(next_non_white_space_char(view, s.b))
            elif mode == VISUAL:
                if s.a < s.b:
                    return Region(s.a, next_non_white_space_char(view, s.b - 1))

                return Region(s.a, next_non_white_space_char(view, s.b))

            return s

        regions_transformer(self.view, advance)


class _vi_minus(ViMotionCommand):
    def run(self, mode=None, count=1):
        self.view.run_command('_vi_k', {'mode': mode, 'count': count})

        def advance(view, s):
            if mode == NORMAL:
                pt = next_non_white_space_char(view, s.b)
                return Region(pt)
            elif mode == VISUAL:
                if s.a < s.b:
                    pt = next_non_white_space_char(view, s.b - 1)
                    return Region(s.a, pt + 1)
                pt = next_non_white_space_char(view, s.b)
                return Region(s.a, pt)
            return s

        regions_transformer(self.view, advance)


class _vi_shift_enter(ViMotionCommand):
    def run(self, mode=None, count=1):
        self.view.run_command('_vi_ctrl_f', {'mode': mode, 'count': count})


class _vi_select_text_object(ViMotionCommand):
    def run(self, text_object=None, mode=None, count=1, extend=False, inclusive=False):
        def f(view, s):
            # TODO: Vim seems to swallow the delimiters if you give this command.
            if mode == INTERNAL_NORMAL:

                # TODO: For the ( object, we have to abort the editing command
                # completely if no match was found. We could signal this to
                # the caller via exception.
                return get_text_object_region(view, s, text_object,
                                              inclusive=inclusive,
                                              count=count)

            if mode == VISUAL:
                return get_text_object_region(view, s, text_object,
                                              inclusive=inclusive,
                                              count=count)

            return s

        regions_transformer(self.view, f)


class _vi_go_to_symbol(ViMotionCommand):
    """
    Go to local declaration.

    Differs from Vim because it leverages Sublime Text's ability to actually
    locate symbols (Vim simply searches from the top of the file).
    """

    def find_symbol(self, r, globally=False):
        query = self.view.substr(self.view.word(r))
        fname = self.view.file_name().replace('\\', '/')

        locations = self.view.window().lookup_symbol_in_index(query)
        if not locations:
            return

        try:
            if not globally:
                location = [hit[2] for hit in locations if fname.endswith(hit[1])][0]
                return location[0] - 1, location[1] - 1
            else:
                # TODO: There might be many symbols with the same name.
                return locations[0]
        except IndexError:
            return

    def run(self, count=1, mode=None, globally=False):

        def f(view, s):
            if mode == NORMAL:
                return Region(location, location)

            elif mode == VISUAL:
                return Region(s.a + 1, location)

            elif mode == INTERNAL_NORMAL:
                return Region(s.a, location)

            return s

        current_sel = self.view.sel()[0]
        self.view.sel().clear()
        self.view.sel().add(current_sel)

        location = self.find_symbol(current_sel, globally=globally)
        if not location:
            return

        if globally:
            # Global symbol; simply open the file; not a motion.
            # TODO: Perhaps must be a motion if the target file happens to be
            #       the current one?
            jumplist_update(self.view)
            self.view.window().open_file(
                location[0] + ':' + ':'.join([str(x) for x in location[2]]),
                ENCODED_POSITION
            )
            jumplist_update(self.view)

            return

        # Local symbol; select.
        location = self.view.text_point(*location)

        jumplist_update(self.view)
        regions_transformer(self.view, f)
        jumplist_update(self.view)


class _vi_gm(ViMotionCommand):
    def run(self, mode=None, count=1):
        def advance(view, s):
            line = view.line(s.b)
            if line.empty():
                return s
            mid_pt = line.size() // 2
            row_start = row_to_pt(self.view, row_at(self.view, s.b))
            return Region(min(row_start + mid_pt, line.b - 1))

        if mode != NORMAL:
            return ui_blink()

        regions_transformer(self.view, advance)


class _vi_left_square_bracket_target(ViMotionCommand):

    def run(self, mode=None, count=1, target=None):
        def move(view, s):
            reg = find_prev_lone_bracket(self.view, s.b, brackets)
            if reg is not None:
                return Region(reg.a)

            return s

        if mode != NORMAL:
            enter_normal_mode(self.view, mode)
            return ui_blink()

        targets = {
            '{': ('\\{', '\\}'),
            '(': ('\\(', '\\)'),
        }

        brackets = targets.get(target)
        if brackets is None:
            return ui_blink()

        regions_transformer(self.view, move)


class _vi_left_square_bracket_c(ViMotionCommand):
    def run(self, mode=None, count=1):
        if int(version()) >= 3189:
            for i in range(count):
                self.view.run_command('prev_modification')
            a = self.view.sel()[0].a
            self.view.sel().clear()
            self.view.sel().add(a)
            self.enter_normal_mode(mode=mode)
        else:
            self.view.run_command('git_gutter_prev_change', {'count': count, 'wrap': False})

        # TODO Refactor set position cursor after operation into reusable api.
        line = self.view.line(self.view.sel()[0].b)
        if line.size() > 0:
            pt = self.view.find('^\\s*', line.begin()).end()
            if pt != line.begin():
                self.view.sel().clear()
                self.view.sel().add(pt)


class _vi_right_square_bracket_target(ViMotionCommand):

    def run(self, mode=None, count=1, target=None):
        def move(view, s):
            reg = find_next_lone_bracket(self.view, s.b, brackets)
            if reg is not None:
                return Region(reg.a)

            return s

        if mode != NORMAL:
            enter_normal_mode(self.view, mode)
            return ui_blink()

        targets = {
            '}': ('\\{', '\\}'),
            ')': ('\\(', '\\)'),
        }

        brackets = targets.get(target)
        if brackets is None:
            return ui_blink()

        regions_transformer(self.view, move)


class _vi_right_square_bracket_c(ViMotionCommand):
    def run(self, mode=None, count=1):
        if int(version()) >= 3189:
            for i in range(count):
                self.view.run_command('next_modification')
            a = self.view.sel()[0].a
            self.view.sel().clear()
            self.view.sel().add(a)
            self.enter_normal_mode(mode=mode)
        else:
            self.view.run_command('git_gutter_next_change', {'count': count, 'wrap': False})

        # TODO Refactor set position cursor after operation into reusable api.
        line = self.view.line(self.view.sel()[0].b)
        if line.size() > 0:
            pt = self.view.find('^\\s*', line.begin()).end()
            if pt != line.begin():
                self.view.sel().clear()
                self.view.sel().add(pt)
