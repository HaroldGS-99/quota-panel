import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Pango from 'gi://Pango';
import St from 'gi://St';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {PROVIDERS, NAMES, usageColor, summaryQuota, countdown, ageText, mergeResult} from './ui-model.js';

const COLORS = {normal: [0.18, 0.77, 0.49], warning: [0.96, 0.76, 0.25],
    critical: [0.95, 0.32, 0.35], unknown: [0.53, 0.56, 0.60]};

const QuotaBar = GObject.registerClass(class QuotaBar extends St.DrawingArea {
    _init(width, height) {
        super._init({width, height, y_align: Clutter.ActorAlign.CENTER});
        this.value = null;
        this.color = 'unknown';
        this.connect('repaint', () => {
            const cr = this.get_context();
            const [w, h] = this.get_surface_size();
            const draw = (x, y, width, height, radius) => {
                if (width <= 0) return;
                radius = Math.min(radius, width / 2);
                cr.newSubPath();
                cr.arc(x + width - radius, y + radius, radius, -Math.PI / 2, 0);
                cr.arc(x + width - radius, y + height - radius, radius, 0, Math.PI / 2);
                cr.arc(x + radius, y + height - radius, radius, Math.PI / 2, Math.PI);
                cr.arc(x + radius, y + radius, radius, Math.PI, Math.PI * 1.5);
                cr.closePath();
                cr.fill();
            };
            cr.setSourceRGBA(0.55, 0.58, 0.62, 0.24);
            draw(0, 0, w, h, h / 2);
            if (Number.isFinite(this.value)) {
                cr.setSourceRGBA(...COLORS[this.color], 1);
                draw(0, 0, w * Math.min(100, Math.max(0, this.value)) / 100, h, h / 2);
            }
            cr.$dispose();
        });
    }

    setUsage(value, color) {
        this.value = value;
        this.color = color;
        this.queue_repaint();
    }
});

const Indicator = GObject.registerClass(class Indicator extends PanelMenu.Button {
    _init(extension) {
        super._init(0.5, 'Quota Panel', false);
        this.extension = extension;
        this.add_style_class_name('pq-indicator');
        const box = new St.BoxLayout({style_class: 'pq-panel'});
        this.add_child(box);
        this.parts = {};
        for (const id of PROVIDERS) {
            const segment = new St.BoxLayout({style_class: 'pq-segment'});
            segment.add_child(extension.icon(id, 16));
            const bar = new QuotaBar(42, 5);
            const label = new St.Label({text: '—', style_class: 'pq-panel-percent',
                y_align: Clutter.ActorAlign.CENTER});
            segment.add_child(bar);
            segment.add_child(label);
            box.add_child(segment);
            this.parts[id] = {bar, label};
        }
        const item = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
        this.scroll = new St.ScrollView({style_class: 'pq-scroll', reactive: true,
            enable_mouse_scrolling: false,
            hscrollbar_policy: St.PolicyType.NEVER, vscrollbar_policy: St.PolicyType.AUTOMATIC});
        // Clutter.Actor.content is a native ClutterContent property, not an actor slot.
        this.menuContent = new St.BoxLayout({vertical: true, style_class: 'pq-content'});
        this.scroll.set_child(this.menuContent);
        this.sections = new Map();
        this.scroll.connect('scroll-event', (_actor, event) => this._onScroll(event));
        this.scroll.connect('captured-event', (_actor, event) => {
            if (event.type() === Clutter.EventType.BUTTON_PRESS ||
                event.type() === Clutter.EventType.TOUCH_BEGIN)
                this._cancelScroll();
            return Clutter.EVENT_PROPAGATE;
        });
        item.add_child(this.scroll);
        this.menu.addMenuItem(item);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this.refreshItem = this.menu.addAction('Actualizar', () => extension.refresh(true));
        this.menu.addAction('Preferencias', () => extension.openPreferences());
        this.menu.connect('open-state-changed', (_menu, open) => {
            if (open) {
                this.render();
                extension.refresh(true);
            } else this._cancelScroll();
        });
        this.render();
    }

    _onScroll(event) {
        const direction = event.get_scroll_direction();
        let delta = 0;
        if (direction === Clutter.ScrollDirection.UP) delta = -1;
        else if (direction === Clutter.ScrollDirection.DOWN) delta = 1;
        else if (direction === Clutter.ScrollDirection.SMOOTH)
            [, delta] = event.get_scroll_delta();
        if (!Number.isFinite(delta) || delta === 0) return Clutter.EVENT_STOP;
        const adjustment = this.scroll.vadjustment;
        const wheel = event.get_scroll_source?.() === Clutter.ScrollSource.WHEEL;
        if (direction === Clutter.ScrollDirection.SMOOTH && !wheel) {
            // Touchpad events already describe continuous motion; avoid added lag.
            this._cancelScroll();
            adjustment.value += delta * 28;
            return Clutter.EVENT_STOP;
        }
        const moving = adjustment.get_transition('value');
        const sameDirection = Math.sign(delta) === this._scrollDirection;
        const from = moving && sameDirection ? this._scrollTarget : adjustment.value;
        const maximum = Math.max(adjustment.lower, adjustment.upper - adjustment.page_size);
        this._scrollTarget = Math.max(adjustment.lower, Math.min(maximum, from + delta * 48));
        this._scrollDirection = Math.sign(delta);
        // Retarget from the current frame, accumulating wheel ticks in the same
        // direction. Reversal immediately follows the user's new direction.
        adjustment.ease(this._scrollTarget, {
            duration: 160,
            mode: Clutter.AnimationMode.EASE_OUT_CUBIC,
        });
        return Clutter.EVENT_STOP;
    }

    _cancelScroll() {
        this.scroll.vadjustment.remove_transition('value');
        this._scrollTarget = null;
        this._scrollDirection = 0;
    }

    _createSection(id) {
        const section = new St.BoxLayout({vertical: true, style_class: 'pq-section'});
        const header = new St.BoxLayout({style_class: 'pq-header'});
        header.add_child(this.extension.icon(id, 22));
        header.add_child(new St.Label({text: NAMES[id], style_class: 'pq-title', x_expand: true}));
        section.add_child(header);
        if (id === 'antigravity')
            section.add_child(new St.Label({text: 'Gemini Models · Flash y Pro', style_class: 'pq-muted'}));
        const status = new St.Label({style_class: 'pq-status', visible: false});
        status.clutter_text.line_wrap = true;
        status.clutter_text.line_wrap_mode = Pango.WrapMode.WORD_CHAR;
        status.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
        section.add_child(status);
        const rows = new St.BoxLayout({vertical: true, style_class: 'pq-quota-list'});
        section.add_child(rows);
        const resets = new St.Label({style_class: 'pq-resets', visible: id === 'codex'});
        section.add_child(resets);
        const age = new St.Label({style_class: 'pq-age'});
        section.add_child(age);
        this.menuContent.add_child(section);
        const view = {section, status, rows, resets, age, quotas: new Map()};
        this.sections.set(id, view);
        return view;
    }

    _createQuotaRow() {
        const row = new St.BoxLayout({vertical: true, style_class: 'pq-quota'});
        const heading = new St.BoxLayout();
        const title = new St.Label({x_expand: true, style_class: 'pq-window'});
        const value = new St.Label();
        heading.add_child(title);
        heading.add_child(value);
        row.add_child(heading);
        const bar = new QuotaBar(336, 8);
        row.add_child(bar);
        const timing = new St.BoxLayout({style_class: 'pq-timing'});
        const countdownLabel = new St.Label({x_expand: true, style_class: 'pq-muted'});
        const date = new St.Label({style_class: 'pq-muted'});
        timing.add_child(countdownLabel);
        timing.add_child(date);
        row.add_child(timing);
        return {row, title, value, bar, countdownLabel, date};
    }

    render() {
        const ext = this.extension;
        const warning = ext.settings.get_int('warning-percent');
        const critical = Math.max(warning + 1, ext.settings.get_int('critical-percent'));
        const accessible = [];
        for (const id of PROVIDERS) {
            const data = ext.data[id] ?? {quotas: [], status: 'loading', message: 'Consultando…'};
            const summary = summaryQuota(data.quotas);
            const used = summary?.usedPercent ?? null;
            this.parts[id].bar.setUsage(used, usageColor(used, warning, critical));
            this.parts[id].label.text = used === null ? '—' : `${Math.round(used)}%`;
            this.parts[id].label.opacity = data.status === 'ok' ? 255 : 140;
            accessible.push(`${NAMES[id]}: ${used === null ? 'sin datos' : `${Math.round(used)} por ciento consumido`}`);
            // Retain actors and the adjustment across countdown, data and loading updates.
            const view = this.sections.get(id) ?? this._createSection(id);
            view.status.text = data.message ?? 'Cuota no disponible';
            view.status.visible = data.status !== 'ok';
            const rank = q => q.windowMinutes === 300 ? 0 : q.windowMinutes === 10080 ? 1 : 2;
            const quotas = [...(data.quotas ?? [])].sort((a, b) =>
                Number(Boolean(a.group)) - Number(Boolean(b.group)) || rank(a) - rank(b) ||
                String(a.id).localeCompare(String(b.id)));
            const present = new Set();
            for (const [index, q] of quotas.entries()) {
                const key = q.id ?? `${q.group ?? ''}:${q.label}:${index}`;
                present.add(key);
                let row = view.quotas.get(key);
                if (!row) {
                    row = this._createQuotaRow();
                    view.quotas.set(key, row);
                    view.rows.add_child(row.row);
                }
                if (view.rows.get_child_at_index(index) !== row.row)
                    view.rows.set_child_at_index(row.row, index);
                row.title.text = q.group && id !== 'antigravity' ? `${q.group} · ${q.label}` : q.label;
                row.value.text = q.disabled ? 'No disponible' : Number.isFinite(q.usedPercent) ? `${Math.round(q.usedPercent)}% usado` : 'Sin porcentaje';
                row.value.style_class = `pq-value pq-${usageColor(q.usedPercent, warning, critical)}`;
                row.bar.setUsage(q.disabled ? null : q.usedPercent, usageColor(q.usedPercent, warning, critical));
                row.countdownLabel.text = countdown(q.resetsAt);
                row.date.visible = Number.isFinite(q.resetsAt);
                if (row.date.visible) {
                    const date = GLib.DateTime.new_from_unix_local(Math.floor(q.resetsAt));
                    row.date.text = `${date.format('%d/%m')} ${date.get_hour() % 12 || 12}:${date.format('%M')} ${date.get_hour() < 12 ? 'AM' : 'PM'}`;
                }
            }
            for (const [key, row] of view.quotas) {
                if (!present.has(key)) {
                    row.row.destroy();
                    view.quotas.delete(key);
                }
            }
            view.resets.text = data.resetsAvailable === null || data.resetsAvailable === undefined ?
                'Resets adicionales: no disponible' : `Resets adicionales disponibles: ${data.resetsAvailable}`;
            view.age.text = ageText(data.updatedAt);
        }
        this.accessible_name = accessible.join('. ');
        this.refreshItem.label.text = ext.process ? 'Actualizando…' : 'Actualizar';
        this.refreshItem.setSensitive(!ext.process);
    }

});

export default class QuotaPanel extends Extension {
    enable() {
        this.settings = this.getSettings();
        this.data = {};
        this.due = {};
        this.failures = {};
        this.active = true;
        this.lastManual = 0;
        const dir = GLib.build_filenamev([GLib.get_user_cache_dir(), 'quota-panel']);
        GLib.mkdir_with_parents(dir, 0o700);
        this.cache = Gio.File.new_for_path(GLib.build_filenamev([dir, 'quotas.json']));
        try {
            const [, bytes] = this.cache.load_contents(null);
            const cached = JSON.parse(new TextDecoder().decode(bytes));
            for (const id of PROVIDERS) {
                if (cached[id]?.id === id && Array.isArray(cached[id].quotas))
                    this.data[id] = {...cached[id], status: 'offline', message: 'Comprobando el último dato…'};
            }
        } catch (_) { /* First run or invalid cache. */ }
        this.indicator = new Indicator(this);
        Main.panel.addToStatusArea(this.uuid, this.indicator, 1, 'left');
        this.settingsId = this.settings.connect('changed', () => {
            this.due = {};
            this.indicator.render();
            this.refresh(false);
        });
        this.timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 15, () => {
            this.refresh(false);
            if (this.indicator.menu.isOpen) this.indicator.render();
            return GLib.SOURCE_CONTINUE;
        });
        this.resumeId = Main.screenShield.connect('active-changed', () => {
            if (!Main.screenShield.active) this.refresh(true);
        });
        this.sleepSubscription = 0;
        this.systemBus = null;
        const lifecycle = new Gio.Cancellable();
        this.lifecycle = lifecycle;
        Gio.bus_get(Gio.BusType.SYSTEM, lifecycle, (_source, res) => {
            if (!this.active || this.lifecycle !== lifecycle) return;
            try {
                this.systemBus = Gio.bus_get_finish(res);
                this.sleepSubscription = this.systemBus.signal_subscribe('org.freedesktop.login1',
                    'org.freedesktop.login1.Manager', 'PrepareForSleep', '/org/freedesktop/login1',
                    null, Gio.DBusSignalFlags.NONE, (_connection, _sender, _path, _interface, _signal, params) => {
                        const [sleeping] = params.deep_unpack();
                        if (!sleeping && this.active) {
                            this.lastManual = 0;
                            this.refresh(true);
                        }
                    });
            } catch (_) { /* Polling still refreshes after resume without logind. */ }
        });
        this.refresh(false);
    }

    icon(id, size) {
        const filename = id === 'antigravity' ? 'antigravity-symbolic.svg' :
            id === 'opencode' ? 'opencode.png' : 'codex.svg';
        const file = this.dir.get_child(`icons/${filename}`);
        return new St.Icon({gicon: new Gio.FileIcon({file}), icon_size: size,
            style_class: 'pq-icon', y_align: Clutter.ActorAlign.CENTER});
    }

    refresh(manual) {
        if (!this.active || this.process) return;
        const now = Date.now() / 1000;
        if (manual && now - this.lastManual < 15) return;
        const selected = PROVIDERS.filter(id => manual || now >= (this.due[id] ?? 0));
        if (!selected.length) return;
        if (manual) this.lastManual = now;
        const config = {providers: selected, codexPath: this.settings.get_string('codex-path'),
            agyPath: this.settings.get_string('agy-path')};
        this.cancellable = new Gio.Cancellable();
        try {
            this.process = Gio.Subprocess.new(['/usr/bin/python3', `${this.path}/backend/collector.py`],
                Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
            const proc = this.process;
            const cancel = this.cancellable;
            const input = proc.get_stdin_pipe();
            input.write_all(new TextEncoder().encode(`${JSON.stringify(config)}\n`), cancel);
            input.close(cancel);
            const output = new Gio.DataInputStream({base_stream: proc.get_stdout_pipe()});
            const received = new Set();
            const read = () => output.read_line_async(GLib.PRIORITY_DEFAULT, cancel, (stream, res) => {
                if (!this.active || this.process !== proc) return;
                try {
                    const [line] = stream.read_line_finish_utf8(res);
                    if (line === null) return;
                    const data = JSON.parse(line);
                    if (selected.includes(data.id) && Array.isArray(data.quotas)) {
                        received.add(data.id);
                        this.receive(data);
                    }
                    read();
                } catch (_) { /* Cancellation or malformed helper output. */ }
            });
            read();
            this.watchdog = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 45, () => {
                this.watchdog = 0;
                if (this.process === proc) proc.send_signal(15);
                return GLib.SOURCE_REMOVE;
            });
            proc.wait_async(null, (child, res) => {
                try { child.wait_finish(res); } catch (_) { /* Process already stopped. */ }
                if (!this.active || this.process !== proc) return;
                // Let the pipe callback consume buffered final lines before marking missing providers.
                this.finishIdle = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                    this.finishIdle = 0;
                    if (!this.active || this.process !== proc) return GLib.SOURCE_REMOVE;
                    if (this.watchdog) GLib.Source.remove(this.watchdog);
                    this.watchdog = 0;
                    this.process = null;
                    for (const id of selected) {
                        if (!received.has(id))
                            this.receive({id, status: 'offline', message: 'La consulta no terminó; se reintentará', quotas: []});
                    }
                    this.indicator.render();
                    return GLib.SOURCE_REMOVE;
                });
            });
        } catch (_) {
            this.process = null;
            for (const id of selected)
                this.receive({id, status: 'unavailable', message: 'No se pudo iniciar Python 3', quotas: []});
        }
        this.indicator.render();
    }

    receive(incoming) {
        const id = incoming.id;
        this.data[id] = mergeResult(this.data[id], incoming);
        this.failures[id] = incoming.status === 'ok' ? 0 : (this.failures[id] ?? 0) + 1;
        const interval = this.settings.get_int('refresh-seconds');
        this.due[id] = Date.now() / 1000 + Math.min(900, interval * 2 ** Math.min(4, this.failures[id]));
        try {
            this.cache.replace_contents(JSON.stringify(this.data), null, false,
                Gio.FileCreateFlags.PRIVATE | Gio.FileCreateFlags.REPLACE_DESTINATION, null);
        } catch (_) { /* Cache failure must not stop live quotas. */ }
        this.indicator.render();
    }

    disable() {
        this.active = false;
        for (const source of [this.timer, this.watchdog, this.finishIdle])
            if (source) GLib.Source.remove(source);
        this.timer = this.watchdog = this.finishIdle = 0;
        if (this.resumeId) Main.screenShield.disconnect(this.resumeId);
        if (this.settingsId) this.settings.disconnect(this.settingsId);
        if (this.sleepSubscription) this.systemBus?.signal_unsubscribe(this.sleepSubscription);
        this.sleepSubscription = 0;
        this.lifecycle?.cancel();
        this.lifecycle = null;
        this.systemBus = null;
        this.cancellable?.cancel();
        if (this.process) {
            try { this.process.send_signal(15); } catch (_) { /* Already exited. */ }
        }
        this.process = null;
        this.indicator?._cancelScroll();
        this.indicator?.destroy();
        this.indicator = null;
        this.settings = null;
        this.cancellable = null;
        this.data = null;
    }
}
