#!/usr/bin/env python3
"""
Echtzeit Serial Plotter - Ähnlich wie Thonny's Serial Plotter
Plottet numerische Werte von der seriellen Schnittstelle in Echtzeit.

Unterstützte Formate:
- Einzelwert pro Zeile: "123.45"
- Mehrere Werte (komma-getrennt): "10,20,30"
- Mehrere Werte (leerzeichen-getrennt): "10 20 30"
- Label:Wert Format: "temp:25.5,humidity:60"
"""

import sys
import argparse
import serial
import serial.tools.list_ports
from collections import deque
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import re


class SerialPlotter:
    def __init__(self, port, baudrate=115200, max_points=200):
        self.port = port
        self.baudrate = baudrate
        self.max_points = max_points
        self.serial_conn = None
        
        # Daten-Speicher: Dict von Deques für mehrere Datenreihen
        self.data = {}
        self.time_index = 0
        self.time_data = deque(maxlen=max_points)
        
        # Plot Setup
        self.fig, self.ax = plt.subplots(figsize=(12, 6))
        self.lines = {}
        self.colors = plt.cm.tab10.colors
        
        # UI Setup
        self.fig.canvas.manager.set_window_title(f'Serial Plotter - {port} @ {baudrate}')
        self.ax.set_xlabel('Samples')
        self.ax.set_ylabel('Wert')
        self.ax.set_title(f'Serielle Daten von {port}')
        self.ax.grid(True, alpha=0.3)
        
    def connect(self):
        """Verbindung zur seriellen Schnittstelle herstellen"""
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=0.1
            )
            print(f"Verbunden mit {self.port} @ {self.baudrate} baud")
            return True
        except serial.SerialException as e:
            print(f"Fehler beim Verbinden: {e}")
            return False
    
    def parse_line(self, line):
        """
        Parst eine Zeile und extrahiert numerische Werte.
        Gibt ein Dict zurück: {label: wert}
        """
        line = line.strip()
        if not line:
            return {}
        
        values = {}
        
        # Format: "label:wert,label2:wert2" oder "label:wert label2:wert2"
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
                    # Nur numerische Teile extrahieren
                    num_match = re.search(r'[-+]?\d*\.?\d+', part)
                    if num_match:
                        values[f'Kanal_{i+1}'] = float(num_match.group())
                except ValueError:
                    pass
        
        return values
    
    def read_serial_data(self):
        """Liest Daten von der seriellen Schnittstelle"""
        if self.serial_conn and self.serial_conn.in_waiting:
            try:
                line = self.serial_conn.readline().decode('utf-8', errors='ignore')
                return self.parse_line(line)
            except Exception as e:
                print(f"Lesefehler: {e}")
        return {}
    
    def update_plot(self, frame):
        """Update-Funktion für die Animation"""
        # Mehrere Zeilen lesen falls verfügbar
        for _ in range(10):  # Max 10 Zeilen pro Update
            values = self.read_serial_data()
            if not values:
                break
                
            self.time_index += 1
            self.time_data.append(self.time_index)
            
            # Neue Datenreihen hinzufügen oder bestehende aktualisieren
            for label, value in values.items():
                if label not in self.data:
                    # Neue Datenreihe erstellen
                    self.data[label] = deque(maxlen=self.max_points)
                    color_idx = len(self.lines) % len(self.colors)
                    line, = self.ax.plot([], [], label=label, 
                                         color=self.colors[color_idx],
                                         linewidth=1.5)
                    self.lines[label] = line
                    self.ax.legend(loc='upper left')
                
                self.data[label].append(value)
            
            # Fehlende Werte mit None auffüllen
            for label in self.data:
                if label not in values:
                    self.data[label].append(None)
        
        # Linien aktualisieren
        for label, line in self.lines.items():
            if label in self.data and len(self.data[label]) > 0:
                # Zeit-Daten anpassen
                x_data = list(self.time_data)[-len(self.data[label]):]
                y_data = list(self.data[label])
                
                # None-Werte für das Plotting behandeln
                valid_x = []
                valid_y = []
                for x, y in zip(x_data, y_data):
                    if y is not None:
                        valid_x.append(x)
                        valid_y.append(y)
                
                line.set_data(valid_x, valid_y)
        
        # Achsen anpassen
        if self.time_data:
            self.ax.set_xlim(min(self.time_data), max(self.time_data) + 1)
            
            # Y-Achse automatisch skalieren
            all_values = []
            for data in self.data.values():
                all_values.extend([v for v in data if v is not None])
            
            if all_values:
                y_min, y_max = min(all_values), max(all_values)
                margin = (y_max - y_min) * 0.1 if y_max != y_min else 1
                self.ax.set_ylim(y_min - margin, y_max + margin)
        
        return list(self.lines.values())
    
    def run(self):
        """Startet den Plotter"""
        if not self.connect():
            return
        
        try:
            # Animation starten
            self.ani = FuncAnimation(
                self.fig, 
                self.update_plot,
                interval=50,  # 50ms = 20 FPS
                blit=False,
                cache_frame_data=False
            )
            plt.tight_layout()
            plt.show()
        except KeyboardInterrupt:
            print("\nBeendet.")
        finally:
            if self.serial_conn:
                self.serial_conn.close()
                print("Serielle Verbindung geschlossen.")


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
        description='Echtzeit Serial Plotter - Plottet serielle Daten wie Thonny',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  %(prog)s /dev/ttyUSB0              # Standard 115200 baud
  %(prog)s /dev/ttyACM0 -b 9600      # Mit 9600 baud
  %(prog)s COM3 -b 115200 -p 500     # Windows, 500 Datenpunkte
  %(prog)s --list                    # Verfügbare Ports anzeigen

Unterstützte Eingabeformate (vom Mikrocontroller):
  123.45                             # Einzelwert
  10,20,30                           # Mehrere Werte (komma-getrennt)
  10 20 30                           # Mehrere Werte (leerzeichen-getrennt)
  temp:25.5,humidity:60              # Mit Labels
        """
    )
    
    parser.add_argument('port', nargs='?', help='Serieller Port (z.B. /dev/ttyUSB0, COM3)')
    parser.add_argument('-b', '--baudrate', type=int, default=115200,
                        help='Baudrate (Standard: 115200)')
    parser.add_argument('-p', '--points', type=int, default=200,
                        help='Maximale Anzahl anzuzeigender Datenpunkte (Standard: 200)')
    parser.add_argument('-l', '--list', action='store_true',
                        help='Verfügbare serielle Ports auflisten')
    
    args = parser.parse_args()
    
    if args.list:
        list_serial_ports()
        return
    
    if not args.port:
        # Versuche automatisch einen Port zu finden
        ports = list_serial_ports()
        if ports:
            print(f"\nTipp: Starte mit: python {sys.argv[0]} {ports[0]}")
        else:
            parser.print_help()
        return
    
    plotter = SerialPlotter(
        port=args.port,
        baudrate=args.baudrate,
        max_points=args.points
    )
    plotter.run()


if __name__ == '__main__':
    main()
