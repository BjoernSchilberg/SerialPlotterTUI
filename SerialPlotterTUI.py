#!/usr/bin/env python3
"""
Echtzeit Serial Plotter TUI - Terminal User Interface Version
Verwendet Textual für eine moderne Terminal-Oberfläche mit plotext-Graphen.

Unterstützte Formate:
- Einzelwert pro Zeile: "123.45"
- Mehrere Werte (komma-getrennt): "10,20,30"
- Mehrere Werte (leerzeichen-getrennt): "10 20 30"
- Label:Wert Format: "temp:25.5,humidity:60"
"""

import sys
import argparse
import re
import csv
import os
from collections import deque
from datetime import datetime

import serial
import serial.tools.list_ports
import plotext as plt

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Log, RichLog
from textual.reactive import reactive
from textual import work
from rich.text import Text
from rich.panel import Panel
from rich.table import Table


# Graph-Modi
GRAPH_MODE_LINE = "line"
GRAPH_MODE_BAR = "bar"
GRAPH_MODE_SCATTER = "scatter"

# Standard-Farben für plotext (RGB-Tuples) - werden vom Theme überschrieben
PLOTEXT_COLORS_DARK = [
    (84, 239, 174),   # grün
    (68, 180, 255),   # cyan/blau
    (252, 213, 121),  # gelb
    (191, 121, 252),  # magenta
    (255, 73, 112),   # rot
    (172, 207, 231),  # hellblau
]

PLOTEXT_COLORS_LIGHT = [
    (0, 150, 80),     # dunkelgrün
    (0, 100, 200),    # dunkelblau
    (180, 140, 0),    # dunkelgelb/orange
    (130, 50, 180),   # dunkelmagenta
    (200, 30, 60),    # dunkelrot
    (50, 100, 150),   # dunkelblaugrau
]


def hex_to_rgb(hex_color: str) -> tuple:
    """Konvertiert Hex-Farbe (#RRGGBB) zu RGB-Tuple"""
    if not hex_color or hex_color == "None":
        return None
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    return None


class PlotextGraph(Static):
    """Widget für plotext-basierte Graphen-Darstellung (wie Dolphie)"""
    
    graph_mode = reactive(GRAPH_MODE_LINE)
    
    def __init__(self, max_points: int = 100, **kwargs):
        super().__init__(**kwargs)
        self.max_points = max_points
        self.data_series: dict[str, deque] = {}
        self.timestamps: deque = deque(maxlen=max_points)
        self.sample_count = 0
    
    def _get_theme_colors(self) -> dict:
        """Holt die Farben aus dem aktuellen Textual-Theme"""
        try:
            theme = self.app.current_theme
            if theme:
                is_dark = theme.dark
                
                # Hintergrund aus Theme holen
                bg_color = theme.background
                if bg_color:
                    bg_rgb = hex_to_rgb(str(bg_color))
                else:
                    bg_rgb = (10, 14, 27) if is_dark else (250, 250, 250)
                
                # Surface-Farbe für Achsen
                surface_color = theme.surface
                if surface_color:
                    surface_rgb = hex_to_rgb(str(surface_color))
                else:
                    surface_rgb = bg_rgb
                
                # Vordergrundfarbe für Ticks/Beschriftung
                fg_color = theme.foreground
                if fg_color:
                    fg_rgb = hex_to_rgb(str(fg_color))
                else:
                    fg_rgb = (200, 200, 200) if is_dark else (50, 50, 50)
                
                # Theme-Farben für die Linien (primary, secondary, success, warning, error, accent)
                plot_colors = []
                for color_attr in ['success', 'primary', 'warning', 'accent', 'error', 'secondary']:
                    color = getattr(theme, color_attr, None)
                    if color:
                        rgb = hex_to_rgb(str(color))
                        if rgb:
                            plot_colors.append(rgb)
                
                if not plot_colors:
                    plot_colors = PLOTEXT_COLORS_DARK if is_dark else PLOTEXT_COLORS_LIGHT
                
                # Rich-Farben für den Text
                rich_colors = ["green", "cyan", "yellow", "magenta", "red", "blue"] if is_dark else \
                              ["dark_green", "blue", "dark_orange", "dark_magenta", "dark_red", "dark_cyan"]
                
                return {
                    "is_dark": is_dark,
                    "canvas_color": bg_rgb or ((10, 14, 27) if is_dark else (250, 250, 250)),
                    "axes_color": surface_rgb or bg_rgb or ((10, 14, 27) if is_dark else (250, 250, 250)),
                    "ticks_color": fg_rgb or ((200, 200, 200) if is_dark else (50, 50, 50)),
                    "plot_colors": plot_colors,
                    "rich_colors": rich_colors,
                }
        except Exception:
            pass
        
        # Fallback
        return {
            "is_dark": True,
            "canvas_color": (10, 14, 27),
            "axes_color": (10, 14, 27),
            "ticks_color": (133, 159, 213),
            "plot_colors": PLOTEXT_COLORS_DARK,
            "rich_colors": ["green", "cyan", "yellow", "magenta", "red", "blue"],
        }
    
    def add_values(self, values: dict[str, float]) -> None:
        """Fügt neue Werte hinzu"""
        self.sample_count += 1
        self.timestamps.append(self.sample_count)
        
        for label, value in values.items():
            if label not in self.data_series:
                self.data_series[label] = deque(maxlen=self.max_points)
            self.data_series[label].append(value)
        
        # Fehlende Werte mit None auffüllen
        for label in self.data_series:
            if label not in values:
                self.data_series[label].append(None)
        
        self.refresh()
    
    def toggle_mode(self) -> str:
        """Wechselt zwischen den Graph-Modi"""
        modes = [GRAPH_MODE_LINE, GRAPH_MODE_BAR, GRAPH_MODE_SCATTER]
        current_idx = modes.index(self.graph_mode)
        self.graph_mode = modes[(current_idx + 1) % len(modes)]
        self.refresh()
        return self.graph_mode
    
    def on_resize(self) -> None:
        """Re-render bei Größenänderung"""
        self.refresh()
    
    def render(self) -> Text:
        """Rendert den Graph mit plotext"""
        if not self.data_series or not self.timestamps:
            return Text("Warte auf Daten...", style="dim italic")
        
        try:
            # Theme-Farben aus Textual holen
            theme_cfg = self._get_theme_colors()
            
            # Plot konfigurieren
            plt.clf()
            plt.theme("dark" if theme_cfg["is_dark"] else "clear")
            plt.canvas_color(theme_cfg["canvas_color"])
            plt.axes_color(theme_cfg["axes_color"])
            plt.ticks_color(theme_cfg["ticks_color"])
            
            # Größe an Widget anpassen
            width = max(40, self.size.width - 2)
            height = max(10, self.size.height - 4)
            plt.plotsize(width, height)
            
            # X-Achsen-Daten
            x = list(self.timestamps)
            
            # Farben aus Theme holen
            plot_colors = theme_cfg["plot_colors"]
            rich_colors = theme_cfg["rich_colors"]
            
            # Statistik-Header erstellen
            stats_text = Text()
            mode_names = {
                GRAPH_MODE_LINE: "Linie",
                GRAPH_MODE_BAR: "Balken", 
                GRAPH_MODE_SCATTER: "Punkte"
            }
            stats_text.append(f"[{mode_names[self.graph_mode]}] ", style="bold cyan")
            stats_text.append("(g=wechseln) ", style="dim")
            
            # Jede Datenreihe plotten
            for i, (label, data) in enumerate(self.data_series.items()):
                color = plot_colors[i % len(plot_colors)]
                y = list(data)
                
                # None-Werte durch Interpolation oder Filterung behandeln
                valid_x = []
                valid_y = []
                for xi, yi in zip(x, y):
                    if yi is not None:
                        valid_x.append(xi)
                        valid_y.append(yi)
                
                if valid_x and valid_y:
                    if self.graph_mode == GRAPH_MODE_LINE:
                        plt.plot(valid_x, valid_y, label=label, color=color, marker="braille")
                    elif self.graph_mode == GRAPH_MODE_BAR:
                        plt.bar(valid_x, valid_y, label=label, color=color)
                    else:  # SCATTER
                        plt.scatter(valid_x, valid_y, label=label, color=color, marker="braille")
                    
                    # Statistiken zum Header hinzufügen
                    current = valid_y[-1]
                    avg = sum(valid_y) / len(valid_y)
                    rich_color = rich_colors[i % len(rich_colors)]
                    stats_text.append(f"● {label}: ", style=f"bold {rich_color}")
                    stats_text.append(f"{current:.1f} ", style=rich_color)
                    stats_text.append(f"(Ø{avg:.1f}) ", style="dim")
            
            # Graph rendern
            graph_str = plt.build()
            
            # Zusammenbauen
            result = Text()
            result.append(stats_text)
            result.append("\n")
            result.append(Text.from_ansi(graph_str))
            
            return result
            
        except Exception as e:
            return Text(f"Graph-Fehler: {e}", style="red")


class CurrentValues(Static):
    """Widget für aktuelle Werte als Tabelle"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.values: dict[str, float] = {}
    
    def _get_colors(self) -> list[str]:
        """Gibt die Farbliste basierend auf dem aktuellen Theme zurück"""
        try:
            theme = self.app.current_theme
            if theme and not theme.dark:
                return ["dark_green", "blue", "dark_orange", "dark_magenta", "dark_red", "dark_cyan"]
        except:
            pass
        return ["green", "cyan", "yellow", "magenta", "red", "blue"]
    
    def update_values(self, values: dict[str, float]) -> None:
        self.values.update(values)
        self.refresh()
    
    def render(self) -> Text:
        if not self.values:
            return Text("Warte auf Daten...", style="dim italic")
        
        text = Text()
        text.append("Aktuelle Werte\n", style="bold underline")
        text.append("\n")
        
        colors = self._get_colors()
        for i, (label, value) in enumerate(self.values.items()):
            color = colors[i % len(colors)]
            text.append(f"  ● {label}: ", style=f"bold {color}")
            text.append(f"{value:.4f}\n", style=color)
        
        return text


class SerialPlotterTUI(App):
    """Textual-basierte Serial Plotter Anwendung"""
    
    CSS = """
    Screen {
        layout: horizontal;
    }
    
    #left-panel {
        width: 35%;
        height: 100%;
        border: solid green;
    }
    
    #right-panel {
        width: 65%;
        height: 100%;
    }
    
    #serial-log {
        height: 70%;
        border: solid $primary;
    }
    
    #current-values {
        height: 30%;
        border: solid $secondary;
        padding: 1;
    }
    
    #graph {
        height: 100%;
        border: solid cyan;
        padding: 1;
    }
    
    .title {
        text-style: bold;
        color: $text;
        padding: 0 1;
    }
    """
    
    BINDINGS = [
        ("q", "quit", "Beenden"),
        ("c", "clear", "Löschen"),
        ("p", "pause", "Pause"),
        ("g", "toggle_graph", "Graph-Modus"),
        ("t", "toggle_theme", "Theme"),
        ("s", "save_csv", "Speichern der Daten als csv"),
    ]
    
    paused = reactive(False)
    
    def __init__(self, port: str, baudrate: int = 115200, max_points: int = 100):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.max_points = max_points
        self.serial_conn = None
        self.running = True
        # Session-Daten für CSV-Export
        self.session_data: list[dict] = []
        self.session_start = datetime.now()
        self.all_labels: set[str] = set()
    
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        
        with Horizontal():
            with Vertical(id="left-panel"):
                yield Static(f" 📡 Serielle Daten - {self.port} @ {self.baudrate}", 
                           classes="title")
                yield RichLog(id="serial-log", highlight=True, markup=True)
                yield CurrentValues(id="current-values")
            
            with Vertical(id="right-panel"):
                yield Static(" 📊 Echtzeit-Graph", classes="title")
                yield PlotextGraph(max_points=self.max_points, id="graph")
        
        yield Footer()
    
    def on_mount(self) -> None:
        """Wird beim Start aufgerufen"""
        self.connect_serial()
        self.read_serial_loop()
    
    def connect_serial(self, silent: bool = False) -> bool:
        """Verbindung zur seriellen Schnittstelle herstellen"""
        try:
            # Falls noch eine alte Verbindung offen ist, schließen
            if self.serial_conn:
                try:
                    self.serial_conn.close()
                except Exception:
                    pass
                self.serial_conn = None
            
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=0.1
            )
            if not silent:
                log = self.query_one("#serial-log", RichLog)
                log.write(f"[green]✓ Verbunden mit {self.port} @ {self.baudrate} baud[/green]")
                log.write("")
            return True
        except serial.SerialException as e:
            if not silent:
                log = self.query_one("#serial-log", RichLog)
                log.write(f"[red]✗ Fehler: {e}[/red]")
            return False
        except Exception as e:
            if not silent:
                log = self.query_one("#serial-log", RichLog)
                log.write(f"[red]✗ Unerwarteter Fehler: {e}[/red]")
            return False
    
    def parse_line(self, line: str) -> dict[str, float]:
        """Parst eine Zeile und extrahiert numerische Werte"""
        line = line.strip()
        if not line:
            return {}
        
        values = {}
        
        # Format: "label:wert,label2:wert2"
        labeled_pattern = r'(\w+)\s*[:=]\s*([-+]?\d*\.?\d+)'
        labeled_matches = re.findall(labeled_pattern, line)
        
        if labeled_matches:
            for label, value in labeled_matches:
                try:
                    values[label] = float(value)
                except ValueError:
                    pass
        else:
            # Format: Komma- oder Leerzeichen-getrennte Werte
            parts = re.split(r'[,;\s\t]+', line)
            for i, part in enumerate(parts):
                try:
                    num_match = re.search(r'[-+]?\d*\.?\d+', part)
                    if num_match:
                        values[f'CH{i+1}'] = float(num_match.group())
                except ValueError:
                    pass
        
        return values
    
    @work(exclusive=True, thread=True)
    def read_serial_loop(self) -> None:
        """Hintergrund-Thread zum Lesen der seriellen Daten"""
        import time
        
        disconnected = False
        reconnect_interval = 1.0  # Sekunden zwischen Reconnect-Versuchen
        last_reconnect_attempt = 0
        
        while self.running:
            if self.paused:
                time.sleep(0.1)
                continue
            
            # Prüfen ob Verbindung besteht
            if not self.serial_conn or not self.serial_conn.is_open:
                current_time = time.time()
                if current_time - last_reconnect_attempt >= reconnect_interval:
                    last_reconnect_attempt = current_time
                    if not disconnected:
                        disconnected = True
                        self.call_from_thread(self._show_disconnected)
                    
                    # Versuche Reconnect
                    if self._try_reconnect():
                        disconnected = False
                        self.call_from_thread(self._show_reconnected)
                
                time.sleep(0.1)
                continue
            
            try:
                if self.serial_conn.in_waiting:
                    line = self.serial_conn.readline().decode('utf-8', errors='ignore')
                    line = line.strip()
                    
                    if line:
                        # UI-Update im Haupt-Thread
                        self.call_from_thread(self.process_line, line)
            except serial.SerialException as e:
                # Gerät wurde getrennt
                if not disconnected:
                    disconnected = True
                    self.call_from_thread(self._show_disconnected)
                try:
                    self.serial_conn.close()
                except Exception:
                    pass
                self.serial_conn = None
            except OSError as e:
                # Gerät nicht mehr verfügbar (z.B. USB getrennt)
                if not disconnected:
                    disconnected = True
                    self.call_from_thread(self._show_disconnected)
                try:
                    self.serial_conn.close()
                except Exception:
                    pass
                self.serial_conn = None
            except Exception as e:
                self.call_from_thread(
                    self.query_one("#serial-log", RichLog).write,
                    f"[red]Fehler: {e}[/red]"
                )
            
            time.sleep(0.01)  # 10ms Pause
    
    def _try_reconnect(self) -> bool:
        """Versucht die serielle Verbindung wiederherzustellen (Thread-safe)"""
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=0.1
            )
            return True
        except Exception:
            return False
    
    def _show_disconnected(self) -> None:
        """Zeigt Disconnect-Meldung im Log"""
        log = self.query_one("#serial-log", RichLog)
        log.write(f"[yellow]⚠ Gerät {self.port} getrennt - warte auf Wiederverbindung...[/yellow]")
    
    def _show_reconnected(self) -> None:
        """Zeigt Reconnect-Meldung im Log"""
        log = self.query_one("#serial-log", RichLog)
        log.write(f"[green]✓ Wiederverbunden mit {self.port}[/green]")
    
    def process_line(self, line: str) -> None:
        """Verarbeitet eine empfangene Zeile"""
        # Zum Log hinzufügen
        log = self.query_one("#serial-log", RichLog)
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log.write(f"[dim]{timestamp}[/dim] {line}")
        
        # Werte parsen und anzeigen
        values = self.parse_line(line)
        if values:
            # Session-Daten für CSV speichern
            data_point = {
                'timestamp': datetime.now().isoformat(),
                'raw_line': line,
                **values
            }
            self.session_data.append(data_point)
            self.all_labels.update(values.keys())
            
            # Aktuelle Werte aktualisieren
            current = self.query_one("#current-values", CurrentValues)
            current.update_values(values)
            
            # Graph aktualisieren
            graph = self.query_one("#graph", PlotextGraph)
            graph.add_values(values)
    
    def action_quit(self) -> None:
        """Beendet die Anwendung"""
        self.running = False
        if self.serial_conn:
            self.serial_conn.close()
        self.exit()
    
    def action_clear(self) -> None:
        """Löscht den Log"""
        log = self.query_one("#serial-log", RichLog)
        log.clear()
    
    def action_pause(self) -> None:
        """Pausiert/Fortsetzt die Datenaufnahme"""
        self.paused = not self.paused
        log = self.query_one("#serial-log", RichLog)
        if self.paused:
            log.write("[yellow]⏸ Pausiert[/yellow]")
        else:
            log.write("[green]▶ Fortgesetzt[/green]")
    
    def action_toggle_graph(self) -> None:
        """Wechselt zwischen den Graph-Modi"""
        graph = self.query_one("#graph", PlotextGraph)
        new_mode = graph.toggle_mode()
        log = self.query_one("#serial-log", RichLog)
        mode_names = {
            GRAPH_MODE_LINE: "Liniendiagramm",
            GRAPH_MODE_BAR: "Balkendiagramm",
            GRAPH_MODE_SCATTER: "Punktdiagramm"
        }
        log.write(f"[cyan]📊 Graph-Modus: {mode_names[new_mode]}[/cyan]")
    
    def action_save_csv(self) -> None:
        """Speichert die Session-Daten als CSV-Datei"""
        if not self.session_data:
            self.notify("Keine Daten zum Speichern vorhanden", severity="warning")
            return
        
        # Dateiname mit Zeitstempel generieren
        timestamp = self.session_start.strftime("%Y%m%d_%H%M%S")
        filename = f"serial_data_{timestamp}.csv"
        
        try:
            # Alle Spalten sammeln (timestamp + raw_line + alle Labels)
            fieldnames = ['timestamp', 'raw_line'] + sorted(self.all_labels)
            
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                
                for data_point in self.session_data:
                    # Fehlende Werte mit leerem String füllen
                    row = {key: data_point.get(key, '') for key in fieldnames}
                    writer.writerow(row)
            
            # Absolute Pfad für Anzeige
            abs_path = os.path.abspath(filename)
            self.notify(
                f"{len(self.session_data)} Datenpunkte gespeichert\n{abs_path}",
                title="💾 CSV gespeichert",
                severity="information"
            )
        except Exception as e:
            self.notify(f"Fehler beim Speichern: {e}", severity="error")
    
    def action_toggle_theme(self) -> None:
        """Wechselt durch die verfügbaren Themes"""
        # Liste der Themes zum Durchschalten
        theme_cycle = [
            "textual-dark",
            "textual-light",
            "nord",
            "gruvbox",
            "dracula",
            "tokyo-night",
            "monokai",
            "catppuccin-mocha",
            "catppuccin-latte",
            "solarized-dark",
            "solarized-light",
        ]
        
        # Aktuelles Theme finden und zum nächsten wechseln
        try:
            current_theme = self.theme
            if current_theme in theme_cycle:
                current_idx = theme_cycle.index(current_theme)
                next_idx = (current_idx + 1) % len(theme_cycle)
            else:
                next_idx = 0
            
            next_theme = theme_cycle[next_idx]
            self.theme = next_theme
            
        except Exception:
            # Fallback
            if not hasattr(self, '_theme_idx'):
                self._theme_idx = 0
            self._theme_idx = (self._theme_idx + 1) % len(theme_cycle)
            next_theme = theme_cycle[self._theme_idx]
            try:
                self.theme = next_theme
            except:
                pass
        
        # Widgets refreshen - sie lesen das Theme automatisch aus self.app.current_theme
        graph = self.query_one("#graph", PlotextGraph)
        graph.refresh()
        
        current_values = self.query_one("#current-values", CurrentValues)
        current_values.refresh()
        
        log = self.query_one("#serial-log", RichLog)
        log.write(f"[cyan]🎨 Theme: {next_theme}[/cyan]")


def list_serial_ports():
    """Listet alle verfügbaren seriellen Ports auf"""
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("Keine seriellen Ports gefunden.")
        return []
    
    print("\nVerfügbare serielle Ports:")
    print("-" * 50)
    for port in ports:
        print(f"  {port.device}")
        print(f"    Beschreibung: {port.description}")
        if port.manufacturer:
            print(f"    Hersteller: {port.manufacturer}")
        print()
    return [p.device for p in ports]


def create_app(port: str = None, baudrate: int = 115200, max_points: int = 100) -> SerialPlotterTUI:
    """Factory-Funktion für textual-serve Kompatibilität.
    
    Für textual-serve muss eine Funktion existieren, die die App-Instanz zurückgibt.
    """
    # Wenn kein Port angegeben, versuche den ersten verfügbaren zu finden
    if not port:
        ports = serial.tools.list_ports.comports()
        if ports:
            port = ports[0].device
        else:
            port = "/dev/ttyUSB0"  # Fallback
    
    return SerialPlotterTUI(
        port=port,
        baudrate=baudrate,
        max_points=max_points
    )


def main():
    parser = argparse.ArgumentParser(
        description='Echtzeit Serial Plotter TUI - Terminal User Interface',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  %(prog)s /dev/ttyUSB0              # Standard 115200 baud
  %(prog)s /dev/ttyACM0 -b 9600      # Mit 9600 baud
  %(prog)s --list                    # Verfügbare Ports anzeigen
  %(prog)s --serve                   # Als Web-Server starten (Browser)
  %(prog)s --serve --host 0.0.0.0    # Server auf allen Interfaces

Tastenkürzel:
  q - Beenden
  c - Log löschen  
  p - Pause/Fortsetzen
  g - Graph-Modus wechseln (Line/Bar/Scatter)
  t - Theme wechseln
  s - Speichern der Daten als csv
        """
    )
    
    parser.add_argument('port', nargs='?', help='Serieller Port')
    parser.add_argument('-b', '--baudrate', type=int, default=115200,
                        help='Baudrate (Standard: 115200)')
    parser.add_argument('-p', '--points', type=int, default=100,
                        help='Maximale Datenpunkte im Graph (Standard: 100)')
    parser.add_argument('-l', '--list', action='store_true',
                        help='Verfügbare Ports auflisten')
    parser.add_argument('--serve', action='store_true',
                        help='Als Web-Server starten (für Browser-Zugriff)')
    parser.add_argument('--host', type=str, default='localhost',
                        help='Host für Web-Server (Standard: localhost)')
    parser.add_argument('--web-port', type=int, default=8000,
                        help='Port für Web-Server (Standard: 8000)')
    
    args = parser.parse_args()
    
    if args.list:
        list_serial_ports()
        return
    
    if args.serve:
        # Web-Server Modus mit textual-serve
        try:
            from textual_serve.server import Server
        except ImportError:
            print("Fehler: textual-serve ist nicht installiert.")
            print("Installiere mit: pip install textual-serve")
            return
        
        # Port für Serial-Verbindung ermitteln
        serial_port = args.port
        if not serial_port:
            ports = serial.tools.list_ports.comports()
            if ports:
                serial_port = ports[0].device
                print(f"Verwende automatisch erkannten Port: {serial_port}")
            else:
                print("Warnung: Kein serieller Port angegeben oder gefunden.")
                serial_port = "/dev/ttyUSB0"
        
        # Kommando für textual-serve zusammenbauen
        command = f"python {sys.argv[0]} {serial_port} -b {args.baudrate} -p {args.points}"
        
        print(f"Starte Web-Server auf http://{args.host}:{args.web_port}")
        print(f"Serial Port: {serial_port} @ {args.baudrate} baud")
        print("Drücke Ctrl+C zum Beenden")
        
        server = Server(command, host=args.host, port=args.web_port)
        server.serve()
        return
    
    if not args.port:
        ports = list_serial_ports()
        if ports:
            print(f"\nTipp: Starte mit: python {sys.argv[0]} {ports[0]}")
            print(f"      Oder im Browser: python {sys.argv[0]} {ports[0]} --serve")
        else:
            parser.print_help()
        return
    
    app = SerialPlotterTUI(
        port=args.port,
        baudrate=args.baudrate,
        max_points=args.points
    )
    app.run()


if __name__ == '__main__':
    main()
