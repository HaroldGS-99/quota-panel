import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';
import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

export default class QuotaPanelPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        window.set_default_size(620, 560);
        const page = new Adw.PreferencesPage({title: 'Cuotas', icon_name: 'view-statistics-symbolic'});
        const display = new Adw.PreferencesGroup({title: 'Consumo y actualización',
            description: 'Las barras muestran el porcentaje consumido. Verde, amarillo y rojo según estos umbrales.'});
        page.add(display);
        const spin = (key, title, min, max, suffix) => {
            const row = new Adw.SpinRow({title, subtitle: suffix,
                adjustment: new Gtk.Adjustment({lower: min, upper: max, step_increment: 1, page_increment: 10}), digits: 0});
            settings.bind(key, row, 'value', Gio.SettingsBindFlags.DEFAULT);
            display.add(row);
            return row;
        };
        const warning = spin('warning-percent', 'Amarillo desde', 1, 98, '% consumido');
        const critical = spin('critical-percent', 'Rojo desde', 2, 100, '% consumido');
        warning.connect('notify::value', () => {
            if (critical.value <= warning.value) critical.value = warning.value + 1;
        });
        critical.connect('notify::value', () => {
            if (warning.value >= critical.value) warning.value = critical.value - 1;
        });
        spin('refresh-seconds', 'Consultar cada', 30, 900, 'Segundos; los errores espacian los reintentos automáticamente');
        const connections = new Adw.PreferencesGroup({title: 'Sesiones existentes',
            description: 'Codex usa tu cuenta ChatGPT, Antigravity el grupo Gemini de agy y OpenCode tu conexión Go. No necesitas pegar claves aquí.'});
        page.add(connections);
        for (const [key, title] of [['codex-path', 'Ejecutable Codex'], ['agy-path', 'Ejecutable agy']]) {
            const row = new Adw.EntryRow({title, show_apply_button: true});
            row.text = settings.get_string(key);
            row.connect('apply', () => settings.set_string(key, row.text.trim()));
            connections.add(row);
        }
        connections.add(new Adw.ActionRow({title: 'Rutas vacías: detección automática',
            subtitle: 'Si una sesión vence, vuelve a iniciar sesión en la aplicación correspondiente.'}));
        connections.add(new Adw.ActionRow({title: 'Solo consulta',
            subtitle: 'Los resets adicionales se muestran; esta extensión no los canjea.'}));
        window.add(page);
    }
}
