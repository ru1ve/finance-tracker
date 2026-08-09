"""
ui/tabs/history.py — HistoryTab: balance history charts.
"""
import calendar
import datetime
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.ticker
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates

import db
from ui.constants import *
from ui.helpers import (fmt_gbp, format_date, styled_frame, styled_label,
                        styled_button, styled_entry)


class HistoryTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._time_range      = db.get_setting("history_default_range", "ALL")
        self._drilldown       = None
        self._excluded        = set()   # names hidden from current chart
        self._data_cache      = None    # full get_category_history() result
        self._drill_cache     = {}      # {cat_name: full breakdown list}
        self._cids            = []
        self._ax2             = None
        self._show_income     = tk.BooleanVar(value=False)
        # Net-worth forecast overlay state (Pass 1)
        self._show_forecast   = tk.BooleanVar(value=False)
        self._fc_months       = tk.StringVar(value="12")
        self._fc_model        = tk.StringVar(value="interest")   # interest | custom | trend
        self._fc_contrib      = tk.StringVar(value="0")
        self._show_band       = tk.BooleanVar(value=False)       # ± confidence range
        self._fc_ctx          = None                             # data for forecast overlay
        self._cat_stack_dates = []
        self._hist_data       = []
        self._cat_polys       = {}
        self._cat_mid_y       = {}
        self._hovered_cat     = None
        self._hover_dots      = []
        self._dot_data        = []
        self._dot_annot       = None
        self._cat_stack_data  = None
        self._build()

    def _build(self):
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Balance History", font=STYLE["font_h1"]).pack(side="left")
        styled_button(hdr, "⟳ Refresh", self.refresh, color=GREEN).pack(side="right")

        ctrl = self._ctrl = styled_frame(self)
        ctrl.pack(fill="x", padx=20, pady=(4, 2))
        tk.Checkbutton(ctrl, text="Show income overlay", variable=self._show_income,
                       bg=BG, fg=SUBTEXT, selectcolor=BG3, activebackground=BG,
                       activeforeground=FG, font=STYLE["font"],
                       command=self._replot).pack(side="right", padx=4)

        # Net-worth forecast overlay toggle
        tk.Checkbutton(ctrl, text="Show forecast", variable=self._show_forecast,
                       bg=BG, fg=SUBTEXT, selectcolor=BG3, activebackground=BG,
                       activeforeground=FG, font=STYLE["font"],
                       command=self._on_forecast_toggle).pack(side="right", padx=4)

        # Forecast controls (only shown when the forecast overlay is on)
        self._fc_bar = styled_frame(self)
        styled_label(self._fc_bar, "Forecast:").pack(side="left")
        self._fc_months_combo = ttk.Combobox(
            self._fc_bar, textvariable=self._fc_months, width=5,
            font=STYLE["font"], state="readonly",
            values=("6", "12", "24", "36", "60"))
        self._fc_months_combo.pack(side="left", padx=(4, 2))
        styled_label(self._fc_bar, "months").pack(side="left", padx=(0, 12))

        tk.Radiobutton(self._fc_bar, text="Interest only", variable=self._fc_model,
                       value="interest", bg=BG, fg=FG, selectcolor=BG3,
                       activebackground=BG, activeforeground=ACCENT,
                       font=STYLE["font"], command=self._on_fc_change).pack(side="left")
        tk.Radiobutton(self._fc_bar, text="Trend (auto)", variable=self._fc_model,
                       value="trend", bg=BG, fg=FG, selectcolor=BG3,
                       activebackground=BG, activeforeground=ACCENT,
                       font=STYLE["font"], command=self._on_fc_change).pack(side="left", padx=(10, 0))
        tk.Radiobutton(self._fc_bar, text="Add £/mo:", variable=self._fc_model,
                       value="custom", bg=BG, fg=FG, selectcolor=BG3,
                       activebackground=BG, activeforeground=ACCENT,
                       font=STYLE["font"], command=self._on_fc_change).pack(side="left", padx=(10, 2))
        self._fc_contrib_entry = styled_entry(self._fc_bar, width=9,
                                              textvariable=self._fc_contrib)
        self._fc_contrib_entry.pack(side="left")
        self._fc_contrib_entry.bind("<Return>", lambda _e: self._replot())
        self._fc_contrib_entry.bind("<FocusOut>", lambda _e: self._replot())
        self._fc_months_combo.bind("<<ComboboxSelected>>", lambda _e: self._replot())

        tk.Checkbutton(self._fc_bar, text="± range", variable=self._show_band,
                       bg=BG, fg=SUBTEXT, selectcolor=BG3, activebackground=BG,
                       activeforeground=FG, font=STYLE["font"],
                       command=self._replot).pack(side="left", padx=(14, 0))

        range_row = styled_frame(self)
        range_row.pack(fill="x", padx=20, pady=(0, 2))
        styled_label(range_row, "Period:").pack(side="left")
        self._range_btns = {}
        for r in ("ALL", "2Y", "1Y", "6M", "3M", "YTD"):
            btn = tk.Button(range_row, text=r,
                            bg=BG3, fg=FG, relief="flat", font=STYLE["font"],
                            padx=8, pady=2, cursor="hand2",
                            activebackground=BG2, activeforeground=ACCENT,
                            command=lambda r=r: self._set_range(r))
            btn.pack(side="left", padx=2)
            self._range_btns[r] = btn
        self._back_btn = styled_button(range_row, "← All categories",
                                       self._clear_drilldown, color=SUBTEXT)

        # Chart area: matplotlib canvas on left, legend panel on right
        chart_area = tk.Frame(self, bg=BG)
        chart_area.pack(fill="both", expand=True, padx=20, pady=(4, 16))

        self.fig = Figure(figsize=(9, 5), facecolor=BG)
        self.ax  = self.fig.add_subplot(111, facecolor=BG2)
        self._fig_canvas = FigureCanvasTkAgg(self.fig, master=chart_area)
        self._fig_canvas.draw()
        self._fig_canvas.get_tk_widget().pack(side="left", fill="both", expand=True)

        # Legend panel
        self._legend_outer = tk.Frame(chart_area, bg=BG2, width=158)
        self._legend_outer.pack(side="right", fill="y", padx=(6, 0))
        self._legend_outer.pack_propagate(False)
        tk.Label(self._legend_outer, text="click to hide", bg=BG2, fg=SUBTEXT,
                 font=("Segoe UI", 7), pady=4).pack(anchor="w", padx=8)
        tk.Frame(self._legend_outer, bg=BG3, height=1).pack(fill="x")
        self._legend_inner = tk.Frame(self._legend_outer, bg=BG2)
        self._legend_inner.pack(fill="both", expand=True, pady=4)

        self._update_range_styles()
        self.after_idle(self.refresh)

    # ---- State changes ----

    def _set_range(self, r):
        self._time_range = r
        self._update_range_styles()
        self._replot()

    def _set_drilldown(self, cat):
        self._drilldown = cat
        self._excluded.clear()
        self._sync_back_btn()
        self._replot()

    def _clear_drilldown(self):
        self._drilldown = None
        self._excluded.clear()
        self._sync_back_btn()
        self._replot()

    def show_category(self, cat_name):
        """Public entry point: drill straight into a category (e.g. from the Dashboard)."""
        self._drilldown = cat_name
        self._excluded.clear()
        self._sync_back_btn()
        self._replot()

    def _on_forecast_toggle(self):
        self._sync_fc_bar()
        self._replot()

    def _on_fc_change(self):
        self._sync_fc_bar()
        self._replot()

    def _sync_fc_bar(self):
        """Show forecast controls only when the overlay is on; enable £ entry only for custom."""
        if self._show_forecast.get():
            self._fc_bar.pack(fill="x", padx=20, pady=(0, 2), after=self._ctrl)
            state = "normal" if self._fc_model.get() == "custom" else "disabled"
            self._fc_contrib_entry.config(state=state)
        else:
            self._fc_bar.pack_forget()

    def _fc_month_count(self):
        try:
            return max(1, int(self._fc_months.get()))
        except (ValueError, TypeError):
            return 12

    def _fc_contrib_value(self):
        raw = self._fc_contrib.get().strip().replace("£", "").replace(",", "")
        try:
            return float(raw) if raw else 0.0
        except ValueError:
            return 0.0

    def _update_range_styles(self):
        for r, btn in self._range_btns.items():
            active = (r == self._time_range)
            btn.config(bg=ACCENT if active else BG3,
                       fg=BG   if active else FG)

    def _sync_back_btn(self):
        if self._drilldown:
            self._back_btn.pack(side="left", padx=(20, 0))
        else:
            self._back_btn.pack_forget()

    # ---- Date filtering ----

    def _date_cutoff(self):
        if self._time_range == "ALL":
            return None
        today = datetime.date.today()
        if self._time_range == "YTD":
            start = datetime.date(today.year, 1, 1)
        else:
            days = {"2Y": 730, "1Y": 365, "6M": 182, "3M": 91}[self._time_range]
            start = today - datetime.timedelta(days=days)
        return start.isoformat()

    def _trim(self, items, date_fn):
        cutoff = self._date_cutoff()
        if not cutoff:
            return items
        return [x for x in items if date_fn(x) >= cutoff]

    # ---- Custom legend ----

    @staticmethod
    def _to_hex(color):
        """Convert matplotlib color (hex string or RGB/RGBA tuple) to '#rrggbb'."""
        if isinstance(color, (tuple, list)):
            return "#{:02x}{:02x}{:02x}".format(
                int(color[0] * 255), int(color[1] * 255), int(color[2] * 255))
        return color

    def _build_legend(self, names, colours):
        for w in self._legend_inner.winfo_children():
            w.destroy()

        nf = tkfont.Font(family="Segoe UI", size=9)
        sf = tkfont.Font(family="Segoe UI", size=9, overstrike=True)

        for name, color in zip(names, colours):
            hex_col  = self._to_hex(color)
            excluded = name in self._excluded

            row = tk.Frame(self._legend_inner, bg=BG2, cursor="hand2")
            row.pack(fill="x", padx=6, pady=1)

            sw = tk.Canvas(row, width=11, height=11, bg=BG2, highlightthickness=0)
            sw.pack(side="left", padx=(2, 4), pady=2)
            sw.create_rectangle(0, 0, 11, 11,
                                 fill=BG3 if excluded else hex_col, outline="")

            lbl = tk.Label(row, text=name, bg=BG2,
                           fg=SUBTEXT if excluded else FG,
                           font=sf if excluded else nf,
                           anchor="w", justify="left", wraplength=118)
            lbl.pack(side="left", fill="x", expand=True)

            def _toggle(n=name, sw=sw, lbl=lbl, hx=hex_col, nf=nf, sf=sf):
                if n in self._excluded:
                    self._excluded.discard(n)
                    lbl.config(fg=FG, font=nf)
                    sw.itemconfig("all", fill=hx)
                else:
                    self._excluded.add(n)
                    lbl.config(fg=SUBTEXT, font=sf)
                    sw.itemconfig("all", fill=BG3)
                self._replot()

            for w in (row, sw, lbl):
                w.bind("<Button-1>", lambda e, t=_toggle: t())

    # ---- Data (cached) ----

    def refresh(self):
        """Full DB reload — call when data changes. Time-range/exclusion changes use _replot()."""
        self._data_cache  = None
        self._drill_cache = {}
        self._replot()

    def _get_category_data(self):
        if self._data_cache is None:
            self._data_cache = db.get_category_history()
        return self._data_cache

    def _get_drilldown_data(self, cat_name):
        if cat_name not in self._drill_cache:
            self._drill_cache[cat_name] = db.get_category_account_breakdown(cat_name)
        return self._drill_cache[cat_name]

    # ---- Replot (no DB hit when data is cached) ----

    def _replot(self):
        if self._ax2 is not None:
            try:
                self._ax2.remove()
            except Exception:
                pass
            self._ax2 = None

        self._cat_polys       = {}
        self._cat_stack_data  = None
        self._cat_stack_dates = []
        self._hist_data       = []
        self._cat_mid_y       = {}
        self._hovered_cat     = None
        self._hover_dots      = []
        self._dot_data        = []
        self._fc_ctx          = None
        if self._dot_annot is not None:
            self._dot_annot.set_visible(False)

        self.ax.clear()
        self.ax.set_facecolor(BG2)
        self.fig.patch.set_facecolor(BG)
        for spine in self.ax.spines.values():
            spine.set_edgecolor(BG3)
        self.ax.tick_params(colors=SUBTEXT)
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        self.ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        self.fig.autofmt_xdate()

        if self._drilldown:
            self._plot_category_drilldown(self._drilldown)
        else:
            self._plot_by_category()
        if self._show_income.get():
            self._overlay_income()
        if self._show_forecast.get():
            self._overlay_forecast()

        self.ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda x, _: f"£{x:,.2f}"))

        self.fig.canvas.draw_idle()
        self._setup_interactions()

    def _add_months(self, d, k):
        """Return date d shifted forward k whole months (clamping the day)."""
        m = d.month - 1 + k
        y = d.year + m // 12
        m = m % 12 + 1
        day = min(d.day, calendar.monthrange(y, m)[1])
        return datetime.date(y, m, day)

    def _parse_dt(self, s):
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(s, fmt)
            except ValueError:
                pass
        return None

    def _dates_to_mpl(self, dates):
        result = []
        for d in dates:
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    result.append(mdates.date2num(datetime.datetime.strptime(d, fmt)))
                    break
                except ValueError:
                    pass
        return result

    # ---- Helpers ----

    def _signed_stackplot(self, x, names, ys_mat, colours):
        has_pos = {n for n, ys in zip(names, ys_mat) if any(v > 0 for v in ys)}
        has_neg = {n for n, ys in zip(names, ys_mat) if any(v < 0 for v in ys)}
        result  = {}

        pos = [(n, [max(0.0, v) for v in ys], c)
               for n, ys, c in zip(names, ys_mat, colours) if n in has_pos]
        neg = [(n, [min(0.0, v) for v in ys], c)
               for n, ys, c in zip(names, ys_mat, colours) if n in has_neg]

        if pos:
            pn, pys, pc = zip(*pos)
            polys = self.ax.stackplot(x, pys, labels=pn, colors=pc, alpha=0.7)
            for poly, name, color in zip(polys, pn, pc):
                result[name] = (poly, color)

        if neg:
            nn, nys, nc = zip(*neg)
            polys = self.ax.stackplot(x, nys, colors=nc, alpha=0.7)
            for poly, name, color in zip(polys, nn, nc):
                if name not in has_pos:
                    poly.set_label(name)
                result.setdefault(name, (poly, color))

        self.ax.axhline(0, color=SUBTEXT, linewidth=0.5, linestyle="--")
        return result

    def _compute_mid_y(self, names, ys_mat, n):
        mid_y = {}
        cum   = [0.0] * n
        for name, ys in zip(names, ys_mat):
            if any(v > 0 for v in ys):
                pos_ys  = [max(0.0, v) for v in ys]
                bottoms = cum[:]
                tops    = [cum[i] + pos_ys[i] for i in range(n)]
                mid_y[name] = [(bottoms[i] + tops[i]) / 2 for i in range(n)]
                cum = tops
        return mid_y

    # ---- Interaction setup ----

    def _setup_interactions(self):
        for cid in self._cids:
            try:
                self.fig.canvas.mpl_disconnect(cid)
            except Exception:
                pass
        self._cids = []

        self._dot_annot = self.ax.annotate(
            "", xy=(0, 0), xytext=(12, 12), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.5", fc=BG3, ec=SUBTEXT, alpha=0.93),
            color=FG, fontsize=8, visible=False, zorder=10,
        )
        self._cids.append(
            self.fig.canvas.mpl_connect("button_press_event", self._on_click))
        self._cids.append(
            self.fig.canvas.mpl_connect("motion_notify_event", self._on_hover))

    # ---- Hit testing ----

    def _hit_test_category(self, xdata, ydata):
        if not self._cat_stack_data:
            return None
        cats, x_vals, ys_mat = self._cat_stack_data
        if not x_vals:
            return None
        idx = min(range(len(x_vals)), key=lambda i: abs(x_vals[i] - xdata))
        has_pos = {n for n, ys in zip(cats, ys_mat) if any(v > 0 for v in ys)}
        has_neg = {n for n, ys in zip(cats, ys_mat) if any(v < 0 for v in ys)}
        pos_cum = 0.0
        neg_cum = 0.0
        for cat, ys in zip(cats, ys_mat):
            pos_val = max(0.0, ys[idx]) if cat in has_pos else 0.0
            neg_val = min(0.0, ys[idx]) if cat in has_neg else 0.0
            if pos_val > 0 and pos_cum <= ydata <= pos_cum + pos_val:
                return cat
            pos_cum += pos_val
            if neg_val < 0 and neg_cum + neg_val <= ydata <= neg_cum:
                return cat
            neg_cum += neg_val
        return None

    # ---- Hover: dot helpers ----

    def _highlight_cat(self, cat):
        if cat == self._hovered_cat:
            return
        self._hovered_cat = cat

        for dot in self._hover_dots:
            try:
                dot.remove()
            except Exception:
                pass
        self._hover_dots = []
        self._dot_data   = []

        for name, (poly, color) in self._cat_polys.items():
            if cat is None:
                poly.set_edgecolor("none")
                poly.set_alpha(0.7)
            elif name == cat:
                poly.set_edgecolor(color)
                poly.set_linewidth(1.5)
                poly.set_alpha(0.9)
            else:
                poly.set_edgecolor("none")
                poly.set_alpha(0.3)

        if cat and self._cat_stack_dates and cat in self._cat_mid_y:
            mids = self._cat_mid_y[cat]
            cat_color = self._cat_polys[cat][1] if cat in self._cat_polys else "white"
            for i, (x, info) in enumerate(zip(self._cat_stack_dates, self._hist_data)):
                val = info.get("values", {}).get(cat, 0.0)
                y   = mids[i]
                dot, = self.ax.plot(x, y, "o", color="white", markersize=5, zorder=7,
                                    markeredgecolor=cat_color, markeredgewidth=1.2)
                self._hover_dots.append(dot)
                self._dot_data.append((x, val, info["date"]))

        self.fig.canvas.draw_idle()

    def _nearest_dot(self, x_px, y_px):
        if not self._hover_dots:
            return None
        threshold = 10
        best      = None
        best_dist = float("inf")
        for dot, data in zip(self._hover_dots, self._dot_data):
            xd, yd = dot.get_xdata()[0], dot.get_ydata()[0]
            xd_px, yd_px = self.ax.transData.transform((xd, yd))
            dist = ((x_px - xd_px) ** 2 + (y_px - yd_px) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best = data
        return best if best_dist <= threshold else None

    def _show_dot_info(self, dot_data):
        x_num, val, date_str = dot_data
        cat = self._hovered_cat
        idx = 0
        if self._cat_stack_dates:
            idx = min(range(len(self._cat_stack_dates)),
                      key=lambda i: abs(self._cat_stack_dates[i] - x_num))
        mid_ys = self._cat_mid_y.get(cat, [])
        y = mid_ys[idx] if idx < len(mid_ys) else 0.0
        self._dot_annot.xy = (x_num, y)
        self._dot_annot.set_text(f"{format_date(date_str)}\n{cat}: {fmt_gbp(val)}")
        self._dot_annot.set_visible(True)
        self.fig.canvas.draw_idle()

    # ---- Event handlers ----

    def _on_click(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return

        if self._hover_dots:
            nearest = self._nearest_dot(event.x, event.y)
            if nearest:
                self._show_dot_info(nearest)
                return

        if not self._drilldown:
            cat = self._hit_test_category(event.xdata, event.ydata)
            if cat and cat not in self._excluded:
                self._set_drilldown(cat)

    def _on_hover(self, event):
        tk_widget = self._fig_canvas.get_tk_widget()

        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            if self._dot_annot and self._dot_annot.get_visible():
                self._dot_annot.set_visible(False)
                self.fig.canvas.draw_idle()
            if self._hovered_cat is not None:
                self._highlight_cat(None)
            tk_widget.config(cursor="")
            return

        if self._hover_dots:
            nearest = self._nearest_dot(event.x, event.y)
            if nearest:
                tk_widget.config(cursor="hand2")
                return

        cat = (self._hit_test_category(event.xdata, event.ydata)
               if not self._drilldown else None)
        if cat:
            tk_widget.config(cursor="hand2")
            self._highlight_cat(cat)
        else:
            if self._hovered_cat is not None:
                self._highlight_cat(None)
            tk_widget.config(cursor="")

    # ---- Plot methods ----

    def _overlay_income(self):
        rows = db.get_all_income()
        if not rows:
            return
        rows = sorted(rows, key=lambda r: r["entry_date"])
        rows = self._trim(rows, date_fn=lambda r: r["entry_date"])
        if not rows:
            return
        x_inc = self._dates_to_mpl([r["entry_date"] for r in rows])
        y_inc = [r["amount"] for r in rows]
        self.ax.plot(x_inc, y_inc, color=ACCENT, linewidth=1.4,
                     marker="o", markersize=3, zorder=5, label="Income")

    def _plot_by_category(self):
        history = self._trim(self._get_category_data(),
                             date_fn=lambda h: h["date"])
        if not history:
            self._build_legend([], [])
            return

        all_cats    = list(history[0]["totals"].keys())
        all_colours = [CAT_COLOURS.get(c, SUBTEXT) for c in all_cats]

        # Only plot non-excluded categories
        vis_cats    = [c for c in all_cats if c not in self._excluded]
        vis_colours = [CAT_COLOURS.get(c, SUBTEXT) for c in vis_cats]
        x           = self._dates_to_mpl([h["date"] for h in history])
        ys_mat      = [[h["totals"].get(c, 0.0) for h in history] for c in vis_cats]

        self._cat_polys      = self._signed_stackplot(x, vis_cats, ys_mat, vis_colours)
        self._cat_stack_data = (vis_cats, list(x), ys_mat)
        self._cat_stack_dates = list(x)
        self._hist_data      = [{"date": h["date"], "values": dict(h["totals"])}
                                 for h in history]
        self._cat_mid_y      = self._compute_mid_y(vis_cats, ys_mat, len(x))
        self.ax.set_title(
            "Balance by Spending Category  ·  click a section to drill down",
            color=FG, pad=10)

        # Context for the forecast overlay (current values + colours + seam date)
        self._fc_ctx = {
            "cur":       dict(history[-1]["totals"]),
            "names":     list(vis_cats),
            "colours":   {c: CAT_COLOURS.get(c, SUBTEXT) for c in vis_cats},
            "last_date": history[-1]["date"],
            "hist":      {c: [h["totals"].get(c, 0.0) for h in history]
                          for c in vis_cats},
        }

        self._build_legend(all_cats, all_colours)

    def _plot_category_drilldown(self, cat_name):
        history = self._trim(self._get_drilldown_data(cat_name),
                             date_fn=lambda h: h["date"])
        if not history:
            self.ax.set_title(f"{cat_name} — no data in range", color=FG, pad=10)
            self._build_legend([], [])
            return

        tab20    = plt.cm.tab20.colors
        all_accs = sorted({name for h in history for name in h["accounts"]})
        x        = self._dates_to_mpl([h["date"] for h in history])
        ys_raw   = {acc: [h["accounts"].get(acc, 0.0) for h in history]
                    for acc in all_accs}
        all_accs = [a for a in all_accs if max(abs(v) for v in ys_raw[a]) >= 1.0]
        all_colours = [tab20[i % len(tab20)] for i in range(len(all_accs))]

        vis_accs    = [a for a in all_accs if a not in self._excluded]
        vis_colours = [all_colours[all_accs.index(a)] for a in vis_accs]
        ys_mat      = [ys_raw[a] for a in vis_accs]

        self._cat_polys       = self._signed_stackplot(x, vis_accs, ys_mat, vis_colours)
        self._cat_stack_data  = (vis_accs, list(x), ys_mat)
        self._cat_stack_dates = list(x)
        self._hist_data       = [{"date": h["date"], "values": dict(h["accounts"])}
                                  for h in history]
        self._cat_mid_y       = self._compute_mid_y(vis_accs, ys_mat, len(x))
        self.ax.set_title(f"{cat_name} — by account  ·  use ← All categories to go back",
                          color=FG, pad=10)

        # Context for the forecast overlay (per-account within this category)
        self._fc_ctx = {
            "cur":       dict(history[-1]["accounts"]),
            "names":     list(vis_accs),
            "colours":   {a: all_colours[all_accs.index(a)] for a in vis_accs},
            "last_date": history[-1]["date"],
            "hist":      {a: list(ys_raw[a]) for a in vis_accs},
        }

        self._build_legend(all_accs, all_colours)

    def _nw_monthly_sigma(self):
        """Std-dev of month-normalised net-worth changes — drives the ± range band."""
        hist = db.get_net_worth_history()
        if len(hist) < 3:
            return 0.0
        rates = []
        for (d0, v0), (d1, v1) in zip(hist, hist[1:]):
            dt0, dt1 = self._parse_dt(d0), self._parse_dt(d1)
            if dt0 is None or dt1 is None:
                continue
            months = max((dt1 - dt0).days / 30.44, 0.03)
            rates.append((v1 - v0) / months)
        if len(rates) < 2:
            return 0.0
        import statistics
        return statistics.pstdev(rates)

    @staticmethod
    def _is_flow_series(vals):
        """True for consumption/flow series (oscillate, mean-revert) rather than
        accumulating ones. Such series should be forecast flat, not compounded.

        Test: if the net drift across the whole window is smaller than a single
        typical month-to-month swing, the series is oscillating, not accumulating.
        """
        vals = [v for v in vals if v is not None]
        n = len(vals)
        if n < 4:
            return False
        import statistics
        deltas = [abs(vals[i + 1] - vals[i]) for i in range(n - 1)]
        mean_abs_delta = statistics.mean(deltas) if deltas else 0.0
        if mean_abs_delta <= 0:
            return False
        third = max(1, n // 3)
        start = statistics.mean(vals[:third])
        end   = statistics.mean(vals[-third:])
        net_drift = abs(end - start)
        return net_drift < mean_abs_delta

    @staticmethod
    def _trailing_level(vals):
        """Representative recent level for a flat forecast — mean of the last third."""
        vals = [v for v in vals if v is not None]
        if not vals:
            return 0.0
        import statistics
        third = max(1, len(vals) // 3)
        return max(0.0, statistics.mean(vals[-third:]))

    def _forecast_contribution(self):
        """Resolve the monthly contribution £ for the selected model."""
        model = self._fc_model.get()
        if model == "custom":
            return self._fc_contrib_value(), None
        if model == "trend":
            t = db.estimate_trend_contribution(6)
            return (t["contribution"] if t else 0.0), t
        return 0.0, None   # interest only

    def _overlay_forecast(self):
        """Extend the current stack (categories, or accounts in a drilldown) into
        the future as see-through bands, projected by the blended net-worth
        growth factor so they join the present stack seamlessly."""
        ctx = self._fc_ctx
        if not ctx:
            return
        last_dt = self._parse_dt(ctx["last_date"])
        if last_dt is None:
            return

        cur   = ctx["cur"]
        names = [n for n in ctx["names"] if cur.get(n, 0.0) > 0]   # positive stack only
        if not names:
            return

        months        = self._fc_month_count()
        contrib, tinfo = self._forecast_contribution()
        proj    = db.project_net_worth(months, contrib)
        series  = proj["series"]                 # series[0] = net worth now
        if len(series) < 2:
            return

        base   = series[0] if abs(series[0]) > 1e-6 else (sum(cur.values()) or 1.0)
        growth = [s / base for s in series]
        n      = len(series)                     # months + 1 (k=0 = seam = now)

        last_date = last_dt.date()
        x_fc = [mdates.date2num(self._add_months(last_date, k)) for k in range(n)]

        # Seam divider where actuals end and forecast begins
        self.ax.axvline(x_fc[0], color=SUBTEXT, linewidth=0.8,
                        linestyle=(0, (4, 3)), alpha=0.4, zorder=3)

        # Stacked, see-through bands (consistent fade across the whole horizon).
        # Accumulating series compound by the shared growth factor; flow/consumption
        # series (e.g. Spending) are held flat at their trailing average.
        FADE     = 0.3
        hist_map = ctx.get("hist", {})
        any_flow = False
        cum = [0.0] * n

        # In a drilldown, inherit the parent category's flow status so every
        # account under a consumption category (e.g. Spending) is held flat,
        # rather than relying on noisier per-account classification.
        force_flat = False
        if self._drilldown:
            per = [v for v in hist_map.values() if v]
            if per:
                L = min(len(s) for s in per)
                cat_series = [sum(s[i] for s in per) for i in range(L)]
                force_flat = self._is_flow_series(cat_series)

        for name in names:
            colour = ctx["colours"].get(name, SUBTEXT)
            series_hist = hist_map.get(name, [])
            if force_flat or self._is_flow_series(series_hist):
                any_flow = True
                level = self._trailing_level(series_hist)
                # k=0 anchored to the actual value for seam continuity, then flat.
                proj_vals = [cur[name]] + [level] * (n - 1)
            else:
                proj_vals = [cur[name] * g for g in growth]
            top = [cum[i] + proj_vals[i] for i in range(n)]
            self.ax.fill_between(x_fc, cum, top, color=colour, alpha=FADE,
                                 linewidth=0, zorder=3)
            cum = top

        # Optional ± confidence band around the projected stack top
        if self._show_band.get():
            sigma = self._nw_monthly_sigma()
            if sigma > 0:
                scale = cum[-1] / series[-1] if abs(series[-1]) > 1e-6 else 1.0
                upper = [cum[k] + scale * sigma * (k ** 0.5) for k in range(n)]
                lower = [cum[k] - scale * sigma * (k ** 0.5) for k in range(n)]
                self.ax.fill_between(x_fc, lower, upper, color=SUBTEXT,
                                     alpha=0.12, linewidth=0, zorder=2)
                self.ax.plot(x_fc, upper, color=SUBTEXT, linewidth=0.7,
                             linestyle=":", alpha=0.5, zorder=3)
                self.ax.plot(x_fc, lower, color=SUBTEXT, linewidth=0.7,
                             linestyle=":", alpha=0.5, zorder=3)

        # Projected total at the horizon
        self.ax.annotate(
            f"£{cum[-1]:,.0f}",
            xy=(x_fc[-1], cum[-1]), xytext=(-6, 8),
            textcoords="offset points", ha="right",
            color=SUBTEXT, fontsize=8, fontweight="bold", alpha=0.9,
            bbox=dict(boxstyle="round,pad=0.35", fc=BG3, ec=SUBTEXT, alpha=0.8))

        # Assumptions footnote
        rate_pct = proj["blended_annual"] * 100
        model    = self._fc_model.get()
        if model == "custom":
            money = f"adding £{contrib:,.0f}/mo"
        elif model == "trend":
            if tinfo:
                money = (f"trend £{contrib:,.0f}/mo "
                         f"(last {tinfo['eff_lookback']:.0f} mo)")
            else:
                money = "trend unavailable — too little history"
        else:
            money = "interest only (no new savings)"
        assume = f"forecast: blended rate {rate_pct:.2f}%/yr  ·  {money}  ·  {months} mo"
        if any_flow:
            assume += "  ·  spending-type bands held flat at recent average"
        self.ax.text(0.01, 0.02, assume, transform=self.ax.transAxes,
                     color=SUBTEXT, fontsize=7.5, ha="left", va="bottom")
