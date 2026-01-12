#!/usr/bin/env python3
"""
Echtzeit Serial Plotter TUI - Terminal User Interface Version
Verwendet Textual für eine moderne Terminal-Oberfläche mit ASCII-Graph.

Unterstützte Formate:
- Einzelwert pro Zeile: "123.45"
- Mehrere Werte (komma-getrennt): "10,20,30"
- Mehrere Werte (leerzeichen-getrennt): "10 20 30"
- Label:Wert Format: "temp:25.5,humidity:60"
"""

import sys
import argparse
import re
from collections import deque
from datetime import datetime

import serial
import serial.tools.list_ports

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Log, RichLog
from textual.reactive import reactive
from textual import work
from rich.text import Text
from rich.panel import Panel
from rich.table import Table


# ASCII-Zeichen für den Graphen
GRAPH_CHARS = " ▁▂▃▄▅▆▇█"


class AsciiGraph(Static):
    """Widget für ASCII-basierte Graphen-Darstellung"""
    
    def __init__(self, max_points: int = 100, height: int = 15, **kwargs):
        super().__init__(**kwargs)
        self.max_points = max_points
        self.graph_height = height
        self.data_series: dict[str, deque] = {}
        self.color_list = ["green", "cyan", "yellow", "magenta", "red", "blue"]
    
    def add_values(self, values: dict[str, float]) -> None:
        """Fügt neue Werte hinzu"""
        for label, value in values.items():
            if label not in self.data_series:
                self.data_series[label] = deque(maxlen=self.max_points)
            self.data_series[label].append(value)
        
        # Fehlende Werte mit None auffüllen
        for label in self.data_series:
            if label not in values:
                self.data_series[label].append(None)
        
        self.refresh()
    
    def render_graph(self) -> Text:
        """Rendert den ASCII-Graphen"""
        if not self.data_series:
            return Text("Warte auf Daten...", style="dim")
        
        # Breite des Graphen (Terminal-Breite minus Rand)
        try:
            width = self.size.width - 12
        except:
            width = 80
        
        if width < 20:
            width = 80
        
        text = Text()
        
        # Alle Werte für Skalierung sammeln
        all_values = []
        for data in self.data_series.values():
            all_values.extend([v for v in data if v is not None])
        
        if not all_values:
            return Text("Keine gültigen Daten", style="dim")
        
        y_min, y_max = min(all_values), max(all_values)
        if y_min == y_max:
            y_min -= 1
            y_max += 1
        
        # Header mit Statistiken
        stats_table = Table.grid(padding=(0, 2))
        stats_table.add_column(style="bold")
        stats_table.add_column()
        
        for i, (label, data) in enumerate(self.data_series.items()):
            color = self.color_list[i % len(self.color_list)]
            valid_data = [v for v in data if v is not None]
            if valid_data:
                current = valid_data[-1]
                avg = sum(valid_data) / len(valid_data)
                text.append(f"● {label}: ", style=f"bold {color}")
                text.append(f"{current:.2f} ", style=color)
                text.append(f"(Ø {avg:.2f}, Min: {min(valid_data):.2f}, Max: {max(valid_data):.2f})\n", 
                           style="dim")
        
        text.append("\n")
        
        # Y-Achsen-Labels
        y_labels = [
            f"{y_max:>8.1f} │",
            f"{(y_max + y_min) / 2:>8.1f} │",
            f"{y_min:>8.1f} │"
        ]
        
        # Graph für jede Datenreihe rendern
        for series_idx, (label, data) in enumerate(self.data_series.items()):
            color = self.color_list[series_idx % len(self.color_list)]
            data_list = list(data)
            
            # Auf Breite anpassen
            if len(data_list) > width:
                data_list = data_list[-width:]
            
            # Graph-Zeilen erstellen
            for row in range(self.graph_height):
                # Y-Achsen-Label nur bei erster Serie
                if series_idx == 0:
                    if row == 0:
                        text.append(y_labels[0], style="dim")
                    elif row == self.graph_height // 2:
                        text.append(y_labels[1], style="dim")
                    elif row == self.graph_height - 1:
                        text.append(y_labels[2], style="dim")
                    else:
                        text.append("         │", style="dim")
                
                # Nur bei erster Serie die Linie zeichnen
                if series_idx == 0:
                    for val in data_list:
                        if val is None:
                            text.append(" ", style="dim")
                        else:
                            # Normalisieren auf 0-1
                            normalized = (val - y_min) / (y_max - y_min)
                            # Invertieren für Terminal (oben = hoch)
                            bar_height = int(normalized * self.graph_height)
                            current_row_from_bottom = self.graph_height - 1 - row
                            
                            if bar_height > current_row_from_bottom:
                                char_idx = min(8, int((normalized * 8)))
                                text.append(GRAPH_CHARS[char_idx], style=color)
                            else:
                                text.append("·", style="dim")
                    text.append("\n")
        
        # X-Achse
        text.append("         └" + "─" * min(width, len(data_list)) + ">\n", style="dim")
        text.append(f"          Samples (letzte {len(data_list)})", style="dim")
        
        return text
    
    def render(self) -> Text:
        return self.render_graph()


class CurrentValues(Static):
    """Widget für aktuelle Werte als Tabelle"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.values: dict[str, float] = {}
        self.color_list = ["green", "cyan", "yellow", "magenta", "red", "blue"]
    
    def update_values(self, values: dict[str, float]) -> None:
        self.values.update(values)
        self.refresh()
    
    def render(self) -> Text:
        if not self.values:
            return Text("Warte auf Daten...", style="dim italic")
        
        text = Text()
        text.append("Aktuelle Werte\n", style="bold underline")
        text.append("\n")
        
        for i, (label, value) in enumerate(self.values.items()):
            color = self.color_list[i % len(self.color_list)]
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
    ]
    
    paused = reactive(False)
    
    def __init__(self, port: str, baudrate: int = 115200, max_points: int = 100):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.max_points = max_points
        self.serial_conn = None
        self.running = True
    
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
                yield AsciiGraph(max_points=self.max_points, id="graph")
        
        yield Footer()
    
    def on_mount(self) -> None:
        """Wird beim Start aufgerufen"""
        self.connect_serial()
        self.read_serial_loop()
    
    def connect_serial(self) -> bool:
        """Verbindung zur seriellen Schnittstelle herstellen"""
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=0.1
            )
            log = self.query_one("#serial-log", RichLog)
            log.write(f"[green]✓ Verbunden mit {self.port} @ {self.baudrate} baud[/green]")
            log.write("")
            return True
        except serial.SerialException as e:
            log = self.query_one("#serial-log", RichLog)
            log.write(f"[red]✗ Fehler: {e}[/red]")
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
        
        while self.running:
            if self.paused:
                time.sleep(0.1)
                continue
            
            if self.serial_conn and self.serial_conn.in_waiting:
                try:
                    line = self.serial_conn.readline().decode('utf-8', errors='ignore')
                    line = line.strip()
                    
                    if line:
                        # UI-Update im Haupt-Thread
                        self.call_from_thread(self.process_line, line)
                except Exception as e:
                    self.call_from_thread(
                        self.query_one("#serial-log", RichLog).write,
                        f"[red]Fehler: {e}[/red]"
                    )
            
            time.sleep(0.01)  # 10ms Pause
    
    def process_line(self, line: str) -> None:
        """Verarbeitet eine empfangene Zeile"""
        # Zum Log hinzufügen
        log = self.query_one("#serial-log", RichLog)
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log.write(f"[dim]{timestamp}[/dim] {line}")
        
        # Werte parsen und anzeigen
        values = self.parse_line(line)
        if values:
            # Aktuelle Werte aktualisieren
            current = self.query_one("#current-values", CurrentValues)
            current.update_values(values)
            
            # Graph aktualisieren
            graph = self.query_one("#graph", AsciiGraph)
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


def main():
    parser = argparse.ArgumentParser(
        description='Echtzeit Serial Plotter TUI - Terminal User Interface',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  %(prog)s /dev/ttyUSB0              # Standard 115200 baud
  %(prog)s /dev/ttyACM0 -b 9600      # Mit 9600 baud
  %(prog)s --list                    # Verfügbare Ports anzeigen

Tastenkürzel:
  q - Beenden
  c - Log löschen  
  p - Pause/Fortsetzen
        """
    )
    
    parser.add_argument('port', nargs='?', help='Serieller Port')
    parser.add_argument('-b', '--baudrate', type=int, default=115200,
                        help='Baudrate (Standard: 115200)')
    parser.add_argument('-p', '--points', type=int, default=100,
                        help='Maximale Datenpunkte im Graph (Standard: 100)')
    parser.add_argument('-l', '--list', action='store_true',
                        help='Verfügbare Ports auflisten')
    
    args = parser.parse_args()
    
    if args.list:
        list_serial_ports()
        return
    
    if not args.port:
        ports = list_serial_ports()
        if ports:
            print(f"\nTipp: Starte mit: python {sys.argv[0]} {ports[0]}")
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
