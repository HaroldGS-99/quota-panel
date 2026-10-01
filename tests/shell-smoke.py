"""Exercise the real actors in an isolated headless GNOME Shell, with fake quotas."""
import json
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--screenshots', type=Path, help='Export clean documentation screenshots here')
args = parser.parse_args()
screenshots = args.screenshots.resolve() if args.screenshots else None
if screenshots:
    screenshots.mkdir(parents=True, exist_ok=True)
CASE = Path(tempfile.mkdtemp(prefix="quota-panel-shell-"))
for name in ("data", "config", "cache", "runtime"):
    (CASE / name).mkdir(mode=0o700)
extension = CASE / "data/gnome-shell/extensions/quota-panel@extensions.local"
extension.parent.mkdir(parents=True)
shutil.copytree(ROOT, extension, ignore=shutil.ignore_patterns(".git", "dist", "__pycache__", ".agents", ".codex"))
subprocess.run(["glib-compile-schemas", "--strict", str(extension / "schemas")], check=True)
(extension / "backend/collector.py").write_text('''import json, sys, time
config = json.load(sys.stdin)
for provider, value in zip(config["providers"], [25, 75, 95]):
    quotas = [{"id": "5h", "label": "5 horas", "usedPercent": value,
               "windowMinutes": 300, "resetsAt": time.time() + 3600}]
    quotas.append({"id": "week", "label": "Semanal", "usedPercent": 30,
                   "windowMinutes": 10080, "resetsAt": time.time() + 86400})
    if provider == "codex":
        quotas.append({"id": "reserve", "label": "Semanal", "usedPercent": 1,
                       "windowMinutes": 10080, "group": "gpt-reserve",
                       "resetsAt": time.time() + 86400})
    if provider == "opencode":
        quotas.append({"id": "month", "label": "Mensual", "usedPercent": 93,
                       "windowMinutes": None, "resetsAt": time.time() + 864000})
    print(json.dumps({"id": provider, "status": "ok", "quotas": quotas,
                      "updatedAt": time.time(), "resetsAvailable": 2}), flush=True)
''')
smoke = extension.parent / "quota-smoke@local"
smoke.mkdir()
(smoke / "metadata.json").write_text(json.dumps({"uuid": smoke.name, "name": "Quota smoke",
    "description": "Isolated test", "shell-version": ["46"]}))
(smoke / "extension.js").write_text('''import GLib from 'gi://GLib';
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import Shell from 'gi://Shell';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
const uuid = 'quota-panel@extensions.local';
const out = GLib.getenv('PQ_SMOKE_DIR');
const documentation = GLib.getenv('PQ_SCREENSHOTS_OUTPUT');
const wait = ms => new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms, () => {
    resolve(); return GLib.SOURCE_REMOVE;
}));
function assert(value, message) { if (!value) throw new Error(message); }
export default class Smoke extends Extension {
    enable() { this.run(); }
    disable() {}
    async run() {
        let status;
        try {
            await wait(5000);
            Main.overview.hide();
            await wait(500);
            let indicator = Main.panel.statusArea[uuid];
            assert(indicator, 'Indicator missing');
            assert(indicator.container.get_parent() === Main.panel._leftBox, 'Wrong panel position');
            assert(indicator.parts.codex.label.text === '25%', 'Codex result not rendered');
            assert(indicator.parts.antigravity.bar.color === 'warning', 'Yellow missing');
            assert(indicator.parts.opencode.bar.color === 'critical', 'Red missing');
            indicator.menu.open();
            await wait(700);
            assert(indicator.menuContent.get_n_children() === 3, 'Missing dropdown sections');
            assert(/ \\d{1,2}:\\d{2} (AM|PM)$/.test(indicator.sections.get('codex').quotas.get('5h').date.text),
                'Reset time must use 12-hour format');
            const adjustment = indicator.scroll.vadjustment;
            const maximum = adjustment.upper - adjustment.page_size;
            assert(maximum > 90, `Fixture must overflow to test scrolling: ${maximum}`);
            const down = {get_scroll_direction: () => Clutter.ScrollDirection.DOWN};
            const up = {get_scroll_direction: () => Clutter.ScrollDirection.UP};
            const smooth = {get_scroll_direction: () => Clutter.ScrollDirection.SMOOTH,
                get_scroll_delta: () => [0, 0.25]};
            const smoothWheel = {...smooth, get_scroll_source: () => Clutter.ScrollSource.WHEEL};
            const animatedStep = async (event, target) => {
                const before = adjustment.value;
                const samples = [];
                const notify = adjustment.connect('notify::value', () => samples.push(adjustment.value));
                indicator._onScroll(event);
                assert(Math.abs(adjustment.value - before) < 0.5, 'Wheel moves instantly');
                await wait(240);
                adjustment.disconnect(notify);
                assert(Math.abs(adjustment.value - target) < 0.5, 'Wheel misses destination');
                assert(samples.some(v => v > Math.min(before, target) + 0.5 &&
                    v < Math.max(before, target) - 0.5), 'Wheel lacks intermediate frames');
                for (let i = 1; i < samples.length; i++)
                    assert((samples[i] - samples[i - 1]) * Math.sign(target - before) >= -0.5,
                        'Animation jumps backward');
            };
            for (const position of [45, maximum - 65]) {
                adjustment.value = position;
                await animatedStep(down, position + 48);
                await animatedStep(up, position);
                indicator._onScroll(smooth);
                assert(Math.abs(adjustment.value - position - 7) < 1, 'Touchpad delta lost');
                const before = adjustment.value;
                const section = indicator.sections.get('codex');
                const row = section.quotas.get('5h');
                indicator.extension.data.codex.quotas.reverse();
                indicator.extension.data.codex.quotas.find(q => q.id === '5h').usedPercent++;
                indicator.render();
                await wait(100);
                assert(Math.abs(adjustment.value - before) < 1, 'Refresh resets scroll position');
                assert(section.quotas.get('5h') === row, 'Refresh recreates quota row');
                assert(section.rows.get_child_at_index(0) === row.row, 'Provider order moves rows');
            }
            adjustment.value = 20;
            await animatedStep(smoothWheel, 32);
            adjustment.value = 20;
            indicator._onScroll(down);
            indicator._onScroll(down);
            indicator._onScroll(down);
            await wait(240);
            assert(Math.abs(adjustment.value - Math.min(maximum, 164)) < 0.5, 'Rapid wheel ticks lost');
            adjustment.value = 60;
            indicator._onScroll(down);
            await wait(50);
            const reversing = adjustment.value;
            await animatedStep(up, Math.max(0, reversing - 48));
            adjustment.value = 45;
            indicator._onScroll(down);
            assert(adjustment.get_transition('value'), 'Wheel transition missing before refresh');
            indicator.render();
            assert(adjustment.get_transition('value'), 'Refresh cancels motion');
            await wait(240);
            assert(Math.abs(adjustment.value - 93) < 0.5, 'Refresh changes motion destination');
            indicator._onScroll(down);
            await wait(40);
            const touchpadStart = adjustment.value;
            indicator._onScroll(smooth);
            await wait(240);
            assert(Math.abs(adjustment.value - Math.min(maximum, touchpadStart + 7)) < 0.5,
                'Wheel keeps moving after touchpad input');
            adjustment.value = maximum - 5;
            await animatedStep(down, maximum);
            await animatedStep(up, maximum - 48);
            adjustment.value = 5;
            await animatedStep(up, 0);
            await animatedStep(down, 48);
            indicator._onScroll(down);
            await wait(40);
            indicator.menu.close();
            const stopped = adjustment.value;
            await wait(240);
            assert(Math.abs(adjustment.value - stopped) < 0.5, 'Closed menu keeps scrolling');
            indicator.menu.open();
            await wait(300);
            adjustment.value = 0;
            const stream = Gio.File.new_for_path(`${out}/menu.png`).replace(null, false,
                Gio.FileCreateFlags.NONE, null);
            const screenshot = new Shell.Screenshot();
            await new Promise((resolve, reject) => screenshot.screenshot(false, stream, (obj, res) => {
                try { obj.screenshot_finish(res); stream.close(null); resolve(); }
                catch (error) { reject(error); }
            }));
            if (documentation) {
                const area = async (name, x, y, width, height) => {
                    x = Math.max(0, Math.floor(x));
                    y = Math.max(0, Math.floor(y));
                    width = Math.min(global.stage.width - x, Math.ceil(width));
                    height = Math.min(global.stage.height - y, Math.ceil(height));
                    const file = Gio.File.new_for_path(`${documentation}/${name}.png`);
                    const stream = file.replace(null, false, Gio.FileCreateFlags.NONE, null);
                    await new Promise((resolve, reject) => screenshot.screenshot_area(
                        x, y, width, height, stream, (obj, res) => {
                            try {
                                assert(obj.screenshot_area_finish(res), 'Screenshot failed');
                                stream.close(null); resolve();
                            } catch (error) { reject(error); }
                        }));
                };
                const menu = async name => {
                    const [x, y] = indicator.menu.actor.get_transformed_position();
                    const [w, h] = indicator.menu.actor.get_transformed_size();
                    await area(name, x - 8, y - 8, w + 16, h + 16);
                };
                indicator.menu.close();
                await wait(300);
                const [panelX] = indicator.container.get_transformed_position();
                const [panelWidth] = indicator.container.get_transformed_size();
                await area('panel', 0, 0, panelX + panelWidth + 12, Main.panel.height);
                indicator.menu.open();
                adjustment.value = 0;
                await wait(400);
                await menu('menu-dark');
                adjustment.value = adjustment.upper - adjustment.page_size;
                await wait(150);
                const [menuX, menuY] = indicator.menu.actor.get_transformed_position();
                const [menuW, menuH] = indicator.menu.actor.get_transformed_size();
                const [, goY] = indicator.sections.get('opencode').section.get_transformed_position();
                await area('opencode-monthly', menuX - 8, goY - 12,
                    menuW + 16, menuY + menuH - goY + 20);
                const desktop = new Gio.Settings({schema_id: 'org.gnome.desktop.interface'});
                desktop.set_string('color-scheme', 'prefer-light');
                desktop.set_string('gtk-theme', 'Yaru');
                adjustment.value = 0;
                await wait(700);
                await menu('menu-light');
            }
            Main.extensionManager.disableExtension(uuid);
            await wait(800);
            assert(!Main.panel.statusArea[uuid], 'Indicator remains after disable');
            Main.extensionManager.enableExtension(uuid);
            await wait(1600);
            indicator = Main.panel.statusArea[uuid];
            assert(indicator, 'Indicator missing after reenable');
            assert(Main.panel._leftBox.get_children().filter(actor => actor === indicator.container).length === 1,
                'Duplicate indicator');
            status = {ok: true, checks: ['left panel', 'live fixture updates', 'threshold colors',
                'dropdown', 'animated wheel frames', 'direct touchpad motion', 'rapid ticks and reversal', 'refresh preserves scroll and rows',
                'scroll boundaries', 'screenshot', 'disable/enable']};
        } catch (error) { status = {ok: false, error: `${error}`, stack: error.stack}; }
        GLib.file_set_contents(`${out}/result.json`, JSON.stringify(status));
        global.context.terminate();
    }
}
''')
env = dict(os.environ, XDG_DATA_HOME=str(CASE / "data"), XDG_CONFIG_HOME=str(CASE / "config"),
           XDG_CACHE_HOME=str(CASE / "cache"), XDG_RUNTIME_DIR=str(CASE / "runtime"),
           PQ_SMOKE_DIR=str(CASE), PQ_SCREENSHOTS_OUTPUT=str(screenshots) if screenshots else '')
command = '''gsettings set org.gnome.shell enabled-extensions "['quota-panel@extensions.local', 'quota-smoke@local']"
gsettings set org.gnome.shell disable-user-extensions false
gsettings set org.gnome.shell welcome-dialog-last-shown-version '46.0'
gsettings set org.gnome.desktop.interface enable-animations true
gsettings set org.gnome.desktop.interface color-scheme 'prefer-dark'
gsettings set org.gnome.desktop.interface gtk-theme 'Yaru-dark'
exec gnome-shell --wayland --headless --no-x11 --virtual-monitor=1280x900 --wayland-display=quota-smoke --sm-disable
'''
print(f"Smoke directory: {CASE}", flush=True)
try:
    with (CASE / "shell.log").open("w") as log:
        subprocess.run(["dbus-run-session", "--", "bash", "-c", command], env=env,
                       stdout=log, stderr=subprocess.STDOUT, timeout=40)
except subprocess.TimeoutExpired:
    print("Headless Shell timed out")
result = CASE / "result.json"
if result.exists():
    value = json.loads(result.read_text())
    if value['ok'] and screenshots:
        subprocess.run(['python3', str(ROOT / 'scripts/clean-screenshots.py'), str(screenshots)], check=True)
    print(json.dumps(value, ensure_ascii=False))
    raise SystemExit(0 if value["ok"] else 1)
print((CASE / "shell.log").read_text()[-8000:])
raise SystemExit(1)
